"""OpenTelemetry tracer (SHI-R2-01, D8, DD-011, FR-2.7, J3 step 2). Owner: WS3.

Serialises the canonical ``TraceEvent`` stream as OpenTelemetry spans. Our own schema stays
the source of truth (DD-011): every span carries the full event as the JSON attribute
``clay.event``, so the trace can be rebuilt exactly from the spans.

Two exporters:

* **File, always on.** One OTLP-JSON-shaped line per span in ``trace.otlp.jsonl``, written
  synchronously as each span ends (so a crash keeps everything up to it, FR-2.6). This is
  what replay reads back and what J3 step 2 compares against the JSONL tracer.
* **Remote, optional (``endpoint``).** OTLP over HTTP to a *local ADOT collector* that
  forwards to X-Ray/CloudWatch.

Decision O-4 (srs): option (a), a local ADOT collector, not direct SigV4 to the X-Ray
endpoint. It keeps request signing and AWS credentials out of this process and the
collector config holds the region and role. The remote path needs the package
``opentelemetry-exporter-otlp-proto-http``; it is imported only when ``endpoint`` is set.
It has not been exercised against a real collector or X-Ray from this repo's tests (no AWS
account in CI), only the file path is.

Mapping: the run is the root span; every event is a child span named by type. Model calls
use ``gen_ai.*`` attributes (chat), tool calls ``gen_ai.operation.name=execute_tool``.
Errors and guard stops become span events and an ERROR span status.
"""

from __future__ import annotations

import json
import logging
import os
import random
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import IO, Any

from opentelemetry import trace as ot_trace
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider
from opentelemetry.sdk.trace.export import (
    BatchSpanProcessor,
    SimpleSpanProcessor,
    SpanExporter,
    SpanExportResult,
)
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.trace import Span, Status, StatusCode
from pydantic import BaseModel

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.registry import register
from claysandbox.contracts.store import StoreWriteRefused
from claysandbox.contracts.trace import (
    OTEL_EVENT_ATTR,
    AnyEvent,
    GuardStop,
    ModelCall,
    RunStart,
    ToolCall,
)

log = logging.getLogger("claysandbox.tracing")

OTLP_FILE = "trace.otlp.jsonl"
ROOT_SPAN_NAME = "clay.run"


# ---------------------------------------------------------------- ids
class XRayCompatibleIdGenerator(IdGenerator):
    """Trace IDs whose first 4 bytes are the epoch seconds, as X-Ray requires.

    X-Ray drops traces whose ID does not start with a recent timestamp, and random W3C IDs
    would be silently lost.
    """

    def generate_span_id(self) -> int:
        return random.getrandbits(64) or 1

    def generate_trace_id(self) -> int:
        return (int(time.time()) << 96) | random.getrandbits(96)


# ---------------------------------------------------------------- file exporter
def _any_value(v: Any) -> dict[str, Any]:
    """OTLP-JSON ``AnyValue``. ``bool`` must be tested before ``int``."""
    if isinstance(v, bool):
        return {"boolValue": v}
    if isinstance(v, int):
        return {"intValue": str(v)}
    if isinstance(v, float):
        return {"doubleValue": v}
    if isinstance(v, (list, tuple)):
        return {"arrayValue": {"values": [_any_value(x) for x in v]}}
    return {"stringValue": str(v)}


def _attrs(attributes: Any) -> list[dict[str, Any]]:
    return [{"key": k, "value": _any_value(v)} for k, v in (attributes or {}).items()]


def span_to_otlp_json(span: ReadableSpan) -> dict[str, Any]:
    """One span as an OTLP/JSON ``resourceSpans`` envelope (a single line in the file)."""
    ctx = span.get_span_context()
    assert ctx is not None
    parent = span.parent.span_id if span.parent else None
    status = span.status
    return {
        "resourceSpans": [
            {
                "resource": {"attributes": _attrs(span.resource.attributes)},
                "scopeSpans": [
                    {
                        "scope": {"name": "claysandbox"},
                        "spans": [
                            {
                                "traceId": format(ctx.trace_id, "032x"),
                                "spanId": format(ctx.span_id, "016x"),
                                "parentSpanId": format(parent, "016x") if parent else "",
                                "name": span.name,
                                "startTimeUnixNano": str(span.start_time or 0),
                                "endTimeUnixNano": str(span.end_time or 0),
                                "attributes": _attrs(span.attributes),
                                "events": [
                                    {
                                        "name": ev.name,
                                        "timeUnixNano": str(ev.timestamp),
                                        "attributes": _attrs(ev.attributes),
                                    }
                                    for ev in span.events
                                ],
                                "status": {
                                    "code": status.status_code.name,
                                    "message": status.description or "",
                                },
                            }
                        ],
                    }
                ],
            }
        ]
    }


class OtlpJsonFileExporter(SpanExporter):
    """Appends one OTLP-JSON line per span; flushes each, fsyncs when the root span ends."""

    def __init__(self, path: Path):
        self.path = Path(path)
        self._fh: IO[str] | None = self.path.open("a", encoding="utf-8")
        self._lock = threading.Lock()

    def export(self, spans: Any) -> SpanExportResult:
        with self._lock:
            if self._fh is None:
                return SpanExportResult.FAILURE
            try:
                for s in spans:
                    self._fh.write(json.dumps(span_to_otlp_json(s), separators=(",", ":")) + "\n")
                    if s.parent is None:  # the run's root span ends last
                        self._fh.flush()
                        os.fsync(self._fh.fileno())
                self._fh.flush()
            except OSError as e:
                log.error("sandbox error", extra={"kind": "otlp_file_export", "error": repr(e)})
                return SpanExportResult.FAILURE
        return SpanExportResult.SUCCESS

    def shutdown(self) -> None:
        with self._lock:
            if self._fh is not None:
                try:
                    self._fh.flush()
                    os.fsync(self._fh.fileno())
                    self._fh.close()
                finally:
                    self._fh = None

    def force_flush(self, timeout_millis: int = 30000) -> bool:  # noqa: ARG002
        return True


class _TimedExporter(SpanExporter):
    """Wraps the remote exporter and records how long its export calls take."""

    def __init__(self, inner: SpanExporter, owner: OtelTracer):
        self._inner = inner
        self._owner = owner

    def export(self, spans: Any) -> SpanExportResult:
        t0 = time.perf_counter_ns()
        try:
            return self._inner.export(spans)
        finally:
            self._owner.export_ns_total += time.perf_counter_ns() - t0
            self._owner.export_batches += 1

    def shutdown(self) -> None:
        self._inner.shutdown()

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        return self._inner.force_flush(timeout_millis)


# ---------------------------------------------------------------- the tracer
def _ns(dt: datetime | None) -> int | None:
    return int(dt.timestamp() * 1_000_000_000) if dt is not None else None


@register("tracer", "otel")
class OtelTracer:
    name = "otel"
    version = "1"

    class Params(BaseModel):
        endpoint: str | None = None  # OTLP/HTTP traces URL of a local ADOT collector
        headers: dict[str, str] = {}
        service_name: str = "clay-sandbox"
        file_name: str = OTLP_FILE

    def __init__(self, params: OtelTracer.Params | dict | None = None):
        self.params = params if isinstance(params, self.Params) else self.Params(**(params or {}))
        self.run_id: str | None = None
        self.path: Path | None = None
        self.incomplete = False
        self._provider: TracerProvider | None = None
        self._tracer: ot_trace.Tracer | None = None
        self._root: Span | None = None
        self._root_ctx: Any = None
        self._lock = threading.Lock()
        self._closed = False
        #: Total time spent inside the remote exporter and the number of batches, measured in
        #: the processor's export callback. Read by the tee tracer (SHI-R2-02).
        self.export_ns_total = 0
        self.export_batches = 0

    # ------------------------------------------------------------ lifecycle
    def open(self, run_id: str, run_dir: Path) -> None:
        """Start the trace. Raises ``StoreWriteRefused`` if the file already has spans and
        ``ConfigError`` if a remote ``endpoint`` is set but its exporter is not installed.
        """
        self.run_id = run_id
        self.path = Path(run_dir) / self.params.file_name
        self.path.parent.mkdir(parents=True, exist_ok=True)
        if self.path.exists() and self.path.stat().st_size > 0:
            raise StoreWriteRefused(
                f"{self.path} already has spans; a run folder is traced once "
                "(use a new run folder for a retry)"
            )
        provider = TracerProvider(
            resource=Resource.create(
                {"service.name": self.params.service_name, "clay.run_id": run_id}
            ),
            id_generator=XRayCompatibleIdGenerator(),
        )
        try:
            provider.add_span_processor(SimpleSpanProcessor(OtlpJsonFileExporter(self.path)))
        except OSError as e:
            self._fail("open", e)
            return
        if self.params.endpoint:
            provider.add_span_processor(
                BatchSpanProcessor(_TimedExporter(self._remote_exporter(), self))
            )
        self._provider = provider
        self._tracer = provider.get_tracer("claysandbox", "1")

    def _remote_exporter(self) -> SpanExporter:
        try:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        except ImportError:
            raise ConfigError(
                "tracer 'otel' has an endpoint but 'opentelemetry-exporter-otlp-proto-http' "
                "is not installed; add it to the project dependencies",
                kind="missing_dependency",
            ) from None
        return OTLPSpanExporter(endpoint=self.params.endpoint, headers=self.params.headers or None)

    def emit(self, event: AnyEvent) -> None:
        if self._tracer is None or self._closed:
            self._fail("emit_before_open_or_after_close", RuntimeError("tracer not open"))
            return
        try:
            with self._lock:
                self._emit(event)
        except Exception as e:  # noqa: BLE001  never raise into the agent loop
            self._fail("emit", e)

    def close(self) -> None:
        if self._closed:
            return
        self._closed = True
        try:
            with self._lock:
                if self._root is not None:
                    self._root.end()
                    self._root = None
            if self._provider is not None:
                self._provider.shutdown()  # flushes the batch processor, closes the file
        except Exception as e:  # noqa: BLE001  never raise into the agent loop
            self._fail("close", e)

    # ------------------------------------------------------------ mapping
    def _ensure_root(self, event: AnyEvent) -> None:
        if self._root is not None:
            return
        assert self._tracer is not None
        attrs: dict[str, Any] = {"clay.run_id": self.run_id or ""}
        if isinstance(event, RunStart):
            attrs["clay.task_instance"] = event.task_instance_id
            attrs["clay.config"] = event.config_name
        self._root = self._tracer.start_span(
            ROOT_SPAN_NAME, start_time=_ns(event.ts_start), attributes=attrs
        )
        self._root_ctx = ot_trace.set_span_in_context(self._root)

    def _emit(self, event: AnyEvent) -> None:
        assert self._tracer is not None
        self._ensure_root(event)
        attrs: dict[str, Any] = {
            OTEL_EVENT_ATTR: event.model_dump_json(),
            "clay.event_id": event.event_id,
            "clay.seq": event.seq,
            "clay.event_type": event.type,
        }
        name: str = event.type
        failed = event.error is not None
        if isinstance(event, ModelCall):
            name = f"chat {event.model_id}"
            attrs.update(
                {
                    "gen_ai.operation.name": "chat",
                    "gen_ai.system": "aws.bedrock",
                    "gen_ai.request.model": event.model_id,
                    "gen_ai.usage.input_tokens": event.input_tokens,
                    "gen_ai.usage.output_tokens": event.output_tokens,
                }
            )
        elif isinstance(event, ToolCall):
            name = f"execute_tool {event.tool}"
            failed = failed or event.status != "ok"
            attrs.update(
                {
                    "gen_ai.operation.name": "execute_tool",
                    "gen_ai.tool.name": event.tool,
                    "clay.tool.server": event.server,
                    "clay.tool.status": event.status,
                }
            )
        elif isinstance(event, GuardStop):
            failed = True
            attrs["clay.guard.limit"] = event.limit

        start = _ns(event.ts_start)
        end = _ns(event.ts_end) or start
        span = self._tracer.start_span(
            name, context=self._root_ctx, start_time=start, attributes=attrs
        )
        if event.error is not None:
            span.add_event(
                "clay.error",
                {
                    "error.source": event.error.source,
                    "error.kind": event.error.kind,
                    "error.message": event.error.message,
                    "error.retryable": event.error.retryable,
                },
                timestamp=end,
            )
        if isinstance(event, GuardStop):
            span.add_event(
                "clay.guard_stop",
                {
                    "limit": event.limit,
                    "limit_value": event.limit_value,
                    "observed": event.observed_value,
                },
                timestamp=end,
            )
        if failed:
            desc = event.error.kind if event.error else event.type
            span.set_status(Status(StatusCode.ERROR, desc))
        span.end(end_time=end)
        if event.type == "run_end" and self._root is not None:
            self._root.end(end_time=end)
            self._root = None

    def _fail(self, where: str, exc: Exception) -> None:
        self.incomplete = True
        log.error(
            "sandbox error",
            extra={"run_id": self.run_id, "kind": f"otel_tracer_{where}", "error": repr(exc)},
        )
