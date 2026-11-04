import numpy as np
import pytest

from claysandbox.contracts.stats import RunRow
from claysandbox.evaluation.stats import (
    cluster_bootstrap_mean,
    compute_stats,
    holm_adjust,
    sign_flip_pvalue,
    wilson_interval,
)


@pytest.mark.parametrize(
    ("k", "n", "low", "high"),
    [
        (8, 10, 0.4902, 0.9433),
        (0, 10, 0.0, 0.2775),
        (10, 10, 0.7225, 1.0),
        (50, 100, 0.4038, 0.5962),
    ],
)
def test_wilson_matches_known_values(k, n, low, high):
    iv = wilson_interval(k, n)
    assert iv.method == "wilson"
    assert iv.n == n
    assert iv.estimate == pytest.approx(k / n)
    assert iv.low == pytest.approx(low, abs=1e-4)
    assert iv.high == pytest.approx(high, abs=1e-4)


def test_wilson_with_no_runs_has_no_estimate():
    iv = wilson_interval(0, 0)
    assert iv.estimate is None and iv.low is None and iv.high is None
    assert iv.method == "none"


def test_cluster_bootstrap_weights_instances_equally_not_runs():
    # Instance means are 2 and 10, so the estimate is 6 (pooling runs would give 4).
    iv = cluster_bootstrap_mean({"a": [1.0, 2.0, 3.0], "b": [10.0]}, iterations=2000, seed=1)
    assert iv.method == "cluster_bootstrap"
    assert iv.n == 2
    assert iv.estimate == pytest.approx(6.0)
    # Resampling two instances can only give means of 2, 6 or 10.
    assert iv.low == pytest.approx(2.0)
    assert iv.high == pytest.approx(10.0)


def test_cluster_bootstrap_is_deterministic_with_a_seed():
    data = {f"i{k}": [float(k), float(k) + 0.5, float(k * k % 7)] for k in range(12)}
    a = cluster_bootstrap_mean(data, iterations=1000, seed=42)
    b = cluster_bootstrap_mean(data, iterations=1000, seed=42)
    c = cluster_bootstrap_mean(data, iterations=1000, seed=43)
    assert (a.low, a.high) == (b.low, b.high)
    assert (a.low, a.high) != (c.low, c.high)
    assert a.low < a.estimate < a.high


def test_cluster_bootstrap_with_no_instances_has_no_estimate():
    iv = cluster_bootstrap_mean({}, iterations=100, seed=0)
    assert iv.estimate is None and iv.n == 0 and iv.method == "none"


@pytest.mark.parametrize(
    ("d", "p"),
    [
        ([1.0, 1.0, 1.0, 1.0, 1.0], 2 / 32),  # only all-plus and all-minus are as extreme
        ([1.0, 2.0, 3.0], 2 / 8),
        ([1.0, -1.0], 1.0),
        ([0.0, 0.0, 0.0], 1.0),
    ],
)
def test_sign_flip_exact_matches_hand_counts(d, p):
    got, test = sign_flip_pvalue(d, seed=0)
    assert test == "sign_flip_exact"
    assert got == pytest.approx(p)


def test_sign_flip_uses_random_flips_above_fifteen_instances():
    d = [0.5] * 20  # exact p would be 2 / 2**20
    got, test = sign_flip_pvalue(d, seed=0)
    assert test == "sign_flip_random"
    assert got <= 0.001
    again, _ = sign_flip_pvalue(d, seed=0)
    assert again == got


@pytest.mark.parametrize(
    ("p", "adjusted"),
    [
        ([0.01, 0.04, 0.03], [0.03, 0.06, 0.06]),
        ([0.02, 0.5, 0.001, 0.04], [0.06, 0.5, 0.004, 0.08]),
        ([0.6, 0.9, 0.5], [1.0, 1.0, 1.0]),
    ],
)
def test_holm_adjusts_in_step_down_order(p, adjusted):
    assert holm_adjust(p) == pytest.approx(adjusted)


# --- compute_stats over RunRows ------------------------------------------------------------


def make_rows(
    effects: dict[str, float],
    n_instances: int = 12,
    trials: int = 3,
    seed: int = 0,
    metric: str = "workflow.composite",
    noise: float = 0.05,
    spread: float = 0.2,
) -> list[RunRow]:
    """Synthetic eval: each instance has its own difficulty; each config adds its effect."""
    rng = np.random.default_rng(seed)
    difficulty = rng.normal(0.5, spread, size=n_instances)
    rows = []
    for config, effect in effects.items():
        for i in range(n_instances):
            for t in range(trials):
                value = difficulty[i] + effect + rng.normal(0.0, noise)
                rows.append(
                    RunRow(
                        run_id=f"{config}-{i}-{t}",
                        config_name=config,
                        task_instance_id=f"inst{i}",
                        trial_index=t,
                        state="completed",
                        success=bool(value > 0.5),
                        metrics={metric: float(value)},
                    )
                )
    return rows


def test_excluded_runs_are_counted_per_config_and_left_out():
    rows = [
        RunRow(
            run_id="r1",
            config_name="A",
            task_instance_id="i1",
            state="completed",
            success=True,
            metrics={"steps": 4.0},
        ),
        RunRow(
            run_id="r2",
            config_name="A",
            task_instance_id="i1",
            state="infra_error",
            success=False,
            metrics={"steps": 400.0},
        ),
        RunRow(run_id="r3", config_name="A", task_instance_id="i2", state="skipped_eval_cap"),
        RunRow(
            run_id="r4",
            config_name="A",
            task_instance_id="i2",
            state="agent_failed",
            success=False,
            metrics={"steps": 6.0},
        ),
        RunRow(
            run_id="r5",
            config_name="A",
            task_instance_id="i3",
            state="budget_stopped",
            success=None,
            metrics={"steps": 8.0},
        ),
        RunRow(run_id="r6", config_name="A", task_instance_id="i3", state="infra_excluded"),
    ]
    result = compute_stats(rows, seed=3, iterations=200)
    assert result.seed == 3 and result.bootstrap_iterations == 200
    (cfg,) = result.configs
    assert cfg.runs_total == 6
    assert cfg.runs_used == 3
    assert cfg.excluded == {"infra_error": 1, "skipped_eval_cap": 1, "infra_excluded": 1}
    assert cfg.instances == 3
    # success None is left out of the rate: 1 of 2.
    assert cfg.success_rate.n == 2 and cfg.success_rate.estimate == pytest.approx(0.5)
    assert cfg.metrics["steps"].estimate == pytest.approx(6.0)
    assert any("3 runs excluded" in w for w in cfg.warnings)
    assert any("fewer than 10" in w for w in cfg.warnings)


def _only(result, variant, metric):
    (c,) = [c for c in result.comparisons if c.variant == variant and c.metric == metric]
    return c


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_planted_effect_is_detected(seed):
    rows = make_rows({"base": 0.0, "better": 0.15}, seed=seed)
    result = compute_stats(rows, baseline="base", variants=["better"], seed=seed, iterations=2000)
    c = _only(result, "better", "workflow.composite")
    assert c.baseline == "base" and c.n_instances == 12
    assert c.test == "sign_flip_exact"
    assert c.effect == pytest.approx(0.15, abs=0.05)
    assert c.ci_low > 0
    assert c.p_value < 0.05 and c.p_adjusted == c.p_value  # one comparison: no Holm
    assert c.verdict.startswith("better is better on workflow.composite by 0.1")
    assert "95% CI" in c.verdict and "p=" in c.verdict


@pytest.mark.parametrize("seed", [0, 1, 2, 3, 4])
def test_no_effect_is_not_detected(seed):
    rows = make_rows({"base": 0.0, "same": 0.0}, seed=seed)
    result = compute_stats(rows, baseline="base", variants=["same"], seed=seed, iterations=2000)
    c = _only(result, "same", "workflow.composite")
    assert c.p_value >= 0.05
    assert c.verdict.startswith("No meaningful difference on workflow.composite")


def test_lower_is_better_metrics_read_a_drop_as_better():
    rows = make_rows({"base": 0.0, "cheap": -0.2}, metric="cost_usd", seed=7)
    result = compute_stats(rows, baseline="base", variants=["cheap"], seed=7, iterations=2000)
    c = _only(result, "cheap", "cost_usd")
    assert c.higher_is_better is False
    assert c.effect == pytest.approx(-0.2, abs=0.05)
    assert c.verdict.startswith("cheap is better on cost_usd by 0.")


def test_higher_is_better_metric_drop_reads_as_worse():
    rows = make_rows({"base": 0.0, "bad": -0.2}, seed=7)
    result = compute_stats(rows, baseline="base", variants=["bad"], seed=7, iterations=2000)
    c = _only(result, "bad", "workflow.composite")
    assert c.effect == pytest.approx(-0.2, abs=0.05)
    assert c.verdict.startswith("bad is worse on workflow.composite by 0.")


def test_pairs_only_instances_complete_in_both():
    rows = make_rows({"base": 0.0, "v": 0.1}, n_instances=12, seed=0)
    rows = [r for r in rows if not (r.config_name == "v" and r.task_instance_id == "inst0")]
    rows += [
        RunRow(
            run_id="x",
            config_name="v",
            task_instance_id="inst1",
            state="infra_error",
            metrics={"workflow.composite": 99.0},
        ),
    ]
    result = compute_stats(rows, baseline="base", variants=["v"], seed=0, iterations=500)
    c = _only(result, "v", "workflow.composite")
    assert c.n_instances == 11
    assert c.effect == pytest.approx(0.1, abs=0.05)


def test_holm_applies_across_variants_only_with_more_than_two_comparisons():
    effects = {"base": 0.0, "v1": 0.15, "v2": 0.02, "v3": -0.1}
    rows = make_rows(effects, n_instances=8, seed=5)
    three = compute_stats(rows, baseline="base", seed=5, iterations=500)
    cs = [_only(three, v, "workflow.composite") for v in ("v1", "v2", "v3")]
    expected = holm_adjust([c.p_value for c in cs])
    assert [c.p_adjusted for c in cs] == pytest.approx(expected)
    assert all(c.p_adjusted >= c.p_value for c in cs)
    assert "after Holm" in cs[0].verdict

    two = compute_stats(rows, baseline="base", variants=["v1", "v2"], seed=5, iterations=500)
    for v in ("v1", "v2"):
        c = _only(two, v, "workflow.composite")
        assert c.p_adjusted == c.p_value
        assert "Holm" not in c.verdict


def test_warns_on_wide_ci_and_few_instances():
    rows = make_rows({"base": 0.0, "v": 0.02}, n_instances=6, noise=0.2, seed=1)
    result = compute_stats(rows, baseline="base", seed=1, iterations=500)
    c = _only(result, "v", "workflow.composite")
    assert any("Wide CI" in w for w in c.warnings)
    assert any("fewer than 10" in w for w in c.warnings)


def test_stats_over_360_runs_is_fast():
    import time

    effects = {"base": 0.0, "model": 0.1, "harness": -0.05, "toolset": 0.0}
    rows = make_rows(effects, n_instances=30, trials=3, seed=0)
    for r in rows:
        r.metrics.update(
            steps=10.0,
            latency_ms=1000.0,
            cost_usd=0.01,
            errors=0.0,
            **{"process.composite": 0.5, "output.iou": 0.4, "workflow.order": 1.0},
        )
    assert len(rows) == 360
    start = time.perf_counter()
    result = compute_stats(rows, baseline="base", seed=0, iterations=5000)
    assert time.perf_counter() - start < 60
    assert len(result.comparisons) == 3 * 9  # 3 variants x (success + 8 metrics)
