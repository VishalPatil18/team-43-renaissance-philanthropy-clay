#!/usr/bin/env python3
"""Stage the LGND embeddings the clay-embeddings server needs (VIS-R2-01, FR-14.3, FR-14.4).

Source: Clay v1.5 embeddings by LGND on Source Cooperative (public, no credentials, CC BY 4.0)::

    s3://us-west-2.opendata.source.coop/clay/lgnd-embeddings/monthly-aggregated/
      model_version=v1.5/collection=sentinel-2-l2a/chip_size=1280m/dims=256/
      geohash=<2 chars>/year=<yyyy>/month=<mm>/<file>.parquet

For each AOI in ``tasks/aois.yaml``, the script finds the precision-2 geohash partitions that
cover the AOI bbox plus a buffer (default 10 km), reads only the chosen months of those
partitions with DuckDB, keeps the chips whose bbox intersects the buffered AOI bbox, and writes:

* ``data/embeddings/staged.parquet``: one row per chip and month (columns in
  ``clay_embeddings.core``), sorted by year, month, chips_id;
* ``data/embeddings/staging_manifest.json``: partitions read, months, buffer, row counts per AOI
  and month, and the sha256 of ``staged.parquet``.

``data/`` is gitignored. To share the staged files, copy them to the sandbox bucket (not deployed
yet; the bucket name comes from the CDK stack outputs)::

    aws s3 cp data/embeddings/ s3://<sandbox-bucket>/data/embeddings/ --recursive

Usage::

    uv run python scripts/stage_embeddings.py                  # January and July 2024
    uv run python scripts/stage_embeddings.py --month 2024-07 --buffer-km 5
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import boto3
import duckdb
import yaml
from botocore import UNSIGNED
from botocore.config import Config

REPO = Path(__file__).resolve().parents[1]
BUCKET = "us-west-2.opendata.source.coop"
PREFIX = (
    "clay/lgnd-embeddings/monthly-aggregated/model_version=v1.5/collection=sentinel-2-l2a/"
    "chip_size=1280m/dims=256"
)
DEFAULT_MONTHS = ["2024-01", "2024-07"]  # June 2024 is missing from every AOI partition
GEOHASH_BASE32 = "0123456789bcdefghjkmnpqrstuvwxyz"


def geohash(lat: float, lon: float, precision: int = 2) -> str:
    lat_range, lon_range = [-90.0, 90.0], [-180.0, 180.0]
    out, bits, value, even = "", 0, 0, True
    while len(out) < precision:
        rng, coord = (lon_range, lon) if even else (lat_range, lat)
        mid = (rng[0] + rng[1]) / 2
        if coord >= mid:
            value, rng[0] = value * 2 + 1, mid
        else:
            value, rng[1] = value * 2, mid
        even, bits = not even, bits + 1
        if bits == 5:
            out, bits, value = out + GEOHASH_BASE32[value], 0, 0
    return out


def covering_geohashes(bbox: list[float], precision: int = 2) -> list[str]:
    """Every geohash cell touching the bbox (sampled finer than the cell size)."""
    west, south, east, north = bbox
    step = 0.5  # precision-2 cells are 11.25° x 5.625°
    lats = [south + i * step for i in range(int((north - south) / step) + 1)] + [north]
    lons = [west + i * step for i in range(int((east - west) / step) + 1)] + [east]
    return sorted({geohash(lat, lon, precision) for lat in lats for lon in lons})


def buffered(bbox: list[float], km: float) -> list[float]:
    west, south, east, north = bbox
    dlat = km / 111.32
    dlon = km / (111.32 * math.cos(math.radians((south + north) / 2)))
    return [west - dlon, south - dlat, east + dlon, north + dlat]


def list_partition(s3: Any, gh: str, year: int, month: int) -> list[str]:
    prefix = f"{PREFIX}/geohash={gh}/year={year}/month={month:02d}/"
    keys: list[str] = []
    for page in s3.get_paginator("list_objects_v2").paginate(Bucket=BUCKET, Prefix=prefix):
        keys += [o["Key"] for o in page.get("Contents", []) if o["Key"].endswith(".parquet")]
    return sorted(keys)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--month", action="append", help="YYYY-MM (repeatable)")
    parser.add_argument("--buffer-km", type=float, default=10.0)
    parser.add_argument("--aois", default=str(REPO / "tasks" / "aois.yaml"))
    parser.add_argument("--out", default=str(REPO / "data" / "embeddings"))
    args = parser.parse_args()
    months = [(int(m[:4]), int(m[5:7])) for m in (args.month or DEFAULT_MONTHS)]
    aois = yaml.safe_load(Path(args.aois).read_text(encoding="utf-8"))["aois"]
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)

    s3 = boto3.client("s3", region_name="us-west-2", config=Config(signature_version=UNSIGNED))
    con = duckdb.connect()
    con.execute("INSTALL httpfs; LOAD httpfs; SET s3_region='us-west-2';")
    con.execute(
        "CREATE TABLE staged (chips_id VARCHAR, cell_id VARCHAR, datetime VARCHAR, year INTEGER,"
        " month INTEGER, aoi VARCHAR, xmin DOUBLE, ymin DOUBLE, xmax DOUBLE, ymax DOUBLE,"
        " geometry BLOB, embedding FLOAT[256])"
    )
    partitions: list[dict[str, Any]] = []
    for aoi in aois:
        west, south, east, north = buffered(aoi["bbox"], args.buffer_km)
        for gh in covering_geohashes([west, south, east, north]):
            for year, month in months:
                keys = list_partition(s3, gh, year, month)
                if not keys:
                    print(f"  {aoi['id']}: no partition geohash={gh} {year}-{month:02d}")
                    continue
                t0 = time.monotonic()
                urls = [f"s3://{BUCKET}/{k}" for k in keys]
                con.execute(
                    "INSERT INTO staged SELECT chips_id, cell_id, datetime::VARCHAR, year, "
                    "month::INTEGER, ?, bbox.xmin, bbox.ymin, bbox.xmax, bbox.ymax, "
                    "ST_AsWKB(geometry), embedding::FLOAT[256] FROM read_parquet(?) "
                    "WHERE bbox.xmax >= ? AND bbox.xmin <= ? AND bbox.ymax >= ? AND bbox.ymin <= ?",
                    [aoi["id"], urls, west, east, south, north],
                )
                partitions.append({"aoi": aoi["id"], "geohash": gh, "year": year,
                                   "month": month, "keys": keys})
                print(f"  {aoi['id']} geohash={gh} {year}-{month:02d}: "
                      f"{len(keys)} file(s) in {time.monotonic() - t0:.1f} s")

    # A chip within the buffer of two AOIs is kept once (first AOI in file order).
    order = {a["id"]: i for i, a in enumerate(aois)}
    con.execute("CREATE TABLE aoi_order (aoi VARCHAR, n INTEGER)")
    con.executemany("INSERT INTO aoi_order VALUES (?, ?)", list(order.items()))
    staged_file = out / "staged.parquet"
    con.execute(
        f"""COPY (
              SELECT s.* EXCLUDE (n) FROM (
                SELECT staged.*, aoi_order.n, row_number() OVER (
                  PARTITION BY chips_id ORDER BY aoi_order.n) AS r
                FROM staged JOIN aoi_order USING (aoi)) s
              WHERE r = 1 ORDER BY year, month, chips_id
            ) TO '{staged_file}' (FORMAT parquet, COMPRESSION zstd)"""
    )
    con.execute("ALTER TABLE staged RENAME TO raw")
    counts = con.execute(
        "SELECT aoi, year, month, count(*) FROM read_parquet(?) GROUP BY ALL ORDER BY ALL",
        [str(staged_file)],
    ).fetchall()
    total = sum(c[3] for c in counts)
    digest = hashlib.sha256(staged_file.read_bytes()).hexdigest()
    manifest = {
        "source": f"s3://{BUCKET}/{PREFIX}",
        "license": "CC BY 4.0 (Clay v1.5 embeddings by LGND)",
        "months": [f"{y}-{m:02d}" for y, m in months],
        "buffer_km": args.buffer_km,
        "aois_file": str(Path(args.aois).relative_to(REPO)) if Path(args.aois).is_relative_to(REPO)
        else args.aois,
        "partitions": partitions,
        "rows": [{"aoi": a, "year": y, "month": m, "chips": n} for a, y, m, n in counts],
        "total_rows": total,
        "file": staged_file.name,
        "bytes": staged_file.stat().st_size,
        "sha256": digest,
        "created_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "duckdb": duckdb.__version__,
    }
    (out / "staging_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n",
                                               encoding="utf-8")
    print(f"wrote {staged_file} ({total} rows, {staged_file.stat().st_size / 1e6:.1f} MB, "
          f"sha256 {digest[:12]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
