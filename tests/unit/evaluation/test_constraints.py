"""Argument-constraint checks (BAR-R1-01 step 1)."""

import pytest

from claysandbox.contracts.task import ArgumentConstraint
from claysandbox.evaluation.constraints import CHECKS, check
from tests.fixtures.traces import load

_, _, REF = load("good_t1")  # AOI: Kern County box [-120.19, 34.79, -117.62, 35.8]


def c(name, **kw):
    return ArgumentConstraint(capability="imagery_search", check=name, **kw)


def test_every_vocabulary_check_is_implemented():
    from typing import get_args

    from claysandbox.contracts.task import ConstraintCheck

    assert set(CHECKS) == set(get_args(ConstraintCheck))


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"bbox": [-119.2, 35.0, -118.0, 35.8]}, True),
        ({"bounds": [-118.0, 35.5, -117.0, 36.5]}, True),  # partial overlap
        ({"bbox": [-80.0, 40.0, -79.0, 41.0]}, False),  # Pennsylvania
        ({"bbox": "-119.2,35.0,-118.0,35.8"}, True),  # comma string
        ({"bbox": {"type": "Point", "coordinates": [-118.5, 35.2]}}, True),  # GeoJSON
        ({"bbox": [1, 2, 3]}, False),  # malformed
        ({"query": "kern"}, None),  # not applicable
    ],
)
def test_bbox_intersects_aoi(args, expected):
    assert check(args, c("bbox_intersects_aoi"), REF) is expected


def test_bbox_check_not_applicable_without_aoi():
    ref = REF.model_copy(update={"aoi": None})
    assert check({"bbox": [0, 0, 1, 1]}, c("bbox_intersects_aoi"), ref) is None


def test_bbox_falls_back_to_aoi_bbox_without_geometry():
    ref = REF.model_copy(update={"aoi": REF.aoi.model_copy(update={"geometry": None})})
    assert check({"bbox": [-119, 35, -118, 35.5]}, c("bbox_intersects_aoi"), ref) is True
    assert check({"bbox": [10, 10, 11, 11]}, c("bbox_intersects_aoi"), ref) is False


def test_custom_candidate_arg_names():
    con = c("bbox_intersects_aoi", args=["area"])
    assert check({"area": [-119, 35, -118, 35.5]}, con, REF) is True
    assert check({"bbox": [-119, 35, -118, 35.5]}, con, REF) is None


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"point": [-118.5, 35.2]}, True),
        ({"lonlat": {"lon": -118.5, "lat": 35.2}}, True),
        ({"coordinates": {"type": "Point", "coordinates": [-118.5, 35.2]}}, True),
        ({"point": [-80.0, 40.0]}, False),
        ({"point": "nowhere"}, False),
        ({}, None),
    ],
)
def test_point_within_aoi(args, expected):
    assert check(args, c("point_within_aoi"), REF) is expected


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"collection": "naip"}, True),
        ({"collections": ["naip"]}, True),
        ({"collection": " NAIP "}, True),
        ({"collections": ["naip", "sentinel-2-l2a"]}, False),
        ({"collection": "sentinel-2-l2a"}, False),
        ({"collections": []}, False),
        ({"bbox": [0, 0, 1, 1]}, None),
    ],
)
def test_collection_in(args, expected):
    assert check(args, c("collection_in", values=["naip"]), REF) is expected


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"datetime": "2022"}, True),
        ({"year": 2022}, True),
        ({"date": "2022-06-01"}, True),
        ({"datetime": "2022-06-01T00:00:00Z"}, True),
        ({"datetime": "2022-01-01/2022-12-31"}, True),
        ({"datetime": "2022-01-01T00:00:00Z/2022-12-31T23:59:59Z"}, True),
        ({"datetime": "2021-06-01/2022-06-01"}, False),
        ({"datetime": "2022-01-01/.."}, False),  # open-ended
        ({"datetime": "2021"}, False),
        ({"datetime": "last summer"}, False),
        ({}, None),
    ],
)
def test_datetime_within_year(args, expected):
    assert check(args, c("datetime_within_year", value="2022"), REF) is expected


def test_datetime_within_year_accepts_int_value():
    assert check({"datetime": "2022"}, c("datetime_within_year", value=2022), REF) is True


@pytest.mark.parametrize(
    "args, expected",
    [
        ({"k": 5}, True),
        ({"limit": 10}, True),
        ({"top_k": "3"}, True),
        ({"k": 11}, False),
        ({"k": "many"}, False),
        ({}, None),
    ],
)
def test_k_at_most(args, expected):
    assert check(args, c("k_at_most", value=10), REF) is expected
