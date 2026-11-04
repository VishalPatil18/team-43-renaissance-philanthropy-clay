"""A tiny stdio MCP server for tool-session tests and conformance (owner: WS2). No network.

Run it with ``python <path to this file>``; ``FIXTURE_SERVER_PATH`` is that path.

Tools: ``echo`` (returns its text), ``fail`` (raises, so the result is an MCP error result),
``sleep`` (waits), ``crash`` (kills the process), ``getenv`` (returns one environment variable or
``<unset>``).
"""

from __future__ import annotations

import asyncio
import os

from mcp.server.mcpserver import MCPServer

FIXTURE_SERVER_PATH = os.path.abspath(__file__)

server = MCPServer("fixture", version="0.0.1", log_level="ERROR")


@server.tool()
def echo(text: str) -> str:
    """Return the text unchanged."""
    return text


@server.tool()
def fail(message: str = "boom") -> str:
    """Always fails."""
    raise ValueError(message)


@server.tool()
async def sleep(seconds: float) -> str:
    """Wait, then answer."""
    await asyncio.sleep(seconds)
    return "awake"


@server.tool()
def crash() -> str:
    """Kill the server process."""
    os._exit(3)


@server.tool()
def getenv(name: str) -> str:
    """One environment variable of the server process."""
    return os.environ.get(name, "<unset>")


if __name__ == "__main__":
    server.run("stdio")
