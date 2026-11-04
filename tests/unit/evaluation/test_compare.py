import numpy as np
import pytest

from claysandbox.contracts.assessment import Assessment, SubScore
from claysandbox.contracts.manifest import ComponentRef, RunManifest
from claysandbox.contracts.stats import MeasurementComparison, RunRow
from claysandbox.evaluation.compare import (
    build_eval_report_content,
    compare_evaluators,
    rows_from_records,
)


def _ev(name: str, kind: str = "evaluator") -> ComponentRef:
    return ComponentRef(kind=kind, name=name, version="1")


def _assess(run_id, kind, name, **kw) -> Assessment:
    return Assessment(
        run_id=run_id, evaluator=_ev(name), kind=kind, task_reference_version="v1", **kw
    )


def test_rows_from_records_maps_assessments_and_totals_to_metrics():
    manifests = [
        RunManifest(run_id="r1", task_instance_id="t1", config_name="base", trial_index=2),
        RunManifest(run_id="r2", task_instance_id="t1", config_name="base"),
    ]
    assessments = [
        _assess(
            "r1",
            "workflow",
            "rules",
            composite=0.8,
            success=True,
            subscores=[SubScore(name="order", value=1.0), SubScore(name="args", value=0.5)],
        ),
        _assess("r1", "output", "geo", metrics={"iou": 0.7}),
        _assess("r1", "process", "proc", composite=0.6),
    ]
    rows = rows_from_records(
        manifests,
        assessments,
        {"r1": "completed", "r2": "infra_error"},
        totals={"r1": {"steps": 7, "wall_ms": 1200, "cost_usd": 0.03, "errors": 1, "tokens": 9}},
    )
    r1, r2 = sorted(rows, key=lambda r: r.run_id)
    assert (r1.config_name, r1.task_instance_id, r1.trial_index) == ("base", "t1", 2)
    assert r1.state == "completed" and r1.success is True
    assert r1.metrics == {
        "workflow.composite": 0.8,
        "workflow.order": 1.0,
        "workflow.args": 0.5,
        "output.iou": 0.7,
        "process.composite": 0.6,
        "steps": 7.0,
        "latency_ms": 1200.0,
        "cost_usd": 0.03,
        "errors": 1.0,
    }
    assert r2.state == "infra_error" and r2.metrics == {} and r2.success is None


def test_rows_from_records_defaults_to_first_evaluator_and_allows_primary_override():
    manifests = [RunManifest(run_id="r1", task_instance_id="t1", config_name="base")]
    assessments = [
        _assess("r1", "workflow", "rules", composite=0.8),
        _assess("r1", "workflow", "llm", composite=0.4),
    ]
    (default,) = rows_from_records(manifests, assessments, {"r1": "completed"})
    assert default.metrics["workflow.composite"] == 0.8
    (row,) = rows_from_records(
        manifests, assessments, {"r1": "completed"}, primary={"workflow": "llm"}
    )
    assert row.metrics["workflow.composite"] == 0.4


def test_compare_evaluators_reports_agreement_on_shared_runs():
    rules = [
        _assess(f"r{i}", "workflow", "rules", composite=c)
        for i, c in enumerate([0.1, 0.4, 0.6, 0.9])
    ]
    llm = [
        _assess("r0", "workflow", "llm", composite=0.2, repeats=[0.1, 0.2, 0.3]),
        _assess("r1", "workflow", "llm", composite=0.3, repeats=[0.3, 0.3, 0.3]),
        _assess("r2", "workflow", "llm", composite=0.7, repeats=[0.6, 0.8, 0.7]),
        _assess("r3", "workflow", "llm", composite=0.8, repeats=[0.7, 0.9, 0.8]),
        _assess("r9", "workflow", "llm", composite=0.0),  # not scored by rules: ignored
    ]
    mc = compare_evaluators({"rules": rules, "llm": llm})
    assert mc.kind == "evaluator"
    assert mc.subjects == ["llm", "rules"]
    assert mc.n_runs == 4
    assert mc.values["spearman"] == pytest.approx(1.0)  # same ranking
    # |0.1-0.2| + |0.4-0.3| + |0.6-0.7| + |0.9-0.8| = 0.4, over 4 runs
    assert mc.values["mean_abs_diff"] == pytest.approx(0.1)
    # spreads (max - min): 0.2, 0, 0.2, 0.2 (r9 has no repeats)
    assert mc.values["llm_self_agreement_mean_spread"] == pytest.approx(0.15)


def test_compare_evaluators_with_reversed_ranking_and_no_repeats():
    a = [_assess(f"r{i}", "workflow", "a", composite=float(i)) for i in range(5)]
    b = [_assess(f"r{i}", "workflow", "b", composite=float(-i)) for i in range(5)]
    mc = compare_evaluators({"a": a, "b": b})
    assert mc.values["spearman"] == pytest.approx(-1.0)
    assert mc.values["llm_self_agreement_mean_spread"] is None


def test_compare_evaluators_notes_when_too_few_shared_runs():
    mc = compare_evaluators(
        {
            "a": [_assess("r1", "workflow", "a", composite=0.5)],
            "b": [_assess("r2", "workflow", "b", composite=0.5)],
        }
    )
    assert mc.n_runs == 0
    assert mc.values["spearman"] is None and mc.values["mean_abs_diff"] is None
    assert mc.notes


# --- eval report content -------------------------------------------------------------------

VARIANTS = {
    "sonnet": {"model": {"name": "claude-sonnet"}},
    "converse": {"harness": {"name": "converse_loop"}},
    "t0": {"toolset": {"name": "T0"}},
}


def _fake_eval(n_instances: int, seed: int = 0) -> list[RunRow]:
    """4 configs x n instances x 3 runs. Planted: sonnet +0.2 composite, converse -0.2
    composite and +5 steps, t0 no effect. One t0 run is an infra error."""
    rng = np.random.default_rng(seed)
    difficulty = rng.normal(0.5, 0.15, size=n_instances)
    planted = {"base": (0.0, 0.0), "sonnet": (0.2, 0.0), "converse": (-0.2, 5.0), "t0": (0.0, 0.0)}
    rows = []
    for config, (d_comp, d_steps) in planted.items():
        for i in range(n_instances):
            for t in range(3):
                comp = difficulty[i] + d_comp + rng.normal(0, 0.02)
                state = "infra_error" if (config == "t0" and i == 0 and t == 0) else "completed"
                rows.append(
                    RunRow(
                        run_id=f"{config}-{i}-{t}",
                        config_name=config,
                        task_instance_id=f"i{i}",
                        trial_index=t,
                        state=state,
                        success=bool(comp > 0.5),
                        metrics={
                            "workflow.composite": float(comp),
                            "steps": float(10 + i + d_steps + rng.integers(0, 2)),
                        },
                    )
                )
    return rows


def _verdict(report, variant, metric):
    (c,) = [c for c in report.stats.comparisons if c.variant == variant and c.metric == metric]
    return c


def test_fake_eval_report_has_every_section():
    rows = _fake_eval(6)
    evaluator_cmp = compare_evaluators(
        {
            "a": [
                _assess("base-0-0", "workflow", "a", composite=0.1),
                _assess("base-0-1", "workflow", "a", composite=0.5),
            ],
            "b": [
                _assess("base-0-0", "workflow", "b", composite=0.2),
                _assess("base-0-1", "workflow", "b", composite=0.6),
            ],
        }
    )
    tracer_cmp = MeasurementComparison(kind="tracer", subjects=["jsonl", "otel"], n_runs=3)
    report = build_eval_report_content(
        "ev1",
        rows,
        "base",
        VARIANTS,
        seed=1,
        iterations=1000,
        tracer_comparison=tracer_cmp,
        evaluator_comparison=evaluator_cmp,
    )
    assert report.eval_id == "ev1" and report.baseline == "base"
    assert [c.config_name for c in report.stats.configs] == ["base", "converse", "sonnet", "t0"]
    assert report.stats.seed == 1 and report.stats.bootstrap_iterations == 1000
    assert {v.variant: v.axis for v in report.variants} == {
        "sonnet": "model",
        "converse": "harness",
        "t0": "toolset",
    }
    assert report.exclusions == {"base": {}, "converse": {}, "sonnet": {}, "t0": {"infra_error": 1}}
    assert report.paired_instances == [f"i{i}" for i in range(6)]
    assert len(report.run_links["t0"]) == 18 and "t0-0-0" in report.run_links["t0"]
    assert set(report.verdicts) == {"sonnet", "converse", "t0"}
    assert report.tracer_comparison == tracer_cmp
    assert report.evaluator_comparison is not None
    assert report.evaluator_comparison.values["mean_abs_diff"] == pytest.approx(0.1)
    for c in report.stats.comparisons:
        assert c.axis == {"sonnet": "model", "converse": "harness", "t0": "toolset"}[c.variant]


def test_fake_eval_with_six_instances_cannot_pass_holm_and_says_so():
    # 3 variants: the smallest exact sign-flip p over 6 instances is 2/64, x3 after Holm.
    report = build_eval_report_content("ev1", _fake_eval(6), "base", VARIANTS, iterations=1000)
    sonnet = _verdict(report, "sonnet", "workflow.composite")
    assert sonnet.effect == pytest.approx(0.2, abs=0.03)
    assert sonnet.ci_low > 0
    assert sonnet.p_value == pytest.approx(2 / 64)
    assert sonnet.p_adjusted == pytest.approx(3 * 2 / 64)
    assert sonnet.verdict.startswith("No meaningful difference on workflow.composite (p=0.0938")
    assert any("smallest possible p" in w for w in sonnet.warnings)
    assert any("fewer than 10" in w for w in sonnet.warnings)
    assert "CI includes 0" in _verdict(report, "t0", "workflow.composite").verdict


def test_fake_eval_with_twelve_instances_gives_planted_verdicts():
    report = build_eval_report_content("ev1", _fake_eval(12), "base", VARIANTS, iterations=2000)
    assert _verdict(report, "sonnet", "workflow.composite").verdict.startswith(
        "sonnet is better on workflow.composite by 0."
    )
    assert _verdict(report, "converse", "workflow.composite").verdict.startswith(
        "converse is worse on workflow.composite by 0."
    )
    steps = _verdict(report, "converse", "steps")
    assert steps.higher_is_better is False and steps.effect == pytest.approx(5, abs=0.5)
    assert steps.verdict.startswith("converse is worse on steps by ")
    assert _verdict(report, "t0", "workflow.composite").verdict.startswith(
        "No meaningful difference on workflow.composite"
    )
    assert any(
        v.startswith("sonnet is better on workflow.composite") for v in report.verdicts["sonnet"]
    )


def test_multi_axis_variant_is_mixed_with_a_warning():
    rows = [r for r in _fake_eval(6) if r.config_name in ("base", "sonnet")]
    report = build_eval_report_content(
        "ev1",
        rows,
        "base",
        {"sonnet": {"model": {"name": "s"}, "harness": {"name": "converse_loop"}}},
        iterations=200,
    )
    (axis,) = report.variants
    assert axis.axis == "mixed" and axis.changed == ["harness", "model"]
    assert axis.warning and "more than one" in axis.warning
    assert any("more than one" in w for w in report.warnings)


def test_paired_comparisons_use_instances_complete_in_each_pair():
    rows = [
        r for r in _fake_eval(6) if not (r.config_name == "converse" and r.task_instance_id == "i5")
    ]
    report = build_eval_report_content("ev1", rows, "base", VARIANTS, iterations=200)
    assert report.paired_instances == [f"i{i}" for i in range(5)]
    assert _verdict(report, "sonnet", "workflow.composite").n_instances == 6
    assert _verdict(report, "converse", "workflow.composite").n_instances == 5
    assert report.paired_instances_by_variant["sonnet"] == [f"i{i}" for i in range(6)]
    assert any("base vs converse" in w and "i5" in w for w in report.warnings)
    assert not any("base vs sonnet" in w for w in report.warnings)
    assert any("1 task instance" in w for w in report.warnings)


@pytest.mark.parametrize("primary, expected", [(None, 0.8), ({"workflow": "workflow@0"}, 0.4)])
def test_report_builds_evaluator_comparison_and_selects_primary_in_spec_order(primary, expected):
    manifests = [
        RunManifest(run_id=f"r{i}", task_instance_id=f"t{i}", config_name="base") for i in range(2)
    ]
    old = [_assess(f"r{i}", "workflow", "workflow", composite=0.4) for i in range(2)]
    for a in old:
        a.evaluator.version = "0"
    new = [_assess(f"r{i}", "workflow", "workflow", composite=0.8) for i in range(2)]
    report = build_eval_report_content(
        "ev",
        None,
        "base",
        {},
        manifests=manifests,
        assessments=[*old, *new],
        run_states={"r0": "completed", "r1": "completed"},
        evaluator_order=[_ev("workflow"), old[0].evaluator],
        primary=primary,
        iterations=20,
    )
    assert report.stats.configs[0].metrics["workflow.composite"].estimate == expected
    assert report.evaluator_comparison.subjects == ["workflow@0", "workflow@1"]
    assert report.evaluator_comparison.values["mean_abs_diff"] == pytest.approx(0.4)


def test_report_can_request_single_evaluator_self_agreement():
    assessments = [_assess("r1", "process", "judge", composite=0.5, repeats=[0.3, 0.7])]
    report = build_eval_report_content(
        "ev",
        [RunRow(run_id="r1", config_name="base", task_instance_id="t1", state="completed")],
        "base",
        {},
        assessments=assessments,
        compare_evaluators_requested=True,
        iterations=20,
    )
    assert report.evaluator_comparison.subjects == ["judge@1"]
    assert report.evaluator_comparison.values["llm_self_agreement_mean_spread"] == pytest.approx(
        0.4
    )


def test_report_keeps_evaluator_comparisons_separate_by_kind():
    assessments = [
        _assess("r1", kind, name, composite=value)
        for kind, name, value in [
            ("workflow", "a", 0.2),
            ("workflow", "b", 0.4),
            ("output", "c", 1.0),
        ]
    ]
    report = build_eval_report_content(
        "ev",
        [RunRow(run_id="r1", config_name="base", task_instance_id="t1", state="completed")],
        "base",
        {},
        assessments=assessments,
        iterations=20,
    )
    assert report.evaluator_comparison.subjects == ["a@1", "b@1"]


def test_report_primary_output_dispatcher_keeps_assessments_from_all_templates():
    manifests = [
        RunManifest(run_id=f"r{i}", task_instance_id=f"T{i}@aoi", config_name="base")
        for i in (1, 2)
    ]
    assessments = [
        _assess("r1", "output", "output.t1", composite=0.8),
        _assess("r2", "output", "output.t2", composite=0.6),
    ]
    report = build_eval_report_content(
        "ev",
        None,
        "base",
        {},
        manifests=manifests,
        assessments=assessments,
        run_states={"r1": "completed", "r2": "completed"},
        evaluator_order=[_ev("output")],
        iterations=20,
    )
    metric = report.stats.configs[0].metrics["output.composite"]
    assert metric.n == 2
    assert metric.estimate == pytest.approx(0.7)
    assert report.evaluator_comparison is None


def test_pair_warning_includes_instances_excluded_on_both_sides():
    rows = _fake_eval(6)
    rows += [
        RunRow(
            run_id=f"{name}-excluded",
            config_name=name,
            task_instance_id="excluded",
            state="infra_error",
        )
        for name in ("base", "sonnet")
    ]
    report = build_eval_report_content("ev", rows, "base", VARIANTS, iterations=20)
    assert any("base vs sonnet" in w and "excluded" in w for w in report.warnings)
    assert _verdict(report, "sonnet", "workflow.composite").n_instances == 6


def test_report_compares_multiple_kinds_without_pooling_their_scores():
    assessments = [
        _assess(run_id, "workflow", name, composite=value)
        for run_id in ("r1", "r2")
        for name, value in (("a", 0.2), ("b", 0.4))
    ] + [
        _assess(run_id, "output", name, composite=value)
        for run_id in ("r1", "r3")
        for name, value in (("c", 0.9), ("d", None))
    ]
    report = build_eval_report_content(
        "ev",
        [RunRow(run_id="r1", config_name="base", task_instance_id="t1", state="completed")],
        "base",
        {},
        assessments=assessments,
        iterations=20,
    )
    comparison = report.evaluator_comparison
    assert comparison.n_runs == 2
    assert comparison.values == {}
    by_kind = comparison.details["by_kind"]
    assert by_kind["workflow"]["values"]["mean_abs_diff"] == pytest.approx(0.2)
    assert by_kind["output"]["n_runs"] == 0
