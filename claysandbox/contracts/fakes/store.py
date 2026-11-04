from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claysandbox.contracts.registry import register
from claysandbox.contracts.store import TERMINAL_STATES, RunStatus, StoreWriteRefused
from claysandbox.contracts.trace import Trace


def _plain(obj: Any) -> Any:
    return obj.model_dump(mode="json") if isinstance(obj, BaseModel) else obj


@register("store", "memory")
class MemoryRunStore:
    """In-memory store with the same write rules as LocalRunStore."""

    name = "memory"
    version = "1"

    def __init__(self, **_: Any):
        self.manifests: dict[str, Any] = {}
        self.traces: dict[str, Trace] = {}
        self.status: dict[str, RunStatus] = {}
        self.summaries: dict[str, Any] = {}
        self.assessments: dict[str, dict[str, Any]] = {}
        self.reports: dict[str, tuple[Any, dict[str, str]]] = {}
        self.evals: dict[str, dict[str, bytes]] = {}

    def run_dir(self, run_id: str) -> Path:
        return Path("memory") / run_id

    def trace_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "trace.jsonl"

    def create_run(self, manifest: Any) -> Path:
        run_id = manifest.run_id if hasattr(manifest, "run_id") else manifest["run_id"]
        if run_id in self.manifests:
            raise StoreWriteRefused(f"run {run_id} already exists")
        self.manifests[run_id] = json.loads(json.dumps(_plain(manifest), default=str))
        self.write_status(run_id, "created")
        return self.run_dir(run_id)

    def put_trace(self, run_id: str, trace: Trace) -> None:
        st = self.status.get(run_id)
        if st and st.state in TERMINAL_STATES:
            raise StoreWriteRefused(f"run {run_id} is finished; its trace is immutable")
        self.traces[run_id] = trace

    def read_trace(self, run_id: str) -> Trace:
        return self.traces.get(run_id, Trace(run_id=run_id, incomplete=True))

    def read_manifest(self, run_id: str) -> Any:
        return self.manifests[run_id]

    def write_status(
        self, run_id: str, state: str, attempt: int = 1, incomplete: bool = False
    ) -> None:
        prev = self.status.get(run_id)
        if prev and prev.state in TERMINAL_STATES and state != prev.state:
            raise StoreWriteRefused(f"run {run_id} already finished as {prev.state}")
        self.status[run_id] = RunStatus(
            state=state,
            updated_at=datetime.now(UTC).isoformat(),
            attempt=attempt,
            incomplete=incomplete,
        )

    def read_status(self, run_id: str) -> RunStatus | None:
        return self.status.get(run_id)

    def write_summary(self, run_id: str, summary: Any) -> None:
        self.summaries[run_id] = _plain(summary)

    def append_assessment(self, run_id: str, assessment: Any) -> None:
        a = _plain(assessment)
        bucket = self.assessments.setdefault(run_id, {})
        if a["assessment_id"] in bucket:
            raise StoreWriteRefused(f"assessment {a['assessment_id']} already exists")
        bucket[a["assessment_id"]] = a

    def list_assessments(self, run_id: str) -> list[dict]:
        return list(self.assessments.get(run_id, {}).values())

    def write_report(
        self, run_id: str, report: Any, rendered: dict[str, str] | None = None
    ) -> None:
        self.reports[run_id] = (_plain(report), dict(rendered or {}))

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        raise NotImplementedError("MemoryRunStore has no SQL")

    def create_eval(self, eval_id: str, spec: Any) -> Path:
        if eval_id in self.evals:
            raise StoreWriteRefused(f"eval {eval_id} already exists")
        self.evals[eval_id] = {
            "spec.yaml": json.dumps(_plain(spec), default=str).encode()
        }
        return Path("memory") / "evals" / eval_id

    def write_eval_artifact(self, eval_id: str, name: str, data: bytes | str) -> None:
        if name == "spec.yaml":
            raise StoreWriteRefused("spec.yaml is written once by create_eval")
        self.evals.setdefault(eval_id, {})[name] = (
            data.encode() if isinstance(data, str) else data
        )

    def read_eval_artifact(self, eval_id: str, name: str) -> bytes:
        return self.evals[eval_id][name]

    def list_eval_runs(self, eval_id: str) -> list[str]:
        raw = self.evals.get(eval_id, {}).get("plan.json")
        if not raw:
            return []
        plan = json.loads(raw)
        runs = plan.get("runs", plan) if isinstance(plan, dict) else plan
        return [r["run_id"] if isinstance(r, dict) else str(r) for r in runs]
