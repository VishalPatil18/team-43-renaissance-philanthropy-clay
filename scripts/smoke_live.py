#!/usr/bin/env python3
"""Live smoke test: a real Bedrock model drives a harness through the instrumented wrappers.

The tool is a canned in-process fake (the real MCP tool sets belong to WS2), so this checks the
model adapter, wrappers, harness, guards and prices against the real Converse API, not the tools.
It is capped by ``budget.run`` (default $0.05 and 8 steps), so it costs a fraction of a cent.

    uv run python scripts/smoke_live.py                         # Nova Lite + Strands
    uv run python scripts/smoke_live.py --harness converse_loop
    uv run python scripts/smoke_live.py --model-id us.amazon.nova-pro-v1:0
"""

from __future__ import annotations

import argparse
import json
import sys

import claysandbox.platform.registry_bootstrap  # noqa: F401  (registers the plugins)
from claysandbox.contracts.fakes.sink import MemoryEventSink
from claysandbox.contracts.fakes.tools import FakeToolSession
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.runtime import RunContext
from claysandbox.contracts.spec import RunLimits
from claysandbox.contracts.tools import ToolResult
from claysandbox.runtime.guard import build_guard
from claysandbox.runtime.instrument import InstrumentedModel, InstrumentedTools, ParentLinks
from claysandbox.runtime.pricing import YamlPriceTable

SEARCH = ToolSpec(
    server="stac",
    name="search_items",
    description="Search NAIP imagery items. Returns the matching item IDs.",
    input_schema={
        "type": "object",
        "properties": {
            "collection": {"type": "string"},
            "bbox": {"type": "array", "items": {"type": "number"}},
            "datetime": {"type": "string"},
        },
        "required": ["collection", "bbox"],
    },
    capability="imagery_search",
)
SYSTEM = "You are a geospatial data assistant. Use the tools provided. Return JSON only."
PROMPT = (
    "Find all NAIP aerial imagery items covering Kern County, CA for 2022 "
    "(bbox -120.2,34.8,-117.6,35.8). "
    'Return {"items": [<item id>, ...]}.'
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--harness", default="strands", choices=["strands", "converse_loop"])
    parser.add_argument("--model-id", default="us.amazon.nova-lite-v1:0")
    parser.add_argument("--max-usd", type=float, default=0.05)
    args = parser.parse_args()

    sink = MemoryEventSink("smoke-1")
    session = FakeToolSession(
        [SEARCH],
        {
            ("stac", "search_items"): ToolResult(
                text=json.dumps({"features": [{"id": "ca_m_3511902_ne_11_060_20220604"}]})
            )
        },
    )
    prices = YamlPriceTable()
    guard = build_guard(RunLimits(max_usd=args.max_usd, max_steps=8))
    links = ParentLinks()
    model = resolve("model", "bedrock")({"model_id": args.model_id, "max_tokens": 600})
    ctx = RunContext(
        run_id="smoke-1",
        prompt=PROMPT,
        system_prompt=SYSTEM,
        model=InstrumentedModel(model, sink, guard, prices, links),
        tools=InstrumentedTools(session, sink, guard, links),
        events=sink,
    )
    try:
        outcome = resolve("harness", args.harness)({}).run(ctx)
    finally:
        guard.close()
        session.close()

    print(f"harness={args.harness} model={args.model_id} price_table={prices.version}")
    for e in sink.events:
        if e.type == "model_call":
            print(
                f"  {e.seq} model_call  in={e.input_tokens} out={e.output_tokens} "
                f"cost=${e.cost_usd:.6f} stop={e.stop_reason} parent={e.parent_id}"
            )
        elif e.type == "tool_call":
            print(
                f"  {e.seq} tool_call   {e.server}.{e.tool} {e.args} -> {e.status} "
                f"parent={e.parent_id}"
            )
        else:
            print(f"  {e.seq} {e.type} {getattr(e, 'error', None)}")
    print(f"outcome: {outcome.state} output={outcome.output!r} error={outcome.error}")
    print(f"totals: {guard.totals()}")
    return 0 if outcome.state == "completed" else 1


if __name__ == "__main__":
    sys.exit(main())
