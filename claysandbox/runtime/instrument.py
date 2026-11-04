"""Instrumented model adapter and tool session (architecture §9.1, principle P6).

Tracing and guards live here, at the boundary, so every harness produces the same events with
the same timing. Harnesses receive only these wrappers.

Event conventions
-----------------
* One ``model_call`` event per model call, including calls that failed with an infra or config
  error (zero tokens, ``error`` set).
* One ``tool_call`` event per tool call. The full result is stored with ``put_blob`` (as text, or
  as JSON when the tool only returned structured content) and referenced by hash. The inline
  preview is capped at ``PREVIEW_TOOL_CHARS``.
* A ``tool_call`` event's ``parent_id`` is the ``model_call`` that requested it, matched through
  the Converse ``toolUseId``. If the caller does not pass a ``tool_use_id``, the latest
  ``model_call`` is used.
* A guard stop emits one ``guard_stop`` event and re-raises ``GuardStopped``. The wrappers never
  catch it anywhere else.
"""

from __future__ import annotations

import asyncio
import json
import threading
import time
from typing import Any

from claysandbox.contracts.errors import ConfigError, GuardStopped, InfraError
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.runtime import BudgetGuard, ModelAdapter, ModelResponse, PriceTable
from claysandbox.contracts.tools import ToolResult, ToolSession
from claysandbox.contracts.trace import (
    ErrorInfo,
    EventSink,
    GuardStop,
    ModelCall,
    ToolCall,
    utcnow,
)

PREVIEW_MODEL_CHARS = 500
PREVIEW_TOOL_CHARS = 1000
DEFAULT_TOOL_TIMEOUT_S = 60.0

_SERVER_DOWN_ERRORS = (ConnectionError, BrokenPipeError, EOFError, OSError)


class ParentLinks:
    """Shared by the two wrappers: maps a ``toolUseId`` to the ``model_call`` that asked for it."""

    def __init__(self) -> None:
        self._by_use: dict[str, str] = {}
        self._latest: str | None = None
        self._lock = threading.Lock()

    def register(self, model_call_id: str, tool_use_ids: list[str]) -> None:
        with self._lock:
            self._latest = model_call_id
            for tool_use_id in tool_use_ids:
                self._by_use[tool_use_id] = model_call_id

    def parent_for(self, tool_use_id: str | None) -> str | None:
        with self._lock:
            if tool_use_id is not None and tool_use_id in self._by_use:
                return self._by_use[tool_use_id]
            return self._latest


def _emit_guard_stop(sink: EventSink, exc: GuardStopped, parent_id: str | None = None) -> None:
    now = utcnow()
    sink.emit(
        GuardStop(
            limit=exc.limit,
            limit_value=exc.limit_value,
            observed_value=exc.observed_value,
            parent_id=parent_id,
            ts_start=now,
            ts_end=now,
            error=ErrorInfo(source=exc.source, kind=exc.kind, message=exc.message),
        )
    )


class InstrumentedModel:
    """Wraps a ``ModelAdapter``: guard check, timing, pricing and a ``model_call`` event."""

    name = "instrumented"
    version = "1"

    def __init__(
        self,
        inner: ModelAdapter,
        sink: EventSink,
        guard: BudgetGuard,
        prices: PriceTable,
        links: ParentLinks | None = None,
    ) -> None:
        self.inner = inner
        self.sink = sink
        self.guard = guard
        self.prices = prices
        self.links = links or ParentLinks()

    @property
    def model_id(self) -> str:
        return self.inner.model_id

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[ToolSpec],
        params: dict[str, Any],
    ) -> ModelResponse:
        try:
            self.guard.before_model_call()
        except GuardStopped as exc:
            _emit_guard_stop(self.sink, exc, self.sink.last_event_id)
            raise

        ts_start = utcnow()
        t0 = time.monotonic()
        try:
            response = self.inner.converse(messages, system, tools, params)
        except (InfraError, ConfigError) as exc:
            self._record_failure(exc, ts_start, t0)
            raise
        wall_ms = (time.monotonic() - t0) * 1000

        model_id = response.model_id or self.inner.model_id
        try:
            cost = self.prices.model_cost(model_id, response.input_tokens, response.output_tokens)
        except ConfigError as exc:
            self._record_failure(
                exc,
                ts_start,
                t0,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
            )
            raise

        event = self.sink.emit(
            ModelCall(
                ts_start=ts_start,
                ts_end=utcnow(),
                latency_ms=response.latency_ms if response.latency_ms is not None else wall_ms,
                model_id=model_id,
                input_tokens=response.input_tokens,
                output_tokens=response.output_tokens,
                stop_reason=response.stop_reason,
                tool_use_requests=[
                    {"tool_use_id": u.tool_use_id, "name": u.name, "input": u.input}
                    for u in response.tool_uses
                ],
                text_preview=response.text[:PREVIEW_MODEL_CHARS] if response.text else None,
                cost_usd=cost,
                price_table_version=self.prices.version,
            )
        )
        self.links.register(event.event_id, [u.tool_use_id for u in response.tool_uses])
        self.guard.record(event)
        return response

    def _record_failure(
        self,
        exc: InfraError | ConfigError,
        ts_start: Any,
        t0: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
    ) -> None:
        event = self.sink.emit(
            ModelCall(
                ts_start=ts_start,
                ts_end=utcnow(),
                latency_ms=(time.monotonic() - t0) * 1000,
                model_id=self.inner.model_id,
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                stop_reason=None,
                cost_usd=0.0,
                price_table_version=self.prices.version,
                error=ErrorInfo(
                    source="infra",
                    kind=exc.kind,
                    message=exc.message,
                    retryable=exc.retryable,
                ),
            )
        )
        self.guard.record(event)


class InstrumentedTools:
    """Wraps a ``ToolSession``: guard check, timeout, a ``tool_call`` event and error mapping."""

    def __init__(
        self,
        inner: ToolSession,
        sink: EventSink,
        guard: BudgetGuard,
        links: ParentLinks | None = None,
        default_timeout_s: float = DEFAULT_TOOL_TIMEOUT_S,
    ) -> None:
        self.inner = inner
        self.sink = sink
        self.guard = guard
        self.links = links or ParentLinks()
        self.default_timeout_s = default_timeout_s
        self._capabilities: dict[tuple[str, str], str | None] | None = None

    def list_tools(self) -> list[ToolSpec]:
        return self.inner.list_tools()

    # -- public API -----------------------------------------------------------------------

    async def call(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: float | None = None,
        tool_use_id: str | None = None,
    ) -> ToolResult:
        timeout = self._before(server, tool, args, timeout_s)
        ts_start, t0 = utcnow(), time.monotonic()
        try:
            result = await asyncio.wait_for(
                self.inner.call(server, tool, args, timeout), timeout=timeout
            )
        except GuardStopped:
            raise
        except Exception as exc:
            return self._failed(server, tool, args, tool_use_id, ts_start, t0, timeout, exc)
        return self._completed(server, tool, args, tool_use_id, ts_start, t0, result)

    def call_blocking(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        timeout_s: float | None = None,
        tool_use_id: str | None = None,
    ) -> ToolResult:
        timeout = self._before(server, tool, args, timeout_s)
        ts_start, t0 = utcnow(), time.monotonic()
        try:
            result = self.inner.call_blocking(server, tool, args, timeout)
        except GuardStopped:
            raise
        except Exception as exc:
            return self._failed(server, tool, args, tool_use_id, ts_start, t0, timeout, exc)
        return self._completed(server, tool, args, tool_use_id, ts_start, t0, result)

    async def aclose(self) -> None:
        await self.inner.aclose()

    # -- internals ------------------------------------------------------------------------

    def _before(
        self, server: str, tool: str, args: dict[str, Any], timeout_s: float | None
    ) -> float:
        try:
            self.guard.before_tool_call(f"{server}.{tool}", args)
        except GuardStopped as exc:
            _emit_guard_stop(self.sink, exc, self.links.parent_for(None))
            raise
        default = timeout_s if timeout_s is not None else self.default_timeout_s
        return self.guard.tool_timeout(default)

    def _capability(self, server: str, tool: str) -> str | None:
        if self._capabilities is None:
            self._capabilities = {(t.server, t.name): t.capability for t in self.inner.list_tools()}
        return self._capabilities.get((server, tool))

    def _completed(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        tool_use_id: str | None,
        ts_start: Any,
        t0: float,
        result: ToolResult,
    ) -> ToolResult:
        error = None
        status = "ok"
        if result.is_error:
            status = "error"
            error = ErrorInfo(
                source="tool", kind="tool_error", message=result.text[:500] or "tool reported error"
            )
        self._emit(server, tool, args, tool_use_id, ts_start, t0, status, result, error)
        return result

    def _failed(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        tool_use_id: str | None,
        ts_start: Any,
        t0: float,
        timeout: float,
        exc: Exception,
    ) -> ToolResult:
        if isinstance(exc, TimeoutError):
            status = "timeout"
            text = f"Tool call timed out after {timeout:g} s"
            error = ErrorInfo(source="tool", kind="tool_timeout", message=text, retryable=True)
        elif isinstance(exc, _SERVER_DOWN_ERRORS):
            status = "error"
            text = f"Tool server unavailable: {exc}"
            error = ErrorInfo(source="tool", kind="server_unavailable", message=text)
        else:
            status = "error"
            text = f"Tool call failed: {exc}"
            error = ErrorInfo(source="tool", kind="tool_error", message=text)
        result = ToolResult(text=text, is_error=True)
        self._emit(server, tool, args, tool_use_id, ts_start, t0, status, result, error)
        return result

    def _emit(
        self,
        server: str,
        tool: str,
        args: dict[str, Any],
        tool_use_id: str | None,
        ts_start: Any,
        t0: float,
        status: str,
        result: ToolResult,
        error: ErrorInfo | None,
    ) -> None:
        full = result.text
        if not full and result.structured is not None:
            full = json.dumps(result.structured, default=str, sort_keys=True)
        ref, digest = self.sink.put_blob(full.encode("utf-8"))
        event = self.sink.emit(
            ToolCall(
                parent_id=self.links.parent_for(tool_use_id),
                ts_start=ts_start,
                ts_end=utcnow(),
                latency_ms=(time.monotonic() - t0) * 1000,
                server=server,
                tool=tool,
                capability=self._capability(server, tool),
                args=args,
                status=status,  # type: ignore[arg-type]
                result_preview=full[:PREVIEW_TOOL_CHARS],
                result_ref=ref,
                result_sha256=digest,
                error=error,
            )
        )
        self.guard.record(event)
