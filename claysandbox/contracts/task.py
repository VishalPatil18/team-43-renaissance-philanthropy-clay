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

  ``arg_names`` (input alias ``args``; read it as ``constraint.args``) names the candidate tool
  arguments, in order (e.g. ``[bbox]``). If it is empty the checker uses its defaults.
* done conditions: ``output_matches_schema_nonempty`` (final output parses against the template's
  output schema and is non-empty, architecture §10.1), ``output_present`` (any final output),
  ``assumptions_or_question`` (``assumptions`` non-empty or ``clarifying_question`` present).

Strictness: these models describe the shape that evaluators, fixtures and tests share, so most
fields have defaults. The authoring rules (AOI ID pattern, FIPS code, geometry, reference
version format, build provenance) are enforced by the WS2 task library when it loads and writes
its own files (``claysandbox.tasks``).

Placeholders: template strings and workflow values may contain ``{year}``, ``{aoi.name}`` and
similar; ``tasks.render`` fills them with plain substitution, never an evaluated template.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any, Literal, Protocol, runtime_checkable

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, field_validator, model_validator

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
    arg_names: list[str] = Field(
        default_factory=list, validation_alias=AliasChoices("arg_names", "args")
    )
    values: list[Any] | None = None
    value: Any = None

    @property
    def args(self) -> list[str] | None:
        """Candidate argument names, or ``None`` for the check's defaults (WS4's reading)."""
        return list(self.arg_names) or None

    @model_validator(mode="after")
    def _has_operand(self) -> ArgumentConstraint:
        if self.check in _NEEDS_VALUES and not self.values:
            raise ValueError(f"{self.check} needs a non-empty 'values' list")
        if self.check in _NEEDS_VALUE and self.value is None:
            raise ValueError(f"{self.check} needs a 'value'")
        return self


class WorkflowSpec(_Strict):
    """Expected workflow (DD-028). Tools are named by capability (FR-4.10)."""

    required: list[str] = Field(default_factory=list)
    forbidden: list[str] = Field(default_factory=list)
    ordering: list[OrderingRule] = Field(default_factory=list)
    argument_constraints: list[ArgumentConstraint] = Field(default_factory=list)
    expected_steps: int = Field(default=4, gt=0)
    step_limit: int = Field(default=15, gt=0)
    done: DoneCondition = "output_matches_schema_nonempty"
    # {"recovered_penalty": p}: a recovered agent/tool error costs p (0..1), an unrecovered one 1.
    recovery: dict[str, float] = Field(default_factory=lambda: {"recovered_penalty": 0.25})

    @field_validator("recovery")
    @classmethod
    def _recovery_ok(cls, v: dict[str, float]) -> dict[str, float]:
        unknown = sorted(set(v) - {"recovered_penalty"})
        if unknown:
            raise ValueError(f"unknown recovery keys {unknown}")
        if not 0.0 <= v.get("recovered_penalty", 0.25) <= 1.0:
            raise ValueError("recovered_penalty must be between 0 and 1")
        return v

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
    The task library requires every field for its own AOIs (``tasks/aois.yaml``).
    """

    id: str
    name: str = ""
    state: str = ""
    state_code: str = ""
    fips: str = ""
    bbox: list[float] = Field(default_factory=list)
    geometry: dict[str, Any] | None = None
    tags: list[str] = Field(default_factory=list)
    template_params: dict[str, dict[str, Any]] = Field(default_factory=dict)
    source: str = ""

    @field_validator("bbox")
    @classmethod
    def _bbox_ok(cls, v: list[float]) -> list[float]:
        if not v:
            return v
        if len(v) != 4:
            raise ValueError(f"bbox {v} is not [west, south, east, north]")
        west, south, east, north = v
        if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
            raise ValueError(f"bbox {v} is not [west, south, east, north]")
        return v

    @field_validator("geometry")
    @classmethod
    def _geometry_ok(cls, v: dict[str, Any] | None) -> dict[str, Any] | None:
        if v is not None and (
            v.get("type") not in ("Polygon", "MultiPolygon") or "coordinates" not in v
        ):
            raise ValueError("geometry must be a GeoJSON Polygon or MultiPolygon")
        return v

    def check_complete(self) -> AOI:
        """Raise ``ValueError`` unless this AOI has everything the task library needs."""
        problems = []
        if not AOI_ID.match(self.id):
            problems.append(f"id {self.id!r} must look like us-ca-kern")
        if not (self.name and self.state):
            problems.append("name and state are required")
        if len(self.state_code) != 2:
            problems.append("state_code must be 2 letters")
        if not re.fullmatch(r"[0-9]{5}", self.fips):
            problems.append("fips must be a 5-digit code")
        if len(self.bbox) != 4:
            problems.append("bbox is required")
        if self.geometry is None:
            problems.append("geometry is required")
        if problems:
            raise ValueError(f"AOI {self.id}: " + "; ".join(problems))
        return self


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

    ``version`` is ``<template>.v<n>+sha256:<12 hex>`` for references the task library builds.
    The hash covers the canonical JSON of ``workflow``, ``output_reference`` and ``weights``.
    Stored at ``tasks/references/<template>/<aoi>/<version>.json`` and never overwritten.
    ``aoi`` is the AOI as it was when the reference was built (evaluators read its geometry).
    The library fills every provenance field; fixtures and tests may leave them at defaults.
    """

    schema_version: str = SCHEMA_VERSION
    template: str
    instance_id: str
    version: str
    method: ReferenceMethod = "script"
    builder: str = ""
    builder_sha256: str = ""
    inputs: dict[str, Any] = Field(default_factory=dict)
    built_at: datetime | None = None
    checked_by: str | None = None
    checked_at: datetime | None = None
    notes: list[str] = Field(default_factory=list)
    workflow: WorkflowSpec  # resolved: AOI and parameter values filled in
    output_reference: dict[str, Any] = Field(default_factory=dict)
    weights: dict[str, float] = Field(default_factory=dict)
    output_schema: dict[str, Any] = Field(default_factory=dict)
    process_rubric: str = ""
    aoi: AOI | None = None

    @property
    def aoi_id(self) -> str:
        """The AOI ID: from ``aoi``, else the part of ``instance_id`` after ``@``."""
        return self.aoi.id if self.aoi is not None else self.instance_id.partition("@")[2]


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
