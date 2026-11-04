"""Run requests, run status and the executor interface (architecture §7.4, §8.6).

Owner: WS5 (5th member). Defined here to follow the architecture sketch so WS1's Fargate
executor and cost estimator can be built and tested before WS5 merges.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .manifest import ComponentRef

RunState = Literal[
    "planned",
    "running",
    "infra_retry",
    "completed",
    "budget_stopped",
    "agent_failed",
    "infra_excluded",
    "skipped_eval_cap",
]

TERMINAL_STATES: frozenset[str] = frozenset(
    {"completed", "budget_stopped", "agent_failed", "infra_excluded", "skipped_eval_cap"}
)


class RunRequest(BaseModel):
    """One planned run: a task instance on one configuration."""

    run_id: str
    eval_id: str
    config_name: str
    template: str
    task_instance_id: str
    trial_index: int = 0
    attempt: int = 1
    model: ComponentRef
    harness: ComponentRef
    toolset: ComponentRef
    tracer: ComponentRef | None = None
    extra: dict[str, Any] = Field(default_factory=dict)


class RunStatus(BaseModel):
    run_id: str
    eval_id: str
    state: RunState
    error_kind: str | None = None
    message: str | None = None
    environment: dict[str, Any] = Field(default_factory=dict)


@runtime_checkable
class Executor(Protocol):
    name: str

    def submit(self, requests: Iterable[RunRequest]) -> None: ...

    def poll(self) -> list[RunStatus]: ...

    def cancel(self, eval_id: str) -> None: ...
