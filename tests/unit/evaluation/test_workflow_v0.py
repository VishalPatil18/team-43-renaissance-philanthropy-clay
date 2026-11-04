"""Workflow evaluator v0 (BAR-R0-01): validity, required coverage, done condition."""

import claysandbox.evaluation.workflow  # noqa: F401  (registers the evaluators)
from claysandbox.contracts.registry import resolve
from tests.fixtures.traces import load
from tests.unit.evaluation._mini import (
    GOOD_ARGS,
    GOOD_OUTPUT,
    context,
    err,
    final,
    model,
    tool,
    trace,
)


def v0():
    return resolve("evaluator", "workflow@0")()


def scores(a):
    return {s.name: s.value for s in a.subscores}


def test_good_t1_scores_composite_one():
    trace, manifest, reference = load("good_t1")
    a = v0().assess(trace, manifest, reference)
    assert a.composite == 1.0
    assert a.success is True
    assert set(scores(a)) == {"tool_call_validity", "required_coverage", "done_condition"}
    assert a.evaluator.name == "workflow" and a.evaluator.version == "0"


def test_errors_t1_unknown_tool_lowers_validity():
    a = v0().assess(*load("errors_t1"))
    validity = next(s for s in a.subscores if s.name == "tool_call_validity")
    assert validity.value == 2 / 3
    assert "fixture-errors_t1:6" in validity.evidence
    assert a.composite is not None and a.composite < 1.0


def test_loop_t1_guard_stop_is_not_a_success():
    a = v0().assess(*load("loop_t1"))
    assert a.success is False
    assert "fixture-loop_t1:8" in a.evidence


def test_invalid_args_and_malformed_call_count_as_invalid():
    t = trace(
        model(),
        tool("imagery_search", "rejected", error=err("agent", "invalid_args")),
        model(error=err("agent", "malformed_call")),
        model(),
        tool("imagery_search", "ok", GOOD_ARGS),
        final(GOOD_OUTPUT),
    )
    a = v0().assess(t, *context())
    assert scores(a)["tool_call_validity"] == 1 / 3


def test_required_coverage_needs_a_successful_call():
    t = trace(
        model(),
        tool("imagery_search", "timeout", error=err("tool", "tool_timeout")),
        final(GOOD_OUTPUT),
    )
    a = v0().assess(t, *context(required=["imagery_search", "geocode"]))
    assert scores(a)["required_coverage"] == 0.0
    t2 = trace(model(), tool("imagery_search"), final(GOOD_OUTPUT))
    assert (
        scores(v0().assess(t2, *context(required=["imagery_search", "geocode"])))[
            "required_coverage"
        ]
        == 0.5
    )


def test_done_condition_fails_on_empty_or_schema_violating_output():
    for out in ({"items": []}, {"wrong": 1}, "not json"):
        a = v0().assess(trace(model(), tool("imagery_search"), final(out)), *context())
        assert scores(a)["done_condition"] == 0.0, out
        assert a.success is False
    a = v0().assess(trace(model(), tool("imagery_search"), final('{"items": ["x"]}')), *context())
    assert scores(a)["done_condition"] == 1.0


def test_done_condition_zero_without_final_output():
    a = v0().assess(trace(model(), tool("imagery_search")), *context())
    assert scores(a)["done_condition"] == 0.0


def test_composite_uses_reference_weights():
    t = trace(
        model(),
        tool(None, "rejected", error=err("agent", "unknown_tool")),
        model(),
        tool("imagery_search"),
        final(GOOD_OUTPUT),
    )
    manifest, reference = context()
    reference = reference.model_copy(update={"weights": {"tool_call_validity": 2.0}})
    a = v0().assess(t, manifest, reference)
    # validity 0.5 (weight 2), coverage 1, done 1 -> (1 + 1 + 1) / 4
    assert a.composite == 0.75


def test_infra_run_is_neither_success_nor_failure():
    a = v0().assess(
        trace(model(), tool("imagery_search"), final(GOOD_OUTPUT), state="infra_error"), *context()
    )
    assert a.success is None
