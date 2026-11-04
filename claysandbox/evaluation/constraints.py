"""Argument-constraint checks for the workflow evaluator (DD-028, architecture §14.2).

Each check is ``(args, constraint, reference) -> bool | None``:

* ``True`` / ``False``: the constraint applies and holds / fails. An argument that is
  present but unparseable fails (the agent sent something unusable).
* ``None``: not applicable, e.g. none of the candidate argument names is in ``args``, or
  the reference lacks what the check needs (no AOI).

Tools name their arguments differently, so each check looks for the first present name in
``constraint.args`` or, when that is unset, the check's defaults in ``DEFAULT_ARGS``.
Geometry is EPSG:4326 and compared with shapely; touching the AOI boundary counts as inside.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from shapely.geometry import Point, box, shape
from shapely.geometry.base import BaseGeometry

from claysandbox.contracts.task import ArgumentConstraint, TaskReference

Check = Callable[[dict[str, Any], ArgumentConstraint, TaskReference], bool | None]

DEFAULT_ARGS: dict[str, list[str]] = {
    "bbox_intersects_aoi": ["bbox", "bounds"],
    "point_within_aoi": ["point", "lonlat", "coordinates"],
    "collection_in": ["collection", "collections"],
    "datetime_within_year": ["datetime", "date", "year"],
    "k_at_most": ["k", "limit", "top_k"],
}

_MISSING = object()


def _arg(args: dict[str, Any], constraint: ArgumentConstraint) -> Any:
    for name in constraint.args or DEFAULT_ARGS[constraint.check]:
        if name in args:
            return args[name]
    return _MISSING


def _aoi_geometry(reference: TaskReference) -> BaseGeometry | None:
    aoi = reference.aoi
    if aoi is None:
        return None
    if aoi.geometry:
        return shape(aoi.geometry)
    if len(aoi.bbox) == 4:
        return box(*aoi.bbox)
    return None


def _floats(value: Any) -> list[float] | None:
    if isinstance(value, str):
        value = value.split(",")
    if not isinstance(value, list | tuple):
        return None
    try:
        return [float(v) for v in value]
    except (TypeError, ValueError):
        return None


def _as_bbox_geometry(value: Any) -> BaseGeometry | None:
    if isinstance(value, dict) and "type" in value:
        try:
            return shape(value)
        except (ValueError, KeyError, TypeError, AttributeError):
            return None
    nums = _floats(value)
    if nums is None or len(nums) != 4:
        return None
    minx, miny, maxx, maxy = nums
    if minx > maxx or miny > maxy:
        return None
    return box(minx, miny, maxx, maxy)


def _as_point(value: Any) -> BaseGeometry | None:
    if isinstance(value, dict):
        if "type" in value:
            try:
                geom = shape(value)
            except (ValueError, KeyError, TypeError, AttributeError):
                return None
            return geom if geom.geom_type == "Point" else None
        lon = value.get("lon", value.get("lng", value.get("longitude")))
        lat = value.get("lat", value.get("latitude"))
        value = [lon, lat]
    nums = _floats(value)
    if nums is None or len(nums) != 2:
        return None
    return Point(nums[0], nums[1])


def bbox_intersects_aoi(
    args: dict[str, Any], constraint: ArgumentConstraint, reference: TaskReference
) -> bool | None:
    value = _arg(args, constraint)
    aoi = _aoi_geometry(reference)
    if value is _MISSING or aoi is None:
        return None
    geom = _as_bbox_geometry(value)
    return geom is not None and geom.intersects(aoi)


def point_within_aoi(
    args: dict[str, Any], constraint: ArgumentConstraint, reference: TaskReference
) -> bool | None:
    value = _arg(args, constraint)
    aoi = _aoi_geometry(reference)
    if value is _MISSING or aoi is None:
        return None
    point = _as_point(value)
    return point is not None and aoi.covers(point)


def collection_in(
    args: dict[str, Any], constraint: ArgumentConstraint, reference: TaskReference
) -> bool | None:
    value = _arg(args, constraint)
    allowed_raw = constraint.values if constraint.values is not None else constraint.value
    if value is _MISSING or allowed_raw is None:
        return None
    if not isinstance(allowed_raw, list):
        allowed_raw = [allowed_raw]
    allowed = {str(v).strip().casefold() for v in allowed_raw}
    given = value if isinstance(value, list) else [value]
    return bool(given) and all(str(v).strip().casefold() in allowed for v in given)


_YEAR = re.compile(r"^\s*(\d{4})(?:$|[-T\s])")


def _year_of(text: str) -> int | None:
    m = _YEAR.match(text)
    return int(m.group(1)) if m else None


def datetime_within_year(
    args: dict[str, Any], constraint: ArgumentConstraint, reference: TaskReference
) -> bool | None:
    """Year, ISO date/datetime, or ``start/end`` interval, all inside the year.

    Open interval ends (``..`` or empty) are not within any single year.
    """
    value = _arg(args, constraint)
    if value is _MISSING:
        return None
    try:
        year = int(str(constraint.value).strip())
    except ValueError:
        return None
    if isinstance(value, int) and not isinstance(value, bool):
        return value == year
    if not isinstance(value, str):
        return False
    ends = value.split("/")
    if len(ends) > 2:
        return False
    return all(_year_of(end) == year for end in ends)


def k_at_most(
    args: dict[str, Any], constraint: ArgumentConstraint, reference: TaskReference
) -> bool | None:
    value = _arg(args, constraint)
    if value is _MISSING:
        return None
    try:
        limit = float(constraint.value)
    except (TypeError, ValueError):
        return None
    if isinstance(value, bool):
        return False
    try:
        return float(value) <= limit
    except (TypeError, ValueError):
        return False


CHECKS: dict[str, Check] = {
    "bbox_intersects_aoi": bbox_intersects_aoi,
    "point_within_aoi": point_within_aoi,
    "collection_in": collection_in,
    "datetime_within_year": datetime_within_year,
    "k_at_most": k_at_most,
}


def check(
    args: dict[str, Any], constraint: ArgumentConstraint, reference: TaskReference
) -> bool | None:
    """Run ``constraint.check`` on one tool call's ``args``."""
    return CHECKS[constraint.check](args, constraint, reference)
