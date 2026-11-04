"""Similarity search over pre-staged Clay v1.5 embeddings from LGND (F14, architecture §15).

The staged file (``scripts/stage_embeddings.py``) holds one row per chip and month:

=============  =========================================================================
column         meaning
=============  =========================================================================
chips_id       chip ID (one 1280 m Sentinel-2 L2A chip on the Major TOM grid, one month)
cell_id        grid cell ID (the same place in every month)
datetime       acquisition time of the aggregated scene, ISO 8601 text
year, month    partition of the source dataset
aoi            AOI the chip was staged for
xmin ... ymax  chip bounding box, WGS84
geometry       chip footprint, WKB
embedding      256 float32 values
=============  =========================================================================

Everything here is deterministic for the same staged file and input (FR-14.5): similarities are
rounded to 6 decimals before ranking and ties are broken by ``chips_id``.

Data: Clay v1.5 embeddings by LGND, Sentinel-2 L2A, monthly aggregated, 1280 m chips, 256
dimensions, CC BY 4.0 (https://source.coop/clay/lgnd-embeddings).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import duckdb
import numpy as np
import shapely
from shapely.geometry import Point

STAGED_FILE = "staged.parquet"
ATTRIBUTION = (
    "Clay v1.5 embeddings by LGND (Sentinel-2 L2A, monthly aggregated, 1280 m chips, "
    "256 dimensions), CC BY 4.0, https://source.coop/clay/lgnd-embeddings"
)
SIMILARITY_DECIMALS = 6


class EmbeddingsError(ValueError):
    """A query the staged data can't answer (no chip at the point, unstaged month, ...)."""


def default_data_dir() -> Path:
    """``$CLAY_EMBEDDINGS_DATA``, else ``data/embeddings`` at the repository root."""
    env = os.environ.get("CLAY_EMBEDDINGS_DATA")
    if env:
        return Path(env)
    return Path(__file__).resolve().parents[2] / "data" / "embeddings"


@dataclass(frozen=True)
class Chip:
    chips_id: str
    cell_id: str
    datetime: str
    year: int
    month: int
    aoi: str
    bbox: tuple[float, float, float, float]
    geometry: Any  # shapely geometry

    def as_dict(self) -> dict[str, Any]:
        return {
            "chips_id": self.chips_id,
            "cell_id": self.cell_id,
            "datetime": self.datetime,
            "year": self.year,
            "month": self.month,
            "bbox": list(self.bbox),
            "geometry": shapely.geometry.mapping(self.geometry),
        }


class EmbeddingIndex:
    """The staged chips of one file, loaded once, with L2-normalised float32 vectors."""

    def __init__(self, path: Path | str) -> None:
        path = Path(path)
        if path.is_dir():
            path = path / STAGED_FILE
        if not path.is_file():
            raise FileNotFoundError(
                f"staged embeddings not found at {path}; run scripts/stage_embeddings.py"
            )
        self.path = path
        con = duckdb.connect()
        order = "ORDER BY year, month, chips_id"
        rows = con.execute(
            "SELECT chips_id, cell_id, datetime, year, month, aoi, xmin, ymin, xmax, ymax, "
            f"geometry FROM read_parquet(?) {order}",
            [str(path)],
        ).fetchall()
        embeddings = con.execute(
            f"SELECT embedding FROM read_parquet(?) {order}", [str(path)]
        ).fetchnumpy()["embedding"]
        con.close()
        geometries = shapely.from_wkb([bytes(r[10]) for r in rows])
        self.chips: list[Chip] = [
            Chip(cid, cell, str(dt), int(year), int(month), aoi, (x0, y0, x1, y1), geom)
            for (cid, cell, dt, year, month, aoi, x0, y0, x1, y1, _), geom in zip(
                rows, geometries, strict=True
            )
        ]
        if len(embeddings):
            matrix = np.stack(list(embeddings)).astype(np.float32)
        else:
            matrix = np.zeros((0, 256), dtype=np.float32)
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        self.vectors = matrix / norms
        self._bounds = np.asarray([c.bbox for c in self.chips], dtype=np.float64).reshape(-1, 4)
        self._year = np.asarray([c.year for c in self.chips], dtype=np.int32)
        self._month = np.asarray([c.month for c in self.chips], dtype=np.int32)
        self._by_id = {c.chips_id: i for i, c in enumerate(self.chips)}

    # -- queries --------------------------------------------------------------------------

    def months(self) -> list[tuple[int, int]]:
        return sorted({(c.year, c.month) for c in self.chips})

    def _month_mask(self, year: int, month: int) -> np.ndarray:
        mask = (self._year == year) & (self._month == month)
        if not mask.any():
            staged = ", ".join(f"{y}-{m:02d}" for y, m in self.months())
            raise EmbeddingsError(f"{year}-{month:02d} is not staged (staged months: {staged})")
        return mask

    def chip_index_at(self, lat: float, lon: float, year: int, month: int) -> int:
        """Index of the chip whose footprint contains the point (lowest ``chips_id`` if several)."""
        _check_point(lat, lon)
        mask = self._month_mask(year, month)
        b = self._bounds
        near = np.flatnonzero(
            mask & (b[:, 0] <= lon) & (b[:, 2] >= lon) & (b[:, 1] <= lat) & (b[:, 3] >= lat)
        )
        point = Point(lon, lat)
        hits = [int(i) for i in near if self.chips[i].geometry.covers(point)]
        if not hits:
            raise EmbeddingsError(
                f"no staged chip contains ({lat}, {lon}) in {year}-{month:02d}; only the staged "
                f"areas are searchable"
            )
        return min(hits, key=lambda i: self.chips[i].chips_id)

    def embedding_at(self, lat: float, lon: float, year: int, month: int) -> dict[str, Any]:
        """The chip at a point and month (FR-14.2)."""
        return self.chips[self.chip_index_at(lat, lon, year, month)].as_dict()

    def similar_places(
        self,
        lat: float | None = None,
        lon: float | None = None,
        year: int | None = None,
        month: int | None = None,
        k: int = 10,
        search_bbox: list[float] | None = None,
        chip_id: str | None = None,
    ) -> dict[str, Any]:
        """The ``k`` chips most similar to the query chip by cosine similarity (FR-14.1).

        The query is the chip at ``(lat, lon)`` in ``year``/``month``, or ``chip_id``. Candidates
        are the other chips of the same month whose bbox intersects ``search_bbox``
        (``[west, south, east, north]``; default: every staged chip of that month).
        """
        if not 1 <= k <= 100:
            raise EmbeddingsError("k must be between 1 and 100")
        if chip_id is not None:
            if chip_id not in self._by_id:
                raise EmbeddingsError(f"unknown chip_id {chip_id!r}")
            q = self._by_id[chip_id]
            year, month = self.chips[q].year, self.chips[q].month
        else:
            if lat is None or lon is None or year is None or month is None:
                raise EmbeddingsError("give lat, lon, year and month, or chip_id")
            q = self.chip_index_at(lat, lon, year, month)
        mask = self._month_mask(year, month)
        if search_bbox is not None:
            west, south, east, north = _check_bbox(search_bbox)
            b = self._bounds
            mask &= (b[:, 2] >= west) & (b[:, 0] <= east) & (b[:, 3] >= south) & (b[:, 1] <= north)
        mask[q] = False
        candidates = np.flatnonzero(mask)
        sims = np.round(self.vectors[candidates] @ self.vectors[q], SIMILARITY_DECIMALS)
        order = sorted(range(len(candidates)),
                       key=lambda j: (-float(sims[j]), self.chips[candidates[j]].chips_id))[:k]
        results = []
        for j in order:
            chip = self.chips[candidates[j]].as_dict()
            chip["similarity"] = float(sims[j])
            results.append(chip)
        return {
            "query": self.chips[q].as_dict(),
            "k": k,
            "search_bbox": search_bbox,
            "candidates": int(len(candidates)),
            "results": results,
            "attribution": ATTRIBUTION,
        }


def _check_point(lat: float, lon: float) -> None:
    if not (-90 <= lat <= 90 and -180 <= lon <= 180):
        raise EmbeddingsError(f"({lat}, {lon}) is not a WGS84 latitude/longitude")


def _check_bbox(bbox: list[float]) -> tuple[float, float, float, float]:
    if len(bbox) != 4:
        raise EmbeddingsError("search_bbox must be [west, south, east, north]")
    west, south, east, north = (float(v) for v in bbox)
    if not (west < east and south < north):
        raise EmbeddingsError("search_bbox must be [west, south, east, north]")
    return west, south, east, north


_INDEXES: dict[Path, EmbeddingIndex] = {}


def load_index(data: Path | str | None = None) -> EmbeddingIndex:
    """The index for a staged directory or file, loaded once per process."""
    path = Path(data) if data is not None else default_data_dir()
    key = path.resolve()
    if key not in _INDEXES:
        _INDEXES[key] = EmbeddingIndex(path)
    return _INDEXES[key]


def embedding_at(
    lat: float, lon: float, year: int, month: int, data: Path | str | None = None
) -> dict[str, Any]:
    return load_index(data).embedding_at(lat, lon, year, month)


def similar_places(
    lat: float | None = None,
    lon: float | None = None,
    year: int | None = None,
    month: int | None = None,
    k: int = 10,
    search_bbox: list[float] | None = None,
    chip_id: str | None = None,
    data: Path | str | None = None,
) -> dict[str, Any]:
    return load_index(data).similar_places(lat, lon, year, month, k, search_bbox, chip_id)
