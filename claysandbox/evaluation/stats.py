"""Statistics engine (architecture §11, FR-10.1–FR-10.5, FR-10.8, DD-025).

numpy and scipy only, seeded with ``np.random.default_rng(seed)``. Inputs are ``RunRow``s.
"""

from __future__ import annotations

import math
import zlib
from collections import Counter, defaultdict
from collections.abc import Collection, Mapping, Sequence
from typing import Literal

import numpy as np
from scipy.stats import norm

from claysandbox.contracts.stats import (
    EXCLUDED_STATES,
    ConfigStats,
    Interval,
    PairedComparison,
    RunRow,
    StatsResult,
)

_Z95 = float(norm.ppf(0.975))
DEFAULT_ITERATIONS = 5000


def wilson_interval(successes: int, n: int, z: float = _Z95) -> Interval:
    """Wilson score interval for a binomial proportion."""
    if n <= 0:
        return Interval(estimate=None, low=None, high=None, n=0, method="none")
    p = successes / n
    denom = 1.0 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return Interval(
        estimate=p,
        low=max(0.0, centre - half),
        high=min(1.0, centre + half),
        n=n,
        method="wilson",
    )


def _bootstrap_ci(
    values: np.ndarray, iterations: int, rng: np.random.Generator, alpha: float = 0.05
) -> tuple[float, float]:
    """Percentile CI of the mean of ``values`` (one value per cluster), vectorised."""
    n = len(values)
    idx = rng.integers(0, n, size=(iterations, n))
    boot = values[idx].mean(axis=1)
    low, high = np.percentile(boot, [100 * alpha / 2, 100 * (1 - alpha / 2)])
    return float(low), float(high)


def cluster_bootstrap_mean(
    values_by_instance: Mapping[str, Sequence[float]],
    iterations: int = DEFAULT_ITERATIONS,
    seed: int = 0,
    rng: np.random.Generator | None = None,
    alpha: float = 0.05,
) -> Interval:
    """Mean over task instances of each instance's run mean, with a cluster-bootstrap CI.

    Instances are resampled with replacement; the runs of an instance stay together.
    """
    means = np.array(
        [float(np.mean(v)) for v in values_by_instance.values() if len(v) > 0], dtype=float
    )
    if len(means) == 0:
        return Interval(estimate=None, low=None, high=None, n=0, method="none")
    rng = rng if rng is not None else np.random.default_rng(seed)
    low, high = _bootstrap_ci(means, iterations, rng, alpha)
    return Interval(
        estimate=float(means.mean()), low=low, high=high, n=len(means), method="cluster_bootstrap"
    )


EXACT_MAX_N = 15
RANDOM_FLIPS = 10_000
_TOL = 1e-12


SignFlipTest = Literal["sign_flip_exact", "sign_flip_random", "none"]


def sign_flip_pvalue(
    d: Sequence[float] | np.ndarray,
    seed: int = 0,
    rng: np.random.Generator | None = None,
    random_flips: int = RANDOM_FLIPS,
) -> tuple[float, SignFlipTest]:
    """Two-sided sign-flip permutation p-value for mean(d) = 0.

    Exact over all 2^n sign patterns when n <= 15, else ``random_flips`` random patterns
    (p = (hits + 1) / (flips + 1)).
    """
    arr = np.asarray(d, dtype=float)
    n = len(arr)
    if n == 0:
        return 1.0, "none"
    observed = abs(arr.mean())
    if n <= EXACT_MAX_N:
        bits = (np.arange(2**n)[:, None] >> np.arange(n)) & 1
        signs = 1 - 2 * bits
        stats = np.abs((signs * arr).mean(axis=1))
        return float(np.mean(stats >= observed - _TOL)), "sign_flip_exact"
    rng = rng if rng is not None else np.random.default_rng(seed)
    signs = rng.choice(np.array([-1.0, 1.0]), size=(random_flips, n))
    stats = np.abs((signs * arr).mean(axis=1))
    hits = int(np.sum(stats >= observed - _TOL))
    return (hits + 1) / (random_flips + 1), "sign_flip_random"


def holm_adjust(pvalues: Sequence[float]) -> list[float]:
    """Holm step-down adjusted p-values, returned in the input order."""
    m = len(pvalues)
    order = sorted(range(m), key=lambda i: pvalues[i])
    adjusted = [0.0] * m
    running = 0.0
    for rank, i in enumerate(order):
        running = max(running, min(1.0, (m - rank) * pvalues[i]))
        adjusted[i] = running
    return adjusted


MIN_INSTANCES = 10
SUCCESS_METRIC = "success"


def _rng_for(seed: int, *key: str) -> np.random.Generator:
    """A generator per quantity, so adding a metric or config leaves the others unchanged."""
    return np.random.default_rng([seed, *(zlib.crc32(k.encode()) for k in key)])


def _by_instance(rows: Sequence[RunRow], metric: str) -> dict[str, list[float]]:
    """Run values of ``metric`` grouped by task instance (``success`` reads the run flag)."""
    out: dict[str, list[float]] = defaultdict(list)
    for r in rows:
        if metric == SUCCESS_METRIC:
            if r.success is not None:
                out[r.task_instance_id].append(1.0 if r.success else 0.0)
        elif metric in r.metrics:
            out[r.task_instance_id].append(float(r.metrics[metric]))
    return dict(out)


def _config_stats(
    name: str, rows: Sequence[RunRow], seed: int, iterations: int, alpha: float
) -> ConfigStats:
    used = [r for r in rows if r.state not in EXCLUDED_STATES]
    excluded = Counter(r.state for r in rows if r.state in EXCLUDED_STATES)
    judged = [r for r in used if r.success is not None]
    metric_names = sorted({m for r in used for m in r.metrics})
    metrics = {
        m: cluster_bootstrap_mean(
            _by_instance(used, m), iterations, rng=_rng_for(seed, "config", name, m), alpha=alpha
        )
        for m in metric_names
    }
    instances = len({r.task_instance_id for r in used})
    warnings = []
    if excluded:
        parts = ", ".join(f"{k}: {v}" for k, v in sorted(excluded.items()))
        warnings.append(f"{sum(excluded.values())} runs excluded ({parts}).")
    if instances < MIN_INSTANCES:
        warnings.append(
            f"Only {instances} task instances (fewer than {MIN_INSTANCES}); CIs are unreliable."
        )
    return ConfigStats(
        config_name=name,
        runs_total=len(rows),
        runs_used=len(used),
        excluded=dict(sorted(excluded.items())),
        instances=instances,
        success_rate=wilson_interval(sum(1 for r in judged if r.success), len(judged)),
        metrics=metrics,
        warnings=warnings,
    )


LOWER_IS_BETTER: frozenset[str] = frozenset({"cost_usd", "latency_ms", "steps", "errors"})


def higher_is_better(metric: str) -> bool:
    """Direction of a metric: cost, latency, steps and error counts are lower-is-better."""
    return not (metric in LOWER_IS_BETTER or metric.startswith("errors."))


def _fmt(x: float) -> str:
    return f"{x:.3g}"


def _verdict(
    variant: str,
    metric: str,
    effect: float,
    ci: tuple[float, float],
    p_adj: float,
    alpha: float,
    higher: bool,
    holm: bool,
) -> str:
    sign = 1.0 if higher else -1.0
    gain = sign * effect
    lo, hi = sorted((sign * ci[0], sign * ci[1]))  # CI of the improvement
    includes_zero = lo <= 0.0 <= hi
    p_text = f"p={_fmt(p_adj)}" + (" after Holm" if holm else "")
    if includes_zero:
        return f"No meaningful difference on {metric} (CI includes 0)"
    if p_adj >= alpha:
        return f"No meaningful difference on {metric} ({p_text}; 95% CI {_fmt(lo)}..{_fmt(hi)})"
    if gain > 0:
        word, size, ci_text = "better", gain, f"{_fmt(lo)}..{_fmt(hi)}"
    else:
        word, size, ci_text = "worse", -gain, f"{_fmt(-hi)}..{_fmt(-lo)}"
    return f"{variant} is {word} on {metric} by {_fmt(size)} (95% CI {ci_text}, {p_text})"


def _paired(
    baseline: str,
    variant: str,
    metric: str,
    base_rows: Sequence[RunRow],
    var_rows: Sequence[RunRow],
    seed: int,
    iterations: int,
    alpha: float,
    instances: Collection[str] | None,
) -> PairedComparison:
    a = _by_instance(base_rows, metric)
    b = _by_instance(var_rows, metric)
    shared = sorted(set(a) & set(b) if instances is None else set(a) & set(b) & set(instances))
    higher = higher_is_better(metric)
    if not shared:
        return PairedComparison(
            baseline=baseline,
            variant=variant,
            metric=metric,
            n_instances=0,
            effect=None,
            ci_low=None,
            ci_high=None,
            p_value=None,
            p_adjusted=None,
            test="none",
            higher_is_better=higher,
            verdict=f"Not enough data to compare {metric}: no task instance is complete in both",
            warnings=["No task instances complete in both configurations."],
        )
    d = np.array([np.mean(b[i]) - np.mean(a[i]) for i in shared], dtype=float)
    ci = _bootstrap_ci(d, iterations, _rng_for(seed, "paired", baseline, variant, metric), alpha)
    p, test = sign_flip_pvalue(d, rng=_rng_for(seed, "flip", baseline, variant, metric))
    return PairedComparison(
        baseline=baseline,
        variant=variant,
        metric=metric,
        n_instances=len(shared),
        effect=float(d.mean()),
        ci_low=ci[0],
        ci_high=ci[1],
        p_value=p,
        p_adjusted=p,
        test=test,
        higher_is_better=higher,
        verdict="",
    )


def _finish(c: PairedComparison, m: int, alpha: float, holm: bool) -> None:
    """Fill the verdict and warnings once ``p_adjusted`` is final."""
    if c.effect is None or c.p_adjusted is None or c.ci_low is None or c.ci_high is None:
        return
    c.verdict = _verdict(
        c.variant,
        c.metric,
        c.effect,
        (c.ci_low, c.ci_high),
        c.p_adjusted,
        alpha,
        c.higher_is_better,
        holm,
    )
    half = (c.ci_high - c.ci_low) / 2
    if half > 0.5 * abs(c.effect):
        c.warnings.append(
            f"Wide CI: half-width {_fmt(half)} is more than 50% of the effect "
            f"{_fmt(abs(c.effect))}."
        )
    if c.n_instances < MIN_INSTANCES:
        c.warnings.append(
            f"Only {c.n_instances} complete task instances (fewer than {MIN_INSTANCES}); "
            "treat this result as tentative."
        )
    if c.test == "sign_flip_exact":
        floor = min(1.0, (m if holm else 1) * 2.0 ** (1 - c.n_instances))
        if floor >= alpha:
            c.warnings.append(
                f"With {c.n_instances} instances and {m} comparisons the smallest possible "
                f"p is {_fmt(floor)}, so no difference can reach p<{_fmt(alpha)}."
            )


def compute_stats(
    rows: Sequence[RunRow],
    baseline: str | None = None,
    variants: Sequence[str] | None = None,
    *,
    seed: int = 0,
    iterations: int = DEFAULT_ITERATIONS,
    alpha: float = 0.05,
    axes: Mapping[str, str] | None = None,
    paired_instances: Collection[str] | None = None,
) -> StatsResult:
    """Per-configuration statistics, plus paired comparisons of each variant vs ``baseline``.

    ``variants`` defaults to every other configuration. ``paired_instances`` restricts the
    paired comparisons to those task instances. Without it, each pair uses its own shared
    instances; an unrelated configuration cannot reduce the pair's sample.
    Holm applies across variants, per metric, when there are more than two comparisons.
    """
    by_config: dict[str, list[RunRow]] = defaultdict(list)
    for r in rows:
        by_config[r.config_name].append(r)
    configs = [
        _config_stats(name, by_config[name], seed, iterations, alpha) for name in sorted(by_config)
    ]
    comparisons: list[PairedComparison] = []
    if baseline is not None:
        if baseline not in by_config:
            raise ValueError(f"baseline {baseline!r} has no runs")
        names = list(variants) if variants is not None else sorted(set(by_config) - {baseline})
        used = {
            n: [r for r in by_config.get(n, []) if r.state not in EXCLUDED_STATES]
            for n in [baseline, *names]
        }
        metrics = sorted({m for r in used[baseline] for m in r.metrics})
        if any(r.success is not None for r in used[baseline]):
            metrics = [SUCCESS_METRIC, *metrics]
        for metric in metrics:
            group = [
                _paired(
                    baseline,
                    v,
                    metric,
                    used[baseline],
                    used[v],
                    seed,
                    iterations,
                    alpha,
                    paired_instances,
                )
                for v in names
            ]
            tested = [c for c in group if c.p_value is not None]
            holm = len(tested) > 2
            if holm:
                for c, padj in zip(
                    tested,
                    holm_adjust([c.p_value for c in tested if c.p_value is not None]),
                    strict=True,
                ):
                    c.p_adjusted = padj
            for c in group:
                if axes is not None:
                    c.axis = axes.get(c.variant)
                _finish(c, len(tested), alpha, holm)
            comparisons.extend(group)
    return StatsResult(
        seed=seed,
        bootstrap_iterations=iterations,
        alpha=alpha,
        configs=configs,
        comparisons=comparisons,
    )
