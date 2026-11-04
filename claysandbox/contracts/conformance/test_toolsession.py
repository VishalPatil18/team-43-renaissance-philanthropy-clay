"""ToolSession conformance (architecture §7.7, DD-035). Owner: WS2.

Every tool session must:

* list tools with server, name, a JSON-Schema object and a Bedrock-safe ``model_name``;
* answer ``call`` (async) and ``call_blocking`` (sync) with the same result;
* turn tool failures into a ``ToolResult`` with ``is_error`` and a known ``error_kind``, never an
  exception other than ``TimeoutError`` / ``ConnectionError`` / ``OSError`` (which the
  instrumented wrapper maps);
* keep working after a failed call, and close cleanly.

Implementations under test: ``FakeToolSession``, ``McpStdioToolSession`` on the local fixture
server, and (``CLAY_LIVE=1`` only) ``McpStdioToolSession`` on the real tool set ``T0``.
"""

from __future__ import annotations

import asyncio
import os
import re
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

from claysandbox.contracts.fakes.mcp_fixture_server import FIXTURE_SERVER_PATH
from claysandbox.contracts.fakes.tools import FakeToolSession
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.tools import ServerDef, ToolResult, ToolSession, ToolSetDef
from claysandbox.tools.launcher import McpStdioToolSession, McpToolSetProvider

LIVE = os.environ.get("CLAY_LIVE") == "1"
REPO = Path(__file__).resolve().parents[3]
MODEL_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")
ERROR_KINDS = {"tool_error", "tool_timeout", "server_unavailable"}


@dataclass
class Case:
    session: Any
    ok_call: tuple[str, str, dict[str, Any]]
    failing_call: tuple[str, str, dict[str, Any]]
    close: Callable[[], None]


def _fake() -> Case:
    echo = ToolSpec(server="fx", name="echo", input_schema={"type": "object"})
    fail = ToolSpec(server="fx", name="fail", input_schema={"type": "object"})
    session = FakeToolSession(
        [echo, fail],
        {
            ("fx", "echo"): lambda args: ToolResult(text=str(args.get("text", ""))),
            ("fx", "fail"): ToolResult(text="boom", is_error=True),
        },
    )
    return Case(session, ("fx", "echo", {"text": "hi"}), ("fx", "fail", {}), session.close)


def _stdio_fixture() -> Case:
    ts = ToolSetDef(
        name="TX", servers=[ServerDef(name="fx", command=[sys.executable, FIXTURE_SERVER_PATH])]
    )
    session = McpStdioToolSession(ts).start()
    return Case(session, ("fx", "echo", {"text": "hi"}), ("fx", "fail", {}), session.close)


def _live_t0() -> Case:
    session = McpToolSetProvider(REPO / "toolsets").open_blocking("T0")
    return Case(
        session,
        ("roda", "search_datasets", {"query": "NAIP"}),
        ("roda", "get_dataset_details", {}),  # missing required slug
        session.close,
    )


FACTORIES: dict[str, Callable[[], Case]] = {"fake": _fake, "stdio-fixture": _stdio_fixture}
PARAMS = [pytest.param(name, id=name) for name in FACTORIES] + [
    pytest.param(
        "live-T0",
        id="live-T0",
        marks=pytest.mark.skipif(not LIVE, reason="set CLAY_LIVE=1 to run against RODA"),
    )
]


@pytest.fixture(params=PARAMS)
def case(request: pytest.FixtureRequest) -> Iterator[Case]:
    factory = _live_t0 if request.param == "live-T0" else FACTORIES[request.param]
    c = factory()
    yield c
    c.close()


def test_satisfies_protocol(case: Case) -> None:
    assert isinstance(case.session, ToolSession)


def test_lists_tools_with_schemas_and_bedrock_safe_names(case: Case) -> None:
    tools = case.session.list_tools()
    assert tools
    names = [t.model_name for t in tools]
    assert len(names) == len(set(names))
    for t in tools:
        assert t.server and t.name
        assert MODEL_NAME.match(t.model_name)
        assert isinstance(t.input_schema, dict) and t.input_schema.get("type") == "object"


def test_call_and_call_blocking_agree(case: Case) -> None:
    server, tool, args = case.ok_call
    sync = case.session.call_blocking(server, tool, args, 30)
    async_ = asyncio.run(case.session.call(server, tool, args, 30))
    assert not sync.is_error and sync.status == "ok"
    assert sync.text == async_.text


def test_failure_is_a_result_and_the_session_keeps_working(case: Case) -> None:
    server, tool, args = case.failing_call
    result = case.session.call_blocking(server, tool, args, 30)
    assert result.is_error and result.status != "ok" and result.error_kind in ERROR_KINDS
    ok_server, ok_tool, ok_args = case.ok_call
    assert not case.session.call_blocking(ok_server, ok_tool, ok_args, 30).is_error
