"""The run worker: one ``RunRequest`` in, one finished run folder out (architecture §8.1).

``run_one(request, store)`` follows the order in plan-5th-member M5-R0-02 / M5-R1-01:

1. resolve components from the registry; load the task instance and its task reference;
2. open the tool set; build the full ``RunManifest`` and ``create_run``;
3. open the tracer and the event sink; emit ``run_start``;
4. run the harness through the instrumented model and tools (guards, prices);
5. emit ``final_output`` (if any) and ``run_end``; close the tracer and the tool session;
6. post-process every terminal run: summary, every evaluator in the request, the run report;
7. write the final ``status.json`` (which locks manifest and trace).

The worker returns an execution ``RunStatus``. A run that ended in ``infra_error`` comes back
as ``infra_retry``: the executor decides whether to start a new attempt (DD-012).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import platform as py_platform
import socket
import subprocess
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import claysandbox
import claysandbox.platform.registry_bootstrap  # noqa: F401  (registers every plugin)
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import RunRequest, RunStatus
from claysandbox.contracts.manifest import ComponentRef, RunManifest
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.runtime import RunContext
from claysandbox.contracts.spec import CustomTask, LoopGuardSpec, RunLimits
from claysandbox.contracts.trace import ErrorInfo, FinalOutput, RunEnd, RunStart, Trace
from claysandbox.platform import custom
from claysandbox.runtime.guard import build_guard
from claysandbox.runtime.instrument import InstrumentedModel, InstrumentedTools, ParentLinks
from claysandbox.runtime.pricing import YamlPriceTable
from claysandbox.store.local import LocalRunStore
from claysandbox.tasks.library import FileTaskLibrary
from claysandbox.tracing.sink import RunEventSink

log = logging.getLogger("claysandbox.worker")
REPO_ROOT = Path(__file__).resolve().parents[2]


# ------------------------------------------------------------------ provenance helpers
def _git_sha() -> str:
    if os.environ.get("GIT_SHA") and os.environ["GIT_SHA"] != "unknown":
        return os.environ["GIT_SHA"]
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=REPO_ROOT, capture_output=True, text=True, timeout=5
        )
        return out.stdout.strip() if out.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def _lockfile_sha256() -> str:
    lock = REPO_ROOT / "uv.lock"
    return hashlib.sha256(lock.read_bytes()).hexdigest() if lock.is_file() else ""


def _environment() -> dict[str, Any]:
    env: dict[str, Any] = {
        "os": py_platform.platform(),
        "python": py_platform.python_version(),
        "host": socket.gethostname(),
    }
    if os.environ.get("ECS_CONTAINER_METADATA_URI_V4"):
        env["executor_host"] = "fargate"
    return env


def _versioned(name: str, version: str | None) -> str:
    return f"{name}@{version}" if version else name


def _ref_of(obj: Any, kind: str, name: str, params: dict[str, Any]) -> ComponentRef:
    return ComponentRef(
        kind=kind, name=name, version=str(getattr(obj, "version", "") or ""), params=params
    )


# ------------------------------------------------------------------ evaluators and summary
def _build_evaluators(
    request: RunRequest, prices: Any, offline: bool
) -> tuple[list[Any], list[str]]:
    evaluators: list[Any] = []
    notes: list[str] = []
    for choice in request.extra.get("evaluators") or [{"name": "workflow"}, {"name": "output"}]:
        name, version = choice["name"], choice.get("version")
        params = dict(choice.get("params") or {})
        cls = resolve("evaluator", _versioned(name, version))
        if name == "llm_process":
            if offline:
                notes.append("llm_process skipped: offline run (FR-7.2)")
                continue
            # The judge gets an uninstrumented adapter: its cost is evaluation cost (DD-027).
            judge = resolve("model", "bedrock")(
                {"model_id": params["model_id"], "max_tokens": 1500}
            )
            evaluators.append(cls(params, model=judge, price_table=prices))
        else:
            evaluators.append(cls(params) if params else cls())
    return evaluators, notes


def _summarize(
    request: RunRequest, trace: Trace, manifest: RunManifest, prices: Any, offline: bool
) -> Any:
    choice = request.extra.get("summary") or {"name": "deterministic"}
    name = choice.get("name", "deterministic")
    params = dict(choice.get("params") or {})
    if name == "llm" and not offline and params.get("model_id"):
        model = resolve("model", "bedrock")({"model_id": params["model_id"], "max_tokens": 1500})
        summarizer = resolve("summarizer", "llm")(params, model=model, prices=prices)
    else:
        summarizer = resolve("summarizer", "deterministic")()
    return summarizer.summarize(trace, manifest)


def _render_report(
    store: LocalRunStore,
    run_id: str,
    manifest: RunManifest,
    trace: Trace,
    summary: Any,
    assessments: list[Any],
) -> None:
    try:
        from claysandbox.platform.reports.markdown import render_run_report
    except ImportError:  # renderer not installed yet: keep the run, skip the report
        log.warning("run report renderer missing; %s has no report.md", run_id)
        return
    manifest_d = json.loads(manifest.model_dump_json())
    events = [json.loads(e.model_dump_json()) for e in trace.events]
    summary_d = (
        json.loads(summary.model_dump_json()) if hasattr(summary, "model_dump_json") else summary
    )
    asm = [json.loads(a.model_dump_json()) for a in assessments]
    md = render_run_report(manifest_d, events, summary_d, asm)
    report = {
        "run_id": run_id,
        "state": events[-1].get("state") if events else None,
        "assessments": [a["assessment_id"] for a in asm],
    }
    store.write_report(run_id, report, {"report.md": md})


# ------------------------------------------------------------------ the run
def run_one(
    request: RunRequest, store: LocalRunStore, library: FileTaskLibrary | None = None
) -> RunStatus:
    """Execute one run end to end and return its execution status."""
    library = library or FileTaskLibrary()
    offline = bool(request.extra.get("offline"))
    budget = RunLimits.model_validate(request.extra.get("budget") or {})
    loop_cfg = LoopGuardSpec.model_validate(request.extra.get("loop_guard") or {})
    prices = YamlPriceTable()

    if request.extra.get("custom_task"):  # a custom query: not in the task library
        task = CustomTask.model_validate(request.extra["custom_task"])
        instance, reference = custom.instance(task), custom.reference(task)
    else:
        instance = library.get_instance(request.task_instance_id)
        reference = library.get_reference(request.task_instance_id)
    model_params = dict(request.model.params)
    if offline:
        raise ConfigError("an offline run cannot call a model; use replay instead", kind="offline")
    model = resolve("model", request.model.name)(model_params)
    harness = resolve("harness", request.harness.name)(dict(request.harness.params))
    tracer_ref = request.tracer or ComponentRef(kind="tracer", name="jsonl")
    tracer = resolve("tracer", tracer_ref.name)(dict(tracer_ref.params))
    toolset_cls = resolve("toolset", request.toolset.name)
    evaluators, eval_notes = _build_evaluators(request, prices, offline)

    log.info("run start", extra={"run_id": request.run_id, "eval_id": request.eval_id})
    t0 = time.monotonic()
    session = toolset_cls().open_blocking()
    try:
        manifest = RunManifest(
            run_id=request.run_id,
            eval_id=request.eval_id,
            trial_index=request.trial_index,
            attempt=request.attempt,
            attempts=list(request.extra.get("attempts") or []),
            task_instance_id=instance.id,
            task_reference_version=reference.version,
            prompt=instance.prompt,
            system_prompt=instance.system_prompt,
            config_name=request.config_name,
            toolset=_ref_of(toolset_cls, "toolset", request.toolset.name, {}),
            mcp_servers=[
                s.model_dump(mode="json") for s in getattr(session, "servers", lambda: [])()
            ],
            tools=session.list_tools(),
            model=_ref_of(model, "model", request.model.name, model_params),
            harness=_ref_of(harness, "harness", request.harness.name, dict(request.harness.params)),
            tracer=_ref_of(tracer, "tracer", tracer_ref.name, dict(tracer_ref.params)),
            evaluators=[
                ComponentRef(kind="evaluator", name=e.name, version=e.version) for e in evaluators
            ],
            budget=budget.model_dump(mode="json"),
            loop_guard=loop_cfg.model_dump(mode="json"),
            seed=int(request.extra.get("seed") or 0),
            price_table_version=prices.version,
            executor=ComponentRef(
                kind="executor", name=str(request.extra.get("executor", "local"))
            ),
            environment=_environment(),
            package_version=claysandbox.__version__,
            git_sha=_git_sha(),
            lockfile_sha256=_lockfile_sha256(),
            spec_sha256=str(request.extra.get("spec_sha256") or ""),
            started_at=datetime.now(UTC),
        )
        run_dir = store.create_run(manifest)
        (run_dir / "reference.json").write_text(reference.model_dump_json(indent=2))
        store.write_status(request.run_id, "running", attempt=request.attempt)

        tracer.open(request.run_id, run_dir)
        sink = RunEventSink(request.run_id, run_dir, tracer)
        sink.emit(RunStart(task_instance_id=instance.id, config_name=request.config_name))
        guard = build_guard(budget, loop_cfg)
        links = ParentLinks()
        try:
            ctx = RunContext(
                run_id=request.run_id,
                prompt=instance.prompt,
                system_prompt=instance.system_prompt,
                model=InstrumentedModel(model, sink, guard, prices, links),
                tools=InstrumentedTools(session, sink, guard, links),
                events=sink,
                params={},
            )
            outcome = harness.run(ctx)
        finally:
            guard.close()
        # The run worker writes final_output and run_end from the outcome (open point 11).
        if outcome.output is not None:
            sink.emit(FinalOutput(output=outcome.output))
        totals = {**guard.totals(), "wall_ms": (time.monotonic() - t0) * 1000}
        err = outcome.error if isinstance(outcome.error, ErrorInfo) else None
        sink.emit(RunEnd(state=outcome.state, totals=totals, error=err))
        tracer.close()
    finally:
        session.close()

    # Post-processing, for every terminal state (srs §8.3).
    trace = store.read_trace(request.run_id)
    assessments = []
    for evaluator in evaluators:
        try:
            a = evaluator.assess(trace, manifest, reference)
        except Exception as exc:  # noqa: BLE001  one failing evaluator must not lose the run
            log.warning("evaluator %s failed on %s: %s", evaluator.name, request.run_id, exc)
            continue
        store.append_assessment(request.run_id, a)
        assessments.append(a)
    summary = _summarize(request, trace, manifest, prices, offline)
    store.write_summary(request.run_id, summary)
    _render_report(store, request.run_id, manifest, trace, summary, assessments)
    store.write_status(
        request.run_id,
        outcome.state,
        attempt=request.attempt,
        incomplete=bool(getattr(sink, "incomplete", False)),
    )
    for note in eval_notes:
        log.info(note, extra={"run_id": request.run_id})

    state = "infra_retry" if outcome.state == "infra_error" else outcome.state
    return RunStatus(
        run_id=request.run_id,
        eval_id=request.eval_id,
        state=state,
        error_kind=err.kind if err else None,
        message=err.message if err else None,
        environment={"cost_usd": totals.get("cost_usd", 0.0), "steps": totals.get("steps")},
    )


# ------------------------------------------------------------------ worker entry (CLI / Fargate)
def _read_request(ref: str) -> RunRequest:
    if ref.startswith("s3://"):
        import boto3

        bucket, _, key = ref[5:].partition("/")
        body = boto3.client("s3").get_object(Bucket=bucket, Key=key)["Body"].read()
        return RunRequest.model_validate_json(body)
    return RunRequest.model_validate_json(Path(ref).read_text())


def run_request(ref: str, store_dir: str | Path = ".") -> RunStatus:
    """``clay-sandbox worker --request <path|s3://…>``: run one request, mirror to S3 if asked.

    On Fargate the request comes from S3 and the finished run folder is mirrored back to
    ``s3://<bucket>/runs/<run_id>/``, where the Fargate executor reads ``status.json``.
    """
    request = _read_request(ref)
    store_dir = Path(store_dir)
    bucket = (
        ref[5:].split("/", 1)[0]
        if ref.startswith("s3://")
        else os.environ.get("CLAYSANDBOX_BUCKET")
    )
    if bucket:
        from claysandbox.store.s3 import S3MirrorRunStore

        store: LocalRunStore = S3MirrorRunStore(
            store_dir / "runs", store_dir / "evals", bucket=bucket
        )
    else:
        store = LocalRunStore(store_dir / "runs", store_dir / "evals")
    status = run_one(request, store)
    if bucket:
        store.mirror_run(request.run_id)  # type: ignore[attr-defined]
    return status
