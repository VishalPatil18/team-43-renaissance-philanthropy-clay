#!/usr/bin/env python3
"""Print the T4 query point of each AOI, for ``template_params.T4`` in ``tasks/aois.yaml``.

* Counties with solar (tag ``has_solar``): the centroid of the largest Global Renewables Watch
  solar polygon in the county built by 2023 (so it exists in the 2024 embeddings).
* Negative controls: a named landmark, listed in ``LANDMARKS`` below.

The point is checked to lie inside the county geometry.

    uv run python scripts/pick_t4_points.py
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import yaml
from shapely.geometry import Point, shape

from claysandbox.tasks.library import FileTaskLibrary

REPO = Path(__file__).resolve().parents[1]
LANDMARKS = {
    "us-ny-new-york": ("Central Park", 40.7829, -73.9654),
    "us-ny-hamilton": ("Indian Lake (hamlet)", 43.7826, -74.2721),
}


def t3_builder() -> ModuleType:
    path = REPO / "tasks" / "builders" / "t3_solar_sites.py"
    spec = importlib.util.spec_from_file_location("t3_solar_sites", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def main() -> int:
    t3 = t3_builder()
    out = {}
    for aoi in FileTaskLibrary().list_aois():
        if aoi.id in LANDMARKS:
            name, lat, lon = LANDMARKS[aoi.id]
        else:
            sites = [
                s["properties"]
                for s in t3.solar_sites(aoi)
                if (s["properties"]["construction_year"] or 9999) <= 2023
            ]
            if not sites:
                print(f"{aoi.id}: no GRW site built by 2023 and no landmark", file=sys.stderr)
                return 1
            best = max(sites, key=lambda s: (s["area_m2"], -s["grw_fid"]))
            name = f"solar PV installation (Global Renewables Watch feature {best['grw_fid']})"
            lat, lon = best["lat"], best["lon"]
        if not shape(aoi.geometry).contains(Point(lon, lat)):
            print(f"{aoi.id}: point ({lat}, {lon}) is outside the county", file=sys.stderr)
            return 1
        out[aoi.id] = {"query_name": name, "query_lat": round(lat, 5), "query_lon": round(lon, 5)}
    yaml.safe_dump(out, sys.stdout, sort_keys=False, width=100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
