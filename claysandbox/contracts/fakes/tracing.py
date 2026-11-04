from __future__ import annotations

from pathlib import Path

from claysandbox.contracts.registry import register
from claysandbox.contracts.trace import AnyEvent, Trace


@register("tracer", "memory")
class MemoryTracer:
    """Keeps events in a list. For tests of anything that emits through a sink."""

    name = "memory"
    version = "1"

    def __init__(self, params: dict | None = None):
        self.events: list[AnyEvent] = []
        self.run_id: str | None = None
        self.opened = False
        self.closed = False
        self.incomplete = False

    def open(self, run_id: str, run_dir: Path) -> None:
        self.run_id, self.opened = run_id, True

    def emit(self, event: AnyEvent) -> None:
        self.events.append(event)

    def close(self) -> None:
        self.closed = True

    def trace(self) -> Trace:
        done = bool(self.events) and self.events[-1].type == "run_end"
        return Trace(run_id=self.run_id or "", events=list(self.events), incomplete=not done)
