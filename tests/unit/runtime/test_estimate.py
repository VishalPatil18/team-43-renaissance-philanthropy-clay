from __future__ import annotations

from typing import Any

import pytest

from claysandbox.contracts.execution import RunRequest
from claysandbox.contracts.fakes.pricing import FixedPriceTable
from claysandbox.contracts.manifest import ComponentRef
from claysandbox.contracts.spec import BudgetSpec, EvalLimits, EvalSpec, NamedComponent
from claysandbox.runtime.estimate import CostEstimator, query_token_history

PRICES = FixedPriceTable(input_per_1k=0.001, output_per_1k=0.004)


class HistoryStore:
    """Stands in for WS3's run store: a table of (template, model, harness, in, out)."""

    def __init__(self, rows: list[tuple[str, str, str, int, int]]) -> None:
        self.rows = rows
        self.calls: list[tuple[str, str, str | None]] = []

    def token_history(
        self, template: str, model_id: str, harness: str | None
    ) -> list[tuple[int, int]]:
        self.calls.append((template, model_id, harness))
        return [
            (i, o)
            for t, m, h, i, o in self.rows
            if t == template and m == model_id and (harness is None or h == harness)
        ]


def request(
    n: int,
    template: str = "T1",
    model_id: str = "m1",
    harness: str = "strands",
    config: str = "base",
) -> RunRequest:
    return RunRequest(
        run_id=f"r{n}",
        eval_id="e1",
        config_name=config,
        template=template,
        task_instance_id=f"{template}@aoi{n}",
        model=ComponentRef(kind="model", name="bedrock", params={"model_id": model_id}),
        harness=ComponentRef(kind="harness", name=harness),
        toolset=ComponentRef(kind="toolset", name="T1"),
    )


def spec(cap: float | None = None, **kwargs: Any) -> EvalSpec:
    return EvalSpec(name="t", budget=BudgetSpec(eval=EvalLimits(max_usd=cap)), **kwargs)


def test_median_of_matching_history_is_used() -> None:
    store = HistoryStore(
        [
            ("T1", "m1", "strands", 1000, 100),
            ("T1", "m1", "strands", 3000, 300),
            ("T1", "m1", "strands", 5000, 500),
            ("T1", "m1", "converse_loop", 90000, 9000),  # other harness: ignored
            ("T2", "m1", "strands", 90000, 9000),  # other template: ignored
        ]
    )
    est = CostEstimator(store, PRICES).estimate([request(1)], spec())  # type: ignore[arg-type]
    (line,) = est.lines
    assert (line.input_tokens, line.output_tokens) == (3000, 300)
    assert line.basis == "history_template_model_harness" and line.sample_size == 3
    assert line.agent_usd == pytest.approx(3 * 0.001 + 0.3 * 0.004)
    assert est.notes == []


def test_falls_back_to_template_and_model_when_the_harness_has_no_history() -> None:
    store = HistoryStore([("T1", "m1", "strands", 2000, 200), ("T1", "m1", "strands", 4000, 400)])
    est = CostEstimator(store, PRICES).estimate([request(1, harness="converse_loop")], spec())  # type: ignore[arg-type]
    (line,) = est.lines
    assert line.basis == "history_template_model"
    assert (line.input_tokens, line.output_tokens) == (3000, 300)
    assert store.calls == [("T1", "m1", "converse_loop"), ("T1", "m1", None)]


def test_falls_back_to_a_labelled_default_guess_with_no_history() -> None:
    est = CostEstimator(HistoryStore([]), PRICES).estimate([request(1)], spec())  # type: ignore[arg-type]
    (line,) = est.lines
    assert line.basis == "default_guess" and line.sample_size == 0
    assert line.input_tokens + line.output_tokens == 20_000  # code fallback
    assert any("default token guesses" in n for n in est.notes)


def test_defaults_come_from_the_price_table_when_it_has_them() -> None:
    class WithDefaults(FixedPriceTable):
        defaults = {"tokens_per_run": {"T3": 30_000}, "input_share": 0.5}

    est = CostEstimator(None, WithDefaults(0.001, 0.004)).estimate([request(1, "T3")], spec())
    assert (est.lines[0].input_tokens, est.lines[0].output_tokens) == (15_000, 15_000)


def test_a_store_that_cannot_answer_falls_back_to_defaults_and_says_so() -> None:
    class Broken:
        def query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
            raise RuntimeError("no runs directory")

    est = CostEstimator(Broken(), PRICES).estimate([request(1), request(2)], spec())  # type: ignore[arg-type]
    assert all(line.basis == "default_guess" for line in est.lines)
    assert any("history was unavailable" in n for n in est.notes)


def test_store_with_only_query_is_used_with_a_parameterised_statement() -> None:
    seen: dict[str, Any] = {}

    class QueryOnly:
        root = "runs"

        def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
            seen["sql"], seen["params"] = sql, params
            return [
                {"input_tokens": 100, "output_tokens": 10},
                {"input_tokens": 300, "output_tokens": 30},
            ]

    rows = query_token_history(QueryOnly(), "T1", "m1", "strands")  # type: ignore[arg-type]
    assert rows == [(100, 10), (300, 30)]
    assert seen["params"] == {"model_id": "m1", "template_prefix": "T1@", "harness": "strands"}
    assert "read_json('runs/*/trace.jsonl'" in seen["sql"] and "$model_id" in seen["sql"]


def test_unsafe_store_root_is_rejected() -> None:
    class Evil:
        root = "runs'); DROP TABLE x; --"

        def query(self, sql: str, params: Any = None) -> list[dict[str, Any]]:
            raise AssertionError("must not run")

    from claysandbox.contracts.errors import ConfigError

    with pytest.raises(ConfigError):
        query_token_history(Evil(), "T1", "m1", None)  # type: ignore[arg-type]


def test_totals_per_configuration_and_cap_flag() -> None:
    requests = [request(1, config="base"), request(2, config="base"), request(3, config="sonnet")]
    store = HistoryStore([("T1", "m1", "strands", 10_000, 1_000)])
    one = 10 * 0.001 + 1 * 0.004
    est = CostEstimator(store, PRICES).estimate(requests, spec(cap=0.02))  # type: ignore[arg-type]
    assert est.agent_usd == pytest.approx(3 * one)
    assert est.per_config == {"base": pytest.approx(2 * one), "sonnet": pytest.approx(one)}
    assert est.total_usd == pytest.approx(3 * one)
    assert est.eval_cap_usd == 0.02 and est.exceeds_eval_cap is True
    assert est.price_table_version == "fixed-test"
    ok = CostEstimator(store, PRICES).estimate(requests, spec(cap=10))  # type: ignore[arg-type]
    assert ok.exceeds_eval_cap is False
    assert CostEstimator(store, PRICES).estimate(requests, spec()).exceeds_eval_cap is False  # type: ignore[arg-type]


def test_summary_and_llm_evaluator_cost_are_added_per_run() -> None:
    s = spec(
        summary=NamedComponent(name="llm", params={"model_id": "sum"}),
        evaluators=[
            NamedComponent(name="workflow"),
            NamedComponent(name="llm_process", params={"model_id": "judge", "k": 2}),
        ],
    )
    store = HistoryStore([("T1", "m1", "strands", 1000, 100)])
    est = CostEstimator(store, PRICES).estimate([request(1), request(2)], s)  # type: ignore[arg-type]
    summary = 6 * 0.001 + 0.8 * 0.004
    judge = 2 * (8 * 0.001 + 0.6 * 0.004)
    assert est.lines[0].evaluation_usd == pytest.approx(summary + judge)
    assert est.evaluation_usd == pytest.approx(2 * (summary + judge))


def test_unpriced_evaluation_models_are_noted_not_fatal() -> None:
    class OnlyM1(FixedPriceTable):
        def has(self, model_id: str) -> bool:
            return model_id == "m1"

    s = spec(summary=NamedComponent(name="llm", params={"model_id": "unknown"}))
    est = CostEstimator(HistoryStore([]), OnlyM1(0.001, 0.004)).estimate([request(1)], s)  # type: ignore[arg-type]
    assert est.evaluation_usd == 0
    assert any("No price for the summary model 'unknown'" in n for n in est.notes)


def test_requester_pays_reads_are_added_from_defaults() -> None:
    class WithData(FixedPriceTable):
        defaults = {"requester_pays_gb_per_run": {"T1": 2.0}}

        def data_cost(self, kind: str, amount: float) -> float:
            return amount * 0.09

    est = CostEstimator(None, WithData(0, 0)).estimate([request(1), request(2)], spec())
    assert est.data_usd == pytest.approx(2 * 2.0 * 0.09)
    assert est.total_usd == pytest.approx(est.data_usd)


def test_a_configuration_without_a_model_id_is_a_config_error() -> None:
    from claysandbox.contracts.errors import ConfigError

    bad = request(1)
    bad.model.params.clear()
    with pytest.raises(ConfigError):
        CostEstimator(None, PRICES).estimate([bad], spec())


def test_empty_plan_estimates_zero() -> None:
    est = CostEstimator(None, PRICES).estimate([], spec(cap=1))
    assert est.total_usd == 0 and est.lines == [] and not est.exceeds_eval_cap


def test_fargate_compute_is_added_only_for_the_fargate_executor() -> None:
    from claysandbox.runtime.pricing import YamlPriceTable

    prices = YamlPriceTable()
    plan = [request(1, model_id="us.amazon.nova-lite-v1:0")]
    local = CostEstimator(None, prices).estimate(plan, spec())
    fargate = CostEstimator(None, prices).estimate(
        plan, spec(executor=NamedComponent(name="fargate", params={"vcpus": 2, "memory_gb": 4}))
    )
    assert local.compute_usd == 0 and "Fargate" not in " ".join(local.notes)
    hours = 120 / 3600
    expected = 2 * hours * 0.04048 + 4 * hours * 0.004445
    assert fargate.compute_usd == pytest.approx(expected)
    assert fargate.total_usd == pytest.approx(local.total_usd + expected)
    assert fargate.lines[0].compute_usd == pytest.approx(expected)
    assert any("Fargate compute" in n for n in fargate.notes)
