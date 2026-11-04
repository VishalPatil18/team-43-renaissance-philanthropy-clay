"""Scripted fake model adapter (owner: WS1)."""

from __future__ import annotations

import copy
from typing import Any

from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.runtime import ModelResponse, ToolUse


def text_reply(
    text: str,
    *,
    input_tokens: int = 10,
    output_tokens: int = 5,
    stop_reason: str = "end_turn",
) -> ModelResponse:
    """A reply with only text."""
    content: list[dict[str, Any]] = [{"text": text}] if text else []
    return ModelResponse(
        message={"role": "assistant", "content": content},
        text=text,
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=1.0,
        model_id="fake-model",
    )


def tool_reply(
    *calls: tuple[str, Any] | tuple[str, Any, str],
    text: str = "",
    input_tokens: int = 10,
    output_tokens: int = 5,
    stop_reason: str = "tool_use",
) -> ModelResponse:
    """A reply that asks for one or more tools.

    Each call is ``(model_name, input)`` or ``(model_name, input, tool_use_id)``.
    """
    content: list[dict[str, Any]] = [{"text": text}] if text else []
    uses: list[ToolUse] = []
    for i, call in enumerate(calls):
        name, tool_input = call[0], call[1]
        tool_use_id = call[2] if len(call) == 3 else f"tu-{len(uses)}-{i}"  # type: ignore[misc]
        uses.append(ToolUse(tool_use_id=tool_use_id, name=name, input=tool_input))
        content.append({"toolUse": {"toolUseId": tool_use_id, "name": name, "input": tool_input}})
    return ModelResponse(
        message={"role": "assistant", "content": content},
        text=text,
        tool_uses=uses,
        stop_reason=stop_reason,
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        latency_ms=1.0,
        model_id="fake-model",
    )


class FakeModelAdapter:
    """Plays back a script. An ``Exception`` entry is raised instead of returned."""

    name = "fake"
    version = "1"

    def __init__(self, script: list[ModelResponse | Exception], model_id: str = "fake-model"):
        self.script = list(script)
        self.model_id = model_id
        self.calls: list[dict[str, Any]] = []

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[ToolSpec],
        params: dict[str, Any],
    ) -> ModelResponse:
        self.calls.append(
            {
                "messages": copy.deepcopy(messages),
                "system": system,
                "tools": [t.model_name for t in tools],
                "params": dict(params),
            }
        )
        if len(self.calls) > len(self.script):
            raise RuntimeError("FakeModelAdapter script exhausted")
        item = self.script[len(self.calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item.model_copy(deep=True)
