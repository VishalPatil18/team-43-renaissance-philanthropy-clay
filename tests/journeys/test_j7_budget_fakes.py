"""J7 (budget guard) on fakes, for both harnesses (PRI-R2-01, FR-11.1 to FR-11.6)."""

from __future__ import annotations

from typing import Any

import pytest

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.contracts.fakes.model import text_reply, tool_reply
from claysandbox.contracts.fakes.pricing import FixedPriceTable
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.runtime import EvalBudget, RunOutcome
from claysandbox.contracts.spec import RunLimits
from claysandbox.contracts.tools import ToolResult
from claysandbox.runtime.guard import CompositeGuard, LoopGuard, RunBudgetGuard, build_guard
from claysandbox.runtime.testing import SEARCH_NAME, Harnessed, build_context

HARNESSES = ["strands", "converse_loop"]
ANSWER = '{"items": ["a"]}'


def script(steps: int = 4, **tokens: int) -> list[Any]:
    """``steps`` tool-using model calls (different args each time) and then an answer."""
    replies: list[Any] = [
        tool_reply((SEARCH_NAME, {"collection": "naip", "limit": i + 1}, f"tu{i}"), **tokens)
        for i in range(steps)
    ]
    return [*replies, text_reply(ANSWER, **tokens)]


def run(name: str, h: Harnessed) -> RunOutcome:
    try:
        return resolve("harness", name)({}).run(h.ctx)
    finally:
        h.close()


def stops(h: Harnessed) -> list[Any]:
    return [e for e in h.sink.events if e.type == "guard_stop"]


@pytest.mark.parametrize("name", HARNESSES)
def test_max_steps_stops_the_run_with_the_right_event_and_state(name: str) -> None:
    h = build_context(script(), guard=build_guard(RunLimits(max_steps=1)))
    outcome = run(name, h)
    assert outcome.state == "budget_stopped"
    (stop,) = stops(h)
    assert (stop.limit, stop.limit_value, stop.observed_value) == ("max_steps", 1, 1)
    assert (stop.error.source, stop.error.kind) == ("budget", "budget_exceeded")
    assert outcome.error is not None and outcome.error.kind == "budget_exceeded"
    assert len(h.model.calls) == 1  # the second model call was never made


@pytest.mark.parametrize("name", HARNESSES)
def test_with_no_limits_the_same_script_completes(name: str) -> None:
    h = build_context(script(), guard=build_guard(RunLimits()))
    outcome = run(name, h)
    assert outcome.state == "completed" and outcome.output == {"items": ["a"]}
    assert stops(h) == []
    assert len(h.model.calls) == 5


@pytest.mark.parametrize("name", HARNESSES)
def test_max_tokens_stops_the_run(name: str) -> None:
    h = build_context(
        script(input_tokens=400, output_tokens=100),
        guard=build_guard(RunLimits(max_tokens=1000)),
    )
    outcome = run(name, h)
    assert outcome.state == "budget_stopped"
    (stop,) = stops(h)
    assert stop.limit == "max_tokens" and stop.observed_value == 1000
    assert len(h.model.calls) == 2  # 500 + 500 tokens used, the third call is refused


@pytest.mark.parametrize("name", HARNESSES)
def test_max_usd_stops_the_run_and_the_overshoot_is_visible(name: str) -> None:
    h = build_context(
        script(input_tokens=1000, output_tokens=0),
        guard=build_guard(RunLimits(max_usd=1.5)),
        prices=FixedPriceTable(input_per_1k=1.0),  # $1 per model call
    )
    outcome = run(name, h)
    assert outcome.state == "budget_stopped"
    (stop,) = stops(h)
    assert stop.limit == "max_usd" and stop.limit_value == 1.5 and stop.observed_value == 2.0
    assert len(h.model.calls) == 2


@pytest.mark.parametrize("name", HARNESSES)
def test_max_seconds_stops_the_run(name: str) -> None:
    now = [0.0]
    budget = RunBudgetGuard(max_seconds=10, clock=lambda: now[0])

    def slow_tool(_: dict[str, Any]) -> ToolResult:
        now[0] += 25  # the tool "takes" 25 seconds
        return ToolResult(text="ok")

    h = build_context(
        script(),
        guard=CompositeGuard(budget, LoopGuard(3)),
        handlers={("stac", "search_items"): slow_tool},
    )
    outcome = run(name, h)
    budget.close()
    assert outcome.state == "budget_stopped"
    (stop,) = stops(h)
    assert stop.limit == "max_seconds" and stop.observed_value == 25
    assert len(h.model.calls) == 1


def test_each_limit_fires_once_and_only_its_own() -> None:
    for limits, expected in [
        (RunLimits(max_steps=2), "max_steps"),
        (RunLimits(max_tokens=100), "max_tokens"),
        (RunLimits(max_usd=0.5), "max_usd"),
    ]:
        h = build_context(
            script(input_tokens=100, output_tokens=0),
            guard=build_guard(limits),
            prices=FixedPriceTable(input_per_1k=10.0),
        )
        outcome = run("converse_loop", h)
        assert outcome.state == "budget_stopped"
        assert [s.limit for s in stops(h)] == [expected]


def test_eval_budget_stops_launching_at_the_cap() -> None:
    """The service adds each run's cost and stops launching when ``exhausted`` (FR-11.6)."""
    budget = EvalBudget(max_usd=1.0)
    launched = 0
    for _ in range(10):
        if budget.exhausted:
            break
        h = build_context(
            [text_reply(ANSWER, input_tokens=1000, output_tokens=0)],
            guard=build_guard(None),
            prices=FixedPriceTable(input_per_1k=0.4),
        )
        run("converse_loop", h)
        launched += 1
        budget.add(sum(e.cost_usd for e in h.sink.events if e.type == "model_call"))  # type: ignore[union-attr]
    assert launched == 3  # 0.4 + 0.4 + 0.4 >= 1.0
    assert budget.exhausted
