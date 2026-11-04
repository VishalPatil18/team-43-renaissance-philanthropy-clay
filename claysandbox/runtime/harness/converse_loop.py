"""Plain Converse tool loop: the second harness, with no framework (DD-009).

Loop: call the model, run the tools it asked for in the order given (deterministic, FR-1.11),
send all results back in one user message, repeat until the model stops asking for tools.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field

from claysandbox.contracts.registry import register
from claysandbox.contracts.runtime import RunContext, RunOutcome
from claysandbox.contracts.trace import ErrorEvent, ErrorInfo, utcnow

from ._checks import (
    DEFAULT_MAX_TURNS,
    Rejected,
    ToolIndex,
    check_tool_use,
    finish,
    outcome_for_exception,
    tool_result_block,
)


@register("harness", "converse_loop")
class ConverseLoopHarness:
    name = "converse_loop"
    version = "1"

    class Params(BaseModel):
        max_turns: int = Field(default=DEFAULT_MAX_TURNS, gt=0)

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = self.Params(**(params or {}))

    def run(self, ctx: RunContext) -> RunOutcome:
        steps = 0
        try:
            tools = ctx.tools.list_tools()
            index = ToolIndex(tools)
            messages: list[dict[str, Any]] = [{"role": "user", "content": [{"text": ctx.prompt}]}]
            for _ in range(self.params.max_turns):
                response = ctx.model.converse(messages, ctx.system_prompt, tools, ctx.params)
                steps += 1
                model_event_id = ctx.events.last_event_id
                messages.append(response.message)

                if not response.tool_uses:
                    return finish(
                        response.text, response.stop_reason, steps, ctx.events, model_event_id
                    )

                results: list[dict[str, Any]] = []
                for use in response.tool_uses:
                    verdict = check_tool_use(index, use, ctx.events, model_event_id)
                    if isinstance(verdict, Rejected):
                        results.append(tool_result_block(use.tool_use_id, verdict.message, True))
                        continue
                    result = ctx.tools.call_blocking(
                        verdict.server, verdict.name, use.input, tool_use_id=use.tool_use_id
                    )
                    results.append(tool_result_block(use.tool_use_id, result.text, result.is_error))
                messages.append({"role": "user", "content": results})

            now = utcnow()
            error = ErrorInfo(
                source="agent",
                kind="no_final_output",
                message=f"No final answer after {self.params.max_turns} turns",
            )
            ctx.events.emit(ErrorEvent(ts_start=now, ts_end=now, error=error))
            return RunOutcome(state="agent_failed", error=error, steps=steps)
        except Exception as exc:
            return outcome_for_exception(exc, ctx.events, steps, ctx.events.last_event_id)
