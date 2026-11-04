"""T4 reference builder: the top-k similar chips, from the same function the tool uses.

Calls ``clay_embeddings.core.similar_places`` with exactly the inputs the prompt gives (query
point, year, month, k, and the AOI bbox as the search area) over the staged embeddings
(``scripts/stage_embeddings.py``), so the answer key and the ``similar_places`` tool agree by
construction (DD-030). The key records the staged file's sha256: restaging different data gives
a new reference version.

Data: Clay v1.5 embeddings by LGND, CC BY 4.0.
"""

from __future__ import annotations

import json
from typing import Any

from clay_embeddings.core import ATTRIBUTION, default_data_dir, load_index

from claysandbox.contracts.task import AOI, TaskInstance, TaskTemplate
from claysandbox.tasks.references import BuildResult


def build(template: TaskTemplate, aoi: AOI, instance: TaskInstance) -> BuildResult:
    p = instance.params
    data_dir = default_data_dir()
    index = load_index(data_dir)
    result = index.similar_places(
        lat=float(p["query_lat"]),
        lon=float(p["query_lon"]),
        year=int(p["year"]),
        month=int(p["month"]),
        k=int(p["k"]),
        search_bbox=list(aoi.bbox),
    )
    manifest_path = data_dir / "staging_manifest.json"
    manifest: dict[str, Any] = (
        json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {}
    )
    chips = [r["chips_id"] for r in result["results"]]
    inputs: dict[str, Any] = {
        "function": "clay_embeddings.core.similar_places",
        "query": {"lat": p["query_lat"], "lon": p["query_lon"], "name": p["query_name"]},
        "year": p["year"],
        "month": p["month"],
        "k": p["k"],
        "search_bbox": aoi.bbox,
        "staged_sha256": manifest.get("sha256"),
        "staged_months": manifest.get("months"),
        "attribution": ATTRIBUTION,
    }
    return BuildResult(
        output_reference={
            "top_k": chips,  # ranked; the key output.t4 reads
            "k": int(p["k"]),
            "query_chip": result["query"]["chips_id"],
            "similarities": [r["similarity"] for r in result["results"]],
            "candidates": result["candidates"],
        },
        inputs=inputs,
        method="script",
    )
