"""McpStdioToolSession against a local fixture server (no network, no AWS)."""

from __future__ import annotations

import asyncio
import sys
from collections.abc import Iterator
from pathlib import Path

import pytest

from claysandbox.contracts.fakes.mcp_fixture_server import FIXTURE_SERVER_PATH
from claysandbox.contracts.tools import ServerDef, ToolSession, ToolSetDef
from claysandbox.tools.launcher import McpStdioToolSession

FIXTURE = FIXTURE_SERVER_PATH


def fixture_server(name: str = "fx", **kw: object) -> ServerDef:
    return ServerDef(name=name, command=[sys.executable, FIXTURE], **kw)  # type: ignore[arg-type]


def toolset(*servers: ServerDef, capabilities: dict[str, list[str]] | None = None) -> ToolSetDef:
    return ToolSetDef(name="TX", servers=list(servers), capabilities=capabilities or {})


@pytest.fixture
def session(tmp_path: Path) -> Iterator[McpStdioToolSession]:
    s = McpStdioToolSession(
        toolset(fixture_server(), capabilities={"echoing": ["fx.echo"]}), log_dir=tmp_path
    )
    s.start()
    yield s
    s.close()


def test_session_satisfies_the_tool_session_protocol(session: McpStdioToolSession) -> None:
    assert isinstance(session, ToolSession)


def test_lists_tools_with_schemas_capabilities_and_model_names(
    session: McpStdioToolSession,
) -> None:
    tools = {t.name: t for t in session.list_tools()}
    assert set(tools) == {"echo", "fail", "sleep", "crash", "getenv"}
    echo = tools["echo"]
    assert echo.server == "fx" and echo.model_name == "fx__echo"
    assert echo.capability == "echoing" and tools["fail"].capability is None
    assert echo.input_schema["properties"]["text"]["type"] == "string"
    assert echo.description == "Return the text unchanged."


def test_call_blocking_returns_the_text(session: McpStdioToolSession) -> None:
    result = session.call_blocking("fx", "echo", {"text": "hello"}, 10)
    assert (result.text, result.status, result.is_error, result.error_kind) == (
        "hello", "ok", False, None
    )


def test_async_call_works_from_another_event_loop(session: McpStdioToolSession) -> None:
    result = asyncio.run(session.call("fx", "echo", {"text": "async"}, 10))
    assert result.text == "async"


def test_tool_exception_is_a_tool_error(session: McpStdioToolSession) -> None:
    result = session.call_blocking("fx", "fail", {"message": "bad bbox"}, 10)
    assert result.is_error and result.status == "error" and result.error_kind == "tool_error"
    assert "fail" in result.text  # the MCP SDK server hides the exception message itself


def test_invalid_arguments_are_a_tool_error_not_a_crash(session: McpStdioToolSession) -> None:
    result = session.call_blocking("fx", "echo", {"wrong": 1}, 10)
    assert result.error_kind == "tool_error"
    assert session.call_blocking("fx", "echo", {"text": "still up"}, 10).text == "still up"


def test_slow_call_times_out(session: McpStdioToolSession) -> None:
    result = session.call_blocking("fx", "sleep", {"seconds": 5}, 0.3)
    assert (result.status, result.error_kind) == ("timeout", "tool_timeout")
    assert "0.3 s" in result.text


def test_server_timeout_caps_the_caller_timeout(tmp_path: Path) -> None:
    with McpStdioToolSession(toolset(fixture_server(timeout_s=0.3)), log_dir=tmp_path) as s:
        assert s.call_blocking("fx", "sleep", {"seconds": 5}, 60).status == "timeout"


def test_crashed_server_is_unavailable_and_others_keep_working(tmp_path: Path) -> None:
    ts = toolset(fixture_server("a"), fixture_server("b"))
    with McpStdioToolSession(ts, log_dir=tmp_path) as s:
        first = s.call_blocking("a", "crash", {}, 10)
        assert first.is_error
        later = s.call_blocking("a", "echo", {"text": "x"}, 10)
        assert later.error_kind == "server_unavailable"
        assert {i.name: i.status for i in s.servers()} == {"a": "unavailable", "b": "ok"}
        assert s.call_blocking("b", "echo", {"text": "fine"}, 10).text == "fine"


def test_server_that_fails_to_start_is_unavailable_and_does_not_raise(tmp_path: Path) -> None:
    ts = toolset(ServerDef(name="broken", command=["false"]), fixture_server("ok"))
    with McpStdioToolSession(ts, log_dir=tmp_path) as s:
        info = {i.name: i for i in s.servers()}
        assert info["broken"].status == "unavailable" and info["broken"].error
        assert info["ok"].status == "ok" and info["ok"].tool_count == 5
        assert {t.server for t in s.list_tools()} == {"ok"}
        result = s.call_blocking("broken", "echo", {"text": "x"}, 10)
        assert (result.status, result.error_kind) == ("error", "server_unavailable")


def test_missing_executable_is_unavailable(tmp_path: Path) -> None:
    ts = toolset(ServerDef(name="ghost", command=["python-does-not-exist-xyz"]))
    with McpStdioToolSession(ts, log_dir=tmp_path) as s:
        assert s.servers()[0].status == "unavailable"
        assert s.list_tools() == []


def test_unknown_server_is_a_tool_error(session: McpStdioToolSession) -> None:
    assert session.call_blocking("nope", "echo", {}, 10).error_kind == "tool_error"


def test_manifest_info_records_versions_and_server_identity(session: McpStdioToolSession) -> None:
    (info,) = session.servers()
    assert info.server_name == "fixture" and info.server_version == "0.0.1"
    assert info.package is None and info.needs_aws is False
    assert info.startup_ms is not None and info.startup_ms > 0


def test_close_is_idempotent_and_blocks_further_calls(tmp_path: Path) -> None:
    s = McpStdioToolSession(toolset(fixture_server()), log_dir=tmp_path).start()
    s.close()
    s.close()
    with pytest.raises(RuntimeError):
        s.call_blocking("fx", "echo", {"text": "x"}, 1)


def test_aclose_works_from_an_event_loop(tmp_path: Path) -> None:
    s = McpStdioToolSession(toolset(fixture_server()), log_dir=tmp_path).start()
    asyncio.run(s.aclose())
    assert s._closed  # noqa: SLF001
