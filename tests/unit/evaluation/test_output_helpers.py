"""Builders shared by the test_output_*.py modules."""

from __future__ import annotations

import json
from typing import Any

import claysandbox.evaluation.output  # noqa: F401  (registers the evaluators)
from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.task import AOI, TaskReference, WorkflowSpec
from claysandbox.contracts.trace import FinalOutput, ToolCall, Trace

AOI_BOX = [-120.0, 35.0, -119.0, 36.0]
AOI_GEOM = {
    "type": "Polygon",
    "coordinates": [[[-120, 35], [-119, 35], [-119, 36], [-120, 36], [-120, 35]]],
}


def make_case(
    template: str,
    output: Any,
    reference: dict[str, Any],
    schema: dict[str, Any] | None = None,
    tool_calls: list[ToolCall] | None = None,
    blobs: dict[str, bytes] | None = None,
) -> tuple[Trace, RunManifest, TaskReference]:
    events: list[Any] = []
    for i, tc in enumerate(tool_calls or []):
        events.append(tc.model_copy(update={"event_id": f"r:{i}", "seq": i}))
    final = FinalOutput(output=output, event_id="r:final", seq=len(events))
    events.append(final)
    trace = Trace(run_id="r", events=events)
    if blobs is not None:
        trace.with_blobs(lambda ref: blobs[ref])
    manifest = RunManifest(run_id="r", task_instance_id=f"{template}@aoi-x")
    ref = TaskReference(
        template=template,
        instance_id=f"{template}@aoi-x",
        version="v1",
        workflow=WorkflowSpec(),
        output_reference=reference,
        output_schema=schema or {},
        aoi=AOI(id="aoi-x", bbox=AOI_BOX, geometry=AOI_GEOM),
    )
    return trace, manifest, ref


def tool_call(
    preview: str | None = None, ref: str | None = None, cap: str | None = None
) -> ToolCall:
    return ToolCall(
        server="s", tool="t", capability=cap, status="ok", result_preview=preview, result_ref=ref
    )


def as_json_fenced(obj: Any) -> str:
    return "```json\n" + json.dumps(obj) + "\n```"
