"""Conformance suite: every registered ``Harness`` must pass these (FR-1.3, FR-1.6, DD-035).

Runs on fakes, so it needs no AWS. A new harness is covered the moment it is registered.
"""

from __future__ import annotations

import pytest

import claysandbox.platform.registry_bootstrap  # noqa: F401  (registers every plugin)
from claysandbox.contracts.errors import ConfigError, InfraError
from claysandbox.contracts.fakes.guard import TripGuard
from claysandbox.contracts.fakes.model import text_reply, tool_reply
from claysandbox.contracts.registry import list_components, resolve
from claysandbox.contracts.runtime import Harness
from claysandbox.contracts.tools import ToolResult
from claysandbox.runtime.testing import SEARCH_NAME, build_context

HARNESSES = sorted(c["name"] for c in list_components("harness"))


def make(name: str) -> Harness:
    return resolve("harness", name)({})


def test_at_least_the_two_planned_harnesses_are_registered() -> None:
    assert {"strands", "converse_loop"} <= set(HARNESSES)


@pytest.mark.parametrize("name", HARNESSES)
def test_implements_the_harness_interface(name: str) -> None:
    harness = make(name)
    assert isinstance(harness, Harness)
    assert harness.name == name
    assert harness.version


@pytest.mark.parametrize("name", HARNESSES)
def test_two_step_tool_use_reaches_a_final_output(name: str) -> None:
    h = build_context(
        [
            tool_reply((SEARCH_NAME, {"collection": "naip"})),
            text_reply('{"items": ["a", "b"]}'),
        ],
        handlers={("stac", "search_items"): ToolResult(text='{"features": ["a", "b"]}')},
    )
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()

    assert outcome.state == "completed"
    assert outcome.output == {"items": ["a", "b"]}
    assert outcome.steps == 2
    types = [e.type for e in h.sink.events]
    assert types == ["model_call", "tool_call", "model_call"]
    assert h.sink.events[1].parent_id == h.sink.events[0].event_id  # type: ignore[union-attr]
    assert h.session.calls == [("stac", "search_items", {"collection": "naip"})]


@pytest.mark.parametrize("name", HARNESSES)
def test_plain_text_answer_is_kept_as_text(name: str) -> None:
    h = build_context([text_reply("Nothing found.")])
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()
    assert outcome.state == "completed"
    assert outcome.output == "Nothing found."


@pytest.mark.parametrize("name", HARNESSES)
def test_guard_stop_before_a_model_call_is_not_swallowed(name: str) -> None:
    h = build_context([text_reply("never reached")], guard=TripGuard(model_call=1))
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()
    assert outcome.state == "budget_stopped"
    assert outcome.error is not None and outcome.error.kind == "budget_exceeded"
    assert [e.type for e in h.sink.events] == ["guard_stop"]
    assert h.model.calls == []


@pytest.mark.parametrize("name", HARNESSES)
def test_guard_stop_inside_a_tool_call_ends_the_run(name: str) -> None:
    """Strands swallows tool exceptions; the harness must still stop the run."""
    h = build_context(
        [tool_reply((SEARCH_NAME, {"collection": "naip"})), text_reply("should not be reached")],
        guard=TripGuard(tool_call=1),
    )
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()
    assert outcome.state == "budget_stopped"
    assert h.session.calls == []
    assert [e.type for e in h.sink.events] == ["model_call", "guard_stop"]
    assert len(h.model.calls) == 1


@pytest.mark.parametrize("name", HARNESSES)
def test_infra_error_ends_the_run_as_retryable_infra_error(name: str) -> None:
    h = build_context([InfraError("throttled", "ThrottlingException: slow down")])
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()
    assert outcome.state == "infra_error"
    assert outcome.error is not None
    assert (outcome.error.source, outcome.error.kind, outcome.error.retryable) == (
        "infra",
        "throttled",
        True,
    )
    model_call = h.sink.events[0]
    assert model_call.type == "model_call" and model_call.error is not None


@pytest.mark.parametrize("name", HARNESSES)
def test_config_error_ends_the_run_without_retry(name: str) -> None:
    h = build_context([ConfigError("AccessDeniedException: no", kind="access_denied")])
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()
    assert outcome.state == "infra_error"
    assert outcome.error is not None and outcome.error.retryable is False


@pytest.mark.parametrize("name", HARNESSES)
def test_unexpected_exception_becomes_agent_failed_not_a_crash(name: str) -> None:
    h = build_context([RuntimeError("boom")])
    try:
        outcome = make(name).run(h.ctx)
    finally:
        h.close()
    assert outcome.state == "agent_failed"
    assert outcome.error is not None and outcome.error.source == "agent"
    assert h.sink.events[-1].type == "error"
