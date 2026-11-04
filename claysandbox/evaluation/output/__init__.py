"""Output evaluators T1-T5 and the generic ``output`` evaluator that dispatches on template."""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.assessment import Assessment, EvaluatorKind
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.registry import register, resolve
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace

from ._common import Params
from .t1 import T1Evaluator
from .t2 import T2Evaluator
from .t3 import T3Evaluator
from .t4 import T4Evaluator
from .t5 import T5Evaluator


def template_of(manifest: RunManifest, reference: TaskReference) -> str:
    """Template from ``<template>@<aoi>`` in the manifest, else ``reference.template``."""
    head = manifest.task_instance_id.split("@", 1)[0].strip()
    return (head or reference.template).upper()


@register("evaluator", "output@1")
@register("evaluator", "output")
class OutputDispatcher:
    name = "output"
    version = "1"
    kind: EvaluatorKind = "output"
    deterministic = True
    Params = Params

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = self.Params.model_validate(params or {})

    def assess(self, trace: Trace, manifest: RunManifest, reference: TaskReference) -> Assessment:
        template = template_of(manifest, reference).lower()
        try:
            cls = resolve("evaluator", f"output.{template}")
        except ConfigError:
            raise ConfigError(
                f"No output evaluator for template {template!r}", kind="unknown_component"
            ) from None
        return cls(self.params.model_dump()).assess(trace, manifest, reference)


__all__ = [
    "OutputDispatcher",
    "T1Evaluator",
    "T2Evaluator",
    "T3Evaluator",
    "T4Evaluator",
    "T5Evaluator",
]
