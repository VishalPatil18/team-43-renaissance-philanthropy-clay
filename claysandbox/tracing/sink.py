"""The event sink every instrumented component writes through (SHI-R0-01).

``RunEventSink`` assigns ``seq`` (from 0, strictly increasing) and
``event_id = f"{run_id}:{seq}"``, fills ``run_id``, redacts the event, then
hands it to the tracer. It never raises into the agent loop (arch §9.3): a
tracer failure is logged as a sandbox error and marks the run ``incomplete``.
Thread-safe, because tool calls can arrive from the MCP event-loop thread.
"""

from __future__ import annotations

import hashlib
import logging
import os
import threading
from pathlib import Path
from typing import Any

from claysandbox.contracts.trace import (
    TRACE_EVENT_ADAPTER,
    AnyEvent,
    ErrorEvent,
    ErrorInfo,
)

from .redact import redact_event_dict, redact_text

log = logging.getLogger("claysandbox.tracing")

PREVIEW_CHARS = 500


class RunEventSink:
    def __init__(
        self,
        run_id: str,
        run_dir: str | Path,
        tracer: Any,
        preview_chars: int = PREVIEW_CHARS,
    ):
        self.run_id = run_id
        self.run_dir = Path(run_dir)
        self.tracer = tracer
        self.preview_chars = preview_chars
        self.incomplete = False
        self._seq = 0
        self._last: str | None = None
        self._lock = threading.Lock()

    @property
    def last_event_id(self) -> str | None:
        return self._last

    def emit(self, event: AnyEvent) -> AnyEvent:
        with self._lock:
            seq = self._seq
            data = event.model_dump(mode="json")
            data.update(run_id=self.run_id, seq=seq, event_id=f"{self.run_id}:{seq}")
            try:
                stamped = TRACE_EVENT_ADAPTER.validate_python(redact_event_dict(data))
            except Exception as e:  # noqa: BLE001  a malformed event must not break the run
                # Fail closed: never forward the original, unredacted event. Keep the
                # sequence gap-free with a payload-free error event instead.
                self._sandbox_error("redaction_or_validation_failed", e)
                stamped = ErrorEvent(
                    run_id=self.run_id,
                    seq=seq,
                    event_id=f"{self.run_id}:{seq}",
                    error=ErrorInfo(
                        source="infra",
                        kind="trace_event_invalid",
                        message=(
                            f"a {event.type} event could not be redacted or validated "
                            f"({type(e).__name__}); its content was dropped"
                        ),
                    ),
                )
            self._seq += 1
            self._last = stamped.event_id
            try:
                self.tracer.emit(stamped)
            except Exception as e:  # noqa: BLE001  never raise into the agent loop
                self._sandbox_error("tracer_emit_failed", e)
            if getattr(self.tracer, "incomplete", False):
                self.incomplete = True
            return stamped

    def put_blob(self, data: bytes | str) -> tuple[str, str]:
        """Write the full payload once under blobs/<sha256> (deduplicated); return (ref, sha).

        Text payloads are redacted here, so no caller can store a secret by skipping
        a step. The returned hash is of the stored (redacted) bytes. Binary payloads
        that are not valid UTF-8 are stored as given.
        """
        if isinstance(data, str):
            raw = redact_text(data).encode()
        else:
            try:
                raw = redact_text(data.decode("utf-8")).encode()
            except UnicodeDecodeError:
                raw = data  # binary payload: store untouched
        sha = hashlib.sha256(raw).hexdigest()
        ref = f"blobs/{sha}"
        path = self.run_dir / ref
        if not path.exists():
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix(f".tmp{threading.get_ident()}")
                tmp.write_bytes(raw)
                os.replace(tmp, path)
            except OSError as e:
                self._sandbox_error("blob_write_failed", e)
        return ref, sha

    def result_fields(self, result_text: str) -> dict[str, str | None]:
        """FR-2.5 helper for tool wrappers: full result to a blob, redacted preview inline."""
        # Redact first, then truncate: cutting first could leave half a secret that
        # no pattern recognises.
        text = redact_text(result_text)
        if len(text) <= self.preview_chars:
            return {"result_preview": text, "result_ref": None, "result_sha256": None}
        ref, sha = self.put_blob(text)
        return {
            "result_preview": text[: self.preview_chars] + "…",
            "result_ref": ref,
            "result_sha256": sha,
        }

    def _sandbox_error(self, kind: str, exc: Exception) -> None:
        self.incomplete = True
        log.error(
            "sandbox error",
            extra={"run_id": self.run_id, "kind": kind, "error": repr(exc)},
        )
