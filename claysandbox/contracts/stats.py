"""Statistics contracts (architecture §11, FR-10). Owner: WS4 (Barath).

Inputs are ``RunRow``s (one per run). Outputs are the per-configuration stats, paired
comparisons, measurement comparisons and the planted-trace validation report that the eval
report (WS5) renders.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, Field

RunState = Literal[
    "completed",
    "budget_stopped",
    "agent_failed",
    "infra_error",
    "infra_excluded",
    "skipped_eval_cap",
]
EXCLUDED_STATES: frozenset[str] = frozenset({"infra_excluded", "infra_error", "skipped_eval_cap"})


class RunRow(BaseModel):
    """One run's numbers, as the stats engine sees them."""

    run_id: str
    config_name: str
    task_instance_id: str
    trial_index: int = 0
    state: RunState
    success: bool | None = None
    metrics: dict[str, float] = Field(default_factory=dict)
    # e.g. workflow.composite, workflow.<subscore>, output.<metric>, process.composite,
    # steps, latency_ms, cost_usd, errors


class Interval(BaseModel):
    estimate: float | None
    low: float | None
    high: float | None
    n: int  # runs (rates) or task instances (bootstrap means)
    method: Literal["wilson", "cluster_bootstrap", "none"]


class ConfigStats(BaseModel):
    config_name: str
    runs_total: int
    runs_used: int
    excluded: dict[str, int] = Field(default_factory=dict)  # state -> count (FR-10.5)
    instances: int
    success_rate: Interval
    metrics: dict[str, Interval] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)


class PairedComparison(BaseModel):
    baseline: str
    variant: str
    axis: str | None = None  # model | harness | toolset | tracer | mixed
    metric: str
    n_instances: int
    effect: float | None  # mean(d_i), d_i = variant - baseline
    ci_low: float | None
    ci_high: float | None
    p_value: float | None
    p_adjusted: float | None  # Holm when > 2 comparisons, else = p_value
    test: Literal["sign_flip_exact", "sign_flip_random", "none"]
    higher_is_better: bool = True
    verdict: str
    warnings: list[str] = Field(default_factory=list)


class MeasurementComparison(BaseModel):
    kind: Literal["evaluator", "tracer"]
    subjects: list[str]  # evaluator or tracer names
    n_runs: int
    values: dict[str, float | None] = Field(default_factory=dict)
    # evaluator: spearman, mean_abs_diff, llm_self_agreement_mean_spread
    details: dict[str, object] = Field(default_factory=dict)
    notes: list[str] = Field(default_factory=list)


class FlawResult(BaseModel):
    template: str
    flaw: str
    expected_drops: list[str]
    detected: bool
    good_value: dict[str, float | None] = Field(default_factory=dict)
    bad_value: dict[str, float | None] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)  # expected drops that did not happen
    unchecked: list[str] = Field(default_factory=list)  # drops whose evaluator was not run
    notes: list[str] = Field(default_factory=list)


class ValidationReport(BaseModel):
    evaluators: list[str]
    flaws: list[FlawResult] = Field(default_factory=list)
    detection_rate: dict[str, float] = Field(default_factory=dict)  # per flaw type
    margin: float | None = None  # workflow mean(good composite) - mean(bad composite)
    margins: dict[str, float | None] = Field(default_factory=dict)  # per evaluator kind
    ci_halfwidth: float | None = None
    margin_exceeds_ci: bool | None = None
    llm_agreement: float | None = None
    notes: list[str] = Field(default_factory=list)


class StatsResult(BaseModel):
    seed: int
    bootstrap_iterations: int
    alpha: float = 0.05
    configs: list[ConfigStats] = Field(default_factory=list)
    comparisons: list[PairedComparison] = Field(default_factory=list)


class VariantAxis(BaseModel):
    """What a variant changes relative to the baseline, read from its overrides (FR-9.3)."""

    variant: str
    axis: str | None  # model | harness | toolset | tracer | mixed | another override key
    changed: list[str] = Field(default_factory=list)  # the override keys
    warning: str | None = None


class EvalReportContent(BaseModel):
    """Everything the eval report (WS5 renders it) needs, computed by WS4 (BAR-R2-04)."""

    eval_id: str
    baseline: str
    variants: list[VariantAxis] = Field(default_factory=list)
    stats: StatsResult  # per-config stats, paired comparisons, seed and iterations
    paired_instances: list[str] = Field(default_factory=list)  # complete in every config
    paired_instances_by_variant: dict[str, list[str]] = Field(default_factory=dict)
    exclusions: dict[str, dict[str, int]] = Field(default_factory=dict)  # config -> state -> n
    verdicts: dict[str, list[str]] = Field(default_factory=dict)  # variant -> verdict lines
    run_links: dict[str, list[str]] = Field(default_factory=dict)  # config -> run IDs
    tracer_comparison: MeasurementComparison | None = None
    evaluator_comparison: MeasurementComparison | None = None
    warnings: list[str] = Field(default_factory=list)
