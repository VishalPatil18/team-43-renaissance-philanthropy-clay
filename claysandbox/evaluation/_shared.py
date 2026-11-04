"""Shared evaluator provenance and infra-event filtering."""

from pydantic import BaseModel

from claysandbox.contracts.manifest import ComponentRef
from claysandbox.contracts.trace import AnyEvent, Trace


def evaluator_ref(name: str, version: str, params: BaseModel) -> ComponentRef:
    return ComponentRef(kind="evaluator", name=name, version=version, params=params.model_dump())


def scored_events(trace: Trace) -> list[AnyEvent]:
    """Infra failures cannot change an evaluator's score (FR-4.4)."""
    return [e for e in trace.events if not (e.error is not None and e.error.source == "infra")]
