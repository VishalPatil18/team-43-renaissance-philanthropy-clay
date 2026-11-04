"""T3 reference builder: Global Renewables Watch solar PV polygons inside the AOI.

Source: Global Renewables Watch v1.0, ``solar_all_2024q2_v1.gpkg`` from
https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0 (MIT): 86,345 solar PV
polygons worldwide, detected in satellite imagery up to the second quarter of 2024, in EPSG:3857.
The file (395 MB) is downloaded once to ``~/.cache/claysandbox/grw/`` and checked by sha256.

The key is every polygon that intersects the AOI geometry (the simplified county boundary in
``tasks/aois.yaml``), sorted by GRW feature ID, as GeoJSON Features: the footprint (simplified by
0.0001°) as ``geometry`` and the GRW feature ID, centroid (WGS84), area and construction quarter
as ``properties``. The two negative-control AOIs have no polygons, so their correct answer is an
empty list. ``output.t3`` matches the agent's points to the footprints within ``tolerance_m``
(500 m).

The GeoPackage is read with sqlite3 and its R-tree index; geometries are converted from Web
Mercator with the closed-form inverse (no pyproj needed).
"""

from __future__ import annotations

import hashlib
import math
import os
import sqlite3
import struct
import urllib.request
from pathlib import Path
from typing import Any

import numpy as np
import shapely
from shapely.geometry import mapping, shape

from claysandbox.contracts.task import AOI, TaskInstance, TaskTemplate
from claysandbox.tasks.references import BuildResult

GRW_URL = (
    "https://github.com/microsoft/global-renewables-watch/releases/download/v1.0/"
    "solar_all_2024q2_v1.gpkg"
)
GRW_SHA256 = "9f27c76313fcd78418a7277e4f7526c536887965fd3ef80160ed1d1ceedf947b"
GRW_TABLE = "solar_all_2024q2"
TOLERANCE_M = 500
EARTH_RADIUS = 6378137.0
DECIMALS = 6
# Footprints are simplified by 0.0001 deg (at most ~17 m off the original outline, far below the
# 500 m tolerance) to keep reference files small: Kern has 241 polygons with 66,835 vertices.
SIMPLIFY_DEG = 1e-4


def cache_path() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claysandbox" / "grw" / "solar_all_2024q2_v1.gpkg"


def ensure_grw() -> Path:
    path = cache_path()
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        part = path.with_suffix(".part")
        urllib.request.urlretrieve(GRW_URL, part)  # noqa: S310
        part.rename(path)
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    if digest.hexdigest() != GRW_SHA256:
        raise RuntimeError(f"{path} has the wrong sha256; delete it and rebuild")
    return path


def to_mercator(lon: float, lat: float) -> tuple[float, float]:
    x = math.radians(lon) * EARTH_RADIUS
    y = math.log(math.tan(math.pi / 4 + math.radians(lat) / 2)) * EARTH_RADIUS
    return x, y


def _to_wgs84(coords: np.ndarray) -> np.ndarray:
    lon = np.degrees(coords[:, 0] / EARTH_RADIUS)
    lat = np.degrees(2 * np.arctan(np.exp(coords[:, 1] / EARTH_RADIUS)) - math.pi / 2)
    return np.column_stack([lon, lat])


def gpkg_geometry(blob: bytes) -> Any:
    """Decode a GeoPackage geometry blob (header + WKB) into a shapely geometry."""
    if blob[:2] != b"GP":
        raise ValueError("not a GeoPackage geometry")
    flags = blob[3]
    envelope = (flags >> 1) & 0b111
    size = {0: 0, 1: 32, 2: 48, 3: 48, 4: 64}[envelope]
    struct.unpack_from("<i" if flags & 1 else ">i", blob, 4)  # srs_id, unused
    return shapely.from_wkb(bytes(blob[8 + size:]))


def solar_sites(aoi: AOI, path: Path | None = None) -> list[dict[str, Any]]:
    """GRW polygons intersecting the AOI geometry, as GeoJSON Features sorted by feature ID."""
    path = path or ensure_grw()
    west, south, east, north = aoi.bbox
    x0, y0 = to_mercator(west, south)
    x1, y1 = to_mercator(east, north)
    area = shape(aoi.geometry)
    con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        rows = con.execute(
            f"""SELECT t.fid, t.geom, t.layer, t.construction_year, t.construction_quarter,
                       t.landcover_in_2018, t.area
                FROM {GRW_TABLE} t JOIN rtree_{GRW_TABLE}_geom r ON t.fid = r.id
                WHERE r.maxx >= ? AND r.minx <= ? AND r.maxy >= ? AND r.miny <= ?
                ORDER BY t.fid""",
            (x0, x1, y0, y1),
        ).fetchall()
    finally:
        con.close()
    sites: list[dict[str, Any]] = []
    for fid, blob, layer, year, quarter, landcover, area_m2 in rows:
        geom = shapely.transform(gpkg_geometry(blob), _to_wgs84)
        if not geom.intersects(area):
            continue
        centroid = geom.centroid
        sites.append(
            {
                "type": "Feature",
                "geometry": mapping(
                    shapely.set_precision(geom.simplify(SIMPLIFY_DEG), 10**-DECIMALS)
                ),
                "properties": {
                    "grw_fid": int(fid),
                    "lat": round(centroid.y, DECIMALS),
                    "lon": round(centroid.x, DECIMALS),
                    "area_m2": round(float(area_m2), 1),
                    "construction_year": year,
                    "construction_quarter": quarter,
                    "landcover_in_2018": landcover,
                    "source_layer": layer,
                },
            }
        )
    return sites


def build(template: TaskTemplate, aoi: AOI, instance: TaskInstance) -> BuildResult:
    sites = solar_sites(aoi)
    expected_empty = "no_solar" in aoi.tags
    if expected_empty and sites:
        raise RuntimeError(f"{aoi.id} is a negative control but GRW has {len(sites)} sites")
    if not expected_empty and not sites:
        raise RuntimeError(f"{aoi.id} is tagged has_solar but GRW has no sites")
    inputs: dict[str, Any] = {
        "dataset": "Global Renewables Watch v1.0 (solar, 2024 Q2)",
        "url": GRW_URL,
        "sha256": GRW_SHA256,
        "license": "MIT",
        "match": "polygon intersects the AOI geometry",
        "sites": len(sites),
    }
    return BuildResult(
        output_reference={"sites": sites, "tolerance_m": TOLERANCE_M},
        inputs=inputs,
        method="script",
    )
