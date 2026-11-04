"""Shared machinery for the output evaluators (architecture §10.2, FR-4.6, FR-4.7).

An output evaluator parses the run's last ``final_output`` against ``reference.output_schema``,
then scores it against ``reference.output_reference``. It never sets ``success`` and never
reads workflow data. A parse failure scores 0 on every metric, with the error in ``notes`` and
the ``final_output`` event id in ``evidence``.
"""

from __future__ import annotations

from typing import Any, ClassVar

import jsonschema
from pydantic import BaseModel

from claysandbox.contracts.assessment import Assessment, EvaluatorKind
from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import FinalOutput, Trace
from claysandbox.evaluation._parsing import ParseError, load_json_value
from claysandbox.evaluation._shared import evaluator_ref


class Params(BaseModel):
    pass


def f1(precision: float, recall: float) -> float:
    return 0.0 if precision + recall == 0 else 2 * precision * recall / (precision + recall)


def precision_recall(matched: int, n_pred: int, n_ref: int) -> tuple[float, float]:
    """Precision and recall from counts. An empty side is vacuously 1.0 (nothing wrong / nothing
    missed); F1 still drops to 0 when exactly one side is empty."""
    p = 1.0 if n_pred == 0 else matched / n_pred
    r = 1.0 if n_ref == 0 else matched / n_ref
    return p, r


def id_list(value: Any, keys: tuple[str, ...], id_field: str | None = None) -> list[str]:
    """Pull a list of IDs out of ``value`` (a list, or a dict holding one under one of ``keys``).
    Entries are strings, or dicts carrying ``id_field``. IDs are trimmed and de-duplicated in
    order; matching stays case-sensitive."""
    if isinstance(value, dict):
        for k in keys:
            if k in value:
                value = value[k]
                break
        else:
            raise ParseError(f"none of the keys {list(keys)} found")
    if not isinstance(value, list):
        raise ParseError("expected a list of IDs")
    out: list[str] = []
    for e in value:
        if isinstance(e, dict) and id_field and id_field in e:
            e = e[id_field]
        if not isinstance(e, str):
            raise ParseError(f"ID entries must be strings, got {type(e).__name__}")
        s = e.strip()
        if s and s not in out:
            out.append(s)
    return out


class OutputEvaluator:
    """Base class. Subclasses set ``name`` and ``metric_names`` and implement ``score``."""

    name: str
    version: str = "1"
    kind: EvaluatorKind = "output"
    deterministic: bool = True
    metric_names: ClassVar[tuple[str, ...]]
    composite_metric: ClassVar[str]
    Params = Params

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = self.Params(**(params or {}))

    def score(
        self,
        output: Any,
        trace: Trace,
        manifest: RunManifest,
        reference: TaskReference,
        event_id: str,
    ) -> tuple[dict[str, float], list[str], list[str]]:
        """Return (metrics, notes, evidence). Raise ``ParseError`` for unusable output."""
        raise NotImplementedError

    def assess(self, trace: Trace, manifest: RunManifest, reference: TaskReference) -> Assessment:
        finals = [e for e in trace.events if isinstance(e, FinalOutput)]
        notes: list[str] = []
        evidence: list[str] = []
        metrics = {m: 0.0 for m in self.metric_names}
        event_id = ""
        try:
            if not finals:
                raise ParseError("no final_output event in the trace")
            final = finals[-1]
            event_id = final.event_id
            output = load_json_value(final.output)
            if reference.output_schema:
                try:
                    jsonschema.validate(output, reference.output_schema)
                except jsonschema.ValidationError as e:
                    raise ParseError(f"output does not match the schema: {e.message}") from e
            metrics, notes, evidence = self.score(output, trace, manifest, reference, event_id)
        except ParseError as e:
            metrics = {m: 0.0 for m in self.metric_names}
            notes = [f"parse error: {e}"]
            evidence = [event_id] if event_id else []
        return Assessment(
            run_id=trace.run_id,
            evaluator=evaluator_ref(self.name, self.version, self.params),
            kind="output",
            task_reference_version=reference.version,
            composite=metrics[self.composite_metric],
            metrics=metrics,
            evidence=evidence,
            notes=notes,
        )
