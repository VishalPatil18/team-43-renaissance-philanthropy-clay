"""Custom queries: a free-form prompt run as a task of its own (``tasks.custom`` in a spec).

A custom task has the instance ID ``Q@<id>`` (template ``Q``). It is not in the task library and
has no scripted reference, so the worker builds its instance and reference here, and the only
evaluator that runs on it is ``expect``: the share of expected strings found in the answer.
Everything else (plan, executors, guards, trace, store, reports, the UI) is the normal pipeline.
"""

from __future__ import annotations

import hashlib
import json
import re
from typing import Any

from claysandbox.contracts.assessment import Assessment, EvaluatorKind, SubScore
from claysandbox.contracts.manifest import ComponentRef, RunManifest
from claysandbox.contracts.registry import register
from claysandbox.contracts.spec import CustomTask
from claysandbox.contracts.task import TaskInstance, TaskReference, WorkflowSpec
from claysandbox.contracts.trace import FinalOutput, Trace

TEMPLATE = "Q"
EVALUATORS = [{"name": "expect", "version": "1"}]
SYSTEM_PROMPT = (
    "You are a geospatial research agent. Use the available tools to find the answer; do not "
    "guess identifiers or numbers you have not seen in a tool result. Finish with a concise "
    "final answer that lists the specific items (IDs, names, coordinates or values) you found."
)


def instance_id(task: CustomTask) -> str:
    return f"{TEMPLATE}@{task.id}"


def is_custom(instance_id: str) -> bool:
    return instance_id.startswith(f"{TEMPLATE}@")


def slug(text: str, used: set[str] | None = None) -> str:
    """A task ID from a prompt: its first words, lower-case, with a counter if taken."""
    words = re.findall(r"[a-z0-9]+", text.lower())[:6]
    base = "-".join(words)[:40].strip("-") or "query"
    out, n = base, 2
    while used and out in used:
        out, n = f"{base}-{n}", n + 1
    return out


def instance(task: CustomTask) -> TaskInstance:
    # model_construct: the library's ID rule (T<n>@<aoi>) is for library tasks only.
    return TaskInstance.model_construct(
        id=instance_id(task),
        template=TEMPLATE,
        aoi="",
        title=task.prompt[:80],
        prompt=task.prompt,
        system_prompt=task.system_prompt or SYSTEM_PROMPT,
        params={},
        output_schema={},
    )


def reference(task: CustomTask) -> TaskReference:
    body = {"prompt": task.prompt, "system_prompt": task.system_prompt, "expect": task.expect}
    digest = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()[:12]
    return TaskReference(
        template=TEMPLATE,
        instance_id=instance_id(task),
        version=f"{TEMPLATE}.v1+sha256:{digest}",
        builder="custom query",
        workflow=WorkflowSpec(),
        output_reference={"expect": list(task.expect)},
        notes=["Custom query: no scripted reference; scored only against `expect`."],
    )


def _answer_text(output: Any) -> str:
    return output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)


@register("evaluator", "expect@1")
@register("evaluator", "expect")
class ExpectEvaluator:
    """Share of the expected strings that appear in the final answer (case-insensitive)."""

    name = "expect"
    version = "1"
    kind: EvaluatorKind = "output"
    deterministic = True

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = dict(params or {})

    def assess(self, trace: Trace, manifest: RunManifest, reference: TaskReference) -> Assessment:
        expected = [str(x) for x in reference.output_reference.get("expect", [])]
        final = next((e for e in reversed(trace.events) if isinstance(e, FinalOutput)), None)
        base = {
            "run_id": manifest.run_id,
            "evaluator": ComponentRef(kind="evaluator", name=self.name, version=self.version),
            "kind": self.kind,
            "task_reference_version": reference.version,
        }
        if not expected:
            return Assessment(**base, notes=["No expected answers given; nothing to score."])
        if final is None:
            return Assessment(
                **base,
                composite=0.0,
                metrics={"found": 0.0},
                notes=["The run produced no final answer."],
            )
        text = _answer_text(final.output).casefold()
        subs = [
            SubScore(
                name=item,
                value=1.0 if item.casefold() in text else 0.0,
                evidence=[final.event_id],
            )
            for item in expected
        ]
        found = sum(s.value for s in subs)
        missing = [s.name for s in subs if not s.value]
        return Assessment(
            **base,
            composite=found / len(subs),
            subscores=subs,
            metrics={"found": found / len(subs)},
            evidence=[final.event_id],
            notes=[f"Missing from the answer: {', '.join(missing)}"] if missing else [],
        )
