"""Deterministic workflow evaluator (architecture §10.1, DD-028, DD-041, DD-042).

Versions and registry names
---------------------------
Both versions stay registered so assessments made by either still resolve (FR-4.8):

* ``"workflow@0"`` -> :class:`WorkflowEvaluatorV0` (validity, required coverage, done).
* ``"workflow@1"`` -> :class:`WorkflowEvaluatorV1` (all eight sub-scores).
* ``"workflow"``   -> the latest version, currently :class:`WorkflowEvaluatorV1`.

The ``name@version`` form matches the CLI's ``rescore --evaluator <name@ver>``. Every class
reports ``name="workflow"`` and its own ``version`` in ``Assessment.evaluator``; use
:func:`resolve_workflow` to look a version up from a recorded ``(name, version)`` pair.

Scoring rules shared by every version
-------------------------------------
* Tools are matched by ``ToolCall.capability`` (FR-4.10), never by server or tool name.
* Events carrying an ``infra`` error are dropped before scoring, so infra errors never
  move any sub-score (FR-4.4, DD-012).
* A step is one non-infra ``model_call`` event.
* ``success`` = done condition met and no ``guard_stop`` event (DD-042); ``None`` when the
  run ended in ``infra_error`` (excluded runs are neither success nor failure).
* Composite = weighted mean over the sub-scores present, weights from
  ``reference.weights`` (missing names weigh 1.0).

Evaluators are pure: no I/O, clock or randomness, so ``Assessment.stable_json()`` is
byte-identical for identical inputs.
"""

from __future__ import annotations

from typing import Any

import jsonschema
from pydantic import BaseModel

from claysandbox.contracts.assessment import Assessment, EvaluatorKind, SubScore
from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.registry import register, resolve
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import (
    AnyEvent,
    FinalOutput,
    GuardStop,
    ModelCall,
    RunEnd,
    ToolCall,
    Trace,
)
from claysandbox.evaluation._parsing import ParseError, load_json_value
from claysandbox.evaluation._shared import evaluator_ref, scored_events
from claysandbox.evaluation.constraints import check

INVALID_CALL_KINDS = frozenset({"unknown_tool", "invalid_args", "malformed_call"})
SCORED_ERROR_SOURCES = frozenset({"agent", "tool"})


# ------------------------------------------------------------------ trace view
class _View:
    """The parts of a trace the sub-scores read, with infra-errored events removed."""

    def __init__(self, trace: Trace) -> None:
        self.events = scored_events(trace)
        self.tool_calls = [e for e in self.events if isinstance(e, ToolCall)]
        self.model_calls = [e for e in self.events if isinstance(e, ModelCall)]
        self.guard_stops = [e for e in self.events if isinstance(e, GuardStop)]
        self.final_outputs = [e for e in self.events if isinstance(e, FinalOutput)]
        run_ends = [e for e in trace.events if isinstance(e, RunEnd)]
        self.run_end: RunEnd | None = run_ends[-1] if run_ends else None
        # Index of each event in the filtered list, for "later than" comparisons.
        self.index = {e.event_id: i for i, e in enumerate(self.events)}

    def calls_of(self, capability: str) -> list[ToolCall]:
        return [c for c in self.tool_calls if c.capability == capability]


def _ok(call: ToolCall) -> bool:
    return call.status == "ok" and call.error is None


def _ratio(num: float, den: float) -> float:
    return 1.0 if den == 0 else num / den


# ------------------------------------------------------------------ v0 sub-scores
def tool_call_validity(view: _View) -> SubScore:
    """Valid tool-call attempts / all attempts. Invalid = unknown_tool/invalid_args/malformed.

    An invalid-call error raised on a model call or as a free-standing error event (no tool
    call was recorded) counts as an attempt too, unless it points at a tool call already
    counted (``related_event_id``).
    """
    attempts: list[AnyEvent] = list(view.tool_calls)
    counted = {e.event_id for e in attempts}
    attempts += [
        e
        for e in view.events
        if not isinstance(e, ToolCall)
        and e.error is not None
        and e.error.kind in INVALID_CALL_KINDS
        and e.error.related_event_id not in counted
    ]
    attempts.sort(key=lambda e: view.index[e.event_id])
    invalid = [e for e in attempts if e.error is not None and e.error.kind in INVALID_CALL_KINDS]
    notes = [f"{e.error.kind} in event {e.event_id}" for e in invalid if e.error is not None]
    if not attempts:
        notes = ["no tool-call attempts"]
    elif not invalid:
        notes = [f"all {len(attempts)} tool-call attempts valid"]
    return SubScore(
        name="tool_call_validity",
        value=_ratio(len(attempts) - len(invalid), len(attempts)),
        evidence=[e.event_id for e in attempts],
        notes=notes,
    )


def required_coverage(view: _View, reference: TaskReference) -> SubScore:
    """Required capabilities with at least one successful call / required capabilities."""
    required = reference.workflow.required
    evidence: list[str] = []
    missing: list[str] = []
    for cap in required:
        ok = [c for c in view.calls_of(cap) if _ok(c)]
        if ok:
            evidence.append(ok[0].event_id)
        else:
            missing.append(cap)
    if not required:
        notes = ["no required capabilities"]
    elif missing:
        notes = [f"no successful call of {cap}" for cap in missing]
    else:
        notes = [f"all {len(required)} required capabilities called successfully"]
    return SubScore(
        name="required_coverage",
        value=_ratio(len(required) - len(missing), len(required)),
        evidence=evidence,
        notes=notes,
    )


def _parsed_output(event: FinalOutput) -> Any:
    try:
        return load_json_value(event.output)
    except ParseError:
        # Free-text answers remain valid for output_present and assumptions_or_question.
        return event.output


def _nonempty(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, str | list | dict | tuple):
        return len(value) > 0
    return True


def _done_holds(condition: str, output: Any, schema: dict[str, Any]) -> tuple[bool, str]:
    if condition == "output_present":
        return (_nonempty(output), "final output present" if _nonempty(output) else "empty")
    if condition == "output_matches_schema_nonempty":
        try:
            jsonschema.validate(output, schema)
        except jsonschema.ValidationError as exc:
            return False, f"final output fails the output schema: {exc.message}"
        if isinstance(output, dict):
            required = schema.get("required", [])
            empty = [k for k in required if not _nonempty(output.get(k))]
            if empty or not _nonempty(output):
                return False, f"final output has empty required fields {empty}"
        elif not _nonempty(output):
            return False, "final output is empty"
        return True, "final output matches the output schema and is non-empty"
    if condition == "assumptions_or_question":
        if isinstance(output, dict):
            keys = ("assumptions", "question", "questions")
            if any(_nonempty(output.get(k)) for k in keys):
                return True, "final output states assumptions or asks a question"
        if isinstance(output, str) and "?" in output:
            return True, "final output asks a question"
        return False, "final output has neither assumptions nor a question"
    return False, f"unknown done condition {condition!r}"


def done_condition(view: _View, reference: TaskReference) -> SubScore:
    """1 if the reference's done condition holds on the last final output, else 0."""
    condition = reference.workflow.done
    if not view.final_outputs:
        return SubScore(name="done_condition", value=0.0, notes=[f"{condition}: no final output"])
    last = view.final_outputs[-1]
    holds, why = _done_holds(condition, _parsed_output(last), reference.output_schema)
    return SubScore(
        name="done_condition",
        value=1.0 if holds else 0.0,
        evidence=[last.event_id],
        notes=[f"{condition}: {why} (event {last.event_id})"],
    )


# ------------------------------------------------------------------ evaluator base
class _WorkflowEvaluator:
    name = "workflow"
    version = ""
    kind: EvaluatorKind = "workflow"
    deterministic = True

    class Params(BaseModel):
        pass

    def __init__(self, params: dict | None = None) -> None:
        self.params = self.Params(**(params or {}))

    def subscores(self, view: _View, reference: TaskReference) -> list[SubScore]:
        raise NotImplementedError

    def assess(self, trace: Trace, manifest: RunManifest, reference: TaskReference) -> Assessment:
        view = _View(trace)
        subs = [
            s.model_copy(update={"weight": float(reference.weights.get(s.name, 1.0))})
            for s in self.subscores(view, reference)
        ]
        total = sum(s.weight for s in subs)
        composite = sum(s.weight * s.value for s in subs) / total if total > 0 else None
        done = next((s.value for s in subs if s.name == "done_condition"), 0.0)
        notes: list[str] = []
        success: bool | None = done == 1.0 and not view.guard_stops
        if view.guard_stops:
            notes.append(
                "not a success: guard_stop "
                + ", ".join(f"{g.limit} in event {g.event_id}" for g in view.guard_stops)
            )
        if view.run_end is not None and view.run_end.state == "infra_error":
            success = None
            notes.append("run ended in infra_error: excluded from success counts")
        return Assessment(
            run_id=manifest.run_id,
            evaluator=evaluator_ref(self.name, self.version, self.params),
            kind=self.kind,
            task_reference_version=reference.version,
            composite=composite,
            subscores=subs,
            success=success,
            evidence=[g.event_id for g in view.guard_stops],
            notes=notes,
        )


@register("evaluator", "workflow@0")
class WorkflowEvaluatorV0(_WorkflowEvaluator):
    """v0: tool_call_validity, required_coverage, done_condition."""

    version = "0"

    def subscores(self, view: _View, reference: TaskReference) -> list[SubScore]:
        return [
            tool_call_validity(view),
            required_coverage(view, reference),
            done_condition(view, reference),
        ]


# ------------------------------------------------------------------ v1 sub-scores
def argument_constraints(view: _View, reference: TaskReference) -> SubScore:
    """Satisfied checks / applicable checks, one check per (call, constraint) pair.

    Every attempt of the constraint's capability is checked, whatever its status: the
    arguments are the agent's choice even when the tool then failed.
    """
    applicable = 0
    satisfied = 0
    evidence: list[str] = []
    failures: list[str] = []
    for con in reference.workflow.argument_constraints:
        for call in view.calls_of(con.capability):
            result = check(call.args, con, reference)
            if result is None:
                continue
            applicable += 1
            if call.event_id not in evidence:
                evidence.append(call.event_id)
            if result:
                satisfied += 1
            else:
                failures.append(f"{con.capability} {con.check} failed in event {call.event_id}")
    evidence.sort(key=lambda i: view.index[i])
    if applicable == 0:
        notes = ["no applicable argument checks"]
    elif failures:
        notes = failures
    else:
        notes = [f"all {applicable} applicable argument checks satisfied"]
    return SubScore(
        name="argument_constraints",
        value=_ratio(satisfied, applicable),
        evidence=evidence,
        notes=notes,
    )


def ordering(view: _View, reference: TaskReference) -> SubScore:
    """Satisfied rules / rules. ``A before B`` holds if the first successful A precedes the
    first B call. A rule whose ``after`` is never called holds; with ``optional_first`` a
    rule whose ``before`` is never called holds too."""
    rules = reference.workflow.ordering
    satisfied = 0
    evidence: list[str] = []
    notes: list[str] = []
    for rule in rules:
        before_calls = view.calls_of(rule.before)
        after_calls = view.calls_of(rule.after)
        first_ok = next((c for c in before_calls if _ok(c)), None)
        first_after = after_calls[0] if after_calls else None
        for e in (first_ok, first_after):
            if e is not None and e.event_id not in evidence:
                evidence.append(e.event_id)
        label = f"{rule.before} before {rule.after}"
        if first_after is None:
            satisfied += 1
            notes.append(f"{label}: holds, {rule.after} never called")
        elif rule.optional_first and not before_calls:
            satisfied += 1
            notes.append(f"{label}: holds, optional {rule.before} not used")
        elif first_ok is None:
            notes.append(
                f"{label}: violated, no successful {rule.before} before event "
                f"{first_after.event_id}"
            )
        elif view.index[first_ok.event_id] < view.index[first_after.event_id]:
            satisfied += 1
            notes.append(f"{label}: holds ({first_ok.event_id} < {first_after.event_id})")
        else:
            notes.append(
                f"{label}: violated, first {rule.after} in event {first_after.event_id} "
                f"precedes first successful {rule.before} in event {first_ok.event_id}"
            )
    evidence.sort(key=lambda i: view.index[i])
    return SubScore(
        name="ordering",
        value=_ratio(satisfied, len(rules)),
        evidence=evidence,
        notes=notes or ["no ordering rules"],
    )


def forbidden_tools(view: _View, reference: TaskReference) -> SubScore:
    """1 if no forbidden capability was called (any status), else 0."""
    forbidden = set(reference.workflow.forbidden)
    hits = [c for c in view.tool_calls if c.capability in forbidden]
    notes = [f"forbidden {c.capability} called in event {c.event_id}" for c in hits]
    return SubScore(
        name="forbidden_tools",
        value=0.0 if hits else 1.0,
        evidence=[c.event_id for c in hits],
        notes=notes or ["no forbidden capability called"],
    )


def recovery(view: _View, reference: TaskReference) -> SubScore:
    """1 - (sum of penalties / number of agent and tool errors); 1 with no errors.

    Penalty 1 for an unrecovered error, ``recovered_penalty`` (default 0.25) for a recovered
    one. Recovered = a later successful call of the same capability. Errors on events with
    no capability (an unknown tool, a guard stop, a free-standing error) cannot be
    recovered. Budget and infra errors do not count.
    """
    penalty_recovered = float(reference.workflow.recovery.get("recovered_penalty", 0.25))
    errors = [
        e for e in view.events if e.error is not None and e.error.source in SCORED_ERROR_SOURCES
    ]
    total = 0.0
    evidence: list[str] = []
    notes: list[str] = []
    for e in errors:
        assert e.error is not None
        evidence.append(e.event_id)
        fix = None
        if isinstance(e, ToolCall) and e.capability is not None:
            fix = next(
                (
                    c
                    for c in view.calls_of(e.capability)
                    if _ok(c) and view.index[c.event_id] > view.index[e.event_id]
                ),
                None,
            )
        if fix is not None:
            total += penalty_recovered
            evidence.append(fix.event_id)
            notes.append(
                f"{e.error.source}/{e.error.kind} in event {e.event_id} recovered by "
                f"event {fix.event_id}"
            )
        else:
            total += 1.0
            notes.append(f"{e.error.source}/{e.error.kind} in event {e.event_id} not recovered")
    value = 1.0 if not errors else max(0.0, 1.0 - total / len(errors))
    return SubScore(
        name="recovery",
        value=value,
        evidence=sorted(dict.fromkeys(evidence), key=lambda i: view.index[i]),
        notes=notes or ["no agent or tool errors"],
    )


def step_efficiency(view: _View, reference: TaskReference) -> SubScore:
    """1 up to ``expected_steps``, falling linearly to 0 at ``step_limit``."""
    expected = reference.workflow.expected_steps
    limit = reference.workflow.step_limit
    steps = len(view.model_calls)
    if steps <= expected:
        value = 1.0
    elif steps >= limit or limit <= expected:
        value = 0.0
    else:
        value = (limit - steps) / (limit - expected)
    return SubScore(
        name="step_efficiency",
        value=value,
        evidence=[m.event_id for m in view.model_calls],
        notes=[f"{steps} steps (expected {expected}, limit {limit})"],
    )


@register("evaluator", "workflow@1")
@register("evaluator", "workflow")
class WorkflowEvaluatorV1(_WorkflowEvaluator):
    """v1: all eight sub-scores of architecture §10.1."""

    version = "1"

    def subscores(self, view: _View, reference: TaskReference) -> list[SubScore]:
        return [
            tool_call_validity(view),
            argument_constraints(view, reference),
            required_coverage(view, reference),
            ordering(view, reference),
            forbidden_tools(view, reference),
            recovery(view, reference),
            step_efficiency(view, reference),
            done_condition(view, reference),
        ]


def resolve_workflow(version: str | None = None) -> type:
    """Return the workflow evaluator class for ``version`` (None = latest)."""
    return resolve("evaluator", "workflow" if version is None else f"workflow@{version}")
