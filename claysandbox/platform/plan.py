"""Expand an ``EvalSpec`` into concrete ``RunRequest``s (architecture §8.5, FR-9.1–FR-9.3).

Configurations are the baseline plus each variant (the variant's ``override`` deep-merged into
the baseline). Every configuration runs on the same task instances with the same trials
(FR-9.2). The plan is ordered instance-major with configurations round-robin, so a partial or
capped eval still holds paired results for the instances it reached.

Each request carries what a worker needs to run on its own, locally or on Fargate, in
``RunRequest.extra``: limits, loop guard, evaluators, summarizer, seed, offline flag, spec
hash and the configuration's tracer.
"""

from __future__ import annotations

import copy
import hashlib
import json
from typing import Any

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import RunRequest
from claysandbox.contracts.ids import new_id
from claysandbox.contracts.manifest import ComponentRef
from claysandbox.contracts.spec import ConfigSpec, EvalSpec

AGENT_AXES = ("model", "harness", "toolset")


def spec_sha256(spec: EvalSpec) -> str:
    canonical = json.dumps(spec.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    out = copy.deepcopy(base)
    for key, value in override.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def configurations(spec: EvalSpec) -> tuple[list[ConfigSpec], list[str]]:
    """The baseline and every variant as full configurations, plus FR-9.3 warnings."""
    if spec.baseline is None:
        raise ConfigError("the spec has no baseline configuration", kind="invalid_spec")
    base = spec.baseline.model_dump(mode="json")
    configs = [spec.baseline]
    warnings: list[str] = []
    names = {spec.baseline.name}
    for variant in spec.variants:
        if variant.name in names:
            raise ConfigError(f"duplicate configuration name {variant.name!r}", kind="invalid_spec")
        names.add(variant.name)
        merged = _deep_merge(base, variant.override)
        merged["name"] = variant.name
        configs.append(ConfigSpec.model_validate(merged))
        changed = [axis for axis in AGENT_AXES if axis in variant.override]
        if len(changed) > 1:
            warnings.append(
                f"variant {variant.name!r} changes more than one agent axis "
                f"({', '.join(changed)}); its effect can't be attributed to one of them (FR-9.3)"
            )
        if not variant.override:
            warnings.append(f"variant {variant.name!r} has no override; it equals the baseline")
    return configs, warnings


def _ref(kind: str, name: str, version: str | None, params: dict[str, Any]) -> ComponentRef:
    return ComponentRef(kind=kind, name=name, version=version or "", params=dict(params))


def build_requests(
    spec: EvalSpec, eval_id: str, instance_ids: list[str]
) -> tuple[list[RunRequest], list[str]]:
    """One request per instance x configuration x trial, instance-major, configs round-robin."""
    configs, warnings = configurations(spec)
    digest = spec_sha256(spec)
    common = {
        "budget": spec.budget.run.model_dump(mode="json"),
        "loop_guard": spec.loop_guard.model_dump(mode="json"),
        "evaluators": [e.model_dump(mode="json") for e in spec.evaluators],
        "summary": spec.summary.model_dump(mode="json") if spec.summary else None,
        "seed": spec.seed,
        "offline": spec.offline,
        "spec_sha256": digest,
        "spec_name": spec.name,
    }
    requests: list[RunRequest] = []
    for instance_id in instance_ids:
        template = instance_id.split("@", 1)[0]
        for trial in range(spec.trials):
            for cfg in configs:
                requests.append(
                    RunRequest(
                        run_id=new_id(),
                        eval_id=eval_id,
                        config_name=cfg.name,
                        template=template,
                        task_instance_id=instance_id,
                        trial_index=trial,
                        attempt=1,
                        model=_ref("model", cfg.model.name, cfg.model.version, cfg.model.params),
                        harness=_ref(
                            "harness", cfg.harness.name, cfg.harness.version, cfg.harness.params
                        ),
                        toolset=_ref("toolset", cfg.toolset, None, {}),
                        tracer=_ref(
                            "tracer", cfg.tracer.name, cfg.tracer.version, cfg.tracer.params
                        ),
                        extra=copy.deepcopy(common),
                    )
                )
    return requests, warnings
