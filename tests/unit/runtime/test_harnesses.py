from __future__ import annotations

from typing import Any

import pytest

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.contracts.fakes.model import text_reply, tool_reply
from claysandbox.contracts.tools import ToolResult
from claysandbox.runtime.harness._checks import (
    ToolIndex,
    parse_final_output,
)
from claysandbox.runtime.harness.converse_loop import ConverseLoopHarness
from claysandbox.runtime.harness.strands_harness import StrandsHarness
from claysandbox.runtime.testing import (
    GEOCODE_TOOL,
    SEARCH_NAME,
    SEARCH_TOOL,
    build_context,
)

ALL = [StrandsHarness, ConverseLoopHarness]


# -- A-4: Strands must never use its own Bedrock or MCP clients -----------------------------


def test_strands_makes_no_bedrock_calls_of_its_own(monkeypatch: pytest.MonkeyPatch) -> None:
    """Only the bridge (through our adapter) may call Bedrock (assumption A-4)."""
    import botocore.client

    calls: list[str] = []

    def spy(self: Any, operation_name: str, api_params: Any) -> Any:
        calls.append(f"{self.meta.service_model.service_name}.{operation_name}")
        raise AssertionError("an AWS call was made")

    monkeypatch.setattr(botocore.client.BaseClient, "_make_api_call", spy)
    h = build_context(
        [tool_reply((SEARCH_NAME, {"collection": "naip"})), text_reply('{"items": []}')]
    )
    outcome = StrandsHarness({}).run(h.ctx)
    h.close()
    assert outcome.state == "completed"
    assert calls == []
    assert len(h.model.calls) == 2  # both model calls went through ctx.model


def test_strands_receives_the_system_prompt_prompt_and_tool_list_through_our_adapter() -> None:
    h = build_context([text_reply("hi")], prompt="Find NAIP for Kern", system_prompt="Be terse.")
    StrandsHarness({}).run(h.ctx)
    h.close()
    call = h.model.calls[0]
    assert call["system"] == "Be terse."
    assert call["messages"][0] == {"role": "user", "content": [{"text": "Find NAIP for Kern"}]}
    assert call["tools"] == [SEARCH_TOOL.model_name, GEOCODE_TOOL.model_name]


def test_strands_turn_limit_is_reported_as_no_final_output() -> None:
    replies = [
        tool_reply((SEARCH_NAME, {"collection": "naip", "limit": i + 1}, f"tu{i}"))
        for i in range(10)
    ]
    h = build_context(replies)
    outcome = StrandsHarness({"max_cycles": 2}).run(h.ctx)
    h.close()
    assert outcome.state == "agent_failed"
    assert outcome.error is not None and outcome.error.kind == "no_final_output"
    assert len(h.model.calls) == 2


def test_converse_loop_turn_limit_is_reported_as_no_final_output() -> None:
    replies = [
        tool_reply((SEARCH_NAME, {"collection": "naip", "limit": i + 1}, f"tu{i}"))
        for i in range(10)
    ]
    h = build_context(replies)
    outcome = ConverseLoopHarness({"max_turns": 3}).run(h.ctx)
    h.close()
    assert outcome.state == "agent_failed"
    assert outcome.error is not None and outcome.error.kind == "no_final_output"
    assert len(h.model.calls) == 3


def test_max_tokens_stop_with_text_still_completes_and_without_text_fails() -> None:
    for harness in ALL:
        h = build_context([text_reply("partial answer", stop_reason="max_tokens")])
        assert harness({}).run(h.ctx).state == "completed"
        h.close()
    h = build_context([text_reply("", stop_reason="max_tokens")])
    outcome = ConverseLoopHarness({}).run(h.ctx)
    h.close()
    assert outcome.state == "agent_failed"
    assert outcome.error is not None and outcome.error.kind == "no_final_output"


# -- FR-1.11: deterministic ordering ---------------------------------------------------------


@pytest.mark.parametrize("harness", ALL)
def test_tool_calls_run_in_the_order_the_model_gave_them(harness: type) -> None:
    h = build_context(
        [
            tool_reply(
                ("osm__geocode", {"query": "A"}, "t1"),
                (SEARCH_NAME, {"collection": "naip"}, "t2"),
                ("osm__geocode", {"query": "B"}, "t3"),
            ),
            text_reply("done"),
        ],
    )
    harness({}).run(h.ctx)
    h.close()
    assert h.session.calls == [
        ("osm", "geocode", {"query": "A"}),
        ("stac", "search_items", {"collection": "naip"}),
        ("osm", "geocode", {"query": "B"}),
    ]


def test_converse_loop_sends_all_results_in_one_user_message_in_order() -> None:
    h = build_context(
        [
            tool_reply(
                ("osm__geocode", {"query": "A"}, "t1"), (SEARCH_NAME, {"collection": "n"}, "t2")
            ),
            text_reply("done"),
        ],
        handlers={
            ("osm", "geocode"): ToolResult(text="geo"),
            ("stac", "search_items"): ToolResult(text="boom", is_error=True),
        },
    )
    ConverseLoopHarness({}).run(h.ctx)
    h.close()
    second = h.model.calls[1]["messages"]
    assert [m["role"] for m in second] == ["user", "assistant", "user"]
    results = [b["toolResult"] for b in second[2]["content"]]
    assert [(r["toolUseId"], r["status"]) for r in results] == [("t1", "success"), ("t2", "error")]
    assert results[0]["content"] == [{"text": "geo"}]


@pytest.mark.parametrize("harness", ALL)
def test_same_script_gives_the_same_event_sequence_on_both_harnesses(harness: type) -> None:
    """Equivalence (PRI-R1-02): types, tool names and arguments match across harnesses."""

    def trace(cls: type) -> list[tuple[Any, ...]]:
        h = build_context(
            [
                tool_reply((SEARCH_NAME, {"collection": "naip", "limit": 2}, "t1")),
                tool_reply(("osm__geocode", {"query": "Kern"}, "t2")),
                text_reply('{"items": ["x"]}'),
            ],
            handlers={("stac", "search_items"): ToolResult(text="[1,2]")},
        )
        outcome = cls({}).run(h.ctx)
        h.close()
        rows: list[tuple[Any, ...]] = [("outcome", outcome.state, outcome.output)]
        for e in h.sink.events:
            if e.type == "tool_call":
                rows.append((e.type, e.server, e.tool, e.args, e.status, e.capability))
            elif e.type == "model_call":
                rows.append((e.type, e.input_tokens, e.output_tokens, e.stop_reason))
            else:
                rows.append((e.type,))
        return rows

    assert trace(harness) == trace(ConverseLoopHarness)


# -- shared checks ---------------------------------------------------------------------------


def test_parse_final_output() -> None:
    assert parse_final_output('{"items": [1]}') == {"items": [1]}
    assert parse_final_output('  {"a": 1}\n') == {"a": 1}
    assert parse_final_output('Here you go:\n```json\n{"items": ["a"]}\n```\nBye') == {
        "items": ["a"]
    }
    assert parse_final_output('```\n{"a": 2}\n```') == {"a": 2}
    assert parse_final_output("plain words") == "plain words"
    assert parse_final_output("[1, 2]") == "[1, 2]"  # only objects are structured output
    assert parse_final_output("{broken") == "{broken"
    # Nova models put the answer after a <thinking> block (seen in the live smoke test).
    nova = '<thinking>The tool returned {"x": 1}. I will answer.</thinking>\n{"items": ["a"]}'
    assert parse_final_output(nova) == {"items": ["a"]}
    assert parse_final_output('Sure! {"items": ["a", "b"]} Hope that helps.') == {
        "items": ["a", "b"]
    }
    assert parse_final_output('{"outer": {"inner": 1}} trailing') == {"outer": {"inner": 1}}
    assert (
        parse_final_output("<thinking>just thinking</thinking>")
        == "<thinking>just thinking</thinking>"
    )


def test_a_reply_with_only_thinking_is_no_final_output() -> None:
    for harness in ALL:
        h = build_context([text_reply("<thinking>hmm</thinking>")])
        outcome = harness({}).run(h.ctx)
        h.close()
        assert outcome.state == "agent_failed"
        assert outcome.error is not None and outcome.error.kind == "no_final_output"


def test_tool_index_validates_against_the_schema_and_tolerates_odd_schemas() -> None:
    index = ToolIndex([SEARCH_TOOL])
    assert index.schema_error(SEARCH_TOOL, {"collection": "naip"}) is None
    assert "collection" in (index.schema_error(SEARCH_TOOL, {}) or "")
    assert "limit" in (index.schema_error(SEARCH_TOOL, {"collection": "n", "limit": "x"}) or "")

    broken = SEARCH_TOOL.model_copy(update={"input_schema": {"type": "not-a-type"}})
    assert ToolIndex([broken]).schema_error(broken, {"anything": 1}) is None  # not enforced


def test_harness_params_are_validated() -> None:
    with pytest.raises(ValueError):
        StrandsHarness({"max_cycles": 0})
    with pytest.raises(ValueError):
        ConverseLoopHarness({"max_turns": -1})
