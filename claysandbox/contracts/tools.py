"""Tool contracts: tool results, tool sessions, tool-set definitions and environment policy.

Owner: WS2 (Vishal). Architecture §7.4, §14.3 and §18; contracts open points 1 and 2.

* ``ToolSession.call`` is async. ``call_blocking`` runs the call on the session's background event
  loop so synchronous harnesses can use it (open point 1).
* The tool name the model sees is ``ToolSpec.model_name`` (``<server>__<tool>``, Bedrock-safe,
  open point 2), built by ``contracts.manifest.make_model_name``.
* ``ToolResult.status`` and ``error_kind`` say how a call failed (DD-045). A session may also
  raise ``TimeoutError`` or ``ConnectionError``/``OSError`` instead; the instrumented wrapper maps
  both forms to the same trace event.
"""

from __future__ import annotations

import re
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from .manifest import ToolSpec

ToolStatus = Literal["ok", "error", "timeout"]
ToolErrorKind = Literal["tool_error", "tool_timeout", "server_unavailable"]

# Letters, digits and "_" only. Bedrock allows "-" in tool names, but Amazon Nova fails to call a
# tool whose name contains one ("Model produced invalid sequence as part of ToolUse", checked
# 2026-11-04), and the server name becomes the "<server>__" prefix of every tool name.
_SERVER_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_]*$")


class ToolResult(BaseModel):
    """What a tool returned. ``text`` is the text the model reads; ``structured`` is optional.

    ``status`` and ``error_kind`` are kept consistent with ``is_error``:

    * ``ToolResult(text=..., is_error=True)`` means ``status="error"``, ``error_kind="tool_error"``.
    * ``status="timeout"`` implies ``is_error=True`` and ``error_kind="tool_timeout"``.
    * ``error_kind="server_unavailable"`` implies ``is_error=True`` and ``status="error"``.
    """

    text: str = ""
    structured: Any = None
    is_error: bool = False
    status: ToolStatus = "ok"
    error_kind: ToolErrorKind | None = None

    @model_validator(mode="after")
    def _consistent(self) -> ToolResult:
        if self.error_kind == "tool_timeout":
            self.status = "timeout"
        elif self.error_kind is not None and self.status == "ok":
            self.status = "error"
        if self.status != "ok":
            self.is_error = True
        elif self.is_error:
            self.status = "error"
        if self.is_error and self.error_kind is None:
            self.error_kind = "tool_timeout" if self.status == "timeout" else "tool_error"
        if not self.is_error:
            self.error_kind = None
        return self


@runtime_checkable
class ToolSession(Protocol):
    """A live MCP tool set.

    A call that exceeds ``timeout_s`` either returns ``ToolResult(status="timeout")`` or raises
    ``TimeoutError``. A call to a server that failed to start or has died either returns
    ``ToolResult(error_kind="server_unavailable")`` or raises ``ConnectionError``/``OSError``.
    """

    def list_tools(self) -> list[ToolSpec]: ...

    async def call(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult: ...

    def call_blocking(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float
    ) -> ToolResult: ...

    async def aclose(self) -> None: ...


class ServerDef(BaseModel):
    """One MCP server in a tool set (architecture §14.3).

    ``command`` must pin the package version (``uvx pkg@1.2.3``, ``npx -y pkg@1.2.3``) unless it
    runs our own code (``python -m ...``), FR-1.10. ``env`` holds non-secret settings only; it is
    committed to the repo. ``needs_aws`` decides whether AWS credentials reach the server (FR-1.9).
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    command: list[str] = Field(min_length=1)
    env: dict[str, str] = Field(default_factory=dict)
    needs_aws: bool = False
    timeout_s: float = Field(default=60.0, gt=0)
    description: str = ""

    @field_validator("name")
    @classmethod
    def _name_ok(cls, v: str) -> str:
        if not _SERVER_NAME.match(v):
            raise ValueError(f"server name {v!r} must match {_SERVER_NAME.pattern}")
        return v


class ToolSetDef(BaseModel):
    """A named tool set: pinned MCP servers plus a capability map (FR-4.10).

    ``capabilities`` maps a capability name to concrete tools written ``"<server>.<tool>"``. A tool
    belongs to at most one capability. ``test_only`` tool sets (e.g. ``T1-faulty``) are excluded
    from comparisons.
    """

    model_config = ConfigDict(extra="forbid")

    name: str
    description: str = ""
    servers: list[ServerDef] = Field(min_length=1)
    capabilities: dict[str, list[str]] = Field(default_factory=dict)
    test_only: bool = False

    @model_validator(mode="after")
    def _check(self) -> ToolSetDef:
        names = [s.name for s in self.servers]
        dupes = sorted({n for n in names if names.count(n) > 1})
        if dupes:
            raise ValueError(f"tool set {self.name!r}: duplicate server names {dupes}")
        seen: dict[str, str] = {}
        for capability, refs in self.capabilities.items():
            for ref in refs:
                server, sep, tool = ref.partition(".")
                if not sep or not tool:
                    raise ValueError(f"capability {capability!r}: {ref!r} is not '<server>.<tool>'")
                if server not in names:
                    raise ValueError(f"capability {capability!r}: unknown server {server!r}")
                if ref in seen:
                    raise ValueError(
                        f"tool {ref!r} is mapped to both {seen[ref]!r} and {capability!r}"
                    )
                seen[ref] = capability
        return self

    def capability_of(self, server: str, tool: str) -> str | None:
        """The capability a concrete tool provides, or ``None``."""
        ref = f"{server}.{tool}"
        for capability, refs in self.capabilities.items():
            if ref in refs:
                return capability
        return None

    def server(self, name: str) -> ServerDef:
        for s in self.servers:
            if s.name == name:
                return s
        raise KeyError(name)


class EnvPolicy(BaseModel):
    """Which environment variables an MCP server process may see (FR-1.9, DD-034).

    A server gets the variables in ``allow`` that are set in the parent environment, its own
    ``env`` entries, and, only if ``needs_aws`` is true, the variables in ``aws_allow``. Nothing
    else is passed. ``tools.env.default_policy()`` gives the standard lists.
    """

    model_config = ConfigDict(extra="forbid")

    allow: list[str] = Field(default_factory=list)
    aws_allow: list[str] = Field(default_factory=list)


class ServerInfo(BaseModel):
    """What the run manifest records about one MCP server (srs §12.2)."""

    name: str
    command: list[str]
    package: str | None = None
    version: str | None = None
    needs_aws: bool = False
    status: Literal["ok", "unavailable"] = "ok"
    error: str | None = None
    server_name: str | None = None  # as reported by the server's ``initialize`` response
    server_version: str | None = None
    tool_count: int = 0
    startup_ms: float | None = None
    stderr_log: str | None = None


@runtime_checkable
class ToolSetProvider(Protocol):
    """Opens a named tool set as a live ``ToolSession`` (architecture §6).

    ``open`` is async. ``open_blocking`` is the same for synchronous callers (the run worker).
    Servers that fail to start do not make ``open`` fail: their status is ``unavailable`` and calls
    to them return ``server_unavailable``.
    """

    async def open(self, toolset_name: str, env_policy: EnvPolicy | None = None) -> ToolSession: ...

    def open_blocking(
        self, toolset_name: str, env_policy: EnvPolicy | None = None
    ) -> ToolSession: ...
