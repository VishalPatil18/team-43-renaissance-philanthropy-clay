"""J4 (error capture) on fakes, for both harnesses (PRI-R1-01, FR-1.7, FR-1.8, FR-11.5).

Every agent-side mistake becomes one typed error event with the right ``source`` and ``kind``,
and the run continues where srs §12.4 says it should.
"""

from __future__ import annotations

from typing import Any

import pytest

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.contracts.fakes.model import text_reply, tool_reply
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.runtime import RunOutcome
from claysandbox.contracts.tools import ToolResult
from claysandbox.runtime.guard import build_guard
from claysandbox.runtime.testing import SEARCH_NAME, Harnessed, build_context

HARNESSES = ["strands", "converse_loop"]
ANSWER = '{"items": ["a"]}'


def run(name: str, h: Harnessed) -> RunOutcome:
    try:
        return resolve("harness", name)({}).run(h.ctx)
    finally:
        h.close()


def errors(h: Harnessed) -> list[tuple[str, str, str]]:
    """(event type, source, kind) for every event that carries an error."""
    return [
        (e.type, e.error.source, e.error.kind)
        for e in h.sink.events
        if getattr(e, "error", None) is not None
    ]


def last_tool_result(h: Harnessed) -> dict[str, Any]:
    """The toolResult block the model received in its final call."""
    for message in reversed(h.model.calls[-1]["messages"]):
        for block in message["content"]:
            if "toolResult" in block:
                return block["toolResult"]
    raise AssertionError("no toolResult sent to the model")


@pytest.mark.parametrize("name", HARNESSES)
def test_unknown_tool_is_an_agent_error_and_the_run_continues(name: str) -> None:
    h = build_context([tool_reply(("made__up_tool", {"x": 1})), text_reply(ANSWER)])
    outcome = run(name, h)
    assert outcome.state == "completed" and outcome.output == {"items": ["a"]}
    assert errors(h) == [("error", "agent", "unknown_tool")]
    assert h.session.calls == []  # never reached a server
    assert last_tool_result(h)["status"] == "error"
    error_event = next(e for e in h.sink.events if e.type == "error")
    assert error_event.parent_id == h.sink.events[0].event_id  # links to the model call


@pytest.mark.parametrize("name", HARNESSES)
def test_invalid_arguments_are_rejected_before_the_server_is_called(name: str) -> None:
    h = build_context(
        [tool_reply((SEARCH_NAME, {"limit": "ten"})), text_reply(ANSWER)]  # collection missing
    )
    outcome = run(name, h)
    assert outcome.state == "completed"
    assert errors(h) == [("tool_call", "agent", "invalid_args")]
    rejected = next(e for e in h.sink.events if e.type == "tool_call")
    assert rejected.status == "rejected"  # type: ignore[union-attr]
    assert rejected.args == {"limit": "ten"}  # type: ignore[union-attr]
    assert (rejected.server, rejected.tool) == ("stac", "search_items")  # type: ignore[union-attr]
    assert h.session.calls == []
    result = last_tool_result(h)
    assert result["status"] == "error"
    assert "collection" in result["content"][0]["text"]  # the model is told what is wrong


@pytest.mark.parametrize("name", HARNESSES)
def test_wrong_argument_type_is_invalid_args(name: str) -> None:
    h = build_context(
        [tool_reply((SEARCH_NAME, {"collection": "naip", "limit": "ten"})), text_reply(ANSWER)]
    )
    run(name, h)
    assert errors(h) == [("tool_call", "agent", "invalid_args")]


@pytest.mark.parametrize("name", HARNESSES)
def test_tool_use_that_is_not_a_json_object_is_a_malformed_call(name: str) -> None:
    h = build_context([tool_reply((SEARCH_NAME, "not an object")), text_reply(ANSWER)])
    outcome = run(name, h)
    assert outcome.state == "completed"
    assert errors(h) == [("tool_call", "agent", "malformed_call")]
    assert h.session.calls == []


@pytest.mark.parametrize("name", HARNESSES)
def test_valid_calls_raise_no_errors(name: str) -> None:
    h = build_context(
        [tool_reply((SEARCH_NAME, {"collection": "naip", "limit": 5})), text_reply(ANSWER)]
    )
    assert run(name, h).state == "completed"
    assert errors(h) == []
    assert h.session.calls == [("stac", "search_items", {"collection": "naip", "limit": 5})]


@pytest.mark.parametrize("name", HARNESSES)
def test_empty_answer_is_no_final_output_and_agent_failed(name: str) -> None:
    h = build_context([text_reply("")])
    outcome = run(name, h)
    assert outcome.state == "agent_failed"
    assert outcome.error is not None and outcome.error.kind == "no_final_output"
    assert errors(h) == [("error", "agent", "no_final_output")]


@pytest.mark.parametrize("name", HARNESSES)
@pytest.mark.parametrize("stop", ["content_filtered", "guardrail_intervened"])
def test_refusal_with_no_text_is_agent_failed(name: str, stop: str) -> None:
    h = build_context([text_reply("", stop_reason=stop)])
    outcome = run(name, h)
    assert outcome.state == "agent_failed"
    assert outcome.error is not None and outcome.error.kind == "refusal"
    assert errors(h) == [("error", "agent", "refusal")]


@pytest.mark.parametrize("name", HARNESSES)
def test_refusal_with_text_completes_with_that_output(name: str) -> None:
    h = build_context([text_reply("I cannot help with that.", stop_reason="content_filtered")])
    outcome = run(name, h)
    assert outcome.state == "completed" and outcome.output == "I cannot help with that."
    assert errors(h) == [("error", "agent", "refusal")]


@pytest.mark.parametrize("name", HARNESSES)
def test_tool_error_is_traced_returned_to_the_model_and_can_be_recovered(name: str) -> None:
    calls = {"n": 0}

    def flaky(_: dict[str, Any]) -> ToolResult:
        calls["n"] += 1
        return (
            ToolResult(text="bad bbox", is_error=True) if calls["n"] == 1 else ToolResult(text="ok")
        )

    h = build_context(
        [
            tool_reply((SEARCH_NAME, {"collection": "naip", "limit": 1})),
            tool_reply((SEARCH_NAME, {"collection": "naip", "limit": 2})),
            text_reply(ANSWER),
        ],
        handlers={("stac", "search_items"): flaky},
    )
    outcome = run(name, h)
    assert outcome.state == "completed"
    assert errors(h) == [("tool_call", "tool", "tool_error")]
    assert [e.status for e in h.sink.events if e.type == "tool_call"] == ["error", "ok"]  # type: ignore[union-attr]


@pytest.mark.parametrize("name", HARNESSES)
def test_tool_timeout_is_traced_and_the_run_continues(name: str) -> None:
    h = build_context(
        [tool_reply((SEARCH_NAME, {"collection": "naip"})), text_reply(ANSWER)],
        handlers={("stac", "search_items"): TimeoutError()},
    )
    outcome = run(name, h)
    assert outcome.state == "completed"
    assert errors(h) == [("tool_call", "tool", "tool_timeout")]
    assert last_tool_result(h)["status"] == "error"


@pytest.mark.parametrize("name", HARNESSES)
def test_four_identical_calls_trip_the_loop_guard(name: str) -> None:
    same = {"collection": "naip", "limit": 5}
    h = build_context(
        [tool_reply((SEARCH_NAME, same, f"tu{i}")) for i in range(6)] + [text_reply(ANSWER)],
        guard=build_guard(None, {"max_identical_calls": 3}),
    )
    outcome = run(name, h)
    assert outcome.state == "budget_stopped"
    assert outcome.error is not None and (outcome.error.source, outcome.error.kind) == (
        "agent",
        "loop_detected",
    )
    assert len(h.session.calls) == 3  # three allowed, the fourth blocked
    stop = h.sink.events[-1]
    assert stop.type == "guard_stop" and stop.limit == "loop"  # type: ignore[union-attr]
    assert (stop.limit_value, stop.observed_value) == (3, 4)  # type: ignore[union-attr]
    assert errors(h) == [("guard_stop", "agent", "loop_detected")]


@pytest.mark.parametrize("name", HARNESSES)
def test_mixed_errors_in_one_response_are_each_reported_once(name: str) -> None:
    h = build_context(
        [
            tool_reply(
                ("made__up_tool", {}, "tu1"),
                (SEARCH_NAME, {"limit": 1}, "tu2"),
                (SEARCH_NAME, {"collection": "naip"}, "tu3"),
            ),
            text_reply(ANSWER),
        ]
    )
    outcome = run(name, h)
    assert outcome.state == "completed"
    assert sorted(errors(h)) == [
        ("error", "agent", "unknown_tool"),
        ("tool_call", "agent", "invalid_args"),
    ]
    assert h.session.calls == [("stac", "search_items", {"collection": "naip"})]
