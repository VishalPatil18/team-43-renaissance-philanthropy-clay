"""Runtime contracts: model adapter, harness, guard, prices and cost estimate.

Owner: WS1 (Prithwish). Architecture §7.4, §9 and §12.

Conventions
-----------
* Plugin classes are constructed with ``cls(params: dict | None = None)`` and parse the dict
  with their own ``Params`` model, which also becomes their schema in ``GET /registry``.
* The model adapter's ``converse(..., params)`` argument holds optional per-call overrides of
  ``temperature``, ``max_tokens`` and ``top_p``. The model ID comes only from the adapter's own
  ``Params`` (FR-1.5).
* ``ModelResponse.message`` is the assistant message in Bedrock Converse shape, ready to be
  appended to the message list for the next call.
"""

from __future__ import annotations

import threading
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field

from .manifest import ToolSpec
from .tools import ToolSession
from .trace import ErrorInfo, EventSink, TraceEvent


class ToolUse(BaseModel):
    """A tool call requested by the model. ``input`` may be malformed (not an object)."""

    tool_use_id: str
    name: str
    input: Any = Field(default_factory=dict)


class ModelResponse(BaseModel):
    message: dict[str, Any]
    text: str = ""
    tool_uses: list[ToolUse] = Field(default_factory=list)
    stop_reason: str | None = None
    input_tokens: int = 0
    output_tokens: int = 0
    latency_ms: float | None = None
    model_id: str = ""


@runtime_checkable
class ModelAdapter(Protocol):
    name: str
    version: str
    model_id: str

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[ToolSpec],
        params: dict[str, Any],
    ) -> ModelResponse: ...


@runtime_checkable
class PriceTable(Protocol):
    version: str

    def model_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float: ...

    def data_cost(self, kind: str, amount: float) -> float: ...

    def has(self, model_id: str) -> bool: ...


@runtime_checkable
class BudgetGuard(Protocol):
    """Checks limits before each call. Raises ``GuardStopped`` on violation."""

    def before_model_call(self) -> None: ...

    def before_tool_call(self, tool: str, args: dict[str, Any]) -> None: ...

    def record(self, event: TraceEvent) -> None: ...

    def tool_timeout(self, default_s: float) -> float:
        """Return the timeout to use for the next tool call (never more than the time left)."""
        ...


class RunContext(BaseModel):
    """What a harness receives. ``model`` and ``tools`` are already instrumented."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    run_id: str
    prompt: str
    system_prompt: str
    model: Any
    tools: Any
    events: Any
    params: dict[str, Any] = Field(default_factory=dict)

    def typed(self) -> tuple[ModelAdapter, ToolSession, EventSink]:
        return self.model, self.tools, self.events


RunState = Literal["completed", "budget_stopped", "agent_failed", "infra_error"]


class RunOutcome(BaseModel):
    """The terminal result of a harness run. The run worker turns it into events (open point 11)."""

    state: RunState
    output: dict[str, Any] | str | None = None
    error: ErrorInfo | None = None
    steps: int = 0


@runtime_checkable
class Harness(Protocol):
    name: str
    version: str

    def run(self, ctx: RunContext) -> RunOutcome: ...


class CostLine(BaseModel):
    run_id: str
    config_name: str
    template: str
    input_tokens: int
    output_tokens: int
    agent_usd: float
    evaluation_usd: float
    data_usd: float = 0.0
    compute_usd: float = 0.0
    basis: Literal["history_template_model_harness", "history_template_model", "default_guess"]
    sample_size: int = 0

    @property
    def total_usd(self) -> float:
        return self.agent_usd + self.evaluation_usd + self.data_usd + self.compute_usd


class CostEstimate(BaseModel):
    lines: list[CostLine] = Field(default_factory=list)
    per_config: dict[str, float] = Field(default_factory=dict)
    agent_usd: float = 0.0
    evaluation_usd: float = 0.0
    data_usd: float = 0.0
    compute_usd: float = 0.0
    total_usd: float = 0.0
    price_table_version: str = ""
    eval_cap_usd: float | None = None
    exceeds_eval_cap: bool = False
    notes: list[str] = Field(default_factory=list)


@runtime_checkable
class CostEstimator(Protocol):
    def estimate(self, requests: list[Any], spec: Any) -> CostEstimate: ...


class EvalBudget:
    """Eval-level dollar cap (FR-11.6). Thread-safe.

    The service calls ``add(cost_usd)`` after each run and stops launching new runs when
    ``exhausted`` is true. Runs already started finish.
    """

    def __init__(self, max_usd: float | None) -> None:
        self.max_usd = max_usd
        self._spent = 0.0
        self._lock = threading.Lock()

    @property
    def spent(self) -> float:
        with self._lock:
            return self._spent

    def add(self, cost_usd: float) -> float:
        with self._lock:
            self._spent += max(0.0, cost_usd)
            return self._spent

    @property
    def exhausted(self) -> bool:
        if self.max_usd is None:
            return False
        return self.spent >= self.max_usd
