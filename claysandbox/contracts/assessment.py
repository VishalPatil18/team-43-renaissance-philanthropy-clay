"""Assessment contract (architecture §7.5). Owner: WS4 (Barath).

An ``Assessment`` is one evaluator's judgment of one run. Workflow, output and process
assessments are kept apart: output metrics never feed a workflow composite (FR-4.7).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .ids import new_id
from .manifest import ComponentRef, RunManifest
from .task import TaskReference
from .trace import Trace

SCHEMA_VERSION = "1.0"

EvaluatorKind = Literal["workflow", "output", "process"]


class SubScore(BaseModel):
    name: str
    value: float = Field(ge=0.0, le=1.0)
    weight: float = 1.0
    evidence: list[str] = Field(default_factory=list)  # event IDs (FR-4.2)
    notes: list[str] = Field(default_factory=list)  # one-line human reasons


class Assessment(BaseModel):
    schema_version: str = SCHEMA_VERSION
    assessment_id: str = Field(default_factory=new_id)
    run_id: str
    evaluator: ComponentRef  # name + version + params (FR-4.8)
    kind: EvaluatorKind
    task_reference_version: str
    composite: float | None = None
    subscores: list[SubScore] = Field(default_factory=list)
    metrics: dict[str, float] = Field(default_factory=dict)
    success: bool | None = None  # workflow evaluator only (DD-042)
    repeats: list[float] | None = None  # LLM evaluator: the k composite scores
    evidence: list[str] = Field(default_factory=list)  # event IDs for metric-level evidence
    notes: list[str] = Field(default_factory=list)  # e.g. a parse error, skipped reason
    cost_usd: float = 0.0  # evaluation cost, not agent cost
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    def stable_json(self) -> str:
        """JSON without the fields that differ between identical evaluations (DD-035)."""
        return self.model_dump_json(exclude={"assessment_id", "created_at"})


@runtime_checkable
class Evaluator(Protocol):
    """Scores one run. Deterministic evaluators are pure: no I/O, clock or randomness."""

    name: str
    version: str
    kind: EvaluatorKind
    deterministic: bool

    def assess(
        self, trace: Trace, manifest: RunManifest, reference: TaskReference
    ) -> Assessment: ...
