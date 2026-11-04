"""T1 reference builder: every NAIP item intersecting the AOI bbox in the given year.

Source: the STAC API that stac-mcp searches when the agent gives no ``catalog_url`` (Microsoft
Planetary Computer, collection ``naip``). Using the same catalog as the tool means the answer key
and what the agent can find agree. Searches by the AOI bbox (as the agent would after geocoding)
and the whole year, follows every page, and stores the item IDs sorted.

NAIP imagery is public domain (USDA Farm Service Agency).
"""

from __future__ import annotations

from typing import Any

from pystac_client import Client

from claysandbox.contracts.task import AOI, TaskInstance, TaskTemplate
from claysandbox.tasks.references import BuildResult

STAC_API = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION = "naip"
PAGE_SIZE = 1000


def search_item_ids(bbox: list[float], year: int, stac_api: str = STAC_API) -> list[str]:
    client = Client.open(stac_api)
    search = client.search(
        collections=[COLLECTION], bbox=bbox, datetime=str(year), limit=PAGE_SIZE
    )
    return sorted({item.id for item in search.items()})


def build(template: TaskTemplate, aoi: AOI, instance: TaskInstance) -> BuildResult:
    year = int(instance.params["year"])
    ids = search_item_ids(aoi.bbox, year)
    if not ids:
        raise RuntimeError(f"no NAIP items for {aoi.id} in {year}: choose another year")
    inputs: dict[str, Any] = {
        "stac_api": STAC_API,
        "collection": COLLECTION,
        "year": year,
        "bbox": aoi.bbox,
        "match": "item intersects the AOI bbox",
    }
    return BuildResult(output_reference={"items": ids}, inputs=inputs, method="script")
