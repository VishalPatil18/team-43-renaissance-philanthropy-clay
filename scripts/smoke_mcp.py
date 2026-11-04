#!/usr/bin/env python3
"""Smoke-test the third-party MCP servers before anyone codes against them (VIS-R0-00).

For each server: start it over stdio, ``initialize``, ``list_tools``, make one realistic call, and
print the tool names, input schemas, the shape of the result, the startup time and whether the
call needed AWS credentials. Each server is first started with a scrubbed environment that has no
AWS variables. If ``--with-aws`` is given and that attempt fails, it is retried with the AWS
variables passed through, which tells us whether the server ``needs_aws``.

Usage::

    uv run python scripts/smoke_mcp.py                   # all servers
    uv run python scripts/smoke_mcp.py --only stac --schemas
    uv run python scripts/smoke_mcp.py --with-aws        # retry with AWS variables on failure

The results are recorded by hand in ``toolsets/README.md``.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import time
from dataclasses import dataclass, field
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

BASE_VARS = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "UV_CACHE_DIR", "UV_TOOL_DIR")
AWS_VARS = (
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONFIG_FILE",
    "AWS_SHARED_CREDENTIALS_FILE",
)

# Kern County, California: the R0 area of interest.
KERN_BBOX = [-120.194, 34.788, -117.616, 35.798]


@dataclass
class Server:
    name: str
    command: list[str]
    call_tool: str
    call_args: dict[str, Any]
    env: dict[str, str] = field(default_factory=dict)


SERVERS: list[Server] = [
    Server(
        name="roda",
        command=["uvx", "awslabs.roda-mcp-server@0.1.7"],
        env={"FASTMCP_LOG_LEVEL": "ERROR"},
        call_tool="search_datasets",
        call_args={"query": "NAIP aerial imagery"},
    ),
    Server(
        name="stac-earth-search",
        command=["uvx", "stac-mcp@6.5.0"],
        call_tool="search_items",
        call_args={
            "catalog_url": "https://earth-search.aws.element84.com/v1",
            "collections": ["naip"],
            "bbox": KERN_BBOX,
            "datetime": "2022-01-01T00:00:00Z/2022-12-31T23:59:59Z",
            "limit": 5,
            "output_format": "json",
        },
    ),
    Server(
        name="stac-planetary-computer",
        command=["uvx", "stac-mcp@6.5.0"],
        call_tool="search_items",
        call_args={
            "catalog_url": "https://planetarycomputer.microsoft.com/api/stac/v1",
            "collections": ["naip"],
            "bbox": KERN_BBOX,
            "datetime": "2022-01-01T00:00:00Z/2022-12-31T23:59:59Z",
            "limit": 5,
            "output_format": "json",
        },
    ),
    Server(
        name="osm",
        command=["npx", "-y", "@cyanheads/openstreetmap-mcp-server@0.7.0"],
        env={
            "MCP_LOG_LEVEL": "error",
            "OSM_USER_AGENT": "clay-agent-eval-sandbox/0.1 (+https://github.com/VishalPatil18/team-43-renaissance-philanthropy-clay)",
        },
        call_tool="openstreetmap_search_places",
        call_args={"query": "Kern County, California"},
    ),
]


def build_env(server: Server, with_aws: bool) -> dict[str, str]:
    env = {k: os.environ[k] for k in BASE_VARS if k in os.environ}
    env.update(server.env)
    if with_aws:
        env.update({k: os.environ[k] for k in AWS_VARS if k in os.environ})
    return env


def describe(value: Any, depth: int = 0) -> str:
    """A short description of a JSON value's shape."""
    if depth > 3:
        return "…"
    if isinstance(value, dict):
        inner = ", ".join(f"{k}: {describe(v, depth + 1)}" for k, v in list(value.items())[:8])
        return "{" + inner + ("" if len(value) <= 8 else ", …") + "}"
    if isinstance(value, list):
        return f"[{len(value)} × {describe(value[0], depth + 1)}]" if value else "[]"
    return type(value).__name__


async def smoke(server: Server, with_aws: bool, show_schemas: bool, timeout_s: float) -> bool:
    params = StdioServerParameters(
        command=server.command[0], args=server.command[1:], env=build_env(server, with_aws)
    )
    label = f"{server.name} ({'with' if with_aws else 'without'} AWS variables)"
    print(f"\n=== {label}: {' '.join(server.command)}")
    t0 = time.monotonic()
    try:
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                init = await asyncio.wait_for(session.initialize(), timeout=timeout_s)
                listed = await asyncio.wait_for(session.list_tools(), timeout=timeout_s)
                startup = time.monotonic() - t0
                info = init.server_info
                print(f"server: {info.name} {info.version}  startup: {startup:.1f} s")
                print(f"tools ({len(listed.tools)}): {[t.name for t in listed.tools]}")
                if show_schemas:
                    for t in listed.tools:
                        print(f"- {t.name}: {(t.description or '').strip()[:200]}")
                        print(f"  input_schema: {json.dumps(t.input_schema)}")
                tool = server.call_tool or next(
                    (t.name for t in listed.tools if "geocode" in t.name), listed.tools[0].name
                )
                t1 = time.monotonic()
                result = await asyncio.wait_for(
                    session.call_tool(tool, server.call_args), timeout=timeout_s
                )
                elapsed = time.monotonic() - t1
                text = "\n".join(c.text for c in result.content if getattr(c, "text", None))
                print(f"call {tool}({json.dumps(server.call_args)}) -> is_error={result.is_error}"
                      f" in {elapsed:.1f} s")
                try:
                    print(f"result shape: {describe(json.loads(text))}")
                except ValueError:
                    pass
                print(f"result preview: {text[:800]}")
                return not result.is_error
    except Exception as exc:  # noqa: BLE001 - a smoke test reports every failure
        print(f"FAILED after {time.monotonic() - t0:.1f} s: {root_cause(exc)}")
        return False


def root_cause(exc: BaseException) -> str:
    """Unwrap the ExceptionGroups that anyio's task groups raise."""
    while isinstance(exc, BaseExceptionGroup) and exc.exceptions:
        exc = exc.exceptions[0]
    return f"{type(exc).__name__}: {exc}"


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--only", action="append", help="server name (repeatable)")
    parser.add_argument("--with-aws", action="store_true", help="retry with AWS vars on failure")
    parser.add_argument("--schemas", action="store_true", help="print every tool's input schema")
    parser.add_argument("--timeout", type=float, default=180.0)
    args = parser.parse_args()
    selected = [s for s in SERVERS if not args.only or s.name in args.only]
    failures = 0
    for server in selected:
        ok = await smoke(server, False, args.schemas, args.timeout)
        if not ok and args.with_aws:
            ok = await smoke(server, True, args.schemas, args.timeout)
            if ok:
                print(f"--> {server.name} needs AWS credentials (needs_aws: true)")
        failures += 0 if ok else 1
    print(f"\n{len(selected) - failures}/{len(selected)} servers answered a call.")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
