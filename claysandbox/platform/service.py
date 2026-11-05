"""The service layer: the composition root behind the CLI and the API (architecture §4, §8.5).

``run_eval`` is the whole eval lifecycle (srs §8.2):

1. validate the spec and expand it into a run plan (``plan.py``);
2. estimate the cost and refuse when it exceeds the eval cap or the caller hasn't confirmed;
3. write ``evals/<id>/spec.yaml``, ``plan.json`` and ``estimate.json``;
4. submit runs to the executor (``local`` or ``fargate``), keeping ``plan.json`` current;
   an ``infra_retry`` gets a new attempt with a new run ID until ``infra_retries`` is used
   up, then ``infra_excluded`` (DD-012); once the eval's dollar cap is spent, the remaining
   runs become ``skipped_eval_cap`` (FR-11.6);
5. build the eval report (WS4 ``build_eval_report_content``) and render it.

Fargate runs land in S3; the service syncs them into the local store before reporting.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import TERMINAL_STATES, RunRequest, RunStatus
from claysandbox.contracts.ids import new_id
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.runtime import CostEstimate, EvalBudget
from claysandbox.contracts.spec import EvalSpec
from claysandbox.platform import custom, worker
from claysandbox.platform.plan import build_requests, configurations
from claysandbox.runtime.pricing import YamlPriceTable
from claysandbox.store.local import LocalRunStore
from claysandbox.tasks.library import FileTaskLibrary

log = logging.getLogger("claysandbox.service")
StatusCallback = Callable[[str, str], None]


@dataclass
class EvalResult:
    eval_id: str
    run_ids: list[str] = field(default_factory=list)
    states: dict[str, str] = field(default_factory=dict)
    report_path: Path | None = None
    warnings: list[str] = field(default_factory=list)


# ------------------------------------------------------------------ spec
def load_spec(path: str | Path) -> EvalSpec:
    data = yaml.safe_load(Path(path).read_text())
    try:
        return EvalSpec.model_validate(data)
    except Exception as exc:  # pydantic ValidationError -> one clear config error
        raise ConfigError(f"invalid spec {path}: {exc}", kind="invalid_spec") from None


def _instances(spec: EvalSpec, library: FileTaskLibrary) -> list[str]:
    custom_ids = [custom.instance_id(t) for t in spec.tasks.custom]
    if len(set(custom_ids)) != len(custom_ids):
        raise ConfigError("custom task IDs must be unique", kind="invalid_spec")
    if spec.tasks.custom and not spec.tasks.templates:
        return custom_ids  # a custom-only spec: empty templates means none, not all
    templates = spec.tasks.templates or None
    aois = spec.tasks.aois
    try:
        return [i.id for i in library.instances(templates, aois)] + custom_ids
    except Exception as exc:  # noqa: BLE001
        raise ConfigError(f"unknown task or AOI in the spec: {exc}", kind="invalid_spec") from None


def validate_spec(spec: EvalSpec, library: FileTaskLibrary | None = None) -> list[str]:
    """Raise ``ConfigError`` on problems that would fail every run; return warnings."""
    library = library or FileTaskLibrary()
    configs, warnings = configurations(spec)
    if not _instances(spec, library):
        raise ConfigError("the spec selects no task instances", kind="invalid_spec")
    prices = YamlPriceTable()
    agent_models: list[str] = []
    for cfg in configs:
        for kind, name in (
            ("model", cfg.model.name),
            ("harness", cfg.harness.name),
            ("toolset", cfg.toolset),
            ("tracer", cfg.tracer.name),
        ):
            resolve(kind, name)  # raises ConfigError(kind="unknown_component")
        model_id = str(cfg.model.params.get("model_id", ""))
        if not model_id:
            raise ConfigError(f"configuration {cfg.name!r} has no model_id", kind="invalid_spec")
        if not prices.has(model_id):
            raise ConfigError(
                f"no price for model {model_id!r} (pricing/prices.yaml)", kind="unpriced_model"
            )
        agent_models.append(model_id)
    for ev in spec.evaluators:
        name = f"{ev.name}@{ev.version}" if ev.version else ev.name
        resolve("evaluator", name)
        if ev.name == "llm_process":
            from claysandbox.evaluation.llm_process import check_judge_family

            check_judge_family(str(ev.params.get("model_id", "")), agent_models)  # DD-027
    if spec.executor.name not in ("local", "fargate"):
        raise ConfigError(f"unknown executor {spec.executor.name!r}", kind="unknown_component")
    return warnings


def plan(spec: EvalSpec, eval_id: str, library: FileTaskLibrary | None = None) -> list[RunRequest]:
    requests, _ = build_requests(spec, eval_id, _instances(spec, library or FileTaskLibrary()))
    customs = {custom.instance_id(t): t for t in spec.tasks.custom}
    for r in requests:
        r.extra["executor"] = spec.executor.name
        task = customs.get(r.task_instance_id)
        if task is not None:  # the worker builds the task; only `expect` can score it
            r.extra["custom_task"] = task.model_dump(mode="json")
            r.extra["evaluators"] = custom.EVALUATORS
    return requests


def _store(store_dir: str | Path, s3: bool = False) -> LocalRunStore:
    store_dir = Path(store_dir)
    if s3:
        from claysandbox.store.s3 import S3MirrorRunStore

        return S3MirrorRunStore(store_dir / "runs", store_dir / "evals")
    return LocalRunStore(store_dir / "runs", store_dir / "evals")


def estimate(spec: EvalSpec, store_dir: str | Path = ".") -> CostEstimate:
    from claysandbox.runtime.estimate import CostEstimator

    requests = plan(spec, "estimate")
    return CostEstimator(_store(store_dir), YamlPriceTable()).estimate(requests, spec)


# ------------------------------------------------------------------ plan.json
class _Plan:
    def __init__(self, store: LocalRunStore, eval_id: str, requests: list[RunRequest]):
        self.store, self.eval_id = store, eval_id
        self.rows: dict[str, dict[str, Any]] = {
            r.run_id: {
                "run_id": r.run_id,
                "config_name": r.config_name,
                "task_instance_id": r.task_instance_id,
                "trial_index": r.trial_index,
                "attempt": r.attempt,
                "state": "planned",
            }
            for r in requests
        }
        self.save()

    def set(self, run_id: str, state: str, **extra: Any) -> None:
        self.rows[run_id].update(state=state, **extra)
        self.save()

    def add(self, req: RunRequest, retry_of: str) -> None:
        self.rows[req.run_id] = {
            "run_id": req.run_id,
            "config_name": req.config_name,
            "task_instance_id": req.task_instance_id,
            "trial_index": req.trial_index,
            "attempt": req.attempt,
            "state": "planned",
            "retry_of": retry_of,
        }
        self.save()

    def save(self) -> None:
        body = {
            "eval_id": self.eval_id,
            "updated_at": datetime.now(UTC).isoformat(),
            "runs": list(self.rows.values()),
        }
        self.store.write_eval_artifact(self.eval_id, "plan.json", json.dumps(body, indent=2))


def eval_status(eval_id: str, store_dir: str | Path = ".") -> dict:
    return json.loads(_store(store_dir).read_eval_artifact(eval_id, "plan.json"))


# ------------------------------------------------------------------ eval report
def build_report(
    spec: EvalSpec, eval_id: str, store: LocalRunStore, run_ids: list[str]
) -> Path | None:
    from claysandbox.contracts.assessment import Assessment
    from claysandbox.contracts.manifest import RunManifest
    from claysandbox.evaluation.compare import build_eval_report_content

    manifests: list[RunManifest] = []
    assessments: list[Assessment] = []
    states: dict[str, Any] = {}
    totals: dict[str, dict[str, Any]] = {}
    for run_id in run_ids:
        d = store.run_dir(run_id)
        if not (d / "manifest.json").exists():
            continue
        manifests.append(RunManifest.model_validate_json((d / "manifest.json").read_text()))
        assessments += [Assessment.model_validate(a) for a in store.list_assessments(run_id)]
        st = store.read_status(run_id)
        states[run_id] = st.state if st else "agent_failed"
        ends = [e for e in store.read_trace(run_id).events if e.type == "run_end"]
        totals[run_id] = dict(ends[-1].totals) if ends else {}
    if not manifests:
        return None
    variants = {v.name: v.override for v in spec.variants}
    stats = getattr(spec, "stats", None) or {}
    stats = stats if isinstance(stats, dict) else {}
    report = build_eval_report_content(
        eval_id,
        None,
        spec.baseline.name if spec.baseline else "",
        variants,
        seed=spec.seed,
        iterations=int(stats.get("bootstrap_iterations", 5000)),
        alpha=float(stats.get("alpha", 0.05)),
        manifests=manifests,
        assessments=assessments,
        run_states=states,
        totals=totals,
    )
    store.write_eval_artifact(eval_id, "eval_report.json", report.model_dump_json(indent=2))
    try:
        from claysandbox.platform.reports.markdown import render_eval_report

        store.write_eval_artifact(
            eval_id, "eval_report.md", render_eval_report(json.loads(report.model_dump_json()))
        )
        return store.evals_root / eval_id / "eval_report.md"
    except ImportError:
        return store.evals_root / eval_id / "eval_report.json"


# ------------------------------------------------------------------ the eval loop
def _executor(spec: EvalSpec, store: LocalRunStore) -> Any:
    params = dict(spec.executor.params)
    if spec.executor.name == "fargate":
        return resolve("executor", "fargate")(params)
    from claysandbox.platform.executors.local import LocalExecutor

    return LocalExecutor(params).bind(lambda req: worker.run_one(req, store))


def check_aws_credentials(spec: EvalSpec) -> None:
    """Fail once, before any run starts, when Bedrock or Fargate would have no credentials.

    Without this every run crashes on its own and is retried, and the real cause (often the
    ``botocore[crt]`` extra that ``aws login`` credentials need) is buried in tracebacks.
    """
    configs, _ = configurations(spec)
    needs_aws = (
        spec.executor.name == "fargate"
        or any(c.model.name == "bedrock" for c in configs)
        or any(e.name == "llm_process" for e in spec.evaluators)
        or (spec.summary is not None and spec.summary.name == "llm")
    )
    if spec.offline or not needs_aws:
        return
    import boto3
    from botocore.exceptions import MissingDependencyException

    try:
        credentials = boto3.Session().get_credentials()
        if credentials is not None:
            credentials.get_frozen_credentials()  # refreshes now: an expired login fails here
    except MissingDependencyException:
        raise ConfigError(
            "AWS credentials from `aws login` need botocore[crt]; run `uv sync` and retry",
            kind="aws_credentials",
        ) from None
    except Exception as exc:  # noqa: BLE001  any provider failure: say it once, plainly
        message = f"AWS credentials are not usable ({exc}); run `aws login` and retry"
        raise ConfigError(message, kind="aws_credentials") from None
    if credentials is None:
        raise ConfigError(
            "no AWS credentials found: run `aws login` (or set AWS_PROFILE) and retry",
            kind="aws_credentials",
        )


def run_eval(
    spec: EvalSpec,
    *,
    store_dir: str | Path = ".",
    confirm: bool = False,
    eval_id: str | None = None,
    on_status: StatusCallback | None = None,
    poll_seconds: float = 1.0,
) -> EvalResult:
    warnings = validate_spec(spec)
    eval_id = eval_id or f"{spec.name}-{new_id()[-8:].lower()}"
    requests = plan(spec, eval_id)
    est = estimate(spec, store_dir)
    if est.exceeds_eval_cap:
        raise ConfigError(
            f"estimated ${est.total_usd:.2f} exceeds the eval cap ${spec.budget.eval.max_usd}",
            kind="needs_confirm",
        )
    if len(requests) > 1 and not confirm:
        raise ConfigError(
            f"{len(requests)} runs, estimated ${est.total_usd:.2f}: confirm to launch",
            kind="needs_confirm",
        )

    check_aws_credentials(spec)
    fargate = spec.executor.name == "fargate"
    store = _store(store_dir, s3=fargate)
    store.create_eval(eval_id, spec.model_dump(mode="json"))  # writes spec.yaml
    store.write_eval_artifact(eval_id, "estimate.json", est.model_dump_json(indent=2))
    tracked = _Plan(store, eval_id, requests)
    by_id = {r.run_id: r for r in requests}
    budget = EvalBudget(spec.budget.eval.max_usd)
    executor = _executor(spec, store)
    result = EvalResult(eval_id=eval_id, warnings=warnings)

    queue = list(requests)
    in_flight = 0
    max_parallel = int(spec.executor.params.get("max_parallel", 2))

    def launch_more() -> None:
        nonlocal in_flight
        batch: list[RunRequest] = []
        while queue and in_flight + len(batch) < max_parallel:
            req = queue.pop(0)
            if budget.exhausted:
                tracked.set(req.run_id, "skipped_eval_cap")
                result.states[req.run_id] = "skipped_eval_cap"
                if on_status:
                    on_status(req.run_id, "skipped_eval_cap")
                continue
            tracked.set(req.run_id, "running")
            batch.append(req)
        if batch:
            executor.submit(batch)
            in_flight += len(batch)

    launch_more()
    while in_flight:
        time.sleep(poll_seconds)
        for status in executor.poll():
            in_flight -= 1
            req = by_id[status.run_id]
            if fargate:  # bring the finished run folder down from S3
                try:
                    store.sync_down(f"runs/{status.run_id}/")  # type: ignore[attr-defined]
                except Exception as exc:  # noqa: BLE001
                    log.warning("sync of %s failed: %s", status.run_id, exc)
            cost = float((status.environment or {}).get("cost_usd") or 0.0)
            budget.add(cost)
            state = status.state
            if state == "infra_retry":
                if req.attempt <= spec.infra_retries:
                    retry = req.model_copy(update={"run_id": new_id(), "attempt": req.attempt + 1})
                    retry.extra = {
                        **req.extra,
                        "attempts": [
                            *req.extra.get("attempts", []),
                            {
                                "run_id": req.run_id,
                                "attempt": req.attempt,
                                "error_kind": status.error_kind,
                            },
                        ],
                    }
                    by_id[retry.run_id] = retry
                    tracked.set(req.run_id, "infra_retry", error_kind=status.error_kind)
                    tracked.add(retry, retry_of=req.run_id)
                    queue.insert(0, retry)
                    state = "infra_retry"
                else:
                    state = "infra_excluded"
            if state != "infra_retry":
                tracked.set(
                    req.run_id, state, error_kind=status.error_kind, cost_usd=round(cost, 6)
                )
                result.states[req.run_id] = state
                if state in TERMINAL_STATES:
                    result.run_ids.append(req.run_id)
            else:
                result.states[req.run_id] = "infra_retry"
            if on_status:
                on_status(req.run_id, state)
        launch_more()

    if hasattr(executor, "shutdown"):
        executor.shutdown()
    result.report_path = build_report(spec, eval_id, store, result.run_ids)
    if fargate:
        try:
            store.mirror_eval(eval_id)  # type: ignore[attr-defined]
        except Exception as exc:  # noqa: BLE001
            log.warning("mirroring eval %s failed: %s", eval_id, exc)
    return result


def run_worker_request(request_ref: str, store_dir: str | Path = ".") -> RunStatus:
    return worker.run_request(request_ref, store_dir)
