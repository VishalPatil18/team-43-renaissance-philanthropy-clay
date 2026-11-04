"""Workflow evaluator v1 (BAR-R1-01): all eight sub-scores, capability matching, recovery."""

import pytest

import claysandbox.evaluation.workflow  # noqa: F401  (registers the evaluators)
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.task import ArgumentConstraint, OrderingRule
from claysandbox.evaluation.workflow import resolve_workflow
from tests.fixtures.traces import load
from tests.unit.evaluation._mini import (
    GOOD_ARGS,
    GOOD_OUTPUT,
    context,
    err,
    error_event,
    final,
    guard,
    model,
    tool,
    trace,
)

ALL = {
    "tool_call_validity",
    "argument_constraints",
    "required_coverage",
    "ordering",
    "forbidden_tools",
    "recovery",
    "step_efficiency",
    "done_condition",
}


def v1():
    return resolve("evaluator", "workflow")()


def sub(a, name):
    return next(s for s in a.subscores if s.name == name)


def score(t, name, **workflow):
    return sub(v1().assess(t, *context(**workflow)), name).value


# ------------------------------------------------------------------ registry and fixtures
def test_both_versions_stay_resolvable():
    assert resolve("evaluator", "workflow").version == "1"
    assert resolve("evaluator", "workflow@1").version == "1"
    assert resolve("evaluator", "workflow@0").version == "0"
    assert resolve_workflow("0").version == "0"
    assert resolve_workflow().version == "1"


def test_good_t1_composite_one_with_all_subscores():
    a = v1().assess(*load("good_t1"))
    assert {s.name for s in a.subscores} == ALL
    assert a.composite == 1.0
    assert a.success is True
    assert all(s.notes for s in a.subscores)


def test_errors_t1_lowers_validity_and_recovery():
    a = v1().assess(*load("errors_t1"))
    assert sub(a, "tool_call_validity").value < 1
    # timeout recovered (0.25) + unknown_tool with no capability, unrecovered (1) over 2 errors
    assert sub(a, "recovery").value == pytest.approx(1 - 1.25 / 2)
    assert a.success is True


def test_errors_t1_recovery_beats_the_same_run_without_the_retry():
    trace_, manifest, reference = load("errors_t1")
    dropped = {"fixture-errors_t1:3", "fixture-errors_t1:4"}  # the successful retry
    unrecovered = trace_.model_copy(
        update={"events": [e for e in trace_.events if e.event_id not in dropped]}
    )
    recovered = sub(v1().assess(trace_, manifest, reference), "recovery").value
    worse = sub(v1().assess(unrecovered, manifest, reference), "recovery").value
    assert 0 < recovered < 1
    assert worse < recovered


def test_loop_t1_is_not_a_success():
    a = v1().assess(*load("loop_t1"))
    assert a.success is False


# ------------------------------------------------------------------ one test per sub-score
def test_argument_constraints_counts_applicable_checks_per_call():
    wrong_year = {**GOOD_ARGS, "datetime": "2019"}
    t = trace(
        model(),
        tool("imagery_search", args=GOOD_ARGS),
        model(),
        tool("imagery_search", args=wrong_year),
        model(),
        tool("geocode", args={"query": "kern"}, server="osm", name="geocode"),
        final(GOOD_OUTPUT),
    )
    a = v1().assess(t, *context())
    s = sub(a, "argument_constraints")
    assert s.value == pytest.approx(5 / 6)
    assert "mini:4" in s.evidence and "mini:6" not in s.evidence
    assert any("datetime_within_year" in n and "mini:4" in n for n in s.notes)


def test_argument_constraints_skip_not_applicable_checks():
    t = trace(model(), tool("imagery_search", args={"collection": "naip"}), final(GOOD_OUTPUT))
    assert score(t, "argument_constraints") == 1.0


def test_ordering_first_successful_before_must_precede_first_after():
    rule = [OrderingRule(before="geocode", after="imagery_search")]
    geo = tool("geocode", server="osm", name="geocode")
    in_order = trace(model(), geo, model(), tool("imagery_search"), final(GOOD_OUTPUT))
    reversed_ = trace(model(), tool("imagery_search"), model(), geo, final(GOOD_OUTPUT))
    failed_geo = trace(
        model(),
        tool("geocode", "error", server="osm", name="geocode", error=err("tool", "tool_error")),
        model(),
        tool("imagery_search"),
        final(GOOD_OUTPUT),
    )
    assert score(in_order, "ordering", ordering=rule) == 1.0
    assert score(reversed_, "ordering", ordering=rule) == 0.0
    assert score(failed_geo, "ordering", ordering=rule) == 0.0


def test_ordering_optional_first_applies_only_when_before_is_used():
    rule = [OrderingRule(before="geocode", after="imagery_search", optional_first=True)]
    no_geo = trace(model(), tool("imagery_search"), final(GOOD_OUTPUT))
    late_geo = trace(
        model(),
        tool("imagery_search"),
        model(),
        tool("geocode", server="osm", name="geocode"),
        final(GOOD_OUTPUT),
    )
    assert score(no_geo, "ordering", ordering=rule) == 1.0
    assert score(late_geo, "ordering", ordering=rule) == 0.0
    strict = [OrderingRule(before="geocode", after="imagery_search")]
    assert score(no_geo, "ordering", ordering=strict) == 0.0


def test_forbidden_tools():
    t = trace(
        model(),
        tool("dataset_discovery", server="roda", name="search_datasets"),
        model(),
        tool("imagery_search"),
        final(GOOD_OUTPUT),
    )
    a = v1().assess(t, *context(forbidden=["dataset_discovery"]))
    s = sub(a, "forbidden_tools")
    assert s.value == 0.0 and s.evidence == ["mini:2"]
    assert score(t, "forbidden_tools", forbidden=[]) == 1.0


def test_recovered_error_costs_less_than_unrecovered():
    timeout = tool("imagery_search", "timeout", error=err("tool", "tool_timeout"))
    recovered = trace(model(), timeout, model(), tool("imagery_search"), final(GOOD_OUTPUT))
    unrecovered = trace(
        model(), timeout, model(), tool("geocode", server="osm", name="g"), final(GOOD_OUTPUT)
    )
    clean = trace(model(), tool("imagery_search"), final(GOOD_OUTPUT))
    assert score(clean, "recovery") == 1.0
    assert score(recovered, "recovery") == pytest.approx(0.75)
    assert score(unrecovered, "recovery") == 0.0
    assert score(recovered, "recovery", recovery={"recovered_penalty": 0.5}) == 0.5


def test_recovery_ignores_budget_and_infra_errors():
    t = trace(
        model(),
        tool("imagery_search", "error", error=err("infra", "network")),
        error_event("budget", "budget_exceeded"),
        final(GOOD_OUTPUT),
    )
    assert score(t, "recovery") == 1.0


@pytest.mark.parametrize(
    "steps, expected", [(3, 1.0), (4, 1.0), (5, 10 / 11), (15, 0.0), (20, 0.0)]
)
def test_step_efficiency_linear_between_expected_and_limit(steps, expected):
    t = trace(*[model() for _ in range(steps)], final(GOOD_OUTPUT))
    assert score(t, "step_efficiency", expected_steps=4, step_limit=15) == pytest.approx(expected)


def test_guard_stop_fails_success_even_with_good_output():
    t = trace(model(), tool("imagery_search"), final(GOOD_OUTPUT), guard("max_steps"))
    a = v1().assess(t, *context())
    assert sub(a, "done_condition").value == 1.0
    assert a.success is False


# ------------------------------------------------------------------ capability mapping
def test_same_rule_scores_t0_and_t1_tool_sets_identically():
    """FR-4.10: rules name capabilities, so renaming servers and tools changes nothing."""

    def run(search, geocode):
        return trace(
            model(),
            tool("geocode", args={"q": "kern"}, server=geocode[0], name=geocode[1]),
            model(),
            tool("imagery_search", args=GOOD_ARGS, server=search[0], name=search[1]),
            final(GOOD_OUTPUT),
        )

    t1 = run(("stac", "search_items"), ("osm", "geocode"))
    t0 = run(("planetary-computer", "stac_search"), ("nominatim", "lookup_place"))
    manifest, reference = context(
        required=["imagery_search", "geocode"],
        ordering=[OrderingRule(before="geocode", after="imagery_search")],
        argument_constraints=[
            ArgumentConstraint(capability="imagery_search", check="collection_in", values=["naip"]),
            ArgumentConstraint(capability="imagery_search", check="bbox_intersects_aoi"),
        ],
    )
    a0 = v1().assess(t0, manifest, reference)
    a1 = v1().assess(t1, manifest, reference)
    assert a0.stable_json() == a1.stable_json()
    assert a1.composite == 1.0


def test_free_standing_unknown_tool_error_counts_as_an_invalid_attempt():
    """arch §10.1: unknown_tool/invalid_args are invalid attempts even when the harness reports
    them as a free-standing error event rather than a rejected tool_call."""
    from claysandbox.contracts.registry import resolve
    from claysandbox.contracts.trace import ErrorEvent, ErrorInfo
    from tests.fixtures.traces import load

    trace, manifest, reference = load("good_t1")
    err = ErrorEvent(
        run_id=trace.run_id,
        seq=50,
        event_id=f"{trace.run_id}:50",
        error=ErrorInfo(source="agent", kind="unknown_tool", message="fly_drone not in tool set"),
    )
    flawed = trace.model_copy(update={"events": [*trace.events[:-2], err, *trace.events[-2:]]})
    a = resolve("evaluator", "workflow")().assess(flawed, manifest, reference)
    validity = next(s for s in a.subscores if s.name == "tool_call_validity")
    assert validity.value < 1.0
    assert err.event_id in validity.evidence


def test_error_event_about_a_rejected_tool_call_is_not_counted_twice():
    from claysandbox.contracts.registry import resolve
    from claysandbox.contracts.trace import ErrorEvent, ErrorInfo
    from tests.fixtures.traces import load

    trace, manifest, reference = load("errors_t1")
    rejected = next(e for e in trace.events if e.type == "tool_call" and e.status == "rejected")
    dup = ErrorEvent(
        run_id=trace.run_id,
        seq=50,
        event_id=f"{trace.run_id}:50",
        error=ErrorInfo(
            source="agent", kind="unknown_tool", message="dup", related_event_id=rejected.event_id
        ),
    )
    flawed = trace.model_copy(update={"events": [*trace.events[:-2], dup, *trace.events[-2:]]})
    ev = resolve("evaluator", "workflow")()
    before = next(
        s for s in ev.assess(trace, manifest, reference).subscores if s.name == "tool_call_validity"
    )
    after = next(
        s
        for s in ev.assess(flawed, manifest, reference).subscores
        if s.name == "tool_call_validity"
    )
    assert after.value == before.value
