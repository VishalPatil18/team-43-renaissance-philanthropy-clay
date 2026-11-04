"""Trace contract (DD-011, arch §7.1). Owner: WS3 (Shivaani).

Every run produces an ordered list of ``TraceEvent``s. The trace is the truth
(P1): scoring, summaries, statistics and replay all read it back.

Contract decisions recorded here (contracts session, open points 3, 4, 12):

* ``EventSink.emit`` assigns ``seq``, ``event_id`` and ``run_id``, so callers
  build events without them (those fields default to placeholders).
* ``Trace`` holds ``events``, ``incomplete`` and ``blob(ref)``.
* ``trace_digest`` is the one compact text view of a trace, shared by the
  summarizer and the LLM process evaluator so neither imports the other.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, TypeAdapter

SCHEMA_VERSION = "1.0"

ErrorSource = Literal["agent", "tool", "budget", "infra"]
RunState = Literal["completed", "budget_stopped", "agent_failed", "infra_error"]


def utcnow() -> datetime:
    return datetime.now(UTC)


class ErrorInfo(BaseModel):
    """FR-2.4: every error carries source, kind (srs §12.4), message and retryability."""

    model_config = ConfigDict(extra="forbid")

    source: ErrorSource
    kind: str
    message: str
    retryable: bool = False
    related_event_id: str | None = None


class _Base(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = SCHEMA_VERSION
    # Filled by EventSink.emit (open point 3); placeholders until then.
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
    tool_use_requests: list[dict] = Field(default_factory=list)
    text_preview: str | None = None
    cost_usd: float = 0.0
    price_table_version: str = ""


class ToolCall(_Base):
    type: Literal["tool_call"] = "tool_call"
    server: str
    tool: str
    capability: str | None = None
    args: dict = Field(default_factory=dict)
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
    output: dict | str


class RunEnd(_Base):
    type: Literal["run_end"] = "run_end"
    state: RunState
    totals: dict = Field(default_factory=dict)  # steps, tokens, cost_usd, wall_ms


TraceEvent = Annotated[
    RunStart | ModelCall | ToolCall | GuardStop | ErrorEvent | FinalOutput | RunEnd,
    Field(discriminator="type"),
]
TRACE_EVENT_ADAPTER: TypeAdapter[TraceEvent] = TypeAdapter(TraceEvent)

AnyEvent = (
    RunStart | ModelCall | ToolCall | GuardStop | ErrorEvent | FinalOutput | RunEnd
)


def parse_event(data: str | bytes | dict) -> AnyEvent:
    """Parse one serialised event (a JSONL line or a dict)."""
    if isinstance(data, dict):
        return TRACE_EVENT_ADAPTER.validate_python(data)
    return TRACE_EVENT_ADAPTER.validate_json(data)


@runtime_checkable
class EventSink(Protocol):
    """Where instrumented code sends events (open point 3)."""

    def emit(self, event: AnyEvent) -> AnyEvent:
        """Assign seq, event_id and run_id, redact, hand to the tracer. Never raises."""
        ...

    def put_blob(self, data: bytes | str) -> tuple[str, str]:
        """Store a full payload once; return ("blobs/<sha256>", sha256)."""
        ...

    @property
    def last_event_id(self) -> str | None: ...


class Trace(BaseModel):
    """A run's events as read back (open point 4)."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    events: list[TraceEvent] = Field(default_factory=list)
    incomplete: bool = False
    _blob_loader: Callable[[str], bytes] | None = PrivateAttr(default=None)

    def with_blobs(self, loader: Callable[[str], bytes]) -> Trace:
        self._blob_loader = loader
        return self

    def blob(self, ref: str) -> bytes:
        if self._blob_loader is None:
            raise LookupError("this trace has no blob store attached")
        return self._blob_loader(ref)

    def event(self, event_id: str) -> AnyEvent | None:
        return next((e for e in self.events if e.event_id == event_id), None)

    @property
    def errors(self) -> list[AnyEvent]:
        return [e for e in self.events if e.error is not None]


# ---------------------------------------------------------------- digest (open point 12)
def _clip(value: object, n: int) -> str:
    s = (
        value
        if isinstance(value, str)
        else json.dumps(value, default=str, separators=(",", ":"))
    )
    return s if len(s) <= n else s[: n - 1] + "…"


def digest_line(e: AnyEvent) -> str:
    err = f" | {e.error.source}/{e.error.kind}" if e.error else ""
    head = f"[{e.event_id}] {e.type}"
    if isinstance(e, ModelCall):
        asked = ", ".join(
            str(r.get("name") or r.get("tool") or "?") for r in e.tool_use_requests
        )
        return (
            f"{head} {e.model_id} {e.input_tokens}→{e.output_tokens} tok"
            f"{' requested: ' + asked if asked else ''}{err}"
        )
    if isinstance(e, ToolCall):
        result = (
            e.result_preview
            if e.status == "ok"
            else (e.error.message if e.error else e.result_preview)
        )
        return f"{head} {e.server}.{e.tool}({_clip(e.args, 200)}) -> {e.status}/{_clip(result or '', 200)}{err}"
    if isinstance(e, GuardStop):
        return (
            f"{head} {e.limit} limit {e.limit_value} observed {e.observed_value}{err}"
        )
    if isinstance(e, FinalOutput):
        return f"{head} {_clip(e.output, 200)}{err}"
    if isinstance(e, RunEnd):
        return f"{head} state={e.state} totals={_clip(e.totals, 200)}{err}"
    if isinstance(e, RunStart):
        return f"{head} task={e.task_instance_id} config={e.config_name}{err}"
    return f"{head}{' ' + e.error.message if e.error else ''}{err}"


def trace_digest(trace: Trace, max_chars: int = 12000) -> str:
    """One line per event. Over budget: keep the start and end, compress the middle."""
    lines = [digest_line(e) for e in trace.events]
    if trace.incomplete:
        lines.append("[trace incomplete: no run_end or a truncated line]")
    text = "\n".join(lines)
    if len(text) <= max_chars:
        return text
    budget = max_chars - 60
    head: list[str] = []
    tail: list[str] = []
    used = 0
    i, j = 0, len(lines) - 1
    while i <= j:  # alternate from both ends so start and end both survive
        for side in ("head", "tail"):
            if i > j:
                break
            line = lines[i] if side == "head" else lines[j]
            if used + len(line) + 1 > budget:
                i = j + 1
                break
            used += len(line) + 1
            if side == "head":
                head.append(line)
                i += 1
            else:
                tail.insert(0, line)
                j -= 1
    omitted = len(lines) - len(head) - len(tail)
    return "\n".join(head + [f"… {omitted} events omitted …"] + tail)
