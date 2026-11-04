"""Fake tool session with canned results, errors and timeouts (owner: WS2; used by WS1 tests).

``call_blocking`` runs on a background event loop, like the real session (open point 1).
A handler can be a ``ToolResult`` (e.g. ``ToolResult(status="timeout")`` or
``ToolResult(error_kind="server_unavailable")``, DD-045), an exception to raise, or a function of
the arguments. ``servers()`` mirrors ``McpStdioToolSession.servers()`` for manifest tests.
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any

from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.tools import ServerInfo, ToolResult

Handler = ToolResult | Exception | Callable[[dict[str, Any]], ToolResult]


class FakeToolSession:
    def __init__(
        self,
        tools: list[ToolSpec],
        handlers: dict[tuple[str, str], Handler] | None = None,
    ):
        self._tools = tools
        self.handlers = handlers or {}
        self.calls: list[tuple[str, str, dict[str, Any]]] = []
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._loop.run_forever, daemon=True)
        self._thread.start()

    def list_tools(self) -> list[ToolSpec]:
        return list(self._tools)

    def servers(self) -> list[ServerInfo]:
        names = list(dict.fromkeys(t.server for t in self._tools))
        return [
            ServerInfo(
                name=n,
                command=["fake"],
                tool_count=sum(1 for t in self._tools if t.server == n),
            )
            for n in names
        ]

    async def call(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult:
        self.calls.append((server, tool, dict(args)))
        handler = self.handlers.get((server, tool), ToolResult(text="ok"))
        if isinstance(handler, Exception):
            raise handler
        if callable(handler):
            return handler(args)
        return handler

    def call_blocking(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult:
        future = asyncio.run_coroutine_threadsafe(
            self.call(server, tool, args, timeout_s), self._loop
        )
        return future.result()

    async def aclose(self) -> None:
        self.close()

    def close(self) -> None:
        if self._loop.is_running():
            self._loop.call_soon_threadsafe(self._loop.stop)
            self._thread.join(timeout=2)
