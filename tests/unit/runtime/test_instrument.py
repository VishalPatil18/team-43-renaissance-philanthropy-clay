from __future__ import annotations

import asyncio

import pytest

from claysandbox.contracts.errors import ConfigError, GuardStopped, InfraError
from claysandbox.contracts.fakes.guard import NoopGuard, TripGuard
from claysandbox.contracts.fakes.model import text_reply, tool_reply
from claysandbox.contracts.fakes.pricing import FixedPriceTable
from claysandbox.contracts.runtime import ModelAdapter
from claysandbox.contracts.tools import ToolResult
from claysandbox.runtime.instrument import PREVIEW_TOOL_CHARS, InstrumentedModel, InstrumentedTools
from claysandbox.runtime.testing import (
    GEOCODE_TOOL,
    SEARCH_NAME,
    SEARCH_TOOL,
    build_context,
)


def test_model_call_event_has_tokens_cost_latency_and_price_version() -> None:
    h = build_context(
        [text_reply("x" * 800, input_tokens=1000, output_tokens=500)],
        prices=FixedPriceTable(0.001, 0.002),
    )
    h.ctx.model.converse([], "s", [], {})
    h.close()
    (event,) = h.sink.events
    assert event.type == "model_call"
    assert (event.input_tokens, event.output_tokens) == (1000, 500)  # type: ignore[union-attr]
    assert event.cost_usd == pytest.approx(1000 / 1000 * 0.001 + 500 / 1000 * 0.002)  # type: ignore[union-attr]
    assert event.price_table_version == "fixed-test"  # type: ignore[union-attr]
    assert event.latency_ms is not None and event.ts_end is not None
    assert len(event.text_preview or "") == 500  # type: ignore[union-attr]
    assert (event.seq, event.event_id) == (0, "run-1:0")


def test_events_are_ordered_and_tool_calls_link_to_the_model_call_that_asked() -> None:
    h = build_context(
        [
            tool_reply(
                (SEARCH_NAME, {"collection": "naip"}, "tu-a"),
                ("osm__geocode", {"query": "Kern County"}, "tu-b"),
            ),
            text_reply("done"),
        ]
    )
    model, tools = h.ctx.model, h.ctx.tools
    model.converse([], "", [SEARCH_TOOL, GEOCODE_TOOL], {})
    tools.call_blocking("stac", "search_items", {"collection": "naip"}, tool_use_id="tu-a")
    tools.call_blocking("osm", "geocode", {"query": "Kern County"}, tool_use_id="tu-b")
    model.converse([], "", [], {})
    h.close()

    assert [e.type for e in h.sink.events] == ["model_call", "tool_call", "tool_call", "model_call"]
    assert [e.seq for e in h.sink.events] == [0, 1, 2, 3]
    assert h.sink.events[1].parent_id == "run-1:0"
    assert h.sink.events[2].parent_id == "run-1:0"
    assert h.sink.events[1].capability == "imagery_search"  # type: ignore[union-attr]
    assert h.sink.events[2].capability == "geocode"  # type: ignore[union-attr]


def test_large_tool_result_is_stored_as_a_blob_with_a_truncated_preview() -> None:
    big = "y" * (PREVIEW_TOOL_CHARS * 5)
    h = build_context([], handlers={("stac", "search_items"): ToolResult(text=big)})
    result = h.ctx.tools.call_blocking("stac", "search_items", {"collection": "naip"})
    h.close()
    assert result.text == big  # the model still gets the full result
    (event,) = h.sink.events
    assert event.type == "tool_call" and event.status == "ok"  # type: ignore[union-attr]
    assert len(event.result_preview or "") == PREVIEW_TOOL_CHARS  # type: ignore[union-attr]
    assert event.result_ref == f"blobs/{event.result_sha256}"  # type: ignore[union-attr]
    assert h.sink.blobs[event.result_ref] == big.encode()  # type: ignore[index,arg-type]


def test_structured_only_result_is_stored_as_json() -> None:
    h = build_context(
        [], handlers={("stac", "search_items"): ToolResult(text="", structured={"n": 1})}
    )
    h.ctx.tools.call_blocking("stac", "search_items", {"collection": "naip"})
    h.close()
    (event,) = h.sink.events
    assert h.sink.blobs[event.result_ref] == b'{"n": 1}'  # type: ignore[index,arg-type]


def test_tool_error_result_is_traced_as_a_tool_error_and_returned() -> None:
    h = build_context(
        [], handlers={("stac", "search_items"): ToolResult(text="bad bbox", is_error=True)}
    )
    result = h.ctx.tools.call_blocking("stac", "search_items", {"collection": "naip"})
    h.close()
    assert result.is_error
    (event,) = h.sink.events
    assert event.status == "error"  # type: ignore[union-attr]
    assert (event.error.source, event.error.kind) == ("tool", "tool_error")  # type: ignore[union-attr]


def test_tool_timeout_is_traced_and_returned_to_the_model_as_an_error() -> None:
    h = build_context([], handlers={("stac", "search_items"): TimeoutError()})
    result = h.ctx.tools.call_blocking("stac", "search_items", {}, timeout_s=5)
    h.close()
    assert result.is_error and "timed out after 5" in result.text
    (event,) = h.sink.events
    assert event.status == "timeout"  # type: ignore[union-attr]
    assert (event.error.source, event.error.kind) == ("tool", "tool_timeout")  # type: ignore[union-attr]


def test_server_crash_is_server_unavailable() -> None:
    h = build_context([], handlers={("stac", "search_items"): BrokenPipeError("pipe closed")})
    result = h.ctx.tools.call_blocking("stac", "search_items", {})
    h.close()
    assert result.is_error
    assert h.sink.events[0].error.kind == "server_unavailable"  # type: ignore[union-attr]


@pytest.mark.parametrize(
    ("result", "status", "kind"),
    [
        (ToolResult(text="timed out after 0.5 s", status="timeout"), "timeout", "tool_timeout"),
        (ToolResult(text="server gone", error_kind="server_unavailable"), "error",
         "server_unavailable"),
        (ToolResult(text="bad", error_kind="tool_error"), "error", "tool_error"),
    ],
)
def test_status_and_error_kind_in_the_result_are_traced(
    result: ToolResult, status: str, kind: str
) -> None:
    """DD-045: the real MCP session reports timeouts and dead servers in the result."""
    h = build_context([], handlers={("stac", "search_items"): result})
    returned = h.ctx.tools.call_blocking("stac", "search_items", {})
    h.close()
    assert returned.is_error
    (event,) = h.sink.events
    assert event.status == status  # type: ignore[union-attr]
    assert (event.error.source, event.error.kind) == ("tool", kind)  # type: ignore[union-attr]
    assert event.error.retryable is (status == "timeout")  # type: ignore[union-attr]


def test_unexpected_tool_exception_is_a_tool_error_not_a_crash() -> None:
    h = build_context([], handlers={("stac", "search_items"): ValueError("bug")})
    result = h.ctx.tools.call_blocking("stac", "search_items", {})
    h.close()
    assert result.is_error
    assert h.sink.events[0].error.kind == "tool_error"  # type: ignore[union-attr]


def test_async_call_works_and_times_out() -> None:
    h = build_context([])

    class Slow:
        def list_tools(self):  # type: ignore[no-untyped-def]
            return []

        async def call(self, server, tool, args, timeout_s):  # type: ignore[no-untyped-def]
            await asyncio.sleep(5)

        async def aclose(self) -> None: ...

    tools = InstrumentedTools(Slow(), h.sink, NoopGuard())  # type: ignore[arg-type]
    result = asyncio.run(tools.call("s", "t", {}, timeout_s=0.05))
    h.close()
    assert result.is_error
    assert h.sink.events[0].status == "timeout"  # type: ignore[union-attr]

    ok = build_context([])
    result = asyncio.run(ok.ctx.tools.call("stac", "search_items", {"collection": "naip"}))
    ok.close()
    assert result.text == "ok" and ok.sink.events[0].status == "ok"  # type: ignore[union-attr]


def test_guard_stop_propagates_and_emits_one_guard_stop_event() -> None:
    h = build_context([text_reply("a"), text_reply("b")], guard=TripGuard(model_call=2))
    h.ctx.model.converse([], "", [], {})
    with pytest.raises(GuardStopped) as info:
        h.ctx.model.converse([], "", [], {})
    h.close()
    assert [e.type for e in h.sink.events] == ["model_call", "guard_stop"]
    stop = h.sink.events[1]
    assert stop.limit == "max_steps"  # type: ignore[union-attr]
    assert stop.error.source == "budget" and stop.error.kind == "budget_exceeded"  # type: ignore[union-attr]
    assert info.value.limit == "max_steps"
    assert len(h.model.calls) == 1  # the second call never reached the model


def test_tool_guard_stop_propagates_before_the_server_is_called() -> None:
    h = build_context([], guard=TripGuard(tool_call=1))
    with pytest.raises(GuardStopped):
        h.ctx.tools.call_blocking("stac", "search_items", {})
    h.close()
    assert h.session.calls == []
    assert [e.type for e in h.sink.events] == ["guard_stop"]
    assert h.sink.events[0].error.kind == "loop_detected"  # type: ignore[union-attr]


def test_infra_error_is_traced_then_reraised() -> None:
    h = build_context([InfraError("throttled", "slow down")])
    with pytest.raises(InfraError):
        h.ctx.model.converse([], "", [], {})
    h.close()
    (event,) = h.sink.events
    assert event.type == "model_call" and event.cost_usd == 0.0  # type: ignore[union-attr]
    assert (event.error.source, event.error.kind, event.error.retryable) == (  # type: ignore[union-attr]
        "infra",
        "throttled",
        True,
    )


def test_config_error_is_traced_then_reraised() -> None:
    h = build_context([ConfigError("denied", kind="access_denied")])
    with pytest.raises(ConfigError):
        h.ctx.model.converse([], "", [], {})
    h.close()
    assert h.sink.events[0].error.kind == "access_denied"  # type: ignore[union-attr]


def test_missing_price_still_records_the_call_then_raises() -> None:
    class NoPrices(FixedPriceTable):
        def model_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
            raise ConfigError("no price", kind="price_missing")

    h = build_context([text_reply("x", input_tokens=7, output_tokens=2)], prices=NoPrices())
    with pytest.raises(ConfigError):
        h.ctx.model.converse([], "", [], {})
    h.close()
    event = h.sink.events[0]
    assert event.type == "model_call" and event.error.kind == "price_missing"  # type: ignore[union-attr]
    assert event.input_tokens == 7  # type: ignore[union-attr]


def test_wrappers_expose_the_adapter_interface() -> None:
    h = build_context([text_reply("x")])
    assert isinstance(h.ctx.model, ModelAdapter)
    assert isinstance(h.ctx.model, InstrumentedModel)
    assert h.ctx.model.model_id == "fake-model"
    h.close()
