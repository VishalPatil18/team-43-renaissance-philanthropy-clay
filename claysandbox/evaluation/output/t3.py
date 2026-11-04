"""T3 output evaluator: predicted solar sites against reference polygons (GRW).

Reference keys (built by WS2):
  ``output_reference["sites"]``: list of GeoJSON geometries (Polygon/MultiPolygon, or Features
  wrapping one) in EPSG:4326. Empty for a negative-control AOI (no solar).
  ``output_reference.get("tolerance_m", 500)``: match tolerance in metres.
Output: ``{"sites": [...]}`` (or ``{"locations": ...}``); each site is ``[lon, lat]``,
``{"lon": .., "lat": ..}`` (``lng``/``longitude``/``latitude`` accepted) or a GeoJSON geometry.

A prediction matches a reference polygon when it lies inside it or within the tolerance of it,
measured in an azimuthal equidistant projection centred on the AOI centroid (the reference
polygons' centroid if the task has no AOI). Matching is greedy and one-to-one, nearest pairs
first. Precision = matched / predicted, recall = matched / reference, composite = F1.
Empty reference and empty output: P = R = 1. Empty reference with output: P = 0 (R = 1 as
nothing was missed). Empty output with a non-empty reference: P = 1 (vacuous), R = 0.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import shapely
from pyproj import Transformer
from shapely.geometry import Point, shape
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from claysandbox.contracts.registry import register

from ._common import OutputEvaluator, ParseError, f1, precision_recall

DEFAULT_TOLERANCE_M = 500.0
_LON = ("lon", "lng", "longitude")
_LAT = ("lat", "latitude")


def _geometry(raw: Any) -> BaseGeometry:
    if isinstance(raw, dict) and raw.get("type") == "Feature":
        raw = raw.get("geometry")
    if isinstance(raw, list | tuple) and len(raw) == 2:
        lon, lat = raw
    elif isinstance(raw, dict) and "type" in raw:
        try:
            return shape(raw)
        except (ValueError, KeyError, TypeError, AttributeError) as e:
            raise ParseError(f"invalid GeoJSON geometry: {e}") from e
    elif isinstance(raw, dict):
        lon = next((raw[k] for k in _LON if k in raw), None)
        lat = next((raw[k] for k in _LAT if k in raw), None)
    else:
        raise ParseError(f"cannot read a site from {raw!r}")
    if not isinstance(lon, int | float) or not isinstance(lat, int | float):
        raise ParseError(f"site coordinates must be numbers: {raw!r}")
    if not (-180 <= lon <= 180 and -90 <= lat <= 90):
        raise ParseError(f"site coordinates out of range: {raw!r}")
    return Point(lon, lat)


def _sites(raw: Any, keys: tuple[str, ...]) -> list[BaseGeometry]:
    if isinstance(raw, dict):
        for k in keys:
            if k in raw:
                raw = raw[k]
                break
        else:
            raise ParseError(f"none of the keys {list(keys)} found")
    if not isinstance(raw, list):
        raise ParseError("expected a list of sites")
    geoms = [_geometry(s) for s in raw]
    return [g for g in geoms if not g.is_empty]


@register("evaluator", "output.t3@1")
@register("evaluator", "output.t3")
class T3Evaluator(OutputEvaluator):
    name = "output.t3"
    metric_names = ("precision", "recall", "f1")
    composite_metric = "f1"

    def score(self, output, trace, manifest, reference, event_id):  # type: ignore[no-untyped-def]
        ref_geoms = _sites(reference.output_reference.get("sites", []), ("sites",))
        pred = _sites(output, ("sites", "locations"))
        tol = float(reference.output_reference.get("tolerance_m", DEFAULT_TOLERANCE_M))

        matched = 0
        if pred and ref_geoms:
            matched = self._match(pred, ref_geoms, tol, reference)
        p, r = precision_recall(matched, len(pred), len(ref_geoms))
        notes = [
            f"{matched} of {len(pred)} predicted and {len(ref_geoms)} reference sites matched"
            f" within {tol:g} m"
        ]
        return {"precision": p, "recall": r, "f1": f1(p, r)}, notes, []

    @staticmethod
    def _match(
        pred: list[BaseGeometry], refs: list[BaseGeometry], tol: float, reference: Any
    ) -> int:
        aoi = reference.aoi
        if aoi is not None and aoi.geometry:
            centre = shape(aoi.geometry).centroid
        elif aoi is not None and len(aoi.bbox) == 4:
            centre = Point((aoi.bbox[0] + aoi.bbox[2]) / 2, (aoi.bbox[1] + aoi.bbox[3]) / 2)
        else:
            centre = unary_union(refs).centroid
        proj = f"+proj=aeqd +lat_0={centre.y} +lon_0={centre.x} +x_0=0 +y_0=0 +datum=WGS84 +units=m"
        tf = Transformer.from_crs("EPSG:4326", proj, always_xy=True)

        def to_m(g: BaseGeometry) -> BaseGeometry:
            def fn(xy: np.ndarray) -> np.ndarray:
                x, y = tf.transform(xy[:, 0], xy[:, 1])
                return np.column_stack([x, y])

            return shapely.transform(g, fn)

        p_m = [to_m(g) for g in pred]
        r_m = [to_m(g) for g in refs]
        pairs = sorted(
            (d, i, j)
            for i, pg in enumerate(p_m)
            for j, rg in enumerate(r_m)
            if (d := pg.distance(rg)) <= tol
        )
        used_p: set[int] = set()
        used_r: set[int] = set()
        for _d, i, j in pairs:
            if i not in used_p and j not in used_r:
                used_p.add(i)
                used_r.add(j)
        return len(used_p)
