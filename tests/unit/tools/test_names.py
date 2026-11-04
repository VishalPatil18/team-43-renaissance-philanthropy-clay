"""Tool names the model sees: ``<server>__<tool>``, Bedrock-safe, ≤ 64 characters (open point 2)."""

from __future__ import annotations

import re

from claysandbox.contracts.manifest import ToolSpec, make_model_name

BEDROCK_NAME = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


def test_plain_names() -> None:
    assert make_model_name("roda", "search_datasets") == "roda__search_datasets"
    assert make_model_name("clay-embeddings", "similar_places") == "clay-embeddings__similar_places"


def test_unsafe_characters_are_replaced() -> None:
    name = make_model_name("osm", "geo.code/v2 beta")
    assert name == "osm__geo_code_v2_beta" and BEDROCK_NAME.match(name)


def test_long_names_are_truncated_with_a_hash_and_stay_distinct() -> None:
    a = make_model_name("server", "t" * 80 + "a")
    b = make_model_name("server", "t" * 80 + "b")
    assert len(a) == len(b) == 64 and a != b
    assert BEDROCK_NAME.match(a) and BEDROCK_NAME.match(b)
    assert a == make_model_name("server", "t" * 80 + "a")  # deterministic


def test_tool_spec_fills_model_name() -> None:
    spec = ToolSpec(server="stac", name="search_items")
    assert spec.model_name == "stac__search_items"
