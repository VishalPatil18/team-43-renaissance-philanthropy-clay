"""Local HTTP API for browsing runs and launching evaluations."""

from __future__ import annotations

import asyncio
import json
import re
import threading
import time
from collections import Counter
from datetime import UTC, datetime
from functools import cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import ValidationError
from starlette.types import ASGIApp, Receive, Scope, Send

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.ids import new_id
from claysandbox.contracts.registry import list_components
from claysandbox.contracts.spec import EvalSpec
from claysandbox.contracts.store import TERMINAL_STATES, RunLifecycle
from claysandbox.contracts.task import TaskReference
from claysandbox.platform import service
from claysandbox.store import query as q
from claysandbox.store.local import LocalRunStore
from claysandbox.tasks.library import FileTaskLibrary

REPO_ROOT = Path(__file__).resolve().parents[2]
UI_DIST = REPO_ROOT / "ui" / "dist"
LOCAL_AUTHORITY = re.compile(r"(?:127\.0\.0\.1|localhost|\[::1\])(?::([0-9]{1,5}))?", re.I)


def _local_authority(value: str, *, origin: bool = False) -> bool:
    """Accept only a loopback authority, with an HTTP(S) scheme required for Origin."""
    if origin:
        if not value.startswith(("http://", "https://")):
            return False
        value = value.split("://", 1)[1]
    match = LOCAL_AUTHORITY.fullmatch(value)
    return bool(match and (match[1] is None or 0 < int(match[1]) <= 65535))


class LocalOnly:
    """403 unless Host is a loopback name and Origin, when present, is one too."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http":
            hosts = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"host"]
            origins = [v.decode("latin-1") for k, v in scope["headers"] if k.lower() == b"origin"]
            if (
                len(hosts) != 1
                or not _local_authority(hosts[0])
                or len(origins) > 1
                or (origins and not _local_authority(origins[0], origin=True))
                or (
                    scope["method"] == "POST"
                    and not origins
                    and any(
                        k.lower() == b"sec-fetch-site" and v.lower() == b"cross-site"
                        for k, v in scope["headers"]
                    )
                )
            ):
                await PlainTextResponse("forbidden: local requests only", 403)(scope, receive, send)
                return
        await self.app(scope, receive, send)


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text()) if path.is_file() else None


@cache
def _validation_result() -> dict:
    from claysandbox.evaluation.validate import default_evaluators, validate

    for source in ("samples/planted", "tests/fixtures/planted"):
        planted = REPO_ROOT / source
        if planted.is_dir():
            report = validate(default_evaluators(), planted_root=planted)
            return {"source": source, "report": report.model_dump(mode="json")}
    raise HTTPException(404, "no planted validation fixtures available")


def create_app(store_root: str | Path, ui_dist: str | Path = UI_DIST) -> FastAPI:
    """App over the store at ``store_root`` (``runs/`` and ``evals/`` below it)."""
    root = Path(store_root).resolve()
    if not (root / "runs").is_dir():
        # LocalRunStore would create the folder; a read-only API must not.
        raise FileNotFoundError(f"no run store at {root} (expected {root / 'runs'})")
    store = LocalRunStore(root / "runs", root / "evals")
    dist = Path(ui_dist).resolve()

    from claysandbox.platform import registry_bootstrap  # noqa: F401  (fills the registry)

    @cache
    def library() -> FileTaskLibrary:
        return FileTaskLibrary()

    def run_dir(run_id: str) -> Path:
        try:
            d = store.run_dir(run_id)
        except ValueError:
            d = None
        if d is None or not (d / "manifest.json").is_file():
            raise HTTPException(404, f"unknown run {run_id!r}")
        return d

    def eval_dir(eval_id: str) -> Path:
        if (
            not eval_id
            or "/" in eval_id
            or "\\" in eval_id
            or eval_id.startswith(".")
            or ".." in eval_id
        ):
            raise HTTPException(404, f"unknown eval {eval_id!r}")
        return store.evals_root / eval_id

    def check_store_boundary() -> None:
        # Queries glob the store directly, so validate links before both lists and detail reads.
        for path in root.rglob("*"):
            if path.is_symlink():
                try:
                    contained = path.resolve().is_relative_to(root)
                except (OSError, RuntimeError):
                    contained = False
                if not contained:
                    raise HTTPException(403, "store contains a link outside its root")

    app = FastAPI(
        title="Clay sandbox API (prototype)",
        version="0.1.0",
        dependencies=[Depends(check_store_boundary)],
    )
    app.add_middleware(LocalOnly)

    launches: dict[str, dict[str, Any]] = {}
    app.state.launches = launches
    launch_lock = threading.Lock()

    @app.exception_handler(ConfigError)
    async def config_error(request: Request, exc: ConfigError) -> JSONResponse:
        return JSONResponse({"detail": str(exc), "kind": exc.kind}, status_code=400)

    async def json_only(request: Request) -> None:
        content_type = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
        if content_type != "application/json":
            raise HTTPException(415, "Content-Type must be application/json")

    def validated(body: dict) -> tuple[EvalSpec, dict]:
        try:
            spec = EvalSpec.model_validate(body.get("spec"))
        except ValidationError as exc:
            raise HTTPException(422, str(exc)) from None
        warnings = service.validate_spec(spec)
        est = service.estimate(spec, root)
        return spec, {
            "runs": len(service.plan(spec, "estimate")),
            **est.model_dump(
                include={"total_usd", "per_config", "exceeds_eval_cap", "eval_cap_usd", "notes"}
            ),
            "warnings": warnings,
        }

    @app.post("/api/estimate", dependencies=[Depends(json_only)])
    def estimate(body: dict) -> dict:
        return validated(body)[1]

    @app.post("/api/evals", status_code=202, dependencies=[Depends(json_only)], response_model=None)
    def launch(body: dict) -> dict | JSONResponse:
        if body.get("confirm") is not True:
            raise ConfigError("confirm must be true to launch", kind="needs_confirm")
        spec, est = validated(body)
        if est["exceeds_eval_cap"]:
            raise ConfigError("estimate exceeds the eval cap", kind="exceeds_eval_cap")
        service.check_aws_credentials(spec)  # answer 400 now, not a failed eval later
        eval_id = f"{spec.name}-{new_id()[-8:].lower()}"
        directory = eval_dir(eval_id)

        def run() -> None:
            try:
                service.run_eval(spec, store_dir=root, confirm=True, eval_id=eval_id)
            except Exception as exc:
                launches[eval_id]["error"] = str(exc)

        with launch_lock:
            if sum(entry["thread"].is_alive() for entry in launches.values()) >= 2:
                return JSONResponse({"detail": "two evaluations are running", "kind": "busy"}, 409)
            thread = threading.Thread(target=run, name=f"eval-{eval_id}", daemon=True)
            launches[eval_id] = {
                "thread": thread,
                "error": None,
                "started_at": datetime.now(UTC).isoformat(),
            }
            thread.start()
        deadline = time.monotonic() + 5
        while time.monotonic() < deadline:
            if launches[eval_id]["error"] is not None:
                raise HTTPException(400, launches[eval_id]["error"])
            if (directory / "plan.json").is_file():
                break
            time.sleep(0.05)
        return {
            "eval_id": eval_id,
            "runs": est["runs"],
            "status_url": f"/api/evals/{eval_id}/status",
            "events_url": f"/api/evals/{eval_id}/events",
        }

    @app.get("/api/evals/{eval_id}/status")
    def eval_status(eval_id: str) -> dict:
        directory = eval_dir(eval_id)
        entry = launches.get(eval_id)
        plan = _read_json(directory / "plan.json")
        if plan is None and entry is None:
            raise HTTPException(404, f"unknown eval {eval_id!r}")
        rows = plan["runs"] if plan else []
        counts = dict(Counter(row["state"] for row in rows))
        return {
            "eval_id": eval_id,
            "runs": rows,
            "counts": counts,
            "done": not any(counts.get(state) for state in ("planned", "running", "infra_retry"))
            and (entry is None or not entry["thread"].is_alive()),
            "error": entry["error"] if entry else None,
            "report": (directory / "eval_report.json").is_file(),
        }

    @app.get("/api/evals/{eval_id}/events", response_class=StreamingResponse)
    def events(eval_id: str, request: Request) -> StreamingResponse:
        eval_status(eval_id)
        path = eval_dir(eval_id) / "plan.json"

        async def stream():
            deadline = time.monotonic() + 2 * 60 * 60
            keepalive = time.monotonic()
            previous = None
            while time.monotonic() < deadline:
                if await request.is_disconnected():
                    return
                check_store_boundary()
                status = eval_status(eval_id)
                stamp = (
                    path.stat().st_mtime_ns if path.is_file() else None,
                    status["error"],
                    status["done"],
                )
                data = json.dumps(status)
                if stamp != previous:
                    yield f"event: status\ndata: {data}\n\n"
                    previous = stamp
                if status["done"]:
                    yield f"event: done\ndata: {data}\n\n"
                    return
                if time.monotonic() - keepalive >= 15:
                    yield ": keepalive\n\n"
                    keepalive = time.monotonic()
                await asyncio.sleep(0.5)

        return StreamingResponse(
            stream(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.get("/api/schema/eval-spec")
    def eval_spec_schema() -> dict:
        return EvalSpec.model_json_schema()

    @app.get("/api/validation")
    def validation() -> dict:
        """Deterministic evaluator validation against bundled planted traces."""
        return _validation_result()

    @app.get("/api/runs")
    def runs(
        template: str | None = None,
        model_id: str | None = None,
        harness_name: str | None = None,
        toolset_name: str | None = None,
        eval_id: str | None = None,
        state: RunLifecycle | None = None,
        limit: Annotated[int, Query(ge=1, le=500)] = 100,
        offset: Annotated[int, Query(ge=0)] = 0,
    ) -> list[dict]:
        """Runs newest first, each with its ``run_end`` totals and composite per evaluator kind."""
        given = {
            "template": template,
            "model_id": model_id,
            "harness_name": harness_name,
            "toolset_name": toolset_name,
            "eval_id": eval_id,
            "state": state,
        }
        rows = q.list_runs(store, {k: v for k, v in given.items() if v is not None}, limit, offset)
        # shortcut: three in-memory loads of the store per call; fine for hundreds of runs,
        # move to one cached connection when the store gets large.
        totals = {r.pop("run_id"): r for r in store.query("SELECT * FROM run_ends")}
        scores: dict[str, dict[str, float | None]] = {}
        for a in store.query("SELECT run_id, kind, composite FROM assessments ORDER BY created_at"):
            scores.setdefault(a["run_id"], {}).setdefault(a["kind"], a["composite"])
        for r in rows:
            r["totals"] = totals.get(r["run_id"], {})
            r["scores"] = scores.get(r["run_id"], {})
        return rows

    @app.get("/api/runs/{run_id}")
    def run(run_id: str) -> dict:
        d = run_dir(run_id)
        status = store.read_status(run_id)
        return {
            "manifest": _read_json(d / "manifest.json"),
            "status": status.model_dump(mode="json") if status else None,
            "summary": _read_json(store.root / run_id / "summary.json"),
            "report": _read_json(store.root / run_id / "report.json"),
        }

    @app.get("/api/runs/{run_id}/trace")
    def trace(run_id: str) -> dict:
        run_dir(run_id)
        return store.read_trace(run_id).model_dump(mode="json")

    @app.get("/api/runs/{run_id}/assessments")
    def assessments(run_id: str) -> list[dict]:
        run_dir(run_id)
        return store.list_assessments(run_id)

    @app.get("/api/runs/{run_id}/reference")
    def reference(run_id: str) -> dict:
        """The task reference the run was scored against; withheld until the run is finished."""
        manifest = _read_json(run_dir(run_id) / "manifest.json")
        status = store.read_status(run_id)
        if status is None or status.state not in TERMINAL_STATES:
            raise HTTPException(409, "the reference is shown once the run has finished")
        instance, version = manifest["task_instance_id"], manifest.get("task_reference_version")
        saved = _read_json(run_dir(run_id) / "reference.json")
        if saved is not None:
            ref = TaskReference.model_validate(saved)
            if ref.instance_id == instance and ref.version == version:
                return {"reference": ref.model_dump(mode="json"), "exact": True}
        try:
            return {
                "reference": library()
                .get_reference(instance, version or None)
                .model_dump(mode="json"),
                "exact": True,
            }
        except ConfigError:
            pass
        try:  # e.g. fixture runs scored against a hand-written reference
            ref = library().get_reference(instance)
        except ConfigError as exc:
            raise HTTPException(404, str(exc)) from None
        return {"reference": ref.model_dump(mode="json"), "exact": False}

    @app.get("/api/evals")
    def evals() -> list[dict]:
        counts = {
            r["eval_id"]: r["runs"]
            for r in store.query(
                "SELECT eval_id, count(*) AS runs FROM manifests "
                "WHERE coalesce(eval_id, '') <> '' GROUP BY eval_id"
            )
        }
        on_disk = (
            {p.name for p in store.evals_root.iterdir() if p.is_dir()}
            if store.evals_root.is_dir()
            else set()
        )
        return [{"eval_id": e, "runs": counts.get(e, 0)} for e in sorted(on_disk | set(counts))]

    @app.get("/api/evals/{eval_id}")
    def eval_detail(eval_id: str) -> dict:
        d = eval_dir(eval_id)
        rows = q.runs_for_eval(store, eval_id)
        if not rows and not d.is_dir():
            raise HTTPException(404, f"unknown eval {eval_id!r}")
        spec = d / "spec.yaml"
        return {
            "eval_id": eval_id,
            "runs": rows,
            "assessments": q.assessments_for_eval(store, eval_id),
            "report": _read_json(d / "eval_report.json"),
            "spec": spec.read_text() if spec.is_file() else None,
        }

    @app.get("/api/components")
    def components() -> list[dict]:
        return list_components()

    @app.get("/api/tasks")
    def tasks() -> list[dict]:
        return [
            {"id": t.id, "template": t.template, "aoi": t.aoi, "title": t.title}
            for t in library().instances()
        ]

    @app.get("/{path:path}", include_in_schema=False)
    def ui(path: str) -> FileResponse:
        """The built UI; unknown paths get ``index.html`` so client-side routes deep-link."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "no such API route")
        index = dist / "index.html"
        if not index.is_file():
            raise HTTPException(404, "UI not built: run `npm ci && npm run build` in ui/")
        target = (dist / path).resolve()
        if target.is_file() and target.is_relative_to(dist):
            return FileResponse(target)
        return FileResponse(index)

    return app
