"""Tool session contract (architecture §7.4).

Owner: WS2 (Vishal). This copy follows the architecture sketch plus contracts open point 1:
``call`` is async, ``call_blocking`` runs the call on the session's background event loop so
synchronous harnesses can use it.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel

from .manifest import ToolSpec


class ToolResult(BaseModel):
    """What a tool returned. ``text`` is the text the model reads; ``structured`` is optional."""

    text: str = ""
    structured: Any = None
    is_error: bool = False


@runtime_checkable
class ToolSession(Protocol):
    """A live MCP tool set. A call that exceeds ``timeout_s`` raises ``TimeoutError``."""

    def list_tools(self) -> list[ToolSpec]: ...

    async def call(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult: ...

    def call_blocking(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult: ...

    async def aclose(self) -> None: ...
