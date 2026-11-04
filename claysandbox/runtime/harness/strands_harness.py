"""Strands Agents harness (D7, FR-1.1 to FR-1.3, assumption A-4).

Strands runs the agent loop, but it never talks to Bedrock or to MCP servers itself:

* A custom Strands ``Model`` (``_BridgeModel``) turns Strands' messages into a call to
  ``ctx.model.converse`` and replays the reply as Strands stream events.
* Every tool in the tool set is registered as a Strands ``PythonAgentTool`` whose handler calls
  ``ctx.tools.call_blocking``.

So the instrumented wrappers see every model call and tool call, exactly as with the Converse
loop. Assumption A-4 (custom model providers and tools are supported) was checked against
``strands-agents`` 1.63.

Strands catches exceptions raised inside tool handlers and turns them into error results. A
``GuardStopped`` raised by the tool wrapper is therefore remembered in ``_RunState`` and re-raised
from the model bridge, which Strands does not intercept, so a guard stop always ends the run.
"""

from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import AsyncGenerator, AsyncIterable
from dataclasses import dataclass, field
from typing import Any

from pydantic import BaseModel, Field
from strands import Agent
from strands.hooks.events import BeforeToolCallEvent
from strands.models.model import Model
from strands.tools.tools import PythonAgentTool
from strands.types.exceptions import MaxTokensReachedException

from claysandbox.contracts.errors import GuardStopped
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.registry import register
from claysandbox.contracts.runtime import RunContext, RunOutcome, ToolUse
from claysandbox.contracts.trace import ErrorEvent, ErrorInfo, utcnow

from ._checks import (
    DEFAULT_MAX_TURNS,
    Rejected,
    ToolIndex,
    check_tool_use,
    finish,
    outcome_for_exception,
)


@dataclass
class _RunState:
    """Shared between the model bridge, the tool handlers and the hook (thread-safe)."""

    steps: int = 0
    last_model_event_id: str | None = None
    stop: GuardStopped | None = None
    model_error: BaseException | None = None
    lock: threading.Lock = field(default_factory=threading.Lock)


class _BridgeModel(Model):
    """A Strands model provider that delegates to ``ctx.model`` (the instrumented adapter)."""

    def __init__(self, ctx: RunContext, tools: list[ToolSpec], state: _RunState) -> None:
        self._ctx = ctx
        self._tools = tools
        self._state = state
        self._config: dict[str, Any] = {}

    def update_config(self, **model_config: Any) -> None:
        self._config.update(model_config)

    def get_config(self) -> Any:
        return dict(self._config)

    async def structured_output(  # type: ignore[override]
        self, output_model: Any, prompt: Any, system_prompt: str | None = None, **kwargs: Any
    ) -> AsyncGenerator[dict[str, Any], None]:
        raise NotImplementedError("Structured output is not used by the sandbox")
        yield {}  # pragma: no cover  (makes this an async generator)

    async def stream(  # type: ignore[override]
        self,
        messages: Any,
        tool_specs: Any = None,
        system_prompt: str | None = None,
        *,
        system_prompt_content: Any = None,
        **kwargs: Any,
    ) -> AsyncIterable[dict[str, Any]]:
        state = self._state
        if state.stop is not None:
            # A tool call was stopped by a guard; Strands swallowed it. End the run here.
            state.model_error = state.stop
            raise state.stop
        system = system_prompt or ""
        if not system and system_prompt_content:
            system = "".join(b.get("text", "") for b in system_prompt_content)
        try:
            response = await asyncio.to_thread(
                self._ctx.model.converse, list(messages), system, self._tools, self._ctx.params
            )
        except BaseException as exc:
            state.model_error = exc
            raise
        with state.lock:
            state.steps += 1
            state.last_model_event_id = self._ctx.events.last_event_id

        yield {"messageStart": {"role": "assistant"}}
        for index, block in enumerate(response.message.get("content", [])):
            if "text" in block:
                yield {
                    "contentBlockDelta": {
                        "contentBlockIndex": index,
                        "delta": {"text": block["text"]},
                    }
                }
            elif "toolUse" in block:
                tool_use = block["toolUse"]
                yield {
                    "contentBlockStart": {
                        "contentBlockIndex": index,
                        "start": {
                            "toolUse": {
                                "toolUseId": tool_use["toolUseId"],
                                "name": tool_use["name"],
                            }
                        },
                    }
                }
                yield {
                    "contentBlockDelta": {
                        "contentBlockIndex": index,
                        "delta": {"toolUse": {"input": json.dumps(tool_use.get("input", {}))}},
                    }
                }
            else:
                continue
            yield {"contentBlockStop": {"contentBlockIndex": index}}
        yield {"messageStop": {"stopReason": response.stop_reason or "end_turn"}}
        yield {
            "metadata": {
                "usage": {
                    "inputTokens": response.input_tokens,
                    "outputTokens": response.output_tokens,
                    "totalTokens": response.input_tokens + response.output_tokens,
                },
                "metrics": {"latencyMs": int(response.latency_ms or 0)},
            }
        }


def _error_result(tool_use_id: str, text: str) -> dict[str, Any]:
    return {"toolUseId": tool_use_id, "status": "error", "content": [{"text": text}]}


def _make_tool(
    spec: ToolSpec, ctx: RunContext, index: ToolIndex, state: _RunState
) -> PythonAgentTool:
    """Register one MCP tool as a Strands tool that delegates to ``ctx.tools``."""

    def handler(tool_use: dict[str, Any], **_: Any) -> dict[str, Any]:
        use = ToolUse(
            tool_use_id=tool_use["toolUseId"], name=tool_use["name"], input=tool_use.get("input")
        )
        if state.stop is not None:
            return _error_result(use.tool_use_id, f"Run stopped: {state.stop.message}")
        verdict = check_tool_use(index, use, ctx.events, state.last_model_event_id)
        if isinstance(verdict, Rejected):
            return _error_result(use.tool_use_id, verdict.message)
        try:
            result = ctx.tools.call_blocking(
                verdict.server, verdict.name, use.input, tool_use_id=use.tool_use_id
            )
        except GuardStopped as exc:
            state.stop = exc
            return _error_result(use.tool_use_id, f"Run stopped: {exc.message}")
        return {
            "toolUseId": use.tool_use_id,
            "status": "error" if result.is_error else "success",
            "content": [{"text": result.text if result.text else "(empty result)"}],
        }

    strands_spec = {
        "name": spec.model_name,
        "description": spec.description or spec.name,
        "inputSchema": {"json": spec.input_schema},
    }
    return PythonAgentTool(spec.model_name, strands_spec, handler)  # type: ignore[arg-type]


@register("harness", "strands")
class StrandsHarness:
    name = "strands"
    version = "1"

    class Params(BaseModel):
        # Strands' own turn limit. Set above the sandbox guards so ours fire first.
        max_cycles: int = Field(default=DEFAULT_MAX_TURNS, gt=0)

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = self.Params(**(params or {}))

    def run(self, ctx: RunContext) -> RunOutcome:
        state = _RunState()
        agent: Agent | None = None
        try:
            specs = ctx.tools.list_tools()
            index = ToolIndex(specs)
            agent = Agent(
                model=_BridgeModel(ctx, specs, state),
                tools=[_make_tool(s, ctx, index, state) for s in specs],
                system_prompt=ctx.system_prompt or None,
                callback_handler=None,
            )

            def on_before_tool(event: BeforeToolCallEvent) -> None:
                if event.selected_tool is None:
                    use = ToolUse(
                        tool_use_id=event.tool_use["toolUseId"],
                        name=event.tool_use["name"],
                        input=event.tool_use.get("input"),
                    )
                    check_tool_use(index, use, ctx.events, state.last_model_event_id)

            agent.hooks.add_callback(BeforeToolCallEvent, on_before_tool)

            result = agent(ctx.prompt, limits={"turns": self.params.max_cycles})
        except MaxTokensReachedException:
            # Strands raises, but keeps the partial message. Treat it like the Converse loop does:
            # partial text is the answer, no text is no_final_output.
            partial = ""
            for message in reversed(agent.messages if agent is not None else []):
                if message.get("role") == "assistant":
                    partial = _message_text(message)
                    break
            return finish(partial, "max_tokens", state.steps, ctx.events, state.last_model_event_id)
        except Exception as exc:
            cause = state.model_error if isinstance(state.model_error, Exception) else exc
            return outcome_for_exception(cause, ctx.events, state.steps, state.last_model_event_id)

        if state.stop is not None:
            return outcome_for_exception(state.stop, ctx.events, state.steps)
        if result.stop_reason == "limit_turns":
            return self._failed(
                "no_final_output",
                f"No final answer after {self.params.max_cycles} turns",
                ctx,
                state,
            )
        text = _message_text(result.message)
        return finish(text, result.stop_reason, state.steps, ctx.events, state.last_model_event_id)

    @staticmethod
    def _failed(kind: str, message: str, ctx: RunContext, state: _RunState) -> RunOutcome:
        now = utcnow()
        error = ErrorInfo(source="agent", kind=kind, message=message)
        ctx.events.emit(
            ErrorEvent(parent_id=state.last_model_event_id, ts_start=now, ts_end=now, error=error)
        )
        return RunOutcome(state="agent_failed", error=error, steps=state.steps)


def _message_text(message: Any) -> str:
    return "".join(b["text"] for b in message.get("content", []) if "text" in b)
