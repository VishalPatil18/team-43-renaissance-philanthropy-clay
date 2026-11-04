"""WS4 evaluators read the real WS2 task references the way WS2 built them.

These run the output evaluators and the argument-constraint checks on the committed references
in ``tasks/references/`` with known-correct and known-wrong answers.
"""

from __future__ import annotations

from typing import Any

import pytest
from shapely.geometry import shape

from claysandbox.contracts.task import TaskReference, WorkflowSpec
from claysandbox.contracts.trace import Trace
from claysandbox.evaluation.constraints import check
from claysandbox.evaluation.output.t1 import T1Evaluator
from claysandbox.evaluation.output.t2 import T2Evaluator
from claysandbox.evaluation.output.t3 import T3Evaluator
from claysandbox.evaluation.output.t4 import T4Evaluator
from claysandbox.tasks.library import FileTaskLibrary

LIB = FileTaskLibrary()
TRACE = Trace(run_id="r", events=[])


def score(evaluator: Any, instance: str, output: Any) -> dict[str, float]:
    metrics, _notes, _evidence = evaluator.score(output, TRACE, None, LIB.get_reference(instance),
                                                 "r:0")
    return metrics


def test_t1_correct_answer_scores_one() -> None:
    items = LIB.get_reference("T1@us-ca-kern").output_reference["items"]
    assert score(T1Evaluator(), "T1@us-ca-kern", {"items": items})["f1"] == 1.0


def test_t2_uses_recall_at_k() -> None:
    ref = LIB.get_reference("T2@us-tx-pecos")
    assert ref.output_reference["k"] == 10
    known = {"naip", "usgs-lidar", "sentinel-2"}
    good = [s for s in ref.output_reference["datasets"] if s in known]
    m = score(T2Evaluator(), "T2@us-tx-pecos", {"datasets": good})
    assert (m["precision"], m["recall"]) == (1.0, pytest.approx(3 / 10))
    ten = ref.output_reference["datasets"][:10]
    assert score(T2Evaluator(), "T2@us-tx-pecos", {"datasets": ten})["f1"] == 1.0
    # Only the first k slugs count for recall; extra wrong slugs still cost precision.
    padded = score(T2Evaluator(), "T2@us-tx-pecos", {"datasets": ten + ["not-a-dataset"]})
    assert padded["recall"] == 1.0 and padded["precision"] == pytest.approx(10 / 11)


def test_t2_without_k_keeps_plain_recall() -> None:
    ref = TaskReference(template="T2", instance_id="T2@x", version="v", workflow=WorkflowSpec(),
                        output_reference={"datasets": ["a", "b", "c", "d"]})
    m, _, _ = T2Evaluator().score({"datasets": ["a"]}, TRACE, None, ref, "r:0")
    assert m["recall"] == 0.25


def test_t3_point_on_a_large_farm_matches_its_footprint() -> None:
    ref = LIB.get_reference("T3@us-ca-kern")
    site = max(ref.output_reference["sites"], key=lambda s: s["properties"]["area_m2"])
    assert site["type"] == "Feature" and site["properties"]["area_m2"] > 10e6
    lon, lat = site["geometry"]["coordinates"][0][0]  # a corner, km from the centroid
    m = score(T3Evaluator(), "T3@us-ca-kern", {"sites": [{"lat": lat, "lon": lon}]})
    assert m["precision"] == 1.0
    assert m["recall"] == pytest.approx(1 / len(ref.output_reference["sites"]))


def test_t3_negative_control_empty_answer_scores_one() -> None:
    assert score(T3Evaluator(), "T3@us-ny-new-york", {"sites": []})["f1"] == 1.0
    assert score(T3Evaluator(), "T3@us-ny-hamilton", {"sites": [{"lat": 43.78, "lon": -74.27}]})[
        "precision"
    ] == 0.0


def test_t4_scores_against_the_reference_top_k() -> None:
    chips = LIB.get_reference("T4@us-nc-robeson").output_reference["top_k"]
    assert len(chips) == 10
    assert score(T4Evaluator(), "T4@us-nc-robeson", {"chips": chips})["recall_at_k"] == 1.0
    assert score(T4Evaluator(), "T4@us-nc-robeson", {"chips": chips[:5]})["recall_at_k"] == 0.5
    assert score(T4Evaluator(), "T4@us-nc-robeson", {"chips": []})["recall_at_k"] == 0.0


def test_t4_point_within_aoi_reads_separate_lat_lon_arguments() -> None:
    ref = LIB.get_reference("T4@us-nc-robeson")
    (point_rule,) = [c for c in ref.workflow.argument_constraints if c.check == "point_within_aoi"]
    assert point_rule.args == ["lat", "lon"]
    inst = LIB.get_instance("T4@us-nc-robeson")
    lat, lon = inst.params["query_lat"], inst.params["query_lon"]
    assert shape(ref.aoi.geometry).contains(shape({"type": "Point", "coordinates": [lon, lat]}))  # type: ignore[union-attr]
    assert check({"lat": lat, "lon": lon, "k": 10}, point_rule, ref) is True
    assert check({"lat": 40.78, "lon": -73.97, "k": 10}, point_rule, ref) is False
    assert check({"chip_id": "abc", "k": 10}, point_rule, ref) is None


def test_point_within_aoi_default_names_find_lat_lon() -> None:
    ref = LIB.get_reference("T4@us-nc-robeson")
    (point_rule,) = [c for c in ref.workflow.argument_constraints if c.check == "point_within_aoi"]
    bare = point_rule.model_copy(update={"arg_names": []})
    inst = LIB.get_instance("T4@us-nc-robeson")
    args = {"latitude": inst.params["query_lat"], "longitude": inst.params["query_lon"]}
    assert check(args, bare, ref) is True
