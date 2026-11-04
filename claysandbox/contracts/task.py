"""Task contracts: templates, workflow specs, AOIs, task instances and task references.

Owner: WS2 (Vishal). Architecture §14, srs F13, DD-014, DD-028, DD-029, DD-043; contracts open
points 5 and 9. WS4 (Barath) scores against ``TaskReference``; WS5 (5th member) instantiates
tasks through ``TaskLibrary``.

Vocabularies (open point 9). They are ``Literal`` types, so adding a value is a contract change:

* ordering-rule shapes: ``before`` (``{before: A, after: B, optional_first: bool}``). The rule
  holds if the first successful call of capability A comes before the first call of B. With
  ``optional_first`` the rule is skipped when A is never called.
* argument-constraint checks, each applied to every call of ``capability``:

  ===================== ======================================== ==========================
  check                 holds when                               ``value`` after resolution
  ===================== ======================================== ==========================
  bbox_intersects_aoi   the bbox argument intersects the AOI     AOI geometry (GeoJSON)
  point_within_aoi      the lat/lon arguments fall in the AOI    AOI geometry (GeoJSON)
  collection_in         the collection argument(s) are in values ``values``: allowed IDs
  datetime_within_year  the datetime argument lies in the year   the year (int)
  k_at_most             the k argument is at most value          the maximum (int)
  ===================== ======================================== ==========================

  ``arg_names`` names the tool arguments to read, in the order given (e.g. ``[bbox]``,
  ``[lat, lon]``). If it is empty the checker uses its default argument name.
* done conditions: ``output_matches_schema_nonempty`` (final output parses against the template's
  output schema and is non-empty, architecture §10.1), ``output_present`` (any final output),
  ``assumptions_or_question`` (``assumptions`` non-empty or ``clarifying_question`` present).

Placeholders: template strings and workflow values may contain ``{year}``, ``{aoi.name}`` and
similar; ``tasks.render`` fills them with plain substitution, never an evaluated template.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

SCHEMA_VERSION = "1.0"

OrderingShape = Literal["before"]
ConstraintCheck = Literal[
    "bbox_intersects_aoi",
    "point_within_aoi",
    "collection_in",
    "datetime_within_year",
    "k_at_most",
]
DoneCondition = Literal[
    "output_matches_schema_nonempty", "output_present", "assumptions_or_question"
]
ReferenceMethod = Literal["script", "script+curated"]
Difficulty = Literal["easy", "medium", "hard"]

TEMPLATE_ID = re.compile(r"^T[0-9]+$")
AOI_ID = re.compile(r"^[a-z]{2}-[a-z]{2}-[a-z0-9-]+$")
INSTANCE_ID = re.compile(r"^(T[0-9]+)@([a-z]{2}-[a-z]{2}-[a-z0-9-]+)$")
REFERENCE_VERSION = re.compile(r"^(T[0-9]+)\.v([0-9]+)\+sha256:([0-9a-f]{12})$")

_NEEDS_VALUES: frozenset[str] = frozenset({"collection_in"})
_NEEDS_VALUE: frozenset[str] = frozenset({"datetime_within_year", "k_at_most"})
_AOI_CHECKS: frozenset[str] = frozenset({"bbox_intersects_aoi", "point_within_aoi"})


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class OrderingRule(_Strict):
    kind: OrderingShape = "before"
    before: str
    after: str
    optional_first: bool = False


class ArgumentConstraint(_Strict):
    capability: str
    check: ConstraintCheck
    arg_names: list[str] = Field(default_factory=list)
    values: list[Any] | None = None
    value: Any = None

    @model_validator(mode="after")
    def _has_operand(self) -> ArgumentConstraint:
        if self.check in _NEEDS_VALUES and not self.values:
            raise ValueError(f"{self.check} needs a non-empty 'values' list")
        if self.check in _NEEDS_VALUE and self.value is None:
            raise ValueError(f"{self.check} needs a 'value'")
        return self


class RecoveryRule(_Strict):
    recovered_penalty: float = Field(default=0.25, ge=0.0, le=1.0)


class WorkflowSpec(_Strict):
    """Expected workflow (DD-028). Tools are named by capability (FR-4.10)."""

    required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    ordering: list[OrderingRule] = Field(default_factory=list)
    argument_constraints: list[ArgumentConstraint] = Field(default_factory=list)
    expected_steps: int = Field(gt=0)
    step_limit: int = Field(gt=0)
    done: DoneCondition
    recovery: RecoveryRule = Field(default_factory=RecoveryRule)

    @model_validator(mode="after")
    def _check(self) -> WorkflowSpec:
        if self.expected_steps > self.step_limit:
            raise ValueError("expected_steps must not exceed step_limit")
        both = sorted(set(self.required) & set(self.forbidden))
        if both:
            raise ValueError(f"capabilities both required and forbidden: {both}")
        return self


class OutputSpec(_Strict):
    builder: str  # path relative to tasks/, e.g. builders/t1_naip_items.py
    metric: str  # output evaluator registry name, e.g. output.t1


class TaskTemplate(_Strict):
    """A reusable task definition (FR-13.1). Loaded from ``tasks/templates/<id>.yaml``."""

    schema_version: str = SCHEMA_VERSION
    id: str
    title: str
    difficulty: Difficulty
    parameters: list[str] = Field(default_factory=lambda: ["aoi"])
    defaults: dict[str, Any] = Field(default_factory=dict)
    system_prompt: str
    prompt: str
    output_schema: dict[str, Any]
    workflow: WorkflowSpec
    weights: dict[str, float] = Field(default_factory=dict)  # empty = equal weights
    output: OutputSpec
    process_rubric: str | None = None  # path relative to tasks/, default process_rubrics/<id>.md

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not TEMPLATE_ID.match(v):
            raise ValueError(f"template id {v!r} must look like T1")
        return v

    @field_validator("weights")
    @classmethod
    def _weights_ok(cls, v: dict[str, float]) -> dict[str, float]:
        if any(w < 0 for w in v.values()):
            raise ValueError("weights must be non-negative")
        return v


class AOI(_Strict):
    """An area of interest: a US county (FR-13.3). Loaded from ``tasks/aois.yaml``.

    ``bbox`` is ``[west, south, east, north]`` in WGS84. ``geometry`` is a simplified GeoJSON
    Polygon or MultiPolygon. ``template_params`` holds per-template values, e.g. the T4 query point.
    """

    id: str
    name: str
    state: str
    state_code: str = Field(min_length=2, max_length=2)
    fips: str = Field(pattern=r"^[0-9]{5}$")
    bbox: list[float] = Field(min_length=4, max_length=4)
    geometry: dict[str, Any]
    tags: list[str] = Field(default_factory=list)
    template_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    source: str = ""

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not AOI_ID.match(v):
            raise ValueError(f"AOI id {v!r} must look like us-ca-kern")
        return v

    @field_validator("bbox")
    @classmethod
    def _bbox_ok(cls, v: list[float]) -> list[float]:
        west, south, east, north = v
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(f"bbox {v} is not [west, south, east, north]")
        return v

    @field_validator("geometry")
    @classmethod
    def _geometry_ok(cls, v: dict[str, Any]) -> dict[str, Any]:
        if v.get("type") not in ("Polygon", "MultiPolygon") or "coordinates" not in v:
            raise ValueError("geometry must be a GeoJSON Polygon or MultiPolygon")
        return v


class TaskInstance(_Strict):
    """A template filled in for one AOI. ID ``<template>@<aoi>`` (DD-043)."""

    id: str
    template: str
    aoi: str
    title: str
    prompt: str
    system_prompt: str
    params: dict[str, Any] = Field(default_factory=dict)  # resolved, e.g. {"year": 2022}
    output_schema: dict[str, Any]

    @field_validator("id")
    @classmethod
    def _id_ok(cls, v: str) -> str:
        if not INSTANCE_ID.match(v):
            raise ValueError(f"instance id {v!r} must look like T1@us-ca-kern")
        return v


class TaskReference(_Strict):
    """What a run of one task instance is scored against (open point 5, DD-029).

    ``version`` is ``<template>.v<n>+sha256:<12 hex>``. The hash covers the canonical JSON of
    ``workflow``, ``output_reference`` and ``weights``. Stored at
    ``tasks/references/<template>/<aoi>/<version>.json`` and never overwritten.
    """

    schema_version: str = SCHEMA_VERSION
    template: str
    aoi: str
    instance_id: str
    version: str
    method: ReferenceMethod
    builder: str
    builder_sha256: str
    inputs: dict[str, Any] = Field(default_factory=dict)
    built_at: datetime
    checked_by: str | None = None
    checked_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)
    workflow: WorkflowSpec  # resolved: AOI and parameter values filled in
    output_reference: dict[str, Any]
    weights: dict[str, float] = Field(default_factory=dict)
    output_schema: dict[str, Any]
    process_rubric: str = ""
    aoi_snapshot: AOI

    @field_validator("version")
    @classmethod
    def _version_ok(cls, v: str) -> str:
        if not REFERENCE_VERSION.match(v):
            raise ValueError(f"reference version {v!r} must look like T1.v1+sha256:0123456789ab")
        return v


@runtime_checkable
class TaskLibrary(Protocol):
    """Templates, AOIs, instances and references (plan-vishal §8)."""

    def list_templates(self) -> list[TaskTemplate]: ...

    def list_aois(self) -> list[AOI]: ...

    def instances(
        self, templates: list[str] | None = None, aois: list[str] | str | None = None
    ) -> list[TaskInstance]:
        """Every instance of the templates over the AOIs. ``None`` or ``"all"`` means all."""
        ...

    def get_instance(self, instance_id: str) -> TaskInstance: ...

    def get_reference(self, instance_id: str, version: str | None = None) -> TaskReference:
        """The latest reference, or exactly ``version``."""
        ...

    def build_references(self, template: str, aoi: str | None = None) -> list[TaskReference]:
        """Run the template's builder for one AOI (or all) and store any new versions."""
        ...
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
