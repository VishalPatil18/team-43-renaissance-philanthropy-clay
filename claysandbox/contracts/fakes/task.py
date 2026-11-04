"""A fixture T1 task instance and reference (owner: WS2).

For tests that need a task without the task library or network: evaluators (WS4), the run worker
and manifest (WS5). The AOI is synthetic (``us-zz-testland``, a 0.2° square) and the answer key
holds three made-up NAIP-style item IDs. Tool names follow the real T1 tool set: imagery search is
``stac.search_items`` with arguments ``collections``, ``bbox`` and ``datetime``.
"""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from claysandbox.contracts.task import (
    AOI,
    ArgumentConstraint,
    OrderingRule,
    TaskInstance,
    TaskReference,
    WorkflowSpec,
)

FIXTURE_YEAR = 2022
FIXTURE_ITEMS = [
    "zz_m_0000001_ne_11_060_20220601",
    "zz_m_0000001_nw_11_060_20220601",
    "zz_m_0000002_se_11_060_20220601",
]
FIXTURE_OUTPUT_SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
}


def fixture_aoi() -> AOI:
    ring = [[-100.2, 40.0], [-100.0, 40.0], [-100.0, 40.2], [-100.2, 40.2], [-100.2, 40.0]]
    return AOI(
        id="us-zz-testland",
        name="Testland County",
        state="Nowhere",
        state_code="ZZ",
        fips="99001",
        bbox=[-100.2, 40.0, -100.0, 40.2],
        geometry={"type": "Polygon", "coordinates": [ring]},
        tags=["fixture"],
        source="synthetic",
    )


def fixture_t1_instance() -> TaskInstance:
    return TaskInstance(
        id="T1@us-zz-testland",
        template="T1",
        aoi="us-zz-testland",
        title="Find NAIP imagery covering an AOI for a year",
        system_prompt="You are a geospatial data assistant. Use the tools provided. "
        "Return JSON only.",
        prompt=f"Find all NAIP aerial imagery items covering Testland County (Nowhere) for "
        f'{FIXTURE_YEAR}. Return {{"items": [<item id>, ...]}}.',
        params={"year": FIXTURE_YEAR},
        output_schema=FIXTURE_OUTPUT_SCHEMA,
    )


def fixture_t1_workflow() -> WorkflowSpec:
    aoi = fixture_aoi()
    return WorkflowSpec(
        required=["imagery_search"],
        ordering=[OrderingRule(before="geocode", after="imagery_search", optional_first=True)],
        argument_constraints=[
            ArgumentConstraint(capability="imagery_search", check="bbox_intersects_aoi",
                               arg_names=["bbox"], value=aoi.geometry),
            ArgumentConstraint(capability="imagery_search", check="collection_in",
                               arg_names=["collections"], values=["naip"]),
            ArgumentConstraint(capability="imagery_search", check="datetime_within_year",
                               arg_names=["datetime"], value=FIXTURE_YEAR),
        ],
        expected_steps=4,
        step_limit=15,
        done="output_matches_schema_nonempty",
    )


def fixture_t1_reference() -> TaskReference:
    """The reference for ``fixture_t1_instance()``. Its version hash matches its content."""
    workflow = fixture_t1_workflow()
    output_reference = {"items": sorted(FIXTURE_ITEMS)}
    # Same rule as tasks.references.content_hash (contracts must not import the tasks package).
    payload = json.dumps(
        {"workflow": workflow.model_dump(mode="json"), "output_reference": output_reference,
         "weights": {}},
        sort_keys=True, separators=(",", ":"), ensure_ascii=False,
    )
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]
    return TaskReference(
        template="T1",
        aoi="us-zz-testland",
        instance_id="T1@us-zz-testland",
        version=f"T1.v1+sha256:{digest}",
        method="script",
        builder="builders/t1_naip_items.py",
        builder_sha256="0" * 64,
        inputs={"stac_api": "fixture", "collection": "naip", "year": FIXTURE_YEAR},
        built_at=datetime(2026, 11, 4, tzinfo=UTC),
        workflow=workflow,
        output_reference=output_reference,
        output_schema=FIXTURE_OUTPUT_SCHEMA,
        process_rubric="Fixture rubric: plan, choose tools, recover from errors, be honest.",
        aoi_snapshot=fixture_aoi(),
    )
