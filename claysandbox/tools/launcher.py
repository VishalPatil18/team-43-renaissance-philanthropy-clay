"""Live MCP tool sessions over stdio (VIS-R0-01, architecture §8.1, §9.3, §14.3).

``McpStdioToolSession`` starts every server of a tool set as a fresh subprocess with a scrubbed
environment, runs ``initialize`` and ``list_tools`` on each, and serves calls from one background
asyncio loop in a dedicated thread:

* ``call`` is async and can be awaited from any event loop.
* ``call_blocking`` submits the call to the background loop and waits (open point 1).

Failures never raise into the caller. They come back as a ``ToolResult``:

=================================================  ========  ======================
condition                                          status    error_kind
=================================================  ========  ======================
the tool reports ``isError``                       error     tool_error
protocol error (e.g. arguments rejected)           error     tool_error
no result within the timeout                       timeout   tool_timeout
server failed to start, crashed or closed          error     server_unavailable
=================================================  ========  ======================

A server that fails to start doesn't stop the others: the session opens with the tools of the
servers that did start, and ``servers()`` reports each server's status for the run manifest.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import tempfile
import threading
import time
from collections.abc import Coroutine, Mapping
from concurrent.futures import Future
from concurrent.futures import TimeoutError as FutureTimeout
from dataclasses import dataclass, field
from pathlib import Path
from typing import IO, Any, TypeVar

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.shared.exceptions import MCPError
from mcp.types import CONNECTION_CLOSED, PaginatedRequestParams

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.tools import EnvPolicy, ServerDef, ServerInfo, ToolResult, ToolSetDef
from claysandbox.tools.env import build_env
from claysandbox.tools.toolsets import package_of

log = logging.getLogger("claysandbox.tools")

T = TypeVar("T")

DEFAULT_STARTUP_TIMEOUT_S = 120.0
CLOSE_TIMEOUT_S = 10.0

_SERVER_GONE: tuple[type[BaseException], ...] = (
    anyio.ClosedResourceError,
    anyio.BrokenResourceError,
    anyio.EndOfStream,
    ConnectionError,
    EOFError,
    OSError,
)


@dataclass
class _ServerState:
    definition: ServerDef
    info: ServerInfo
    tools: list[ToolSpec] = field(default_factory=list)
    session: ClientSession | None = None
    ready: asyncio.Event = field(default_factory=asyncio.Event)
    closing: asyncio.Event = field(default_factory=asyncio.Event)
    task: asyncio.Task[None] | None = None

    def mark_unavailable(self, reason: str) -> None:
        self.info.status = "unavailable"
        self.info.error = reason
        self.session = None


class McpStdioToolSession:
    """A ``ToolSession`` over the stdio MCP servers of one tool set."""

    def __init__(
        self,
        definition: ToolSetDef,
        env_policy: EnvPolicy | None = None,
        *,
        log_dir: Path | str | None = None,
        environ: Mapping[str, str] | None = None,
        startup_timeout_s: float = DEFAULT_STARTUP_TIMEOUT_S,
    ) -> None:
        self.definition = definition
        self.env_policy = env_policy
        self.environ = environ
        self.startup_timeout_s = startup_timeout_s
        self.log_dir = Path(log_dir) if log_dir else Path(tempfile.mkdtemp(prefix="clay-mcp-"))
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._states: dict[str, _ServerState] = {}
        self._closed = False

    # -- lifecycle -----------------------------------------------------------------------

    def start(self) -> McpStdioToolSession:
        """Start the background loop and every server. Returns when all are ready or failed."""
        if self._loop is not None:
            return self
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(
            target=self._loop.run_forever, name=f"mcp-{self.definition.name}", daemon=True
        )
        self._thread.start()
        self._submit(self._start_all()).result()
        return self

    async def _start_all(self) -> None:
        for server in self.definition.servers:
            try:
                package, version = package_of(server)
            except ConfigError:
                package, version = None, None  # validated when the tool-set file is loaded
            info = ServerInfo(
                name=server.name,
                command=list(server.command),
                package=package,
                version=version,
                needs_aws=server.needs_aws,
                stderr_log=str(self.log_dir / f"{server.name}.stderr.log"),
            )
            state = _ServerState(definition=server, info=info)
            self._states[server.name] = state
            state.task = asyncio.create_task(self._serve(state), name=f"mcp-{server.name}")
        for state in self._states.values():
            try:
                await asyncio.wait_for(state.ready.wait(), timeout=self.startup_timeout_s)
            except TimeoutError:
                state.mark_unavailable(f"did not start within {self.startup_timeout_s:g} s")
                if state.task:
                    state.task.cancel()
        up = [s.info.name for s in self._states.values() if s.info.status == "ok"]
        down = [s.info.name for s in self._states.values() if s.info.status != "ok"]
        log.info("tool set %s opened: up=%s down=%s", self.definition.name, up, down)

    async def _serve(self, state: _ServerState) -> None:
        """Own one server's transport for its whole life (anyio: one task enters and exits)."""
        server = state.definition
        params = StdioServerParameters(
            command=server.command[0],
            args=server.command[1:],
            env=build_env(server, self.env_policy, self.environ),
        )
        t0 = time.monotonic()
        errlog: IO[str] | None = None
        try:
            self.log_dir.mkdir(parents=True, exist_ok=True)
            errlog = open(state.info.stderr_log or "", "a", encoding="utf-8")  # noqa: SIM115
            async with stdio_client(params, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    init = await session.initialize()
                    state.tools = await self._list_tools(session, server)
                    state.info.server_name = init.server_info.name
                    state.info.server_version = init.server_info.version
                    state.info.tool_count = len(state.tools)
                    state.info.startup_ms = (time.monotonic() - t0) * 1000
                    state.session = session
                    state.ready.set()
                    await state.closing.wait()
        except asyncio.CancelledError:
            if not state.ready.is_set():
                state.mark_unavailable("startup cancelled")
            raise
        except BaseException as exc:  # noqa: BLE001 - any failure makes the server unavailable
            reason = _root_cause(exc)
            if not state.closing.is_set():
                log.warning("MCP server %s unavailable: %s", server.name, reason)
                state.mark_unavailable(reason)
        finally:
            state.session = None
            state.ready.set()
            if errlog is not None:
                errlog.close()

    async def _list_tools(self, session: ClientSession, server: ServerDef) -> list[ToolSpec]:
        specs: list[ToolSpec] = []
        cursor: str | None = None
        while True:
            params = PaginatedRequestParams(cursor=cursor) if cursor else None
            page = await session.list_tools(params=params)
            for tool in page.tools:
                specs.append(
                    ToolSpec(
                        server=server.name,
                        name=tool.name,
                        description=tool.description or "",
                        input_schema=dict(tool.input_schema or {"type": "object"}),
                        capability=self.definition.capability_of(server.name, tool.name),
                    )
                )
            cursor = page.next_cursor
            if not cursor:
                return specs

    async def aclose(self) -> None:
        if self._loop is None or self._closed:
            return
        future = self._submit(self._close_all())
        await asyncio.wrap_future(future)
        self._stop_loop()

    def close(self) -> None:
        """Close every server and stop the background loop. Safe to call twice."""
        if self._loop is None or self._closed:
            return
        try:
            self._submit(self._close_all()).result(timeout=CLOSE_TIMEOUT_S + 5)
        except FutureTimeout:
            log.warning("tool set %s did not close in time", self.definition.name)
        self._stop_loop()

    async def _close_all(self) -> None:
        for state in self._states.values():
            state.closing.set()
        tasks = [s.task for s in self._states.values() if s.task is not None]
        if not tasks:
            return
        _, pending = await asyncio.wait(tasks, timeout=CLOSE_TIMEOUT_S)
        for task in pending:  # a server that won't shut down: cancelling kills its process
            task.cancel()
        if pending:
            await asyncio.wait(pending, timeout=CLOSE_TIMEOUT_S)

    def _stop_loop(self) -> None:
        self._closed = True
        loop, thread = self._loop, self._thread
        if loop is not None and loop.is_running():
            loop.call_soon_threadsafe(loop.stop)
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=CLOSE_TIMEOUT_S)

    def __enter__(self) -> McpStdioToolSession:
        return self.start()

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- ToolSession -----------------------------------------------------------------------

    def list_tools(self) -> list[ToolSpec]:
        """Every tool of every running server, in tool-set order then server order (FR-1.11)."""
        out: list[ToolSpec] = []
        for server in self.definition.servers:
            state = self._states.get(server.name)
            if state is not None and state.info.status == "ok":
                out.extend(state.tools)
        return out

    def servers(self) -> list[ServerInfo]:
        """Status and versions of every server, for the run manifest."""
        return [self._states[s.name].info.model_copy() for s in self.definition.servers
                if s.name in self._states]

    async def call(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float = 60.0
    ) -> ToolResult:
        self._check_open()
        if _running_loop() is self._loop:
            return await self._call(server, tool, args, timeout_s)
        return await asyncio.wrap_future(self._submit(self._call(server, tool, args, timeout_s)))

    def call_blocking(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float = 60.0
    ) -> ToolResult:
        self._check_open()
        if threading.current_thread() is self._thread:
            raise RuntimeError("call_blocking must not run on the session's own loop; use call")
        return self._submit(self._call(server, tool, args, timeout_s)).result()

    async def _call(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult:
        state = self._states.get(server)
        if state is None:
            return ToolResult(text=f"Unknown server {server!r} in tool set "
                                   f"{self.definition.name!r}", error_kind="tool_error")
        session = state.session
        if session is None or state.info.status != "ok":
            return ToolResult(
                text=f"Tool server {server!r} is unavailable: {state.info.error or 'not running'}",
                error_kind="server_unavailable",
            )
        timeout = min(timeout_s, state.definition.timeout_s)
        try:
            result = await asyncio.wait_for(session.call_tool(tool, args), timeout=timeout)
        except TimeoutError:
            return ToolResult(text=f"Tool call timed out after {timeout:g} s",
                              error_kind="tool_timeout")
        except MCPError as exc:
            if exc.code == CONNECTION_CLOSED:
                state.mark_unavailable(f"connection closed: {exc}")
                return ToolResult(text=f"Tool server {server!r} is unavailable: {exc}",
                                  error_kind="server_unavailable")
            return ToolResult(text=f"Tool call failed: {exc}", error_kind="tool_error")
        except _SERVER_GONE as exc:
            state.mark_unavailable(_root_cause(exc))
            return ToolResult(text=f"Tool server {server!r} is unavailable: {_root_cause(exc)}",
                              error_kind="server_unavailable")
        except Exception as exc:  # noqa: BLE001 - never raise into the agent loop
            return ToolResult(text=f"Tool call failed: {_root_cause(exc)}",
                              error_kind="tool_error")
        return _to_result(result)

    # -- helpers -------------------------------------------------------------------------

    def _check_open(self) -> None:
        if self._loop is None:
            raise RuntimeError("session not started: call start() first")
        if self._closed:
            raise RuntimeError("session is closed")

    def _submit(self, coro: Coroutine[Any, Any, T]) -> Future[T]:
        assert self._loop is not None
        return asyncio.run_coroutine_threadsafe(coro, self._loop)


def _to_result(result: Any) -> ToolResult:
    texts: list[str] = []
    for block in getattr(result, "content", None) or []:
        text = getattr(block, "text", None)
        resource = getattr(block, "resource", None)
        if text is not None:
            texts.append(text)
        elif resource is not None and getattr(resource, "text", None) is not None:
            texts.append(resource.text)
        else:
            texts.append(f"[{getattr(block, 'type', 'unknown')} content omitted]")
    is_error = bool(getattr(result, "is_error", False))
    return ToolResult(
        text="\n".join(texts),
        structured=getattr(result, "structured_content", None),
        is_error=is_error,
        error_kind="tool_error" if is_error else None,
    )


def _running_loop() -> asyncio.AbstractEventLoop | None:
    with contextlib.suppress(RuntimeError):
        return asyncio.get_running_loop()
    return None


def _root_cause(exc: BaseException) -> str:
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


class McpToolSetProvider:
    """``ToolSetProvider`` over the tool-set files in one directory (default ``toolsets/``)."""

    def __init__(self, directory: Path | str = "toolsets", **session_kwargs: Any) -> None:
        from claysandbox.tools.toolsets import load_toolsets

        self.directory = Path(directory)
        self.definitions = load_toolsets(self.directory)
        self.session_kwargs = session_kwargs

    def definition(self, toolset_name: str) -> ToolSetDef:
        try:
            return self.definitions[toolset_name]
        except KeyError:
            raise ConfigError(
                f"No tool set named {toolset_name!r} in {self.directory}. "
                f"Known: {sorted(self.definitions)}",
                kind="unknown_component",
            ) from None

    def open_blocking(
        self, toolset_name: str, env_policy: EnvPolicy | None = None
    ) -> McpStdioToolSession:
        session = McpStdioToolSession(
            self.definition(toolset_name), env_policy, **self.session_kwargs
        )
        return session.start()

    async def open(
        self, toolset_name: str, env_policy: EnvPolicy | None = None
    ) -> McpStdioToolSession:
        return await asyncio.to_thread(self.open_blocking, toolset_name, env_policy)
