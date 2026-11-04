"""Checks and outcome mapping shared by both harnesses (FR-1.6 to FR-1.8, srs §12.4).

Agent-side mistakes become typed error events and never crash a run:

* ``unknown_tool``: the name is not in the tool set. Emitted as an ``error`` event.
* ``invalid_args``: arguments fail the tool's JSON Schema. Emitted as a ``tool_call`` event with
  status ``rejected``. The server is not called.
* ``malformed_call``: tool-use input is not a JSON object. Same shape as ``invalid_args``.
* ``no_final_output``: the run ends with no answer.
* ``refusal``: the model stopped for ``content_filtered`` or ``guardrail_intervened``.

The harnesses never guess "gave up" from text; the workflow evaluator's done condition covers it.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any

from jsonschema import Draft202012Validator, SchemaError
from jsonschema.validators import validator_for

from claysandbox.contracts.errors import ConfigError, GuardStopped, InfraError
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.runtime import RunOutcome, ToolUse
from claysandbox.contracts.trace import ErrorEvent, ErrorInfo, EventSink, ToolCall, utcnow

REFUSAL_STOP_REASONS = frozenset({"content_filtered", "guardrail_intervened"})
DEFAULT_MAX_TURNS = 100


@dataclass
class Rejected:
    """A tool use that must not reach the server. ``message`` goes back to the model."""

    kind: str
    message: str


class ToolIndex:
    """Looks up tools by the name the model sees and validates arguments against their schema."""

    def __init__(self, specs: list[ToolSpec]) -> None:
        self.by_model_name: dict[str, ToolSpec] = {s.model_name: s for s in specs}
        self._validators: dict[str, Any] = {}

    def get(self, model_name: str) -> ToolSpec | None:
        return self.by_model_name.get(model_name)

    def schema_error(self, spec: ToolSpec, args: dict[str, Any]) -> str | None:
        """Return a short description of the first schema violation, or ``None`` if valid."""
        validator: Any = self._validators.get(spec.model_name)
        if validator is None:
            try:
                cls = validator_for(spec.input_schema, default=Draft202012Validator)
                cls.check_schema(spec.input_schema)
                validator = cls(spec.input_schema)
            except SchemaError:
                validator = False  # a schema we cannot interpret is not enforced
            self._validators[spec.model_name] = validator
        if validator is False:
            return None
        errors = sorted(validator.iter_errors(args), key=lambda e: list(e.absolute_path))
        if not errors:
            return None
        err = errors[0]
        where = "/".join(str(p) for p in err.absolute_path) or "(root)"
        return f"{where}: {err.message}"


def check_tool_use(
    index: ToolIndex, use: ToolUse, sink: EventSink, parent_id: str | None
) -> ToolSpec | Rejected:
    """Return the tool to call, or a ``Rejected`` after emitting the matching error event."""
    spec = index.get(use.name)
    if spec is None:
        message = f"Unknown tool {use.name!r}. Available tools: {sorted(index.by_model_name)}"
        now = utcnow()
        sink.emit(
            ErrorEvent(
                parent_id=parent_id,
                ts_start=now,
                ts_end=now,
                error=ErrorInfo(
                    source="agent", kind="unknown_tool", message=f"Unknown tool {use.name!r}"
                ),
            )
        )
        return Rejected("unknown_tool", message)

    if not isinstance(use.input, dict):
        message = (
            f"Tool input for {use.name!r} must be a JSON object, got {type(use.input).__name__}"
        )
        _emit_rejected(sink, spec, {"_raw": repr(use.input)}, "malformed_call", message, parent_id)
        return Rejected("malformed_call", message)

    problem = index.schema_error(spec, use.input)
    if problem is not None:
        message = f"Invalid arguments for {use.name!r}: {problem}"
        _emit_rejected(sink, spec, use.input, "invalid_args", message, parent_id)
        return Rejected("invalid_args", message)
    return spec


def _emit_rejected(
    sink: EventSink,
    spec: ToolSpec,
    args: dict[str, Any],
    kind: str,
    message: str,
    parent_id: str | None,
) -> None:
    now = utcnow()
    sink.emit(
        ToolCall(
            parent_id=parent_id,
            ts_start=now,
            ts_end=now,
            server=spec.server,
            tool=spec.name,
            capability=spec.capability,
            args=args,
            status="rejected",
            result_preview=message[:1000],
            error=ErrorInfo(source="agent", kind=kind, message=message),
        )
    )


def tool_result_block(tool_use_id: str, text: str, is_error: bool) -> dict[str, Any]:
    """A Converse ``toolResult`` content block."""
    return {
        "toolResult": {
            "toolUseId": tool_use_id,
            "content": [{"text": text if text else "(empty result)"}],
            "status": "error" if is_error else "success",
        }
    }


_THINKING = re.compile(r"<thinking>.*?</thinking>", re.DOTALL | re.IGNORECASE)
_FENCE = re.compile(r"```(?:json)?\s*(.*?)```", re.DOTALL)


def parse_final_output(text: str) -> dict[str, Any] | str:
    """The JSON object in ``text`` if there is one, else the text.

    Models wrap the answer in different ways, so this accepts: plain JSON, JSON in a code fence,
    and JSON after ``<thinking>...</thinking>`` (Nova models write this) or other prose. When
    several objects appear, the first (outermost) one that parses wins. Anything that is not a
    JSON *object* is returned as text.
    """
    stripped = text.strip()
    visible = _THINKING.sub("", stripped).strip()
    candidates = [visible]
    fenced = _FENCE.search(visible)
    if fenced:
        candidates.append(fenced.group(1).strip())
    for candidate in candidates:
        try:
            value = json.loads(candidate)
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    decoder = json.JSONDecoder()
    for match in re.finditer(r"\{", visible):
        try:
            value, _ = decoder.raw_decode(visible, match.start())
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    return stripped


def finish(
    final_text: str, stop_reason: str | None, steps: int, sink: EventSink, parent_id: str | None
) -> RunOutcome:
    """Build the outcome for a run that ended because the model stopped asking for tools."""
    now = utcnow()
    text = final_text.strip()
    if not _THINKING.sub("", text).strip():
        text = ""  # only <thinking> blocks: the model never gave an answer
    if stop_reason in REFUSAL_STOP_REASONS:
        error = ErrorInfo(
            source="agent", kind="refusal", message=f"Model stopped with {stop_reason}"
        )
        sink.emit(ErrorEvent(parent_id=parent_id, ts_start=now, ts_end=now, error=error))
        if text:
            return RunOutcome(state="completed", output=parse_final_output(text), steps=steps)
        return RunOutcome(state="agent_failed", error=error, steps=steps)
    if not text:
        error = ErrorInfo(
            source="agent",
            kind="no_final_output",
            message=f"Run ended with no answer (stop reason {stop_reason})",
        )
        sink.emit(ErrorEvent(parent_id=parent_id, ts_start=now, ts_end=now, error=error))
        return RunOutcome(state="agent_failed", error=error, steps=steps)
    return RunOutcome(state="completed", output=parse_final_output(text), steps=steps)


def outcome_for_exception(
    exc: BaseException, sink: EventSink, steps: int, parent_id: str | None = None
) -> RunOutcome:
    """Map an exception raised during a run to an outcome (architecture §9.3).

    * ``GuardStopped`` -> ``budget_stopped`` (the wrapper already emitted ``guard_stop``)
    * ``InfraError`` -> ``infra_error``, retryable (the wrapper already emitted the model call)
    * ``ConfigError`` -> ``infra_error``, not retryable
    * anything else -> an ``error`` event (agent) and ``agent_failed``
    """
    if isinstance(exc, GuardStopped):
        return RunOutcome(
            state="budget_stopped",
            error=ErrorInfo(source=exc.source, kind=exc.kind, message=exc.message),
            steps=steps,
        )
    if isinstance(exc, InfraError | ConfigError):
        return RunOutcome(
            state="infra_error",
            error=ErrorInfo(
                source="infra", kind=exc.kind, message=exc.message, retryable=exc.retryable
            ),
            steps=steps,
        )
    now = utcnow()
    error = ErrorInfo(
        source="agent", kind="harness_exception", message=f"{type(exc).__name__}: {exc}"[:500]
    )
    sink.emit(ErrorEvent(parent_id=parent_id, ts_start=now, ts_end=now, error=error))
    return RunOutcome(state="agent_failed", error=error, steps=steps)
