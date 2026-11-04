"""Deterministic summarizer (SHI-R1-01, FR-3.1-FR-3.4). Owner: WS3.

No model calls, so it works offline (replay, CI) and costs nothing. One claim
per step (a model call plus the tool calls it asked for), one claim per error
naming any later recovery, and a closing line on the outcome. Every claim
cites the events it describes.
"""

from __future__ import annotations

import json
from typing import Any

from pydantic import BaseModel

from claysandbox.contracts.registry import register
from claysandbox.contracts.summary import Claim, Summary
from claysandbox.contracts.trace import (
    AnyEvent,
    FinalOutput,
    ModelCall,
    RunEnd,
    ToolCall,
    Trace,
)

from .citations import check, error_line, is_error_event


def _short(value: Any, n: int = 80) -> str:
    s = (
        value
        if isinstance(value, str)
        else json.dumps(value, separators=(",", ":"), default=str)
    )
    return s if len(s) <= n else s[: n - 1] + "…"


def _result_hint(e: ToolCall) -> str:
    if e.status != "ok":
        return e.status
    try:
        data = json.loads(e.result_preview or "")
        for key in ("count", "total", "numberMatched"):
            if isinstance(data, dict) and isinstance(data.get(key), int):
                return f"{data[key]} results"
        if isinstance(data, dict) and isinstance(data.get("features"), list):
            return f"{len(data['features'])} features"
        if isinstance(data, list):
            return f"{len(data)} results"
    except (json.JSONDecodeError, TypeError):
        pass
    return "ok"


def _steps(events: list[AnyEvent]) -> list[tuple[ModelCall, list[ToolCall]]]:
    """A step is one model call plus the tool calls it requested (open point 6)."""
    steps: list[tuple[ModelCall, list[ToolCall]]] = []
    by_id: dict[str, list[ToolCall]] = {}
    for e in events:
        if isinstance(e, ModelCall):
            steps.append((e, []))
            by_id[e.event_id] = steps[-1][1]
        elif isinstance(e, ToolCall) and steps:
            by_id.get(e.parent_id or "", steps[-1][1]).append(e)
    return steps


@register("summarizer", "deterministic")
class DeterministicSummarizer:
    name = "deterministic"
    version = "1"

    class Params(BaseModel):
        pass

    def __init__(self, params: dict | None = None):
        self.params = self.Params(**(params or {}))

    def summarize(self, trace: Trace, manifest: Any = None) -> Summary:
        claims: list[Claim] = []
        for n, (mc, tools) in enumerate(_steps(trace.events), 1):
            if tools:
                calls = "; ".join(
                    f"called {t.server}.{t.tool}({_short(t.args, 60)}) → {_result_hint(t)}"
                    for t in tools
                )
                claims.append(
                    Claim(
                        claim=f"Step {n}: {calls}.",
                        event_ids=[mc.event_id] + [t.event_id for t in tools],
                    )
                )
            elif mc.error is None:
                claims.append(
                    Claim(
                        claim=f"Step {n}: the model answered without calling tools "
                        f"({mc.input_tokens}→{mc.output_tokens} tokens).",
                        event_ids=[mc.event_id],
                    )
                )
        # errors, with the recovery that followed (a later successful call of the same tool)
        for i, e in enumerate(trace.events):
            if not is_error_event(e):
                continue
            ids, text = [e.event_id], error_line(e)
            if isinstance(e, ToolCall):
                later = next(
                    (
                        x
                        for x in trace.events[i + 1 :]
                        if isinstance(x, ToolCall)
                        and x.tool == e.tool
                        and x.status == "ok"
                    ),
                    None,
                )
                if later is not None:
                    text = (
                        text.rstrip(".")
                        + f"; recovered by a later successful call ({later.event_id})."
                    )
                    ids.append(later.event_id)
                else:
                    text = text.rstrip(".") + "; never recovered."
            claims.append(Claim(claim=text, event_ids=ids, deterministic=True))
        out = next(
            (e for e in reversed(trace.events) if isinstance(e, FinalOutput)), None
        )
        end = next((e for e in reversed(trace.events) if isinstance(e, RunEnd)), None)
        if end is not None:
            totals = end.totals or {}
            bits = ", ".join(
                f"{k} {v}"
                for k, v in totals.items()
                if k in ("steps", "cost_usd", "wall_ms")
            )
            text = f"Run ended {end.state}" + (f" ({bits})" if bits else "")
            text += (
                f" with output {_short(out.output)}."
                if out
                else " with no final output."
            )
            claims.append(
                Claim(
                    claim=text,
                    event_ids=[end.event_id] + ([out.event_id] if out else []),
                )
            )
        elif trace.incomplete:
            last = trace.events[-1].event_id if trace.events else None
            if last:
                claims.append(
                    Claim(
                        claim="The trace stops before run_end (the run crashed or is still running).",
                        event_ids=[last],
                    )
                )
        kept, dropped = check(claims, trace)
        return Summary(
            run_id=trace.run_id,
            claims=kept,
            dropped_claims=dropped,
            summarizer={"name": self.name, "version": self.version, "params": {}},
        )
