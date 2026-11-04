"""Run store interface (architecture §7.4).

Owner: WS3 (Shivaani). WS1 only calls ``query`` (token history for the pre-flight estimate).
Types for summaries, assessments and reports belong to other workstreams, so they are ``Any``
in this copy.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from .trace import Trace


@runtime_checkable
class RunStore(Protocol):
    def create_run(self, manifest: Any) -> Path: ...

    def trace_path(self, run_id: str) -> Path: ...

    def read_trace(self, run_id: str) -> Trace: ...

    def read_manifest(self, run_id: str) -> Any: ...

    def write_summary(self, run_id: str, summary: Any) -> None: ...

    def append_assessment(self, run_id: str, assessment: Any) -> None: ...

    def write_report(self, run_id: str, report: Any, rendered: dict[str, str]) -> None: ...

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]: ...

    def create_eval(self, eval_id: str, spec: Any) -> Path: ...

    def write_eval_artifact(self, eval_id: str, name: str, data: bytes | str) -> None: ...

    def read_eval_artifact(self, eval_id: str, name: str) -> bytes: ...

    def list_eval_runs(self, eval_id: str) -> list[str]: ...
