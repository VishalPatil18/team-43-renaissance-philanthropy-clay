"""LLM process evaluator (BAR-R2-02). Tested at assess() and check_judge_family()."""

from __future__ import annotations

import json

import pytest

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.model import FakeModelAdapter, text_reply
from claysandbox.evaluation.llm_process import LLMProcessEvaluator, check_judge_family
from tests.fixtures.traces import load


def test_judge_family_rejects_same_family_and_strips_region_prefix():
    with pytest.raises(ConfigError):
        check_judge_family("us.amazon.nova-pro-v1:0", ["amazon.nova-lite-v1:0"])
    with pytest.raises(ConfigError):
        check_judge_family(
            "anthropic.claude-sonnet", ["eu.amazon.nova-lite-v1:0", "global.anthropic.claude-x"]
        )
    check_judge_family(
        "us.anthropic.claude-sonnet-4", ["amazon.nova-pro-v1:0", "us.amazon.nova-lite"]
    )


def _reply(items: list[dict], **kw):
    return text_reply(json.dumps({"items": items}), **kw)


def _item(name: str, score: float, ids: list[str] | None = None, reason: str = "ok"):
    return {"name": name, "score": score, "event_ids": ids or [], "reason": reason}


def _evaluator(script, **params):
    model = FakeModelAdapter(script, model_id="judge-x")
    p = {"model_id": "judge-x", **params}
    return LLMProcessEvaluator(p, model=model), model


def test_k_repeats_stored_with_mean_spread_and_per_item_means():
    trace, manifest, ref = load("good_t1")
    eid = trace.events[1].event_id
    script = [
        _reply([_item("planning", 0.9, [eid]), _item("recovery", 0.7)]),
        _reply([_item("planning", 0.7, [eid]), _item("recovery", 0.5)]),
        _reply([_item("planning", 0.5), _item("recovery", 0.3)]),
    ]
    ev, model = _evaluator(script)
    a = ev.assess(trace, manifest, ref)

    assert a.kind == "process" and a.run_id == manifest.run_id
    assert a.evaluator.name == "llm_process" and a.evaluator.version == "1"
    assert a.repeats == pytest.approx([0.8, 0.6, 0.4])
    assert a.composite == pytest.approx(0.6)
    assert a.metrics["spread"] == pytest.approx(0.4)
    assert a.metrics["stdev"] == pytest.approx(0.2)
    assert a.metrics["item.planning"] == pytest.approx(0.7)
    assert a.metrics["item.recovery"] == pytest.approx(0.5)
    by_name = {s.name: s for s in a.subscores}
    assert by_name["planning"].value == pytest.approx(0.7)
    assert by_name["planning"].evidence == [eid]
    assert len(model.calls) == 3
    assert model.calls[0]["params"]["temperature"] == 0.0
    prompt = model.calls[0]["messages"][0]["content"][0]["text"]
    assert eid in prompt and ref.process_rubric in prompt


def test_parse_failure_is_retried_once_and_code_fences_are_stripped():
    trace, manifest, ref = load("good_t1")
    fenced = "```json\n" + json.dumps({"items": [_item("planning", 0.8)]}) + "\n```"
    script = [
        text_reply("sorry, here is my opinion"),  # repeat 1, bad
        text_reply(fenced),  # repeat 1, retry ok
        _reply([_item("planning", 0.6)]),
        _reply([_item("planning", 0.4)]),
    ]
    ev, model = _evaluator(script)
    a = ev.assess(trace, manifest, ref)
    assert a.repeats == pytest.approx([0.8, 0.6, 0.4])
    assert len(model.calls) == 4
    assert any("retrying" in n for n in a.notes)


def test_repeat_failing_twice_is_noted_and_excluded():
    trace, manifest, ref = load("good_t1")
    script = [
        _reply([_item("planning", 0.8)]),
        text_reply("nope"),
        text_reply('{"items": []}'),
        _reply([_item("planning", 0.6)]),
    ]
    ev, _ = _evaluator(script)
    a = ev.assess(trace, manifest, ref)
    assert a.repeats == pytest.approx([0.8, 0.6])
    assert any("excluded" in n for n in a.notes)


def test_all_repeats_failing_gives_no_composite():
    trace, manifest, ref = load("good_t1")
    ev, _ = _evaluator([text_reply("x")] * 6)
    a = ev.assess(trace, manifest, ref)
    assert a.composite is None and a.repeats is None


def test_out_of_range_score_counts_as_parse_failure():
    trace, manifest, ref = load("good_t1")
    script = [_reply([_item("planning", 1.7)]), _reply([_item("planning", 0.5)])]
    ev, _ = _evaluator(script, k=1)
    assert ev.assess(trace, manifest, ref).repeats == [0.5]


def test_unknown_event_ids_are_dropped_and_counted():
    trace, manifest, ref = load("good_t1")
    real = trace.events[2].event_id
    script = [_reply([_item("planning", 0.5, [real, "made-up:1", "made-up:2"])])] * 2
    ev, _ = _evaluator(script, k=2)
    a = ev.assess(trace, manifest, ref)
    assert a.subscores[0].evidence == [real]
    assert a.metrics["dropped_event_ids"] == 4


class _Prices:
    version = "t"

    def model_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        return input_tokens * 0.001 + output_tokens * 0.01

    def data_cost(self, kind: str, amount: float) -> float:
        return 0.0

    def has(self, model_id: str) -> bool:
        return True


def test_cost_is_summed_over_every_call_including_retries():
    trace, manifest, ref = load("good_t1")
    script = [
        text_reply("bad", input_tokens=100, output_tokens=10),
        _reply([_item("planning", 0.5)], input_tokens=100, output_tokens=10),
    ]
    model = FakeModelAdapter(script, model_id="judge-x")
    ev = LLMProcessEvaluator({"model_id": "judge-x", "k": 1}, model=model, price_table=_Prices())
    assert ev.assess(trace, manifest, ref).cost_usd == pytest.approx(2 * (0.1 + 0.1))


def test_missing_judge_model_is_a_config_error():
    trace, manifest, ref = load("good_t1")
    with pytest.raises(ConfigError):
        LLMProcessEvaluator({"model_id": "judge-x"}).assess(trace, manifest, ref)


def test_registered_as_process_evaluator():
    from claysandbox.contracts.registry import resolve

    cls = resolve("evaluator", "llm_process")
    assert cls is LLMProcessEvaluator
    assert (cls.kind, cls.deterministic, cls.version) == ("process", False, "1")


def _digest_judge():
    """A fake judge whose score depends on the digest it is shown."""
    from claysandbox.contracts.runtime import ModelResponse

    class Judge(FakeModelAdapter):
        def converse(self, messages, system, tools, params) -> ModelResponse:
            text = messages[0]["content"][0]["text"]
            bad = ("error" in text.split("## Process rubric")[0]) + (
                "limit" in text.split("## Process rubric")[0]
            )
            score = 0.9 - 0.4 * bad
            return _reply([_item("planning", score), _item("recovery", score)])

    return Judge([], model_id="judge-x")


def test_planted_bad_traces_score_lower_than_good_ones():
    ev = LLMProcessEvaluator({"model_id": "judge-x"}, model=_digest_judge())
    scores = {}
    for name in ("good_t1", "errors_t1", "loop_t1"):
        trace, manifest, ref = load(name)
        scores[name] = ev.assess(trace, manifest, ref).composite
    assert scores["good_t1"] > (scores["errors_t1"] + scores["loop_t1"]) / 2
    assert scores["good_t1"] > max(scores["errors_t1"], scores["loop_t1"])


def test_infra_error_events_never_reach_the_judge():
    """FR-4.4: infra errors must not affect any score, so the judge must not see them."""
    from claysandbox.contracts.trace import ErrorEvent, ErrorInfo

    trace, manifest, reference = load("good_t1")
    infra = ErrorEvent(
        run_id=trace.run_id,
        seq=99,
        event_id=f"{trace.run_id}:99",
        error=ErrorInfo(source="infra", kind="throttled", message="ThrottlingException"),
    )
    noisy = trace.model_copy(update={"events": [*trace.events[:-1], infra, trace.events[-1]]})
    ev, model = _evaluator([_reply([_item("planning", 1.0)])], k=1)
    ev.assess(noisy, manifest, reference)
    sent = json.dumps(model.calls[0]["messages"])
    assert "ThrottlingException" not in sent and ":99" not in sent
