"""The demo spec parses, uses priced models and fits its own budget (PRI-R3-01)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from claysandbox.contracts.execution import RunRequest
from claysandbox.contracts.manifest import ComponentRef
from claysandbox.contracts.spec import EvalSpec
from claysandbox.runtime.estimate import CostEstimator
from claysandbox.runtime.pricing import YamlPriceTable

SPECS = Path(__file__).resolve().parents[3] / "specs"


@pytest.fixture(scope="module")
def spec() -> EvalSpec:
    return EvalSpec.model_validate(yaml.safe_load((SPECS / "demo.yaml").read_text()))


def plan(spec: EvalSpec) -> list[RunRequest]:
    """Expand the spec the way the service will: instances x configurations x trials."""
    assert spec.baseline is not None
    configs = [(spec.baseline.name, spec.baseline.model, spec.baseline.harness)]
    for variant in spec.variants:
        harness = variant.override.get("harness", {}).get("name", spec.baseline.harness.name)
        configs.append(
            (variant.name, spec.baseline.model, type(spec.baseline.harness)(name=harness))
        )
    requests = []
    for aoi in spec.tasks.aois:
        for name, model, harness in configs:
            n = len(requests)
            requests.append(
                RunRequest(
                    run_id=f"r{n}",
                    eval_id="demo",
                    config_name=name,
                    template="T1",
                    task_instance_id=f"T1@{aoi}",
                    model=ComponentRef(kind="model", name=model.name, params=model.params),
                    harness=ComponentRef(kind="harness", name=harness.name),
                    toolset=ComponentRef(kind="toolset", name=spec.baseline.toolset),
                )
            )
    return requests


def test_demo_is_two_configurations_by_two_instances_by_one_trial(spec: EvalSpec) -> None:
    assert spec.trials == 1 and len(spec.variants) == 1 and len(spec.tasks.aois) == 2
    assert len(plan(spec)) == 4


def test_demo_always_sets_a_run_budget_and_an_eval_cap(spec: EvalSpec) -> None:
    run = spec.budget.run
    assert None not in (run.max_steps, run.max_tokens, run.max_usd, run.max_seconds)
    assert spec.budget.eval.max_usd is not None and spec.budget.eval.max_usd <= 20


def test_every_model_in_the_demo_has_a_price(spec: EvalSpec) -> None:
    prices = YamlPriceTable()
    assert spec.baseline is not None and spec.summary is not None
    assert prices.has(spec.baseline.model.params["model_id"])
    assert prices.has(spec.summary.params["model_id"])


def test_the_demo_estimate_is_well_under_its_cap(spec: EvalSpec) -> None:
    estimate = CostEstimator(None, YamlPriceTable()).estimate(plan(spec), spec)
    assert 0 < estimate.total_usd < 0.5
    assert not estimate.exceeds_eval_cap
    assert set(estimate.per_config) == {"novalite-strands-T1", "converse-loop"}
