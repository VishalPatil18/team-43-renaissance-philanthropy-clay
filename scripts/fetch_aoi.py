#!/usr/bin/env python3
"""Print a ``tasks/aois.yaml`` entry for a US county, from the Census TIGERweb service.

The geometry is the county boundary (layer "Counties" of TIGERweb State_County), simplified by
the server with ``maxAllowableOffset`` (default 0.01°, about 1 km) and rounded to 5 decimals. The
bbox is the bounds of that simplified geometry. Paste the output into ``tasks/aois.yaml``.

    uv run python scripts/fetch_aoi.py 06029 --tag has_solar
    uv run python scripts/fetch_aoi.py 48201 --tag no_solar --offset 0.005

Census TIGER/Line data is public domain.
"""

from __future__ import annotations

import argparse
import json
import sys
import urllib.parse
import urllib.request
from datetime import UTC, datetime
from typing import Any

import yaml
from shapely.geometry import shape

SERVICE = "https://tigerweb.geo.census.gov/arcgis/rest/services/TIGERweb/State_County/MapServer/1"

STATES: dict[str, tuple[str, str]] = {
    "01": ("Alabama", "AL"), "02": ("Alaska", "AK"), "04": ("Arizona", "AZ"),
    "05": ("Arkansas", "AR"), "06": ("California", "CA"), "08": ("Colorado", "CO"),
    "09": ("Connecticut", "CT"), "10": ("Delaware", "DE"), "11": ("District of Columbia", "DC"),
    "12": ("Florida", "FL"), "13": ("Georgia", "GA"), "15": ("Hawaii", "HI"),
    "16": ("Idaho", "ID"), "17": ("Illinois", "IL"), "18": ("Indiana", "IN"),
    "19": ("Iowa", "IA"), "20": ("Kansas", "KS"), "21": ("Kentucky", "KY"),
    "22": ("Louisiana", "LA"), "23": ("Maine", "ME"), "24": ("Maryland", "MD"),
    "25": ("Massachusetts", "MA"), "26": ("Michigan", "MI"), "27": ("Minnesota", "MN"),
    "28": ("Mississippi", "MS"), "29": ("Missouri", "MO"), "30": ("Montana", "MT"),
    "31": ("Nebraska", "NE"), "32": ("Nevada", "NV"), "33": ("New Hampshire", "NH"),
    "34": ("New Jersey", "NJ"), "35": ("New Mexico", "NM"), "36": ("New York", "NY"),
    "37": ("North Carolina", "NC"), "38": ("North Dakota", "ND"), "39": ("Ohio", "OH"),
    "40": ("Oklahoma", "OK"), "41": ("Oregon", "OR"), "42": ("Pennsylvania", "PA"),
    "44": ("Rhode Island", "RI"), "45": ("South Carolina", "SC"), "46": ("South Dakota", "SD"),
    "47": ("Tennessee", "TN"), "48": ("Texas", "TX"), "49": ("Utah", "UT"),
    "50": ("Vermont", "VT"), "51": ("Virginia", "VA"), "53": ("Washington", "WA"),
    "54": ("West Virginia", "WV"), "55": ("Wisconsin", "WI"), "56": ("Wyoming", "WY"),
}


def fetch(fips: str, offset: float) -> dict[str, Any]:
    query = urllib.parse.urlencode(
        {
            "where": f"GEOID='{fips}'",
            "outFields": "GEOID,NAME,BASENAME,STATE",
            "outSR": "4326",
            "maxAllowableOffset": str(offset),
            "geometryPrecision": "5",
            "f": "geojson",
        }
    )
    with urllib.request.urlopen(f"{SERVICE}/query?{query}", timeout=60) as response:  # noqa: S310
        data = json.load(response)
    features = data.get("features") or []
    if len(features) != 1:
        raise SystemExit(f"expected one county for FIPS {fips}, got {len(features)}")
    feature: dict[str, Any] = features[0]
    return feature


def aoi_entry(fips: str, offset: float, tags: list[str], aoi_id: str | None) -> dict[str, Any]:
    feature = fetch(fips, offset)
    props = feature["properties"]
    state, code = STATES[props["STATE"]]
    geom = shape(feature["geometry"])
    west, south, east, north = (round(v, 5) for v in geom.bounds)
    slug = props["BASENAME"].lower().replace(" ", "-").replace(".", "").replace("'", "")
    return {
        "id": aoi_id or f"us-{code.lower()}-{slug}",
        "name": props["NAME"],
        "state": state,
        "state_code": code,
        "fips": fips,
        "bbox": [west, south, east, north],
        "geometry": feature["geometry"],
        "tags": tags,
        "source": f"Census TIGERweb State_County layer 1, maxAllowableOffset={offset}, "
        f"retrieved {datetime.now(UTC):%Y-%m-%d}",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("fips", help="5-digit county FIPS code, e.g. 06029")
    parser.add_argument("--tag", action="append", default=[], help="tag (repeatable)")
    parser.add_argument("--id", help="AOI id (default us-<state>-<county>)")
    parser.add_argument("--offset", type=float, default=0.01, help="simplification, degrees")
    args = parser.parse_args()
    entry = aoi_entry(args.fips, args.offset, args.tag, args.id)
    yaml.safe_dump([entry], sys.stdout, sort_keys=False, default_flow_style=None, width=100)
    return 0


if __name__ == "__main__":
    sys.exit(main())
