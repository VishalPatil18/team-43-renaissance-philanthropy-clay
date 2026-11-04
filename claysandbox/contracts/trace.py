"""Trace events and the event sink (architecture §7.1, srs §12.4).

Owner: WS3 (Shivaani). This copy follows the architecture sketch so WS1 can build against it.
``run_id``, ``seq`` and ``event_id`` have defaults because the ``EventSink`` stamps them in
``emit`` (contracts open point 3). If WS3 changes this module, WS1's wrappers only depend on
the field names used below.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

SCHEMA_VERSION = "1.0"


def utcnow() -> datetime:
    return datetime.now(UTC)


class ErrorInfo(BaseModel):
    source: Literal["agent", "tool", "budget", "infra"]
    kind: str
    message: str
    retryable: bool = False
    related_event_id: str | None = None


class _Base(BaseModel):
    schema_version: str = SCHEMA_VERSION
    run_id: str = ""
    seq: int = -1
    event_id: str = ""
    parent_id: str | None = None
    ts_start: datetime = Field(default_factory=utcnow)
    ts_end: datetime | None = None
    latency_ms: float | None = None
    error: ErrorInfo | None = None


class RunStart(_Base):
    type: Literal["run_start"] = "run_start"
    task_instance_id: str
    config_name: str


class ModelCall(_Base):
    type: Literal["model_call"] = "model_call"
    model_id: str
    input_tokens: int
    output_tokens: int
    stop_reason: str | None = None
    tool_use_requests: list[dict[str, Any]] = Field(default_factory=list)
    text_preview: str | None = None
    cost_usd: float
    price_table_version: str


class ToolCall(_Base):
    type: Literal["tool_call"] = "tool_call"
    server: str
    tool: str
    capability: str | None = None
    args: dict[str, Any] = Field(default_factory=dict)
    status: Literal["ok", "error", "timeout", "rejected"]
    result_preview: str | None = None
    result_ref: str | None = None
    result_sha256: str | None = None
    cost_usd: float = 0.0


class GuardStop(_Base):
    type: Literal["guard_stop"] = "guard_stop"
    limit: Literal["max_steps", "max_tokens", "max_usd", "max_seconds", "loop"]
    limit_value: float
    observed_value: float


class ErrorEvent(_Base):
    """An error not attached to a model or tool call."""

    type: Literal["error"] = "error"


class FinalOutput(_Base):
    type: Literal["final_output"] = "final_output"
    output: dict[str, Any] | str


class RunEnd(_Base):
    type: Literal["run_end"] = "run_end"
    state: Literal["completed", "budget_stopped", "agent_failed", "infra_error"]
    totals: dict[str, Any] = Field(default_factory=dict)


TraceEvent = Annotated[
    RunStart | ModelCall | ToolCall | GuardStop | ErrorEvent | FinalOutput | RunEnd,
    Field(discriminator="type"),
]

EventT = RunStart | ModelCall | ToolCall | GuardStop | ErrorEvent | FinalOutput | RunEnd


@runtime_checkable
class EventSink(Protocol):
    """Receives events from the wrappers and harnesses (contracts open point 3).

    * ``emit`` stamps ``run_id``, ``seq`` and ``event_id`` and returns the stamped event.
      It must never raise into the agent loop (FR-2.6).
    * ``put_blob`` stores a full tool result and returns ``("blobs/<sha256>", sha256)``.
    * ``last_event_id`` is the ``event_id`` of the latest emitted event, or ``None``.
    """

    def emit(self, event: EventT) -> EventT: ...

    def put_blob(self, data: bytes) -> tuple[str, str]: ...

    @property
    def last_event_id(self) -> str | None: ...


class Trace(BaseModel):
    """A trace read back from a store (contracts open point 4)."""

    events: list[TraceEvent] = Field(default_factory=list)
    incomplete: bool = False
    blobs: dict[str, bytes] = Field(default_factory=dict)

    def blob(self, ref: str) -> bytes:
        return self.blobs[ref]
