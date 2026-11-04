"""Guard fakes (owner: WS1)."""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.errors import GuardStopped
from claysandbox.contracts.trace import TraceEvent


class NoopGuard:
    """Never stops anything."""

    def before_model_call(self) -> None:
        return None

    def before_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        return None

    def record(self, event: TraceEvent) -> None:
        return None

    def tool_timeout(self, default_s: float) -> float:
        return default_s


class TripGuard(NoopGuard):
    """Stops the run at the nth model call and/or the nth tool call (1-based)."""

    def __init__(self, model_call: int | None = None, tool_call: int | None = None):
        self.stop_model_call = model_call
        self.stop_tool_call = tool_call
        self.model_calls = 0
        self.tool_calls = 0

    def before_model_call(self) -> None:
        self.model_calls += 1
        if self.stop_model_call is not None and self.model_calls >= self.stop_model_call:
            raise GuardStopped("max_steps", self.stop_model_call - 1, self.model_calls - 1)

    def before_tool_call(self, tool: str, args: dict[str, Any]) -> None:
        self.tool_calls += 1
        if self.stop_tool_call is not None and self.tool_calls >= self.stop_tool_call:
            raise GuardStopped("loop", self.stop_tool_call - 1, self.tool_calls)
