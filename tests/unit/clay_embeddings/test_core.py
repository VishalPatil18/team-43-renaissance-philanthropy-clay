"""clay_embeddings core and server on a tiny synthetic staged file (FR-14.1, FR-14.2, FR-14.5)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import duckdb
import numpy as np
import pytest
import shapely
from clay_embeddings.core import EmbeddingIndex, EmbeddingsError
from shapely.geometry import box

from claysandbox.contracts.tools import ServerDef, ToolSetDef
from claysandbox.tools.launcher import McpStdioToolSession

DIMS = 256


def vector(*head: float) -> list[float]:
    v = np.zeros(DIMS, dtype=np.float32)
    v[: len(head)] = head
    return v.tolist()


# A 3 x 2 grid of 0.01° chips in July 2024, plus one chip in January.
CHIPS = [
    # chips_id, x, y, month, embedding
    ("c00", 0, 0, 7, vector(1, 0)),
    ("c01", 1, 0, 7, vector(1, 0.1)),   # most similar to c00
    ("c02", 2, 0, 7, vector(0, 1)),     # orthogonal
    ("c10", 0, 1, 7, vector(1, 0.1)),   # exact tie with c01: broken by chips_id
    ("c11", 1, 1, 7, vector(-1, 0)),    # opposite
    ("c12", 2, 1, 7, vector(1, 0.5)),
    ("j00", 0, 0, 1, vector(1, 0)),     # same place, other month: never a candidate in July
]


def make_staged(directory: Path) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / "staged.parquet"
    con = duckdb.connect()
    con.execute(
        "CREATE TABLE t (chips_id VARCHAR, cell_id VARCHAR, datetime VARCHAR, year INTEGER, "
        "month INTEGER, aoi VARCHAR, xmin DOUBLE, ymin DOUBLE, xmax DOUBLE, ymax DOUBLE, "
        "geometry BLOB, embedding FLOAT[256])"
    )
    for cid, x, y, month, emb in CHIPS:
        x0, y0 = -100 + x * 0.01, 40 + y * 0.01
        geom = shapely.to_wkb(box(x0, y0, x0 + 0.01, y0 + 0.01))
        con.execute(
            "INSERT INTO t VALUES (?, ?, ?, 2024, ?, 'us-zz-testland', ?, ?, ?, ?, ?, ?)",
            [cid, f"cell{x}{y}", f"2024-{month:02d}-15", month, x0, y0, x0 + 0.01, y0 + 0.01,
             geom, emb],
        )
    con.execute(f"COPY t TO '{path}' (FORMAT parquet)")
    con.close()
    return path


@pytest.fixture
def index(tmp_path: Path) -> EmbeddingIndex:
    return EmbeddingIndex(make_staged(tmp_path / "emb"))


def test_embedding_at_finds_the_containing_chip(index: EmbeddingIndex) -> None:
    chip = index.embedding_at(40.015, -99.985, 2024, 7)
    assert chip["chips_id"] == "c11" and chip["cell_id"] == "cell11"
    assert chip["bbox"] == pytest.approx([-99.99, 40.01, -99.98, 40.02])
    assert chip["geometry"]["type"] == "Polygon"
    assert index.embedding_at(40.005, -99.995, 2024, 1)["chips_id"] == "j00"


def test_point_on_a_shared_edge_picks_the_lowest_chip_id(index: EmbeddingIndex) -> None:
    assert index.embedding_at(40.005, -99.99, 2024, 7)["chips_id"] == "c00"


def test_similar_places_orders_by_similarity_then_chip_id(index: EmbeddingIndex) -> None:
    out = index.similar_places(40.005, -99.995, 2024, 7, k=5)
    ids = [r["chips_id"] for r in out["results"]]
    assert out["query"]["chips_id"] == "c00" and "c00" not in ids
    assert ids == ["c01", "c10", "c12", "c02", "c11"]  # c01/c10 tie, broken by ID
    sims = [r["similarity"] for r in out["results"]]
    assert sims == sorted(sims, reverse=True) and sims[-1] == pytest.approx(-1.0)
    assert out["candidates"] == 5 and "CC BY 4.0" in out["attribution"]


def test_k_and_search_bbox_limit_the_candidates(index: EmbeddingIndex) -> None:
    out = index.similar_places(40.005, -99.995, 2024, 7, k=2, search_bbox=[-99.999, 40.001,
                                                                         -99.981, 40.009])
    assert [r["chips_id"] for r in out["results"]] == ["c01"]  # only c01 is in the box
    assert out["candidates"] == 1


def test_query_by_chip_id_gives_the_same_answer(index: EmbeddingIndex) -> None:
    by_point = index.similar_places(40.005, -99.995, 2024, 7, k=3)
    by_id = index.similar_places(chip_id="c00", k=3)
    assert by_point["results"] == by_id["results"]


def test_results_are_deterministic(tmp_path: Path, index: EmbeddingIndex) -> None:
    again = EmbeddingIndex(make_staged(tmp_path / "again"))
    a = index.similar_places(40.005, -99.995, 2024, 7, k=6)
    b = again.similar_places(40.005, -99.995, 2024, 7, k=6)
    assert json.dumps(a, sort_keys=True) == json.dumps(b, sort_keys=True)


def test_empty_search_area_returns_no_results(index: EmbeddingIndex) -> None:
    out = index.similar_places(40.005, -99.995, 2024, 7, search_bbox=[10, 10, 11, 11])
    assert out["results"] == [] and out["candidates"] == 0


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lat": 0.0, "lon": 0.0, "year": 2024, "month": 7},      # outside the staged area
        {"lat": 40.005, "lon": -99.995, "year": 2024, "month": 6},  # month not staged
        {"lat": 40.005, "lon": -99.995, "year": 2024, "month": 7, "k": 0},
        {"lat": 40.005, "lon": -99.995, "year": 2024, "month": 7, "search_bbox": [1, 2, 3]},
        {"chip_id": "nope"},
        {"lat": 40.005},
    ],
)
def test_bad_queries_raise_embeddings_error(index: EmbeddingIndex, kwargs: dict) -> None:
    with pytest.raises(EmbeddingsError):
        index.similar_places(**kwargs)


def test_missing_staged_file_is_a_clear_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError, match="stage_embeddings"):
        EmbeddingIndex(tmp_path / "missing")


def test_stdio_round_trip_through_the_tool_session(tmp_path: Path) -> None:
    data = make_staged(tmp_path / "emb").parent
    ts = ToolSetDef(
        name="TE",
        servers=[ServerDef(name="clay-embeddings",
                           command=[sys.executable, "-m", "clay_embeddings", "--data", str(data)])],
        capabilities={"embedding_similarity": ["clay-embeddings.similar_places"]},
    )
    with McpStdioToolSession(ts, log_dir=tmp_path) as session:
        tools = {t.name: t for t in session.list_tools()}
        assert set(tools) == {"embedding_at", "similar_places"}
        assert tools["similar_places"].capability == "embedding_similarity"
        assert "CC BY 4.0" in tools["similar_places"].description
        assert "1280 m" in tools["embedding_at"].description
        result = session.call_blocking(
            "clay-embeddings", "similar_places",
            {"lat": 40.005, "lon": -99.995, "year": 2024, "month": 7, "k": 2}, 30,
        )
        assert result.status == "ok"
        body = json.loads(result.text)
        assert [r["chips_id"] for r in body["results"]] == ["c01", "c10"]
        bad = session.call_blocking(
            "clay-embeddings", "embedding_at", {"lat": 0, "lon": 0, "year": 2024, "month": 7}, 30
        )
        assert bad.error_kind == "tool_error" and "only the staged areas" in bad.text
