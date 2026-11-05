"""The run pipeline end to end on fake components: worker, plan, local executor, service.

Real: task library (T1 references), harnesses, JSONL tracer, event sink, local store,
evaluators, summarizer, eval report. Fake: the model (scripted replies) and the tool set.
No network, no AWS.
"""

from __future__ import annotations

import json
import threading
from pathlib import Path

import pytest
from pydantic import BaseModel

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.contracts.errors import ConfigError, InfraError
from claysandbox.contracts.fakes.model import FakeModelAdapter, text_reply, tool_reply
from claysandbox.contracts.fakes.tools import FakeToolSession
from claysandbox.contracts.registry import register
from claysandbox.contracts.spec import EvalSpec
from claysandbox.contracts.tools import ToolResult
from claysandbox.platform import service, worker
from claysandbox.platform.plan import build_requests, configurations
from claysandbox.runtime.testing import GEOCODE_TOOL, SEARCH_NAME, SEARCH_TOOL
from claysandbox.store.local import LocalRunStore
from claysandbox.tasks.library import FileTaskLibrary

LIB = FileTaskLibrary()
MODEL_ID = "us.amazon.nova-lite-v1:0"  # priced, so validation and pricing work
_lock = threading.Lock()
FAIL_FIRST: dict[str, int] = {
    "remaining": 0
}  # how many model constructions start with an infra error


def _answer(instance_id: str) -> dict:
    return {"items": LIB.get_reference(instance_id).output_reference["items"]}


@register("model", "fake-scripted")
class ScriptedModel(FakeModelAdapter):
    """Searches once with good arguments, then answers with the reference items of its task."""

    name = "fake-scripted"
    version = "test"

    class Params(BaseModel):
        model_id: str = MODEL_ID
        temperature: float = 0.0

    def __init__(self, params: dict | None = None):
        p = self.Params(**(params or {}))
        with _lock:
            fail = FAIL_FIRST["remaining"] > 0
            FAIL_FIRST["remaining"] -= int(fail)
        self._fail = fail
        super().__init__([], model_id=p.model_id)

    def converse(self, messages, system, tools, params):  # type: ignore[no-untyped-def]
        if self._fail:
            raise InfraError("throttled", "ThrottlingException (fake)")
        first = messages[0]["content"][0]["text"]  # the task prompt, as the harness sent it
        instance = next(i.id for i in LIB.instances(["T1"]) if i.prompt.strip() in first)
        bbox = LIB.get_instance(instance).params.get("area_bbox")
        self.script = [
            tool_reply((SEARCH_NAME, {"collections": ["naip"], "bbox": bbox, "datetime": "2022"})),
            text_reply(json.dumps(_answer(instance))),
        ]
        self.calls = self.calls[: len(self.calls)]
        step = len([m for m in messages if m.get("role") == "assistant"])
        self.calls.append({})
        return self.script[min(step, 1)].model_copy(deep=True, update={"model_id": self.model_id})


@register("toolset", "fake-t1")
class FakeT1Toolset:
    name = "fake-t1"
    version = "test"

    def open_blocking(self, *_a, **_k):
        def search(args):  # returns every reference item of every T1 instance: a superset
            items = sorted({x for i in LIB.instances(["T1"]) for x in _answer(i.id)["items"]})
            return ToolResult(text=json.dumps({"features": [{"id": x} for x in items]}))

        return FakeToolSession([SEARCH_TOOL, GEOCODE_TOOL], {("stac", "search_items"): search})


def _spec(**over) -> EvalSpec:
    base = {
        "name": "fake-eval",
        "tasks": {"templates": ["T1"], "aois": ["us-ca-kern", "us-nv-clark"]},
        "baseline": {
            "name": "base",
            "model": {"name": "fake-scripted", "params": {"model_id": MODEL_ID}},
            "harness": {"name": "converse_loop"},
            "toolset": "fake-t1",
        },
        "variants": [{"name": "warm", "override": {"model": {"params": {"temperature": 0.7}}}}],
        "evaluators": [{"name": "workflow", "version": "1"}, {"name": "output", "version": "1"}],
        "summary": {"name": "deterministic"},
        "trials": 1,
        "budget": {"run": {"max_steps": 10, "max_usd": 0.5}},
        "executor": {"name": "local", "params": {"max_parallel": 2}},
    }
    base.update(over)
    return EvalSpec.model_validate(base)


def test_plan_expands_configs_instance_major_with_warnings():
    spec = _spec(
        variants=[
            {
                "name": "both",
                "override": {
                    "model": {"params": {"temperature": 1}},
                    "harness": {"name": "strands"},
                },
            }
        ]
    )
    configs, warnings = configurations(spec)
    assert [c.name for c in configs] == ["base", "both"]
    assert configs[1].harness.name == "strands" and configs[1].model.params["temperature"] == 1
    assert any("more than one agent axis" in w for w in warnings)
    reqs, _ = build_requests(spec, "e1", ["T1@us-ca-kern", "T1@us-nv-clark"])
    assert [(r.task_instance_id, r.config_name) for r in reqs] == [
        ("T1@us-ca-kern", "base"),
        ("T1@us-ca-kern", "both"),
        ("T1@us-nv-clark", "base"),
        ("T1@us-nv-clark", "both"),
    ]
    assert reqs[0].extra["budget"]["max_steps"] == 10 and reqs[0].extra["spec_sha256"]


def test_worker_runs_one_request_into_a_complete_run_folder(tmp_path: Path):
    spec = _spec()
    req = service.plan(spec, "e-worker")[0]
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    status = worker.run_one(req, store)
    assert status.state == "completed"
    d = store.run_dir(req.run_id)
    for name in (
        "manifest.json",
        "trace.jsonl",
        "status.json",
        "summary.json",
        "report.md",
        "reference.json",
    ):
        assert (d / name).exists(), name
    events = [json.loads(x) for x in (d / "trace.jsonl").read_text().splitlines()]
    assert events[0]["type"] == "run_start" and events[-1]["type"] == "run_end"
    assert "final_output" in [e["type"] for e in events]
    manifest = json.loads((d / "manifest.json").read_text())
    assert manifest["config_name"] == "base" and manifest["tools"] and manifest["spec_sha256"]
    kinds = {a["kind"]: a for a in store.list_assessments(req.run_id)}
    assert kinds["workflow"]["success"] is True and kinds["output"]["composite"] == 1.0
    assert (
        "Workflow" in (d / "report.md").read_text() or "workflow" in (d / "report.md").read_text()
    )


def test_service_runs_an_eval_with_plan_and_comparison_report(tmp_path: Path):
    seen: list[tuple[str, str]] = []
    result = service.run_eval(
        _spec(),
        store_dir=tmp_path,
        confirm=True,
        on_status=lambda r, s: seen.append((r, s)),
        poll_seconds=0.05,
    )
    assert len(result.run_ids) == 4 and set(result.states.values()) == {"completed"}
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    for run_id in result.run_ids:  # every run answered its own task correctly
        out = [a for a in store.list_assessments(run_id) if a["kind"] == "output"]
        assert out and out[0]["composite"] == 1.0, run_id
    plan = service.eval_status(result.eval_id, tmp_path)
    assert {r["state"] for r in plan["runs"]} == {"completed"}
    report = json.loads((tmp_path / "evals" / result.eval_id / "eval_report.json").read_text())
    assert [c["config_name"] for c in report["stats"]["configs"]] == ["base", "warm"]
    assert report["stats"]["comparisons"] and report["variants"][0]["axis"] == "model"
    assert result.report_path and result.report_path.exists()
    assert len(seen) == 4


def test_infra_error_is_retried_as_a_new_attempt(tmp_path: Path):
    FAIL_FIRST["remaining"] = 1
    try:
        spec = _spec(variants=[], tasks={"templates": ["T1"], "aois": ["us-ca-kern"]})
        result = service.run_eval(spec, store_dir=tmp_path, poll_seconds=0.05)
    finally:
        FAIL_FIRST["remaining"] = 0
    plan = service.eval_status(result.eval_id, tmp_path)["runs"]
    assert [r["state"] for r in plan] == ["infra_retry", "completed"]
    assert plan[1]["retry_of"] == plan[0]["run_id"] and plan[1]["attempt"] == 2


def test_multi_run_eval_needs_confirmation(tmp_path: Path):
    with pytest.raises(ConfigError) as exc:
        service.run_eval(_spec(), store_dir=tmp_path)
    assert exc.value.kind == "needs_confirm"


def test_validation_rejects_unknown_components_and_unpriced_models():
    with pytest.raises(ConfigError):
        service.validate_spec(
            _spec(
                baseline={
                    "name": "b",
                    "model": {"name": "nope", "params": {"model_id": MODEL_ID}},
                    "harness": {"name": "converse_loop"},
                    "toolset": "fake-t1",
                }
            )
        )
    with pytest.raises(ConfigError):
        service.validate_spec(
            _spec(
                baseline={
                    "name": "b",
                    "model": {"name": "fake-scripted", "params": {"model_id": "made-up"}},
                    "harness": {"name": "converse_loop"},
                    "toolset": "fake-t1",
                }
            )
        )
