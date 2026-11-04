"""AgentCore Runtime entrypoint for the Clay sandbox agent.

Hosts the sandbox's own agent stack on AgentCore Runtime (HTTP protocol, ``POST /invocations``
and ``GET /ping`` on port 8080, provided by ``BedrockAgentCoreApp``):

    Bedrock adapter -> instrumented model/tool wrappers + guards -> Strands harness
                    -> WS2 MCP launcher -> RODA MCP server (tool set T0)

The only difference from a local run is how the RODA server starts: the managed runtime has no
``uvx``, so the pinned server package is shipped inside the deployment zip and started as
``python -m awslabs.roda_mcp_server.server`` with the same tool set definition otherwise.

Request:  {"prompt": "...", "model_id": "us.amazon.nova-lite-v1:0"}   (model_id optional)
Response: {"run_id", "state", "output", "error", "events", "totals"}

Observability: the runtime starts this file with ``opentelemetry-instrument`` (see the deploy
script's ``entryPoint``), so ADOT traces every request into CloudWatch (AgentCore Observability).
"""

from __future__ import annotations

import logging
import os
import sys
from typing import Any

from bedrock_agentcore.runtime import BedrockAgentCoreApp

# Register only the plugins this agent uses (registry_bootstrap would also pull in the
# evaluation stack, which the runtime does not need).
import claysandbox.runtime.harness.strands_harness  # noqa: F401
import claysandbox.runtime.models.bedrock  # noqa: F401
from claysandbox.contracts.fakes.sink import MemoryEventSink
from claysandbox.contracts.ids import new_id
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.runtime import RunContext
from claysandbox.contracts.spec import RunLimits
from claysandbox.contracts.tools import ServerDef, ToolSetDef
from claysandbox.runtime.guard import build_guard
from claysandbox.runtime.instrument import InstrumentedModel, InstrumentedTools, ParentLinks
from claysandbox.runtime.pricing import YamlPriceTable
from claysandbox.tools.launcher import McpStdioToolSession

log = logging.getLogger("clay.agentcore")
logging.basicConfig(level=logging.INFO)

DEFAULT_MODEL_ID = os.environ.get("CLAY_MODEL_ID", "us.amazon.nova-lite-v1:0")
SYSTEM = "You are a geospatial data assistant. Use the tools provided. Return JSON only."
PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))

# Tool set T0 (toolsets/T0.yaml), with the server started from the deployment package.
T0 = ToolSetDef(
    name="T0",
    description="Registry of Open Data on AWS (RODA) dataset discovery only.",
    servers=[
        ServerDef(
            name="roda",
            command=[sys.executable, "-m", "awslabs.roda_mcp_server.server"],
            env={"FASTMCP_LOG_LEVEL": "ERROR", "PYTHONPATH": PACKAGE_ROOT},
            needs_aws=False,  # anonymous access works for every RODA tool (toolsets/README.md)
            timeout_s=60,
        )
    ],
    capabilities={
        "dataset_discovery": [
            "roda.search_datasets",
            "roda.list_datasets",
            "roda.get_dataset_details",
            "roda.discover_by_organization",
            "roda.discover_by_license",
            "roda.find_related_datasets",
            "roda.search_stac_endpoints",
        ]
    },
)

app = BedrockAgentCoreApp()
PRICES = YamlPriceTable()


@app.entrypoint
def invoke(payload: dict[str, Any]) -> dict[str, Any]:
    prompt = payload.get("prompt")
    if not isinstance(prompt, str) or not prompt.strip():
        return {"error": "'prompt' must be a non-empty string"}
    model_id = payload.get("model_id") or DEFAULT_MODEL_ID

    run_id = new_id()
    sink = MemoryEventSink(run_id)
    guard = build_guard(RunLimits(max_usd=0.10, max_steps=10, max_seconds=240))
    links = ParentLinks()
    session = McpStdioToolSession(T0, log_dir="/tmp/clay-mcp").start()
    try:
        ctx = RunContext(
            run_id=run_id,
            prompt=prompt,
            system_prompt=SYSTEM,
            model=InstrumentedModel(
                resolve("model", "bedrock")({"model_id": model_id, "max_tokens": 1000}),
                sink,
                guard,
                PRICES,
                links,
            ),
            tools=InstrumentedTools(session, sink, guard, links),
            events=sink,
        )
        outcome = resolve("harness", "strands")({}).run(ctx)
    finally:
        guard.close()
        session.close()

    events = []
    for e in sink.events:
        row: dict[str, Any] = {"seq": e.seq, "type": e.type}
        if e.type == "model_call":
            row.update(
                tokens=[e.input_tokens, e.output_tokens], cost_usd=e.cost_usd, stop=e.stop_reason
            )
        elif e.type == "tool_call":
            row.update(tool=f"{e.server}.{e.tool}", status=e.status)
        if getattr(e, "error", None) is not None:
            row["error"] = e.error.kind
        events.append(row)
    log.info("run %s finished: %s", run_id, outcome.state)
    return {
        "run_id": run_id,
        "state": outcome.state,
        "output": outcome.output,
        "error": outcome.error.model_dump() if outcome.error else None,
        "events": events,
        "totals": guard.totals(),
    }


if __name__ == "__main__":
    # AgentCore Runtime requires port 8080. CLAY_LOCAL_PORT is only for local testing.
    app.run(port=int(os.environ.get("CLAY_LOCAL_PORT", "8080")))
