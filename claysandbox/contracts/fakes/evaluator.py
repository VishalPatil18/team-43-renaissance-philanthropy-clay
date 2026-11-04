"""ConstantEvaluator fake (owner: WS4). Gives every run the same workflow score."""

from __future__ import annotations

from pydantic import BaseModel

from claysandbox.contracts.assessment import Assessment, SubScore
from claysandbox.contracts.manifest import ComponentRef, RunManifest
from claysandbox.contracts.registry import register
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace


@register("evaluator", "constant")
class ConstantEvaluator:
    name = "constant"
    version = "1"
    kind = "workflow"
    deterministic = True

    class Params(BaseModel):
        value: float = 1.0

    def __init__(self, params: dict | None = None) -> None:
        self.params = self.Params(**(params or {}))

    def assess(self, trace: Trace, manifest: RunManifest, reference: TaskReference) -> Assessment:
        v = self.params.value
        return Assessment(
            run_id=manifest.run_id,
            evaluator=ComponentRef(
                kind="evaluator",
                name=self.name,
                version=self.version,
                params=self.params.model_dump(),
            ),
            kind="workflow",
            task_reference_version=reference.version,
            composite=v,
            subscores=[SubScore(name="constant", value=v)],
            success=v >= 0.5,
        )
