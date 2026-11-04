"""Local run store (SHI-R0-02, FR-5.1, FR-7.3, NFR-PROV-2, arch §13). Owner: WS3.

Layout (``store_layout_version: 1``)::

    runs/<run_id>/manifest.json trace.jsonl blobs/ summary.json assessments/ report.* status.json
    evals/<eval_id>/spec.yaml plan.json estimate.json eval_report.*

Write rules: ``create_run`` refuses an existing folder and writes the manifest
once; once ``status.json`` is terminal the manifest and trace are locked
(``StoreWriteRefused`` through the store, and read-only file modes as a backstop);
assessments are new files only; summaries and reports may be overwritten.

Read-only roots (e.g. ``samples/runs``) can be listed for replay: reads fall
back to them, and anything written for such a run (assessments, reports) goes
to an overlay folder in the writable root, so committed samples stay untouched.
"""

from __future__ import annotations

import json
import os
import stat
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel

from claysandbox.contracts.registry import register
from claysandbox.contracts.store import (
    TERMINAL_STATES,
    RunLifecycle,
    RunStatus,
    StoreWriteRefused,
)
from claysandbox.contracts.trace import Trace

from .query import run_query
from .reader import read_trace

MANIFEST = "manifest.json"
STATUS = "status.json"
PROTECTED = (MANIFEST, "trace.jsonl", "trace.otlp.jsonl")


def _dump(obj: Any) -> str:
    if isinstance(obj, BaseModel):
        return obj.model_dump_json(indent=2)
    if isinstance(obj, (dict, list)):
        return json.dumps(obj, indent=2, default=str)
    if isinstance(obj, str):
        return obj
    raise TypeError(f"cannot serialise {type(obj).__name__}")


def _atomic_write(path: Path, text: str | bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(text.encode() if isinstance(text, str) else text)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _safe_name(name: str) -> str:
    if not name or "/" in name or "\\" in name or name.startswith(".") or ".." in name:
        raise ValueError(f"unsafe file or id name: {name!r}")
    return name


@register("store", "local")
class LocalRunStore:
    name = "local"
    version = "1"

    class Params(BaseModel):
        root: str = "./runs"
        evals_root: str = "./evals"
        read_roots: list[str] = []

    def __init__(
        self,
        root: str | Path = "./runs",
        evals_root: str | Path = "./evals",
        read_roots: list[str | Path] | None = None,
        manifest_model: type[BaseModel] | None = None,
    ):
        self.root = Path(root)
        self.evals_root = Path(evals_root)
        self.read_roots = [Path(r) for r in (read_roots or [])]
        self.manifest_model = (
            manifest_model  # RunManifest from contracts.manifest once it lands (WS5)
        )
        self.root.mkdir(parents=True, exist_ok=True)

    # ---------------------------------------------------------------- locating runs
    def run_dir(self, run_id: str) -> Path:
        """Folder with the run's manifest and trace: writable root first, then read-only roots."""
        _safe_name(run_id)
        own = self.root / run_id
        if (own / MANIFEST).exists():
            return own
        for r in self.read_roots:
            if (r / run_id / MANIFEST).exists():
                return r / run_id
        return own

    def _write_dir(self, run_id: str) -> Path:
        """Where views and assessments go; an overlay in the writable root for read-only runs."""
        return self.root / _safe_name(run_id)

    def is_read_only(self, run_id: str) -> bool:
        return self.run_dir(run_id).parent != self.root

    def trace_path(self, run_id: str) -> Path:
        return self.run_dir(run_id) / "trace.jsonl"

    def list_runs(self) -> list[str]:
        ids = {p.parent.name for p in self.root.glob(f"*/{MANIFEST}")}
        for r in self.read_roots:
            ids |= {p.parent.name for p in r.glob(f"*/{MANIFEST}")}
        return sorted(ids)

    # ---------------------------------------------------------------- manifest and trace
    def create_run(self, manifest: Any) -> Path:
        run_id = manifest.run_id if hasattr(manifest, "run_id") else manifest["run_id"]
        d = self.root / _safe_name(run_id)
        try:
            d.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise StoreWriteRefused(f"run {run_id} already exists") from None
        with (d / MANIFEST).open("x", encoding="utf-8") as fh:  # written exactly once
            fh.write(_dump(manifest))
        self.write_status(run_id, "created")
        return d

    def read_manifest(self, run_id: str) -> Any:
        raw = json.loads((self.run_dir(run_id) / MANIFEST).read_text())
        return self.manifest_model.model_validate(raw) if self.manifest_model else raw

    def read_trace(self, run_id: str) -> Trace:
        return read_trace(self.run_dir(run_id), run_id)

    def assert_trace_writable(self, run_id: str) -> None:
        """Call before (re)opening a tracer on a run, e.g. on an infra retry."""
        if self.is_read_only(run_id):
            raise StoreWriteRefused(f"run {run_id} is in a read-only root")
        st = self.read_status(run_id)
        if st and st.state in TERMINAL_STATES:
            raise StoreWriteRefused(
                f"run {run_id} is finished ({st.state}); its trace is immutable"
            )

    # ---------------------------------------------------------------- status
    def write_status(
        self,
        run_id: str,
        state: RunLifecycle,
        attempt: int = 1,
        incomplete: bool = False,
    ) -> None:
        if not (self.run_dir(run_id) / MANIFEST).exists():
            # Would otherwise create a stray folder that makes a later create_run fail.
            raise FileNotFoundError(f"unknown run {run_id}: create_run it first")
        d = self._write_dir(run_id)
        prev = self.read_status(run_id)
        if prev and prev.state in TERMINAL_STATES and state != prev.state:
            raise StoreWriteRefused(f"run {run_id} already finished as {prev.state}")
        st = RunStatus(
            state=state,
            updated_at=datetime.now(UTC).isoformat(),
            attempt=attempt,
            incomplete=incomplete or bool(prev and prev.incomplete),
        )
        _atomic_write(d / STATUS, st.model_dump_json(indent=2))
        if state in TERMINAL_STATES and not self.is_read_only(run_id):
            self._lock_files(self.run_dir(run_id))

    def read_status(self, run_id: str) -> RunStatus | None:
        for d in (self._write_dir(run_id), self.run_dir(run_id)):
            p = d / STATUS
            if p.exists():
                return RunStatus.model_validate_json(p.read_text())
        return None

    @staticmethod
    def _lock_files(d: Path) -> None:
        for name in PROTECTED:
            p = d / name
            if p.exists():
                mode = p.stat().st_mode
                p.chmod(mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))

    # ---------------------------------------------------------------- views and assessments
    def write_summary(self, run_id: str, summary: Any) -> None:
        _atomic_write(self._write_dir(run_id) / "summary.json", _dump(summary))

    def append_assessment(self, run_id: str, assessment: Any) -> None:
        aid = (
            assessment.assessment_id
            if hasattr(assessment, "assessment_id")
            else assessment["assessment_id"]
        )
        d = self._write_dir(run_id) / "assessments"
        d.mkdir(parents=True, exist_ok=True)
        try:
            with (d / f"{_safe_name(aid)}.json").open(
                "x", encoding="utf-8"
            ) as fh:  # never overwrite
                fh.write(_dump(assessment))
        except FileExistsError:
            raise StoreWriteRefused(f"assessment {aid} already exists for run {run_id}") from None

    def list_assessments(self, run_id: str) -> list[dict]:
        out: dict[str, dict] = {}
        for d in (
            self.run_dir(run_id),
            self._write_dir(run_id),
        ):  # samples first, overlay after
            for p in sorted((d / "assessments").glob("*.json")):
                out[p.stem] = json.loads(p.read_text())
        return list(out.values())

    def write_report(
        self, run_id: str, report: Any, rendered: dict[str, str] | None = None
    ) -> None:
        d = self._write_dir(run_id)
        _atomic_write(d / "report.json", _dump(report))
        for name, text in (rendered or {}).items():
            _atomic_write(d / _safe_name(name), text)

    def query(self, sql: str, params: dict | None = None) -> list[dict]:
        """Run SQL over the ``manifests``, ``status``, ``assessments`` and ``run_ends`` tables.

        Values go in ``params`` as ``$name`` placeholders, never into the SQL string. File access
        is switched off once the tables are loaded (see ``store/query.py``).
        """
        return run_query(self, sql, params)

    # ------------------------------------------------------- eval artefacts (open point 10)
    def create_eval(self, eval_id: str, spec: Any) -> Path:
        d = self.evals_root / _safe_name(eval_id)
        try:
            d.mkdir(parents=True, exist_ok=False)
        except FileExistsError:
            raise StoreWriteRefused(f"eval {eval_id} already exists") from None
        if isinstance(spec, BaseModel):
            text = yaml.safe_dump(spec.model_dump(mode="json"), sort_keys=False)
        elif isinstance(spec, dict):
            text = yaml.safe_dump(spec, sort_keys=False)
        else:
            text = str(spec)  # the exact spec text as launched
        with (d / "spec.yaml").open("x", encoding="utf-8") as fh:
            fh.write(text)
        return d

    def write_eval_artifact(self, eval_id: str, name: str, data: bytes | str) -> None:
        if _safe_name(name) == "spec.yaml":
            raise StoreWriteRefused("spec.yaml is written once by create_eval")
        _atomic_write(self.evals_root / _safe_name(eval_id) / name, data)

    def read_eval_artifact(self, eval_id: str, name: str) -> bytes:
        return (self.evals_root / _safe_name(eval_id) / _safe_name(name)).read_bytes()

    def list_eval_runs(self, eval_id: str) -> list[str]:
        p = self.evals_root / _safe_name(eval_id) / "plan.json"
        if not p.exists():
            return []
        plan = json.loads(p.read_text())
        runs = plan.get("runs", plan) if isinstance(plan, dict) else plan
        return [r["run_id"] if isinstance(r, dict) else str(r) for r in runs]
