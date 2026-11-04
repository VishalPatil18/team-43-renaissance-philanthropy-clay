"""Builders for crafted mini traces used by the workflow evaluator tests."""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace, parse_event
from tests.fixtures.traces import load

RUN = "mini"


def err(source: str, kind: str) -> dict[str, Any]:
    return {"source": source, "kind": kind, "message": f"{source}/{kind}"}


def model(**kw: Any) -> dict[str, Any]:
    return {"type": "model_call", "model_id": "fake", "input_tokens": 1, "output_tokens": 1, **kw}


def tool(
    capability: str | None,
    status: str = "ok",
    args: dict | None = None,
    *,
    server: str = "stac",
    name: str = "search_items",
    **kw: Any,
) -> dict[str, Any]:
    return {
        "type": "tool_call",
        "server": server,
        "tool": name,
        "capability": capability,
        "args": args or {},
        "status": status,
        **kw,
    }


def final(output: Any) -> dict[str, Any]:
    return {"type": "final_output", "output": output}


def guard(limit: str = "loop") -> dict[str, Any]:
    return {
        "type": "guard_stop",
        "limit": limit,
        "limit_value": 3,
        "observed_value": 4,
        "error": err("agent", "loop_detected"),
    }


def error_event(source: str, kind: str) -> dict[str, Any]:
    return {"type": "error", "error": err(source, kind)}


def trace(*events: dict[str, Any], state: str = "completed") -> Trace:
    """A run_start, the given events in order, then run_end; seq/event_id filled in."""
    body = [
        {"type": "run_start", "task_instance_id": "T1@us-ca-kern", "config_name": "c"},
        *events,
        {"type": "run_end", "state": state},
    ]
    parsed = [
        parse_event({**e, "run_id": RUN, "seq": i, "event_id": f"{RUN}:{i}"})
        for i, e in enumerate(body)
    ]
    return Trace(run_id=RUN, events=parsed)


def context(**workflow: Any) -> tuple[RunManifest, TaskReference]:
    """The good_t1 manifest and reference, with workflow fields overridden."""
    _, manifest, reference = load("good_t1")
    wf = reference.workflow.model_copy(update=workflow)
    return manifest.model_copy(update={"run_id": RUN}), reference.model_copy(
        update={"workflow": wf}
    )


GOOD_ARGS = {"collection": "naip", "bbox": [-119.2, 35.0, -118.0, 35.8], "datetime": "2022"}
GOOD_OUTPUT = {"items": ["a"]}
