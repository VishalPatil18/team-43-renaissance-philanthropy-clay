"""Budget guard and loop guard (architecture §9.2, FR-11.1 to FR-11.5).

Guards check *before* each call, so a run can overshoot a limit by at most one call. The
``GuardStop`` event records the observed value, which makes the overshoot visible.

* ``LoopGuard``: allows ``max_identical_calls`` identical consecutive tool calls (default 3) and
  stops the run on the next one.
* ``RunBudgetGuard``: optional ``max_steps``, ``max_tokens``, ``max_usd``, ``max_seconds``. An
  omitted limit is off. A timer sets a flag at ``max_seconds``; the flag is read at the next call
  because an in-flight Bedrock call cannot be interrupted.
* ``CompositeGuard``: runs several guards as one.
* ``build_guard``: builds the composite from the spec's ``budget.run`` and ``loop_guard``.
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from typing import Any

from claysandbox.contracts.errors import GuardStopped
from claysandbox.contracts.spec import LoopGuardSpec, RunLimits
from claysandbox.contracts.trace import ModelCall, ToolCall, TraceEvent

DEFAULT_MAX_IDENTICAL_CALLS = 3


class LoopGuard:
    def __init__(self, max_identical_calls: int = DEFAULT_MAX_IDENTICAL_CALLS) -> None:
        if max_identical_calls < 1:
            raise ValueError("max_identical_calls must be at least 1")
        self.max_identical_calls = max_identical_calls
        self._last: tuple[str, str] | None = None
        self._count = 0
        self._lock = threading.Lock()

    def before_model_call(self) -> None:
        return None

    def before_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        key = (tool, json.dumps(args, sort_keys=True, default=str, separators=(",", ":")))
        with self._lock:
            if key == self._last:
                self._count += 1
            else:
                self._last, self._count = key, 1
            count = self._count
        if count > self.max_identical_calls:
            raise GuardStopped(
                "loop",
                self.max_identical_calls,
                count,
                message=(
                    f"{tool} called {count} times in a row with identical arguments "
                    f"(allowed {self.max_identical_calls})"
                ),
            )

    def record(self, event: TraceEvent) -> None:
        return None

    def tool_timeout(self, default_s: float) -> float:
        return default_s

    def close(self) -> None:
        return None


class RunBudgetGuard:
    def __init__(
        self,
        max_steps: int | None = None,
        max_tokens: int | None = None,
        max_usd: float | None = None,
        max_seconds: float | None = None,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self.max_steps = max_steps
        self.max_tokens = max_tokens
        self.max_usd = max_usd
        self.max_seconds = max_seconds
        self._clock = clock
        self._lock = threading.Lock()
        self._started_at: float | None = None
        self._timer: threading.Timer | None = None
        self._timed_out = False
        self.steps = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.cost_usd = 0.0

    # -- lifecycle ------------------------------------------------------------------------

    def start(self) -> None:
        """Start the run clock (and the watchdog timer). Idempotent."""
        with self._lock:
            if self._started_at is not None:
                return
            self._started_at = self._clock()
            if self.max_seconds is not None:
                self._timer = threading.Timer(self.max_seconds, self._on_timeout)
                self._timer.daemon = True
                self._timer.start()

    def close(self) -> None:
        with self._lock:
            if self._timer is not None:
                self._timer.cancel()
                self._timer = None

    def _on_timeout(self) -> None:
        self._timed_out = True

    def elapsed(self) -> float:
        if self._started_at is None:
            return 0.0
        return self._clock() - self._started_at

    # -- BudgetGuard ----------------------------------------------------------------------

    def before_model_call(self) -> None:
        self.start()
        with self._lock:
            steps, tokens, cost = self.steps, self.input_tokens + self.output_tokens, self.cost_usd
        if self.max_steps is not None and steps >= self.max_steps:
            raise GuardStopped("max_steps", self.max_steps, steps)
        if self.max_tokens is not None and tokens >= self.max_tokens:
            raise GuardStopped("max_tokens", self.max_tokens, tokens)
        self._check_cost_and_time(cost)

    def before_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        self.start()
        with self._lock:
            cost = self.cost_usd
        self._check_cost_and_time(cost)

    def _check_cost_and_time(self, cost: float) -> None:
        if self.max_usd is not None and cost >= self.max_usd:
            raise GuardStopped("max_usd", self.max_usd, round(cost, 6))
        if self.max_seconds is not None:
            elapsed = self.elapsed()
            if self._timed_out or elapsed >= self.max_seconds:
                raise GuardStopped("max_seconds", self.max_seconds, round(elapsed, 3))

    def record(self, event: TraceEvent) -> None:
        with self._lock:
            if isinstance(event, ModelCall):
                self.steps += 1
                self.input_tokens += event.input_tokens
                self.output_tokens += event.output_tokens
                self.cost_usd += event.cost_usd
            elif isinstance(event, ToolCall):
                self.cost_usd += event.cost_usd

    def tool_timeout(self, default_s: float) -> float:
        if self.max_seconds is None:
            return default_s
        remaining = self.max_seconds - self.elapsed()
        return min(default_s, max(remaining, 0.001))

    def totals(self) -> dict[str, Any]:
        """Totals for the ``run_end`` event."""
        with self._lock:
            return {
                "steps": self.steps,
                "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens,
                "tokens": self.input_tokens + self.output_tokens,
                "cost_usd": self.cost_usd,
                "wall_ms": self.elapsed() * 1000,
            }


class CompositeGuard:
    """Runs several guards as one. The first one to raise wins."""

    def __init__(self, *guards: Any) -> None:
        self.guards = list(guards)

    def before_model_call(self) -> None:
        for g in self.guards:
            g.before_model_call()

    def before_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        for g in self.guards:
            g.before_tool_call(tool, args)

    def record(self, event: TraceEvent) -> None:
        for g in self.guards:
            g.record(event)

    def tool_timeout(self, default_s: float) -> float:
        timeout = default_s
        for g in self.guards:
            timeout = min(timeout, g.tool_timeout(default_s))
        return timeout

    def start(self) -> None:
        for g in self.guards:
            if hasattr(g, "start"):
                g.start()

    def close(self) -> None:
        for g in self.guards:
            if hasattr(g, "close"):
                g.close()

    def totals(self) -> dict[str, Any]:
        for g in self.guards:
            if isinstance(g, RunBudgetGuard):
                return g.totals()
        return {}


def build_guard(
    budget: RunLimits | dict[str, Any] | None = None,
    loop_guard: LoopGuardSpec | dict[str, Any] | None = None,
) -> CompositeGuard:
    """Build the guard for one run from the spec's ``budget.run`` and ``loop_guard``."""
    limits = RunLimits.model_validate(budget) if isinstance(budget, dict) else budget
    limits = limits or RunLimits()
    loop = LoopGuardSpec.model_validate(loop_guard) if isinstance(loop_guard, dict) else loop_guard
    loop = loop or LoopGuardSpec()
    return CompositeGuard(
        RunBudgetGuard(
            max_steps=limits.max_steps,
            max_tokens=limits.max_tokens,
            max_usd=limits.max_usd,
            max_seconds=limits.max_seconds,
        ),
        LoopGuard(loop.max_identical_calls),
    )
