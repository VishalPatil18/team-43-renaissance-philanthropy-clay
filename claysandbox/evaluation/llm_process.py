"""LLM process evaluator (architecture §10.3, DD-007, DD-027).

Judges *how* the agent worked, from the trace digest, a rubric and the workflow spec.
The judge ``ModelAdapter`` is injected so this module imports only ``claysandbox.contracts``.
"""

from __future__ import annotations

import statistics
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from claysandbox.contracts.assessment import Assessment, EvaluatorKind, SubScore
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.registry import register
from claysandbox.contracts.runtime import ModelAdapter, PriceTable
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace, trace_digest
from claysandbox.evaluation._parsing import ParseError, load_json_value
from claysandbox.evaluation._shared import evaluator_ref, scored_events

PROMPT_VERSION = "2"  # 2: infra-error events are left out of the digest

SYSTEM_PROMPT = (
    "You are a strict reviewer of how an AI agent worked on a task. You judge the PROCESS "
    "(planning, tool choice, recovery from errors, honesty about uncertainty), not whether "
    "the final answer is correct. Use only the evidence in the trace digest. "
    "Reply with JSON only, no prose and no code fences, in exactly this shape: "
    '{"items": [{"name": str, "score": number between 0 and 1, '
    '"event_ids": [str], "reason": str}]}. '
    "Give one item per rubric item. Cite the event IDs (the text in square brackets in the "
    "digest) that support each score. Never invent event IDs."
)

REGION_PREFIXES = ("us", "eu", "apac", "global")


def model_family(model_id: str) -> str:
    """Vendor prefix of a Bedrock model ID, ignoring a region/inference-profile prefix."""
    head, _, rest = model_id.partition(".")
    if head in REGION_PREFIXES and rest:
        head = rest.partition(".")[0]
    return head


def check_judge_family(judge_model_id: str, agent_model_ids: list[str]) -> None:
    """Raise ConfigError if the judge shares a family with any agent model (DD-027)."""
    family = model_family(judge_model_id)
    clashes = [m for m in agent_model_ids if model_family(m) == family]
    if clashes:
        raise ConfigError(
            f"Judge model {judge_model_id!r} is in the same family ({family!r}) as agent "
            f"model(s) {clashes}. Pick an out-of-family judge.",
            kind="judge_same_family",
        )


def without_infra(trace: Trace) -> Trace:
    """Drop infra-error events so they cannot move the judge's score (FR-4.4, DD-012)."""
    return trace.model_copy(update={"events": scored_events(trace)})


def build_prompt(trace: Trace, reference: TaskReference, max_chars: int) -> str:
    trace = without_infra(trace)
    workflow = reference.workflow.model_dump_json(indent=2)
    rubric = reference.process_rubric or (
        "(none given: judge planning, tool choice, recovery and honesty)"
    )
    return (
        f"## Trace digest\n{trace_digest(trace, max_chars)}\n\n"
        f"## Process rubric\n{rubric}\n\n"
        f"## Workflow spec\n{workflow}\n"
    )


class _Reply(BaseModel):
    items: list[dict[str, Any]] = Field(min_length=1)


def parse_reply(text: str) -> list[dict[str, Any]]:
    """Validate one judge reply. Raises ValueError on any schema problem."""
    try:
        reply = _Reply.model_validate(load_json_value(text))
    except (ParseError, ValidationError) as e:
        raise ValueError(f"not valid judge JSON: {str(e)[:120]}") from None
    out: list[dict[str, Any]] = []
    seen: set[str] = set()
    for raw in reply.items:
        name, score = raw.get("name"), raw.get("score")
        ids = raw.get("event_ids", [])
        if not isinstance(name, str) or not name:
            raise ValueError("item without a name")
        if isinstance(score, bool) or not isinstance(score, int | float) or not 0 <= score <= 1:
            raise ValueError(f"item {name!r} has a score outside 0..1")
        if not isinstance(ids, list) or not all(isinstance(i, str) for i in ids):
            raise ValueError(f"item {name!r} has bad event_ids")
        if name in seen:
            continue
        seen.add(name)
        out.append(
            {
                "name": name,
                "score": float(score),
                "event_ids": ids,
                "reason": str(raw.get("reason", "")),
            }
        )
    return out


@register("evaluator", "llm_process@1")
@register("evaluator", "llm_process")
class LLMProcessEvaluator:
    name = "llm_process"
    version = "1"
    kind: EvaluatorKind = "process"
    deterministic = False

    class Params(BaseModel):
        model_id: str
        k: int = Field(default=3, ge=1)
        temperature: float = 0.0
        max_digest_chars: int = 12000

    def __init__(
        self,
        params: dict | None = None,
        model: ModelAdapter | None = None,
        price_table: PriceTable | None = None,
    ) -> None:
        try:
            self.params = self.Params.model_validate(params or {})
        except ValidationError as e:
            raise ConfigError(f"llm_process params invalid: {e}", kind="bad_params") from None
        self.model = model
        self.price_table = price_table

    def assess(self, trace: Trace, manifest: RunManifest, reference: TaskReference) -> Assessment:
        if self.model is None:
            raise ConfigError(
                "llm_process has no judge model: the composition root must inject an "
                "uninstrumented ModelAdapter.",
                kind="judge_not_configured",
            )
        p = self.params
        messages = [
            {
                "role": "user",
                "content": [{"text": build_prompt(trace, reference, p.max_digest_chars)}],
            }
        ]
        valid_ids = {e.event_id for e in trace.events}
        notes: list[str] = [f"prompt_version={PROMPT_VERSION}"]
        cost = 0.0
        dropped = 0
        repeats: list[list[dict[str, Any]]] = []

        for rep in range(p.k):
            items: list[dict[str, Any]] | None = None
            for attempt in (1, 2):
                resp = self.model.converse(
                    messages, SYSTEM_PROMPT, [], {"temperature": p.temperature}
                )
                if self.price_table is not None:
                    cost += self.price_table.model_cost(
                        self.model.model_id, resp.input_tokens, resp.output_tokens
                    )
                try:
                    items = parse_reply(resp.text)
                    break
                except ValueError as e:
                    if attempt == 1:
                        notes.append(f"repeat {rep + 1}: {e}; retrying once")
                    else:
                        notes.append(f"repeat {rep + 1}: still invalid after retry; excluded")
            if items is None:
                continue
            for it in items:
                kept = [i for i in it["event_ids"] if i in valid_ids]
                dropped += len(it["event_ids"]) - len(kept)
                it["event_ids"] = kept
            repeats.append(items)

        a = Assessment(
            run_id=manifest.run_id,
            evaluator=evaluator_ref(self.name, self.version, p),
            kind="process",
            task_reference_version=reference.version,
            cost_usd=cost,
            notes=notes,
            metrics={"dropped_event_ids": float(dropped)},
        )
        if not repeats:
            a.notes.append("no valid judge reply; no score")
            return a

        composites = [statistics.fmean(i["score"] for i in r) for r in repeats]
        a.repeats = composites
        a.composite = statistics.fmean(composites)
        a.metrics["spread"] = max(composites) - min(composites)
        a.metrics["stdev"] = statistics.stdev(composites) if len(composites) > 1 else 0.0

        by_item: dict[str, list[dict[str, Any]]] = {}
        for r in repeats:
            for it in r:
                by_item.setdefault(it["name"], []).append(it)
        for name, its in by_item.items():
            mean = statistics.fmean(i["score"] for i in its)
            evidence = list(dict.fromkeys(e for i in its for e in i["event_ids"]))
            reasons = [i["reason"] for i in its if i["reason"]][:1]
            a.metrics[f"item.{name}"] = mean
            a.subscores.append(SubScore(name=name, value=mean, evidence=evidence, notes=reasons))
        return a
