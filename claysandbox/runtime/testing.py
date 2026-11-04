"""Builds a ``RunContext`` wired with fakes and the real instrumented wrappers (owner: WS1).

Used by the harness conformance suite and by tests, so every harness is exercised through the
same wrappers it gets in a real run.
"""

from __future__ import annotations

from dataclasses import dataclass

from claysandbox.contracts.fakes.guard import NoopGuard
from claysandbox.contracts.fakes.model import FakeModelAdapter
from claysandbox.contracts.fakes.pricing import FixedPriceTable
from claysandbox.contracts.fakes.sink import MemoryEventSink
from claysandbox.contracts.fakes.tools import FakeToolSession, Handler
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.runtime import BudgetGuard, ModelResponse, PriceTable, RunContext
from claysandbox.runtime.instrument import InstrumentedModel, InstrumentedTools, ParentLinks

SEARCH_TOOL = ToolSpec(
    server="stac",
    name="search_items",
    description="Search STAC items",
    input_schema={
        "type": "object",
        "properties": {"collection": {"type": "string"}, "limit": {"type": "integer"}},
        "required": ["collection"],
    },
    capability="imagery_search",
)
SEARCH_NAME = SEARCH_TOOL.model_name  # "stac__search_items"

GEOCODE_TOOL = ToolSpec(
    server="osm",
    name="geocode",
    description="Geocode a place name",
    input_schema={
        "type": "object",
        "properties": {"query": {"type": "string"}},
        "required": ["query"],
    },
    capability="geocode",
)


@dataclass
class Harnessed:
    ctx: RunContext
    sink: MemoryEventSink
    model: FakeModelAdapter
    session: FakeToolSession
    guard: BudgetGuard

    def close(self) -> None:
        self.session.close()


def build_context(
    script: list[ModelResponse | Exception],
    *,
    tools: list[ToolSpec] | None = None,
    handlers: dict[tuple[str, str], Handler] | None = None,
    guard: BudgetGuard | None = None,
    prices: PriceTable | None = None,
    prompt: str = "Find imagery",
    system_prompt: str = "You are a geospatial assistant.",
) -> Harnessed:
    sink = MemoryEventSink()
    fake_model = FakeModelAdapter(script)
    session = FakeToolSession(tools if tools is not None else [SEARCH_TOOL, GEOCODE_TOOL], handlers)
    the_guard = guard or NoopGuard()
    links = ParentLinks()
    ctx = RunContext(
        run_id=sink.run_id,
        prompt=prompt,
        system_prompt=system_prompt,
        model=InstrumentedModel(
            fake_model, sink, the_guard, prices or FixedPriceTable(0.001, 0.002), links
        ),
        tools=InstrumentedTools(session, sink, the_guard, links),
        events=sink,
    )
    return Harnessed(ctx, sink, fake_model, session, the_guard)
