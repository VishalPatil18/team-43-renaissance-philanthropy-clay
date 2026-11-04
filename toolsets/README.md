# Tool sets

A tool set is a YAML file in this folder: a list of pinned MCP servers plus a **capability map**
that says which concrete tool provides each capability (FR-4.10). Workflow rules in the task
templates refer to capabilities, so the same rule works with T0 and T1. Each file is registered
under registry kind `toolset` with its file name as the name and the first 12 hex digits of the
file's sha256 as its version.

| Tool set | Servers | Status |
|---|---|---|
| `T0` | `roda` | R0, live |
| `T1` | `roda`, `stac`, `osm`, `clay_embeddings` | R1, live; `clay_embeddings` added in R2 |
| `T1-faulty` | R1's T1 (no `clay-embeddings`) with injected failures plus a dead `broken` server, `test_only: true` | R1, for J4 |
| `lgnd` (LGND Geo MCP) | — | not built: whitelist access unconfirmed, see `docs/FUTURE-WORK.md` |

## Capabilities

| Capability | T0 | T1 |
|---|---|---|
| `dataset_discovery` | `roda.search_datasets`, `list_datasets`, `get_dataset_details`, `discover_by_organization`, `discover_by_license`, `find_related_datasets`, `search_stac_endpoints` | same |
| `imagery_search` | — | `stac.search_items` |
| `geocode` | — | `osm.openstreetmap_search_places` |
| `embedding_similarity` | — | `clay_embeddings.similar_places` |

Not mapped: `clay_embeddings.embedding_at` (a lookup helper; no workflow rule needs it).

No server in T0 or T1 gets AWS credentials.

## T1-faulty (journey J4)

| Server | Injected failure | Result of a call | Checked 2026-11-04 |
|---|---|---|---|
| `roda` | none | `ok` | yes |
| `stac` | `HTTPS_PROXY`/`HTTP_PROXY` = `http://127.0.0.1:9` (connection refused) | `error` / `tool_error` in 0.4 s | yes |
| `osm` | Nominatim and Overpass URLs = `http://10.255.255.1` (non-routable), `timeout_s: 0.5` | `timeout` / `tool_timeout` after 0.5 s | yes |
| `broken` | `command: ["false"]` | the server is `unavailable`; a direct call returns `error` / `server_unavailable` | yes |

`broken` never lists tools, so an agent can't call it; only a direct call (or a test) produces
`server_unavailable`. The STAC and OSM tools are listed normally and fail when called.

## File format

```yaml
name: T0                     # must equal the file name
description: ...
test_only: false             # true = excluded from comparisons
servers:
  - name: roda               # [A-Za-z0-9_], becomes the "<server>__" prefix of model tool names
    command: ["uvx", "awslabs.roda-mcp-server@0.1.7"]   # version pinned (FR-1.10)
    env: {FASTMCP_LOG_LEVEL: ERROR}                      # non-secret settings only, committed
    needs_aws: false         # true = AWS credentials are passed to this server (FR-1.9)
    timeout_s: 60            # per-call cap; the run's own timeout can only lower it
capabilities:
  dataset_discovery: [roda.search_datasets, roda.list_datasets]
```

Allowed commands: `uvx <pkg>@<version>` (or `<pkg>==<version>`, or `--from`), `npx -y
<pkg>@<version>`, `python ...` for our own servers, and `false` for the faulty test set. Anything
unpinned or any other runner fails validation.

## How servers are started

`claysandbox.tools.launcher.McpStdioToolSession` starts every server of the set as a fresh stdio
subprocess per run, calls `initialize` and `list_tools`, and serves calls from one background
asyncio loop (`call` is async, `call_blocking` is for synchronous harnesses). Failures come back as
results, never exceptions:

| Condition | `ToolResult.status` | `error_kind` |
|---|---|---|
| tool reports `isError`, or the server rejects the arguments | `error` | `tool_error` |
| no answer within `min(call timeout, timeout_s)` | `timeout` | `tool_timeout` |
| server failed to start, crashed or closed | `error` | `server_unavailable` |

A server that fails to start doesn't stop the others. Its tools are missing from `list_tools()`,
and `servers()` reports it as `unavailable` (with the reason) for the run manifest. Each server's
stderr goes to `<log_dir>/<server>.stderr.log`.

### Environment scrubbing (DD-034)

A server process gets only: `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR`, the uv and npm cache
settings (`UV_CACHE_DIR`, `UV_TOOL_DIR`, `UV_TOOL_BIN_DIR`, `UV_PYTHON_INSTALL_DIR`, `UV_OFFLINE`,
`XDG_CACHE_HOME`, `XDG_DATA_HOME`, `NPM_CONFIG_CACHE`, `NPM_CONFIG_PREFIX`), its own `env:` entries,
and, only with `needs_aws: true`, the AWS variables (`AWS_PROFILE`, `AWS_REGION`,
`AWS_DEFAULT_REGION`, `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`, the
`AWS_CONTAINER_CREDENTIALS_*` variables used on Fargate, and `AWS_CONFIG_FILE` /
`AWS_SHARED_CREDENTIALS_FILE` pointing at `~/.aws`). The MCP Python SDK also passes `LOGNAME`,
`SHELL`, `TERM` and `USER`, none of which are secret.

Known limit: environment scrubbing doesn't stop a server from reading files under `HOME`
(including `~/.aws`). Per-server containers are out of scope for the MVP (srs §3.2).

## Smoke-test results (VIS-R0-00, 2026-11-04)

Run with `uv run python scripts/smoke_mcp.py --schemas --with-aws`. All three servers started,
listed their tools and answered a realistic call **without AWS credentials**.

| Server | Package (pinned) | Runtime | License | Startup | Needs AWS |
|---|---|---|---|---|---|
| RODA | `awslabs.roda-mcp-server@0.1.7` (reports `roda-mcp 4.1.6`) | Python, `uvx` | Apache-2.0 | 0.8 s | no |
| STAC | `stac-mcp@6.5.0` ([BnJam/stac-mcp](https://github.com/BnJam/stac-mcp)) | Python ≥ 3.11, `uvx` | Apache-2.0 | 1.1 s | no |
| OSM | `@cyanheads/openstreetmap-mcp-server@0.7.0` ([cyanheads/openstreetmap-mcp-server](https://github.com/cyanheads/openstreetmap-mcp-server)) | Node ≥ 24, `npx` | Apache-2.0 | ~8 s first run (npm download), < 1 s after | no |

### RODA (10 tools)

`search_datasets(query, tags?, organization?, license_type?)`, `list_datasets(tag?, limit=20)`,
`get_dataset_details(slug)`, `discover_by_organization(organization, limit=10)`,
`discover_by_license(license_type, limit=10)`, `find_related_datasets(slug, limit=5)`,
`get_knowledge_base_stats()`, `preview_dataset(slug, bucket_arn?)`,
`sample_dataset(slug, file_key, bucket_arn?)`, `search_stac_endpoints(query?, limit=20)`.

- Results are JSON text: `{status, query, total_count, returned_count, top_categories, results:
  [{slug, name, description, managed_by, license}]}` for searches.
- `preview_dataset` and `sample_dataset` use anonymous S3 access, so even they need no
  credentials. **T0 therefore sets `needs_aws: false`** (least privilege). The plan assumed `true`.
- Prints a FastMCP banner on stderr; `FASTMCP_LOG_LEVEL=ERROR` keeps logs quiet.

Capabilities in T0: `dataset_discovery` = the six search/list/details/related tools plus
`search_stac_endpoints`. `get_knowledge_base_stats`, `preview_dataset` and `sample_dataset` are not
mapped (no workflow rule uses them).

### STAC (11 tools)

`get_root`, `get_conformance`, `get_capabilities`, `search_collections(limit?, catalog_url?)`,
`get_collection(collection_id, catalog_url?)`, `get_item(collection_id, item_id, ...)`,
`search_items(collections?, bbox?, datetime?, limit=10, query?, fields?, intersects?, ids?,
sortby?, output_format?, catalog_url?)`, `estimate_data_size`, `get_queryables`,
`get_aggregations`, `get_sensor_registry_info`.

- **The catalog is chosen per call** with `catalog_url`. There is no environment variable for it.
  With no `catalog_url`, the server uses **Microsoft Planetary Computer**
  (`https://planetarycomputer.microsoft.com/api/stac/v1`).
- STAC API choice (A-2): both Planetary Computer and Element 84 Earth Search
  (`https://earth-search.aws.element84.com/v1`) return the same 721 NAIP item IDs for the Kern
  County bbox in 2022 (Earth Search answered in 0.3 s, Planetary Computer in 1.2 s). **The T1 answer key
  uses Planetary Computer** because it is the server's default, so an agent that doesn't pass
  `catalog_url` searches the same catalog the key was built from.
- `output_format: "json"` returns `{"mode": "json", "data": {"type": "item_list", "count", "items":
  [full STAC items], "meta": {..., "has_more"}}}`. The default is a text rendering.
- Full STAC items are large (~3 KB each).
- **Quirk:** in 6.5.0, `search_items` with `fields` (e.g. `["id"]`) fails with "JSON ... does not
  represent a STACObject", because the trimmed items no longer parse as STAC items. Don't suggest
  `fields` in prompts.
- NAIP years available (Planetary Computer, checked 2026-11-04): CA, TX, NC: 2012–2022 even years;
  AZ: 2010, 2013, 2015, 2017, 2019, 2021, 2023.
- Capability in T1: `imagery_search` = `stac.search_items`. Log level: `STAC_MCP_LOG_LEVEL`.

### OSM (6 tools)

`openstreetmap_search_places(query | street/city/county/state/country/postalcode, ...)` (forward
geocoding via Nominatim, returns OSM id, category, address details and a **bounding box**),
`openstreetmap_reverse_geocode(lat, lon, zoom?, layer?, ...)`,
`openstreetmap_lookup_objects(osm_ids, ...)`, `openstreetmap_query_nearby(lat, lon,
radius_meters, ...)`, `openstreetmap_query_bbox(within | south/west/north/east, ...)`,
`openstreetmap_query_raw(query, limit?, offset?)` (Overpass QL).

- `openstreetmap_search_places("Kern County, California")` returns relation `R396494` with bbox
  S 34.7897, N 35.7983, W −120.1942, E −117.6165, which matches the Census bbox.
- Results are Markdown text and include "Data © OpenStreetMap contributors, ODbL 1.0".
- Settings (env): `OSM_USER_AGENT` (required by the Nominatim usage policy; we set
  `clay-agent-eval-sandbox/0.1 (+repo URL)`), `MCP_LOG_LEVEL` (default `info` is very chatty on
  stderr; use `error`), `OSM_NOMINATIM_BASE_URL`, `OSM_OVERPASS_BASE_URL` (useful for the faulty
  tool set: point them at an unreachable host).
- Nominatim requests are spaced 1.05 s apart by the server.
- Node ≥ 24 is required. The Docker image needs `WITH_NODE=true` and Node 24 (WS1).
- Capability in T1: `geocode` = `osm.openstreetmap_search_places`.
- Fallback if this server becomes unusable:
  [jagan-shanmugam/open-streetmap-mcp](https://github.com/jagan-shanmugam/open-streetmap-mcp)
  (MIT, Python ≥ 3.13, `osm-mcp-server` on PyPI, last updated 2025-07).

### clay-embeddings (ours, 2 tools)

`mcp_servers/clay_embeddings/`, run as `python -m clay_embeddings [--data DIR]` (stdio, MCP Python
SDK `MCPServer`). In tool sets the server is named `clay_embeddings`, so the model sees
`clay_embeddings__similar_places`. Server names may not contain `-`: Amazon Nova fails to call
a tool named `clay-embeddings__similar_places` ("Model produced invalid sequence as part of
ToolUse", reproduced 2026-11-04), and the same tool with `_` works. It imports nothing from `claysandbox`. Data: `data/embeddings/staged.parquet`
(default; or `$CLAY_EMBEDDINGS_DATA`), written by `scripts/stage_embeddings.py`.

- `embedding_at(lat, lon, year, month)`: the chip containing the point: `chips_id`, `cell_id`,
  acquisition `datetime`, `bbox`, `geometry`.
- `similar_places(lat?, lon?, year?, month?, k=10, search_bbox?, chip_id?)`: the `k` most similar
  chips of the same month by cosine similarity (rounded to 6 decimals, ties by `chips_id`, never
  the query chip), optionally only chips whose bbox intersects `search_bbox`; returns the query
  chip, the candidate count, the results with `similarity`, and the attribution.
- Errors (no chip at the point, month not staged, staged file missing) are MCP tool errors with
  the reason in the text.
- Both tool descriptions state the dataset, the 1280 m resolution, the staged coverage and the
  CC BY 4.0 attribution (FR-14.6).
- The index loads at server start (about 1 s for the 152,516 staged chips); a call takes ~20 ms.

Staged data (2026-11-04, `data/embeddings/staging_manifest.json`): Clay v1.5, Sentinel-2 L2A,
1280 m chips, 256 dims, months **2024-01 and 2024-07** (June 2024 is missing from every partition
we need), each AOI's bbox plus 10 km, from geohash partitions `9q`, `9t`, `dn`, `dq`, `dr`.
152,516 rows, 158 MB, sha256 `265c44c47ff5…`. `data/` is gitignored; rebuild with
`uv run python scripts/stage_embeddings.py` (anonymous S3, about 2 minutes). The sandbox bucket
doesn't exist yet; once the CDK stack is deployed, share the files with
`aws s3 cp data/embeddings/ s3://<sandbox-bucket>/data/embeddings/ --recursive`.

## Attribution text (for the README and reports, C-14, FR-5.6)

Reports that used results of these tools or data should include the matching lines:

- **Clay embeddings:** "Contains Clay v1.5 embeddings by LGND (Sentinel-2 L2A, monthly
  aggregated), licensed CC BY 4.0, https://source.coop/clay/lgnd-embeddings. Sentinel-2 data:
  Copernicus Sentinel data, processed by ESA."
- **OpenStreetMap:** "Contains data © OpenStreetMap contributors, available under the Open
  Database License (ODbL) 1.0, https://www.openstreetmap.org/copyright."
- **Global Renewables Watch:** "Solar PV reference sites from Global Renewables Watch v1.0
  (Microsoft, The Nature Conservancy and Planet), MIT License,
  https://github.com/microsoft/global-renewables-watch."
- **NAIP:** "NAIP imagery courtesy of the USDA Farm Service Agency (public domain)."

A report used a source if its trace has a tool call to that server (`clay_embeddings`, `osm`), or
its task is T3 (Global Renewables Watch) or T1/T5 (NAIP).

## Data licenses

RODA metadata is published by AWS; each dataset has its own license, which the server reports.
NAIP is public domain. OpenStreetMap data is ODbL 1.0 (attribution required in reports that use
OSM results, C-14).
