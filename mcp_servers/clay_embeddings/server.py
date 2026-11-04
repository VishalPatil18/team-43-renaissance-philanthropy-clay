"""The clay-embeddings MCP server (stdio): two tools over the staged LGND embeddings (F14)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.exceptions import ToolError

from clay_embeddings import __version__
from clay_embeddings.core import ATTRIBUTION, EmbeddingsError, load_index

COVERAGE = (
    "Only pre-staged areas and months are searchable: six US counties (Kern CA, Clark NV, "
    "Pecos TX, Robeson NC, New York NY, Hamilton NY) with a 10 km margin, January and July 2024. "
    "Resolution: one chip is about 1280 m x 1280 m, so this finds similar landscapes, not "
    "individual buildings."
)

EMBEDDING_AT = f"""Return the embedding chip that contains a point in a given month: its chips_id,
cell_id, acquisition datetime, bbox and footprint geometry. Use it to find the chip ID of a place
before searching for similar places.

{COVERAGE}
Data: {ATTRIBUTION}."""

SIMILAR_PLACES = f"""Find the k places most similar to a query place, by cosine similarity of
their Clay embeddings in the same month. The query is the chip containing (lat, lon) in
year/month, or a chip_id from embedding_at. Candidates are restricted to chips whose bbox
intersects search_bbox [west, south, east, north] if given, otherwise every staged chip of that
month. Results are sorted by similarity (ties by chips_id) and never include the query chip.

{COVERAGE}
Data: {ATTRIBUTION}."""


def build_server(data: Path | str | None = None) -> MCPServer:
    server = MCPServer("clay-embeddings", version=__version__, log_level="ERROR")
    try:
        load_index(data)  # load at startup so the first tool call isn't slow
    except FileNotFoundError:
        pass  # each tool call reports the missing data as a tool error

    def index() -> Any:
        try:
            return load_index(data)
        except FileNotFoundError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(description=EMBEDDING_AT)
    def embedding_at(lat: float, lon: float, year: int, month: int) -> dict[str, Any]:
        try:
            return index().embedding_at(lat, lon, year, month)  # type: ignore[no-any-return]
        except EmbeddingsError as exc:
            raise ToolError(str(exc)) from exc

    @server.tool(description=SIMILAR_PLACES)
    def similar_places(
        lat: float | None = None,
        lon: float | None = None,
        year: int | None = None,
        month: int | None = None,
        k: int = 10,
        search_bbox: list[float] | None = None,
        chip_id: str | None = None,
    ) -> dict[str, Any]:
        try:
            return index().similar_places(  # type: ignore[no-any-return]
                lat, lon, year, month, k, search_bbox, chip_id
            )
        except EmbeddingsError as exc:
            raise ToolError(str(exc)) from exc

    return server
