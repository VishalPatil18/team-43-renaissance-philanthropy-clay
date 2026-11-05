"""Eval spec (architecture §7.3).

Owner: WS5 (5th member). WS1 reads ``budget``, ``loop_guard``, ``summary`` and the
configuration blocks (for the pre-flight estimate and the guards). Defined here to follow the
architecture sketch.
"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class NamedComponent(BaseModel):
    name: str
    version: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)


class CustomTask(BaseModel):
    """A free-form query run as its own task (``Q@<id>``), outside the task library.

    It has no reference answer: it is scored only against ``expect`` (strings the final answer
    must contain, e.g. item IDs or place names) by the ``expect`` evaluator, if any are given.
    """

    model_config = ConfigDict(extra="forbid")

    id: str = Field(pattern=r"^[a-z0-9][a-z0-9-]{0,47}$")
    prompt: str = Field(min_length=1)
    system_prompt: str | None = None
    expect: list[str] = Field(default_factory=list)


class TasksSpec(BaseModel):
    """Library tasks (``templates`` x ``aois``) and/or custom queries.

    Empty ``templates`` means every template, unless the spec has custom tasks: then it means
    none, so a custom-only spec runs only its own queries.
    """

    templates: list[str] = Field(default_factory=list)
    aois: str | list[str] = "all"
    custom: list[CustomTask] = Field(default_factory=list)


class ConfigSpec(BaseModel):
    """One agent configuration: model + harness + tool set + tracer."""

    name: str
    model: NamedComponent
    harness: NamedComponent
    toolset: str
    tracer: NamedComponent = Field(default_factory=lambda: NamedComponent(name="jsonl"))


class VariantSpec(BaseModel):
    name: str
    override: dict[str, Any] = Field(default_factory=dict)


class RunLimits(BaseModel):
    """Per-run limits. Any omitted limit is off (FR-11.1)."""

    max_steps: int | None = Field(default=None, gt=0)
    max_tokens: int | None = Field(default=None, gt=0)
    max_usd: float | None = Field(default=None, gt=0)
    max_seconds: float | None = Field(default=None, gt=0)


class EvalLimits(BaseModel):
    max_usd: float | None = Field(default=None, gt=0)


class BudgetSpec(BaseModel):
    run: RunLimits = Field(default_factory=RunLimits)
    eval: EvalLimits = Field(default_factory=EvalLimits)


class LoopGuardSpec(BaseModel):
    max_identical_calls: int = Field(default=3, gt=0)


class EvalSpec(BaseModel):
    model_config = ConfigDict(extra="allow")

    spec_version: int = 1
    name: str
    tasks: TasksSpec = Field(default_factory=TasksSpec)
    baseline: ConfigSpec | None = None
    variants: list[VariantSpec] = Field(default_factory=list)
    evaluators: list[NamedComponent] = Field(default_factory=list)
    summary: NamedComponent | None = None
    trials: int = Field(default=1, gt=0)
    seed: int = 0
    budget: BudgetSpec = Field(default_factory=BudgetSpec)
    loop_guard: LoopGuardSpec = Field(default_factory=LoopGuardSpec)
    infra_retries: int = Field(default=2, ge=0)
    executor: NamedComponent = Field(default_factory=lambda: NamedComponent(name="local"))
    offline: bool = False
