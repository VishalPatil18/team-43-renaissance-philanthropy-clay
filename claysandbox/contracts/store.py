"""Run store contract (arch §7.4, §13). Owner: WS3 (Shivaani).

Layout and write rules are fixed (``store_layout_version: 1``, arch §13.1-13.2):
the manifest is written once; the trace is append-only and owned by the tracer;
after a terminal status the manifest and trace can no longer be written;
assessments are new files only; summaries and reports are regenerable views.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel

from .trace import Trace

STORE_LAYOUT_VERSION = 1
RunLifecycle = Literal[
    "created", "running", "completed", "budget_stopped", "agent_failed", "infra_error"
]
TERMINAL_STATES: frozenset[str] = frozenset(
    {"completed", "budget_stopped", "agent_failed", "infra_error"}
)


class StoreWriteRefused(Exception):
    """A write broke the store's write rules (e.g. changing a finished run's trace)."""


class RunStatus(BaseModel):
    state: RunLifecycle
    updated_at: str
    attempt: int = 1
    incomplete: bool = False


@runtime_checkable
class RunStore(Protocol):
    def create_run(self, manifest: Any) -> Path: ...
    def run_dir(self, run_id: str) -> Path: ...
    def trace_path(self, run_id: str) -> Path: ...
    def read_trace(self, run_id: str) -> Trace: ...
    def read_manifest(self, run_id: str) -> Any: ...
    def write_status(
        self, run_id: str, state: str, attempt: int = 1, incomplete: bool = False
    ) -> None: ...
    def read_status(self, run_id: str) -> RunStatus | None: ...
    def write_summary(self, run_id: str, summary: Any) -> None: ...
    def append_assessment(self, run_id: str, assessment: Any) -> None: ...
    def list_assessments(self, run_id: str) -> list[dict]: ...
    def write_report(
        self, run_id: str, report: Any, rendered: dict[str, str]
    ) -> None: ...
    def query(self, sql: str, params: dict | None = None) -> list[dict]: ...
    def create_eval(self, eval_id: str, spec: Any) -> Path: ...
    def write_eval_artifact(
        self, eval_id: str, name: str, data: bytes | str
    ) -> None: ...
    def read_eval_artifact(self, eval_id: str, name: str) -> bytes: ...
    def list_eval_runs(self, eval_id: str) -> list[str]: ...
