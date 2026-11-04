"""Comparisons and eval report content (architecture §8.5, §11, FR-9, DD-026).

Pure functions over manifests, Assessments and ``RunRow``s; the store adapter is the caller's.
"""

from __future__ import annotations

import itertools
from collections import defaultdict
from collections.abc import Mapping, Sequence
from typing import Any

import numpy as np
from scipy.stats import spearmanr

from claysandbox.contracts.assessment import Assessment, EvaluatorKind
from claysandbox.contracts.manifest import ComponentRef, RunManifest
from claysandbox.contracts.stats import (
    EXCLUDED_STATES,
    EvalReportContent,
    MeasurementComparison,
    RunRow,
    RunState,
    VariantAxis,
)
from claysandbox.evaluation._keys import assessment_values
from claysandbox.evaluation.stats import DEFAULT_ITERATIONS, compute_stats

# Run totals key -> RunRow metric name.
_TOTALS = {
    "steps": "steps",
    "wall_ms": "latency_ms",
    "latency_ms": "latency_ms",
    "cost_usd": "cost_usd",
    "errors": "errors",
}


def _evaluator_label(ref: ComponentRef) -> str:
    return f"{ref.name}@{ref.version}" if ref.version else ref.name


def _in_spec_order(
    assessments: Sequence[Assessment], evaluator_order: Sequence[ComponentRef]
) -> list[Assessment]:
    """Group concrete dispatcher results under their configured evaluator, on copies only."""
    grouped = []
    for assessment in assessments:
        recorded = assessment.evaluator
        configured = next(
            (
                ref
                for ref in evaluator_order
                if ref.version == recorded.version
                and (ref.name == recorded.name or recorded.name.startswith(ref.name + "."))
            ),
            recorded,
        )
        grouped.append(assessment.model_copy(update={"evaluator": configured}))
    order = {_evaluator_label(ref): i for i, ref in enumerate(evaluator_order)}
    return sorted(grouped, key=lambda a: order.get(_evaluator_label(a.evaluator), len(order)))


def _pick(
    assessments: Sequence[Assessment], kind: EvaluatorKind, primary: Mapping[str, str]
) -> dict[str, Assessment]:
    """Select one evaluator per kind, defaulting to its first occurrence in spec order."""
    of_kind = [a for a in assessments if a.kind == kind]
    if kind in primary:
        selected = primary[kind]
        of_kind = [
            a for a in of_kind if selected in (a.evaluator.name, _evaluator_label(a.evaluator))
        ]
        if not of_kind:
            raise ValueError(f"primary {kind} evaluator {selected!r} has no assessments")
        if len({_evaluator_label(a.evaluator) for a in of_kind}) > 1:
            raise ValueError(f"primary {kind} evaluator {selected!r} needs a version")
    if not of_kind:
        return {}
    label = _evaluator_label(of_kind[0].evaluator)
    return {a.run_id: a for a in of_kind if _evaluator_label(a.evaluator) == label}


def rows_from_records(
    manifests: Sequence[RunManifest],
    assessments: Sequence[Assessment],
    run_states: Mapping[str, RunState],
    totals: Mapping[str, Mapping[str, Any]] | None = None,
    primary: Mapping[str, str] | None = None,
) -> list[RunRow]:
    """Build one ``RunRow`` per manifest.

    Workflow composite -> ``workflow.composite``, sub-scores -> ``workflow.<name>``, output
    metrics -> ``output.<name>``, process composite -> ``process.composite``; ``totals``
    (from ``run_end``) adds steps, latency_ms (``wall_ms``), cost_usd and errors. ``primary``
    names the evaluator (name or name@version) per kind; by default the first assessment
    of each kind selects it. Supply assessments in spec order.
    """
    primary = primary or {}
    workflow = _pick(assessments, "workflow", primary)
    output = _pick(assessments, "output", primary)
    process = _pick(assessments, "process", primary)
    totals = totals or {}
    rows = []
    for m in manifests:
        if m.run_id not in run_states:
            raise ValueError(f"no run state for run {m.run_id}")
        metrics: dict[str, float] = {}
        success = None
        for selected in (workflow, output, process):
            if (assessment := selected.get(m.run_id)) is not None:
                metrics.update(
                    {k: v for k, v in assessment_values(assessment).items() if v is not None}
                )
                if assessment.kind == "workflow":
                    success = assessment.success
        for key, value in totals.get(m.run_id, {}).items():
            if key in _TOTALS and value is not None:
                metrics[_TOTALS[key]] = float(value)
        rows.append(
            RunRow(
                run_id=m.run_id,
                config_name=m.config_name,
                task_instance_id=m.task_instance_id,
                trial_index=m.trial_index,
                state=run_states[m.run_id],
                success=success,
                metrics=metrics,
            )
        )
    return rows


def compare_evaluators(
    assessments_by_evaluator: Mapping[str, Sequence[Assessment]],
) -> MeasurementComparison:
    """Agreement between evaluators re-scoring the same runs (DD-026, FR-9.5).

    Spearman correlation and mean absolute difference of composites on the runs every
    evaluator scored (averaged over evaluator pairs when there are more than two), plus the
    LLM evaluator's self-agreement: the mean over runs of max - min of its k repeats.
    """
    subjects = sorted(assessments_by_evaluator)
    composites = {
        name: {a.run_id: a.composite for a in items if a.composite is not None}
        for name, items in assessments_by_evaluator.items()
    }
    shared = sorted(set.intersection(*(set(c) for c in composites.values()))) if subjects else []
    notes: list[str] = []
    pairs: list[dict[str, Any]] = []
    for x, y in itertools.combinations(subjects, 2):
        a = np.array([composites[x][r] for r in shared], dtype=float)
        b = np.array([composites[y][r] for r in shared], dtype=float)
        rho: float | None = None
        mad: float | None = None
        if len(shared) >= 2:
            mad = float(np.mean(np.abs(a - b)))
            if np.ptp(a) > 0 and np.ptp(b) > 0:
                rho = float(spearmanr(a, b).statistic)
            else:
                notes.append(f"Spearman undefined for {x} vs {y}: a composite is constant.")
        pairs.append({"a": x, "b": y, "spearman": rho, "mean_abs_diff": mad})
    if len(shared) < 2:
        notes.append(f"Only {len(shared)} runs scored by every evaluator; agreement not computed.")

    def _mean(key: str) -> float | None:
        vals = [p[key] for p in pairs if p[key] is not None]
        return float(np.mean(vals)) if vals else None

    spreads: dict[str, float] = {}
    for name, items in assessments_by_evaluator.items():
        ranges = [max(a.repeats) - min(a.repeats) for a in items if a.repeats]
        if ranges:
            spreads[name] = float(np.mean(ranges))
    spread = float(np.mean(list(spreads.values()))) if spreads else None
    return MeasurementComparison(
        kind="evaluator",
        subjects=subjects,
        n_runs=len(shared),
        values={
            "spearman": _mean("spearman"),
            "mean_abs_diff": _mean("mean_abs_diff"),
            "llm_self_agreement_mean_spread": spread,
        },
        details={"pairs": pairs, "self_agreement_by_evaluator": spreads, "run_ids": shared},
        notes=notes,
    )


def _report_evaluator_comparison(
    assessments: Sequence[Assessment], requested: bool
) -> MeasurementComparison | None:
    groups: dict[str, dict[str, list[Assessment]]] = {}
    for assessment in assessments:
        group = groups.setdefault(assessment.kind, {})
        group.setdefault(_evaluator_label(assessment.evaluator), []).append(assessment)
    comparisons = {
        kind: compare_evaluators(group)
        for kind, group in groups.items()
        if requested or len(group) > 1
    }
    if not comparisons:
        return None
    if len(comparisons) == 1:
        return next(iter(comparisons.values()))
    # Different evaluator kinds measure different things; never pool their agreement scores.
    return MeasurementComparison(
        kind="evaluator",
        subjects=sorted({s for c in comparisons.values() for s in c.subjects}),
        n_runs=len(
            set().union(
                *(
                    set.intersection(
                        *(
                            {a.run_id for a in items if a.composite is not None}
                            for items in groups[kind].values()
                        )
                    )
                    for kind in comparisons
                )
            )
        ),
        details={"by_kind": {k: c.model_dump() for k, c in comparisons.items()}},
        notes=["Agreement is reported separately by evaluator kind."],
    )


# Override key -> agent axis (DD-026). Unknown keys count as an axis of their own.
_AXIS_KEYS = {
    "model": "model",
    "harness": "harness",
    "toolset": "toolset",
    "tool_set": "toolset",
    "tools": "toolset",
    "tracer": "tracer",
}


def variant_axis(variant: str, overrides: Mapping[str, Any]) -> VariantAxis:
    """The axis a variant changes; more than one axis is ``mixed`` with a warning (FR-9.3)."""
    changed = sorted(overrides)
    axes = sorted({_AXIS_KEYS.get(k, k) for k in changed})
    if not axes:
        return VariantAxis(
            variant=variant,
            axis=None,
            changed=[],
            warning=f"Variant {variant} has no overrides; it is the baseline configuration.",
        )
    if len(axes) > 1:
        return VariantAxis(
            variant=variant,
            axis="mixed",
            changed=changed,
            warning=(
                f"Variant {variant} changes more than one axis ({', '.join(axes)}); "
                "its differences cannot be put down to a single change."
            ),
        )
    return VariantAxis(variant=variant, axis=axes[0], changed=changed)


def build_eval_report_content(
    eval_id: str,
    rows: Sequence[RunRow] | None,
    baseline: str,
    variants: Mapping[str, Mapping[str, Any]],
    *,
    seed: int = 0,
    iterations: int = DEFAULT_ITERATIONS,
    alpha: float = 0.05,
    tracer_comparison: MeasurementComparison | None = None,
    evaluator_comparison: MeasurementComparison | None = None,
    manifests: Sequence[RunManifest] | None = None,
    assessments: Sequence[Assessment] = (),
    run_states: Mapping[str, RunState] | None = None,
    totals: Mapping[str, Mapping[str, Any]] | None = None,
    evaluator_order: Sequence[ComponentRef] = (),
    primary: Mapping[str, str] | None = None,
    compare_evaluators_requested: bool = False,
) -> EvalReportContent:
    """Eval report content for a baseline-plus-variants comparison (arch §8.5, FR-9.4).

    ``variants`` maps each variant config name to its overrides of the baseline. Paired
    comparisons use only task instances complete (at least one non-excluded run) in both
    the baseline and that variant.

    Pass ``rows=None`` plus manifests, assessments and run_states to build stats rows here.
    ``evaluator_order`` is the eval spec's evaluator list; absent it, assessment order is
    treated as spec order. ``primary`` overrides that default per kind. Assessments also
    enable automatic agreement reports for multiple evaluators of the same kind, or an
    explicitly requested report (including a single judge's repeat agreement).
    """
    ordered = _in_spec_order(assessments, evaluator_order)
    if manifests is not None:
        if rows is not None:
            raise ValueError("pass rows or manifests, not both")
        if run_states is None:
            raise ValueError("run_states are required with manifests")
        rows = rows_from_records(manifests, ordered, run_states, totals, primary)
    if rows is None:
        raise ValueError("rows or manifests are required")
    if evaluator_comparison is None:
        evaluator_comparison = _report_evaluator_comparison(ordered, compare_evaluators_requested)
    axes = [variant_axis(v, o) for v, o in variants.items()]
    warnings = [a.warning for a in axes if a.warning]
    compared = [baseline, *variants]
    present = {r.config_name for r in rows}
    for name in compared:
        if name not in present:
            warnings.append(f"Configuration {name} has no runs.")
    complete: dict[str, set[str]] = defaultdict(set)
    seen: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        seen[r.config_name].add(r.task_instance_id)
        if r.state not in EXCLUDED_STATES:
            complete[r.config_name].add(r.task_instance_id)
    # Keep the all-config intersection as legacy report metadata only.
    paired = set.intersection(*(complete[n] for n in compared))
    paired_by_variant = {}
    for variant in variants:
        pair = complete[baseline] & complete[variant]
        paired_by_variant[variant] = sorted(pair)
        dropped = sorted((seen[baseline] | seen[variant]) - pair)
        if dropped:
            suffix = "" if len(dropped) == 1 else "s"
            warnings.append(
                f"{len(dropped)} task instance{suffix} not complete in both configurations "
                f"left out of {baseline} vs {variant}: {', '.join(dropped)}."
            )
    stats = compute_stats(
        rows,
        baseline,
        list(variants),
        seed=seed,
        iterations=iterations,
        alpha=alpha,
        axes={a.variant: a.axis for a in axes if a.axis is not None},
    )
    verdicts: dict[str, list[str]] = {v: [] for v in variants}
    for c in stats.comparisons:
        verdicts[c.variant].append(c.verdict)
    run_links: dict[str, list[str]] = defaultdict(list)
    for r in rows:
        run_links[r.config_name].append(r.run_id)
    return EvalReportContent(
        eval_id=eval_id,
        baseline=baseline,
        variants=axes,
        stats=stats,
        paired_instances=sorted(paired),
        paired_instances_by_variant=paired_by_variant,
        exclusions={c.config_name: c.excluded for c in stats.configs},
        verdicts=verdicts,
        run_links={k: sorted(v) for k, v in sorted(run_links.items())},
        tracer_comparison=tracer_comparison,
        evaluator_comparison=evaluator_comparison,
        warnings=warnings,
    )
