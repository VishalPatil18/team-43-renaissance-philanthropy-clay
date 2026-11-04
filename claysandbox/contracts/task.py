"""Task contracts (architecture §14, contracts open points 5 and 9).

PLACEHOLDER (WS4 branch). Owner: WS2 (Vishal). This copy follows architecture §14.2/§14.4 and
plan-vishal VIS-R0-02 so the evaluators can be built before WS2's module merges. Replace it
with WS2's module on merge; the evaluators read only the fields below.

Assumption to confirm with WS2: ``TaskReference.aoi`` carries the AOI geometry, which the
``bbox_intersects_aoi`` / ``point_within_aoi`` checks and the T3/T5 output evaluators need.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

# Vocabularies (open point 9). WS2 declares them, WS4 implements them.
ConstraintCheck = Literal[
    "bbox_intersects_aoi",
    "point_within_aoi",
    "collection_in",
    "datetime_within_year",
    "k_at_most",
]
DoneCondition = Literal[
    "output_matches_schema_nonempty",
    "output_present",
    "assumptions_or_question",
]


class OrderingRule(BaseModel):
    """``before`` must happen before ``after``. With ``optional_first`` the rule only applies
    when ``before`` is used at all (e.g. geocoding is optional, but if used it comes first)."""

    before: str
    after: str
    optional_first: bool = False


class ArgumentConstraint(BaseModel):
    capability: str
    check: ConstraintCheck
    value: Any = None
    values: list[Any] | None = None
    args: list[str] | None = None  # candidate argument names; None = the check's defaults


class WorkflowSpec(BaseModel):
    required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    ordering: list[OrderingRule] = Field(default_factory=list)
    argument_constraints: list[ArgumentConstraint] = Field(default_factory=list)
    expected_steps: int = 4
    step_limit: int = 15
    done: DoneCondition = "output_matches_schema_nonempty"
    recovery: dict[str, float] = Field(default_factory=lambda: {"recovered_penalty": 0.25})


class AOI(BaseModel):
    id: str
    name: str = ""
    state: str = ""
    fips: str = ""
    bbox: list[float] = Field(default_factory=list)  # [minx, miny, maxx, maxy], EPSG:4326
    geometry: dict[str, Any] | None = None  # GeoJSON, EPSG:4326
    tags: list[str] = Field(default_factory=list)


class TaskReference(BaseModel):
    """Resolved workflow + output reference + weights + output schema + rubric (open point 5)."""

    template: str
    instance_id: str  # "<template>@<aoi>" (DD-043)
    version: str
    workflow: WorkflowSpec
    output_reference: dict[str, Any] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)  # empty = equal weights
    output_schema: dict[str, Any] = Field(default_factory=dict)
    process_rubric: str = ""
    aoi: AOI | None = None
