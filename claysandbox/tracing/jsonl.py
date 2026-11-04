"""JSONL tracer (SHI-R0-01, FR-2.1, FR-2.6). Owner: WS3.

One JSON line per event in ``<run_dir>/trace.jsonl``, flushed after every
event so a crash keeps everything up to the crash, and fsynced at ``run_end``.
``emit`` never raises: an I/O failure is logged and sets ``incomplete``.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import IO

from pydantic import BaseModel

from claysandbox.contracts.registry import register
from claysandbox.contracts.store import StoreWriteRefused
from claysandbox.contracts.trace import AnyEvent

log = logging.getLogger("claysandbox.tracing")

TRACE_FILE = "trace.jsonl"


@register("tracer", "jsonl")
class JsonlTracer:
    name = "jsonl"
    version = "1"

    class Params(BaseModel):
        file_name: str = TRACE_FILE

    def __init__(self, params: JsonlTracer.Params | dict | None = None):
        self.params = params if isinstance(params, self.Params) else self.Params(**(params or {}))
        self.run_id: str | None = None
        self.path: Path | None = None
        self.incomplete = False
        self._fh: IO[str] | None = None

    def open(self, run_id: str, run_dir: Path) -> None:
        """Start the trace. Raises ``StoreWriteRefused`` if the file already has events.

        A run folder is traced exactly once (NFR-PROV-2): an infra retry gets a new
        run folder (arch §8.3), so appending to an existing trace would duplicate
        ``seq`` values or alter a finished run. The check is on content, not file
        permissions, so it also holds when running as root (Docker, Fargate).
        This is a start-up error, not an ``emit`` error, so it may raise.
        """
        self.run_id = run_id
        self.path = Path(run_dir) / self.params.file_name
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            if self.path.exists() and self.path.stat().st_size > 0:
                raise StoreWriteRefused(
                    f"{self.path} already has events; a run folder is traced once "
                    "(use a new run folder for a retry)"
                )
            self._fh = self.path.open("a", encoding="utf-8")
        except OSError as e:
            self._fail("open", e)

    def emit(self, event: AnyEvent) -> None:
        if self._fh is None:
            self._fail("emit_before_open", RuntimeError("tracer not open"))
            return
        try:
            self._fh.write(event.model_dump_json() + "\n")
            self._fh.flush()
            if event.type == "run_end":
                os.fsync(self._fh.fileno())
        except Exception as e:  # noqa: BLE001  never raise into the agent loop
            self._fail("emit", e)

    def close(self) -> None:
        if self._fh is None:
            return
        try:
            self._fh.flush()
            os.fsync(self._fh.fileno())
            self._fh.close()
        except Exception as e:  # noqa: BLE001  never raise into the agent loop
            self._fail("close", e)
        finally:
            self._fh = None

    def _fail(self, where: str, exc: Exception) -> None:
        self.incomplete = True
        log.error(
            "sandbox error",
            extra={
                "run_id": self.run_id,
                "kind": f"jsonl_tracer_{where}",
                "error": repr(exc),
            },
        )
