"""Metric names shared by report rows and planted-trace validation."""

from claysandbox.contracts.assessment import Assessment


def metric_key(kind: str, name: str) -> str:
    return f"{kind}.{name}"


def assessment_values(assessment: Assessment) -> dict[str, float | None]:
    kind = assessment.kind
    values: dict[str, float | None] = {
        metric_key(kind, "composite"): assessment.composite,
    }
    values.update({metric_key(kind, s.name): s.value for s in assessment.subscores})
    values.update({metric_key(kind, k): v for k, v in assessment.metrics.items()})
    return values
