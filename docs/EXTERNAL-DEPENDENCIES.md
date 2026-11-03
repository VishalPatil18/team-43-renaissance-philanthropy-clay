# External Dependencies — Clay Earth Dataset Foundry hackathon

> **For agents — what this file is:** Every outside resource: MCP servers, datasets, answer keys, platform and stack. Each has a link, access path, license, MVP/stretch tag, and a link check from 2026-11-03. Only reference/geomcp-catalog.csv is committed; the source PDFs are kept out of the repo.

All links below were checked on **2026-11-03**. The status column shows the result.
Source documents: the PDFs and their text copies are kept out of the repo by `.gitignore` (the AWS guide is marked Amazon Confidential). Ask the team for a copy. Only the catalog CSV is committed:

| Local file | What it is |
|---|---|
| Clay vision doc (not in repo) | Clay vision doc: business context, the tasks (it says three but defines two), MVP scope, technical environment |
| AWS event guide (not in repo, Amazon Confidential) | AWS Breaking Barriers DC event guide: venues, agenda, sandbox rules, judging |
| [reference/geomcp-catalog.csv](reference/geomcp-catalog.csv) | Snapshot of Clay's geoMCP catalog sheet (first tab, 15 servers). Exported 2026-11-03 |

**Use** column: **MVP** = needed for the ADB eval. **Stretch** = only for the later caption task.

---

## 1. Agent tooling (MCP)

| Dependency | Link | Access / install | License | Use | Status |
|---|---|---|---|---|---|
| RODA MCP server (AWS Registry of Open Data) | [Announcement blog](https://aws.amazon.com/blogs/opensource/introducing-mcp-server-for-registry-of-open-data-on-aws/) · [PyPI](https://pypi.org/project/awslabs.roda-mcp-server/) · [Source (awslabs/mcp)](https://github.com/awslabs/mcp) | `uvx awslabs.roda-mcp-server@latest` | Apache-2.0 | **MVP**: known-good starting tool | Links OK. Install not tested yet |
| Clay geoMCP catalog (about 99 servers; free/priority shortlist to come from Clay) | [Google Sheet](https://docs.google.com/spreadsheets/d/1cMoPxhNTzNHuWEAK_PtAgFUqEMxQ1AyoZxMCzfdkYzQ/edit?usp=sharing) | Public. CSV export: `…/export?format=csv` | Varies per server | **MVP**: pick 1–2 alongside RODA | OK. First tab saved locally |
| LGND Geo MCP server | [lgnd.ai/geo](https://lgnd.ai/geo) | Commercial. Hackathon teams get whitelisted | Commercial | MVP (optional) | Page OK. **Confirm our access with Clay** |

Shortlist candidates from the saved catalog tab (all "active" and "Open"): `stac-mcp` (remote sensing catalog), `earthdata-mcp` (official, remote sensing), `GeoLens MCP` (official, data catalogs), `gis-mcp` (98 tools, GIS toolkit), `openstreetmap-mcp-server`, `Overture Maps MCP`. Clay has the final say on the shortlist.

## 2. Input data

| Dependency | Link | Access | License | Use | Status |
|---|---|---|---|---|---|
| NAIP aerial imagery (0.3–1 m, 4-band, US) | [Registry of Open Data](https://registry.opendata.aws/naip/) | `s3://naip-analytic` (MRF), `s3://naip-source` (GeoTIFF), `s3://naip-visualization` (RGB COG). **Requester-Pays, us-west-2.** Pass `--request-payer requester` | Public domain (USDA) | MVP if the ADB task needs imagery | Link OK. Pre-stage a small sample |
| Vantor open data (sample vector data) | [Registry of Open Data](https://registry.opendata.aws/vantor-open-data/) | `s3://vantor-opendata`. Anonymous listing works (checked) | See registry page | MVP if the ADB task needs it | OK, bucket is public |
| LGND / Clay embeddings | [source.coop/clay/lgnd-embeddings](https://source.coop/clay/lgnd-embeddings) | HTTPS / S3-compatible via Source Cooperative | Apache-2.0 | Stretch (captions / retrieval) | OK |
| SkyScript (large, semantically diverse vision-language dataset for remote sensing) | [GitHub](https://github.com/wangzhecheng/skyscript) | GitHub | Check repo | Stretch (captions) | OK |
| MegaEarth (Sentinel-2 windows + OSM labels, 485 classes in families, split by geography; tests transfer to unseen categories) | [Hugging Face](https://huggingface.co/datasets/Mead0w1ark/megaearth-osm-sentinel2) | Hugging Face dataset | Check dataset card | Stretch | OK |
| ADB task input data (and rubric) | — | **Inputs not coming** (SCOPE D13). Rubric unconfirmed. We generate synthetic tasks with task references built from the public data above (D19) | — | **MVP** | **Team generates** |

## 3. Reference / answer-key data (caption-task retrieval — stretch)

| Dependency | Link | License | Status |
|---|---|---|---|
| Global Renewables Watch v1.0 (solar and wind worldwide) | [GitHub release](https://github.com/microsoft/global-renewables-watch/releases/tag/v1.0) | MIT | OK |
| USGS USPVDB (US solar) | [eerscmap.usgs.gov/uspvdb](https://eerscmap.usgs.gov/uspvdb/) | Public domain | **Unreachable from the dev machine on 2026-11-03** (connection timeout; usgs.gov returned 403). Retry from the venue |
| USGS USWTDB (US wind) | [eerscmap.usgs.gov/uswtdb](https://eerscmap.usgs.gov/uswtdb/) | Public domain | Same as USPVDB: retry from the venue |
| OpenStreetMap | [openstreetmap.org](https://www.openstreetmap.org) | ODbL | OK |

## 4. Auxiliary caption datasets (stretch: check each license before use)

| Dataset | Task type | Link | Notes | Status |
|---|---|---|---|---|
| LEVIR-CC | Change | [GitHub](https://github.com/Chen-Yang-Liu/LEVIR-CC-Dataset) | Change captioning and detection | OK |
| Change-Agent | Change | [GitHub](https://github.com/Chen-Yang-Liu/Change-Agent) | Adds change masks | OK |
| SECOND-CC | Change | [GitHub](https://github.com/ChangeCapsInRS/SecondCC) | Change captioning | OK |
| RSCC | Change | [GitHub](https://github.com/Bili-Sakura/RSCC) | Larger set. Possibly only a small human-labeled subset; score only against that subset | OK |
| VRSBench | Fixed | [GitHub](https://github.com/lx709/VRSBench) | Single-image descriptions | OK |
| RSICD_optimal | Fixed | [GitHub](https://github.com/201528014227051/RSICD_optimal) | Single-image captions | OK |

## 5. Platform and event

| Dependency | Detail |
|---|---|
| AWS sandbox (Workshop Studio) | Provisioned by the team lead. **$500 spend cap.** Wiped after the event, so keep everything in the repo |
| Amazon Bedrock | Agent model, kept behind an abstraction. Enable model access in the sandbox on Day 1 |
| Public GitHub repo | Created at kickoff (per source). Required before judging. Open source (Apache-2.0, to match Clay), with infrastructure as code where it applies |
| Event contact | breaking-barriers-us-2026@amazon.com |
| Expected stack | Python 3.12+, boto3, an MCP SDK, an agent framework (any, kept swappable), an OpenTelemetry-style tracer (swappable), FastAPI for the thin API, scikit-learn/numpy for metrics, and optionally a TS/Node 20+ thin UI. Geospatial stack: rasterio / GDAL / xarray / pystac. Permitted extras: SQL (lightweight trace/metadata store) and Bash (sandbox scripting) |
| Deployment model | Flexible (serverless, containers or K8s) in a single sandbox account |
