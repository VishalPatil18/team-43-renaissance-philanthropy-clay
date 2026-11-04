from __future__ import annotations

import time
from datetime import UTC, datetime
from typing import Any

import pytest

from claysandbox.contracts.errors import GuardStopped
from claysandbox.contracts.runtime import EvalBudget
from claysandbox.contracts.spec import RunLimits
from claysandbox.contracts.trace import ModelCall, ToolCall
from claysandbox.runtime.guard import LoopGuard, RunBudgetGuard, build_guard


def model_call(inp: int = 0, out: int = 0, cost: float = 0.0) -> ModelCall:
    return ModelCall(
        model_id="m", input_tokens=inp, output_tokens=out, cost_usd=cost, price_table_version="v"
    )


def tool_call(cost: float = 0.0) -> ToolCall:
    return ToolCall(server="s", tool="t", status="ok", cost_usd=cost)


class Clock:
    def __init__(self) -> None:
        self.now = 0.0

    def __call__(self) -> float:
        return self.now


# -- loop guard ---------------------------------------------------------------------------


def test_loop_guard_allows_n_identical_calls_and_blocks_the_next() -> None:
    guard = LoopGuard(3)
    for _ in range(3):
        guard.before_tool_call("stac.search", {"b": 2, "a": 1})
    with pytest.raises(GuardStopped) as info:
        guard.before_tool_call("stac.search", {"a": 1, "b": 2})  # same args, key order differs
    assert info.value.limit == "loop"
    assert (info.value.limit_value, info.value.observed_value) == (3, 4)
    assert (info.value.source, info.value.kind) == ("agent", "loop_detected")


def test_loop_guard_resets_when_the_call_changes() -> None:
    guard = LoopGuard(2)
    for args in ({"a": 1}, {"a": 1}, {"a": 2}, {"a": 2}, {"a": 1}, {"a": 1}):
        guard.before_tool_call("t", args)  # never three in a row


def test_loop_guard_treats_different_tools_as_different_calls() -> None:
    guard = LoopGuard(1)
    guard.before_tool_call("a.x", {})
    guard.before_tool_call("b.x", {})
    with pytest.raises(GuardStopped):
        guard.before_tool_call("b.x", {})


def test_loop_guard_handles_non_json_arguments() -> None:
    moment = datetime(2022, 7, 1, tzinfo=UTC)  # not JSON serialisable by default
    guard = LoopGuard(1)
    guard.before_tool_call("t", {"when": moment})
    with pytest.raises(GuardStopped):
        guard.before_tool_call("t", {"when": moment})


def test_loop_guard_rejects_a_nonsense_limit() -> None:
    with pytest.raises(ValueError):
        LoopGuard(0)


# -- budget guard -------------------------------------------------------------------------


def test_no_limits_means_nothing_is_ever_stopped() -> None:
    guard = RunBudgetGuard()
    for _ in range(50):
        guard.before_model_call()
        guard.before_tool_call("t", {})
        guard.record(model_call(10**6, 10**6, 100.0))
    guard.close()


def test_max_steps_allows_n_model_calls_then_stops() -> None:
    guard = RunBudgetGuard(max_steps=2)
    for _ in range(2):
        guard.before_model_call()
        guard.record(model_call())
    with pytest.raises(GuardStopped) as info:
        guard.before_model_call()
    assert (info.value.limit, info.value.limit_value, info.value.observed_value) == (
        "max_steps",
        2,
        2,
    )
    assert (info.value.source, info.value.kind) == ("budget", "budget_exceeded")


def test_max_tokens_uses_cumulative_input_plus_output() -> None:
    guard = RunBudgetGuard(max_tokens=1000)
    guard.before_model_call()
    guard.record(model_call(600, 300))
    guard.before_model_call()  # 900 < 1000
    guard.record(model_call(80, 40))
    with pytest.raises(GuardStopped) as info:
        guard.before_model_call()
    assert info.value.limit == "max_tokens" and info.value.observed_value == 1020


def test_max_usd_counts_model_and_tool_cost_before_both_kinds_of_call() -> None:
    guard = RunBudgetGuard(max_usd=1.0)
    guard.record(model_call(cost=0.6))
    guard.before_model_call()
    guard.before_tool_call("t", {})
    guard.record(tool_call(cost=0.5))
    for call in (lambda: guard.before_model_call(), lambda: guard.before_tool_call("t", {})):
        with pytest.raises(GuardStopped) as info:
            call()
        assert info.value.limit == "max_usd" and info.value.observed_value == pytest.approx(1.1)


def test_steps_and_tokens_are_not_checked_before_tool_calls() -> None:
    guard = RunBudgetGuard(max_steps=1, max_tokens=1)
    guard.record(model_call(100, 100))
    guard.before_tool_call("t", {})  # tools are only limited by cost and time


def test_max_seconds_checks_elapsed_time_on_both_kinds_of_call() -> None:
    clock = Clock()
    guard = RunBudgetGuard(max_seconds=10, clock=clock)
    guard.before_model_call()  # starts the clock
    clock.now = 9.9
    guard.before_tool_call("t", {})
    clock.now = 12.5
    for call in (lambda: guard.before_model_call(), lambda: guard.before_tool_call("t", {})):
        with pytest.raises(GuardStopped) as info:
            call()
        assert info.value.limit == "max_seconds" and info.value.observed_value == 12.5
    guard.close()


def test_watchdog_timer_flags_the_overrun() -> None:
    guard = RunBudgetGuard(max_seconds=0.05)
    guard.start()
    time.sleep(0.2)
    assert guard._timed_out is True
    with pytest.raises(GuardStopped) as info:
        guard.before_model_call()
    assert info.value.limit == "max_seconds"
    guard.close()


def test_close_cancels_the_watchdog() -> None:
    guard = RunBudgetGuard(max_seconds=0.05)
    guard.start()
    guard.close()
    time.sleep(0.15)
    assert guard._timed_out is False


def test_tool_timeout_is_capped_by_the_time_left() -> None:
    clock = Clock()
    guard = RunBudgetGuard(max_seconds=100, clock=clock)
    guard.start()
    assert guard.tool_timeout(60) == 60
    clock.now = 70
    assert guard.tool_timeout(60) == pytest.approx(30)
    guard.close()
    assert RunBudgetGuard().tool_timeout(60) == 60


def test_totals_report_what_the_run_end_event_needs() -> None:
    guard = RunBudgetGuard()
    guard.record(model_call(10, 5, 0.25))
    guard.record(tool_call(0.5))
    totals = guard.totals()
    assert totals["steps"] == 1 and totals["tokens"] == 15
    assert totals["cost_usd"] == pytest.approx(0.75)
    assert set(totals) == {
        "steps",
        "input_tokens",
        "output_tokens",
        "tokens",
        "cost_usd",
        "wall_ms",
    }


# -- composite / build_guard ----------------------------------------------------------------


def test_build_guard_wires_the_spec_limits_and_the_default_loop_guard() -> None:
    guard = build_guard(RunLimits(max_steps=1))
    guard.before_model_call()
    guard.record(model_call())
    with pytest.raises(GuardStopped) as info:
        guard.before_model_call()
    assert info.value.limit == "max_steps"
    for _ in range(3):
        guard.before_tool_call("t", {"a": 1})
    with pytest.raises(GuardStopped) as loop:
        guard.before_tool_call("t", {"a": 1})
    assert loop.value.limit == "loop"
    assert guard.totals()["steps"] == 1


def test_build_guard_accepts_plain_dicts_and_a_custom_loop_limit() -> None:
    spec: dict[str, Any] = {"max_usd": 0.5}
    guard = build_guard(spec, {"max_identical_calls": 1})
    guard.before_tool_call("t", {})
    with pytest.raises(GuardStopped):
        guard.before_tool_call("t", {})


def test_build_guard_with_nothing_still_has_the_default_loop_guard() -> None:
    guard = build_guard(None, None)
    for _ in range(3):
        guard.before_tool_call("t", {})
    with pytest.raises(GuardStopped):
        guard.before_tool_call("t", {})
    guard.close()


# -- eval budget ------------------------------------------------------------------------------


def test_eval_budget_becomes_exhausted_at_the_cap() -> None:
    budget = EvalBudget(1.0)
    assert not budget.exhausted
    budget.add(0.4)
    budget.add(0.4)
    assert not budget.exhausted and budget.spent == pytest.approx(0.8)
    budget.add(0.2)
    assert budget.exhausted


def test_eval_budget_without_a_cap_is_never_exhausted_and_ignores_negatives() -> None:
    budget = EvalBudget(None)
    budget.add(1e9)
    budget.add(-5)
    assert not budget.exhausted and budget.spent == 1e9
