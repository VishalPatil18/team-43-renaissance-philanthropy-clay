# Task library

Synthetic geospatial tasks for the agent, and the references each run is scored against (srs F13,
architecture §14). Owner: WS2 (Vishal).

```
tasks/
  templates/T1.yaml …          task templates (prompt, workflow spec, output schema, builder)
  aois.yaml                    the six counties (areas of interest)
  builders/*.py                one reference-builder script per template
  process_rubrics/T1.md …      rubrics for the LLM process evaluator
  references/<template>/<aoi>/<version>.json   built references, never overwritten
```

A **task instance** is a template filled in for one AOI, with ID `<template>@<aoi>`, for example
`T1@us-ca-kern`. A **task reference** is what a run of that instance is scored against: the
resolved workflow spec, the output reference (answer key), weights, output schema, rubric text,
and how and when it was built.

## Templates

| ID | Task | Answer key | Metric (`output.t<k>`) | Release |
|---|---|---|---|---|
| T1 | NAIP items for 2022 in a 0.1° box around a named place | STAC search, Planetary Computer `naip` | precision, recall, F1 of item IDs | R1 |
| T2 | Up to 10 open imagery, elevation or land-cover datasets covering the county | keyword filter over the Registry of Open Data | precision and recall@k, k = 10 | R1 |
| T5 | "Get me good imagery for <county>" (ambiguous) | three behaviour rules | pass rate | R1 |
| T3 | Existing utility-scale solar PV sites in the whole county | Global Renewables Watch v1.0 polygons intersecting the county | precision/recall within `tolerance_m` = 500 m | R2 |
| T4 | The 10 places most similar to a given point, July 2024, within the county bbox | `clay_embeddings.core.similar_places` with the prompt's inputs | recall@k, k = 10 | R2 |

Notes:

- **T1** asks for a small box, not the whole county: a county has hundreds of NAIP items (Kern
  had 721 in 2022), more than an agent can return. The box and place name are in `aois.yaml`
  under `template_params.T1`; the keys hold 4 to 12 items.
- **T2** has no exact answer, because the registry has no coverage field. The builder keeps
  datasets with an imagery, elevation, lidar or land-cover tag whose name or description says
  they cover the US, the world or the county's state, and drops regional, off-Earth, ocean-only and
  campaign datasets (rules in the builder's docstring). That gives about 120 datasets per county,
  with known false positives, so the agent is asked for at most 10 and scored by precision and
  recall@10.
- **T3** searches the whole county. Keys: Kern 241, Clark 57, Robeson 51, Pecos 39 sites, and
  `{"sites": []}` for the two negative controls (the builder refuses to build if a `no_solar` AOI
  has sites, or a `has_solar` one has none). Each site has its GRW feature ID, centroid, area,
  construction quarter and footprint, simplified by 0.0001° (≤ 17 m).
- **T4** gives every input of the search in the prompt: the query point from
  `template_params.T4`, July 2024, k = 10 and the county bbox. The builder calls the same library
  function the `similar_places` tool uses, so a faithful agent can match the key exactly. It needs
  the staged embeddings (`scripts/stage_embeddings.py`); the key records their sha256.
- **T5** has no answer key. Its reference is a rule list: (a) states assumptions or asks a
  clarifying question, (b) every returned item ID appears in some tool result, (c) every returned
  item's footprint intersects the county.

## AOIs

| ID | County | Role | T1 box around |
|---|---|---|---|
| `us-ca-kern` | Kern County, California | solar | Bakersfield |
| `us-nv-clark` | Clark County, Nevada | solar | Boulder City |
| `us-tx-pecos` | Pecos County, Texas | solar | Fort Stockton |
| `us-nc-robeson` | Robeson County, North Carolina | solar | Lumberton |
| `us-ny-new-york` | New York County (Manhattan), New York | no solar (negative control) | Central Park (0.04° box) |
| `us-ny-hamilton` | Hamilton County, New York | no solar (negative control) | Indian Lake |

Solar presence was checked against OpenStreetMap (`power=plant` + `plant:source=solar`) and
Global Renewables Watch (GRW). All six have NAIP coverage for 2022 and are in the staged
embeddings.

San Francisco County was the urban control until 2026-11-04. GRW has 2 solar sites there, so it
was replaced by New York County. Its T1, T2 and T5 references stay in
`references/*/us-ca-san-francisco/` and are still readable by version.

T4 query points (`template_params.T4`, from `scripts/pick_t4_points.py`): for the solar counties,
the centroid of the largest GRW polygon built by 2023 (Kern: GRW 79552, 14 km² near Rosamond);
for the controls, Central Park and the hamlet of Indian Lake.

### Add an AOI

1. Generate the entry from the Census boundary and paste it under `aois:` in `aois.yaml`:

   ```bash
   uv run python scripts/fetch_aoi.py 06029 --tag has_solar   # 5-digit county FIPS code
   ```

2. Add `template_params.T1` (`area_name` and a 0.1° `area_bbox` inside the county) and
   `template_params.T4` (run `scripts/pick_t4_points.py`; add a landmark for a no-solar county).
   Restage the embeddings (`scripts/stage_embeddings.py`) so the county is searchable.
3. Check the county has NAIP coverage for the T1 year.
4. Build its references (below) and spot-check one.

## Build references

```bash
uv run python -m claysandbox.tasks list                        # instances and latest versions
uv run python -m claysandbox.tasks build --template T1         # every AOI
uv run python -m claysandbox.tasks build --template T1 --aoi us-ca-kern
uv run python -m claysandbox.tasks spot-check T1@us-ca-kern --by "Your Name" --note "what you compared"
```

(`clay-sandbox tasks …` will call the same functions once the CLI is wired by WS5.)

- **Version** `<template>.v<n>+sha256:<12 hex>`: the hash covers the canonical JSON of the
  resolved workflow, the output reference and the weights. Rebuilding identical content returns
  the existing version and writes nothing. Changed content gets `v<n+1>`; old versions stay, so old
  assessments keep the version they were scored against. File names use `-` for the `:`.
- A builder is `build(template, aoi, instance) -> BuildResult` in `builders/<name>.py`. The
  reference records the builder path and the sha256 of its file, the build inputs and the build
  time.
- Write or change the process rubric **before** building: the rubric text is stored in the
  reference but isn't part of the hash, so a later rubric edit alone doesn't create a new version.
- Building needs network access (STAC API, GitHub, Source Cooperative) but no AWS credentials.
  T3 downloads the 395 MB GRW GeoPackage once to `~/.cache/claysandbox/grw/` (sha256-checked);
  T2 caches the registry in `~/.cache/claysandbox/open-data-registry/`.

## `method`

| Value | Meaning |
|---|---|
| `script` | the answer key is exactly what the builder script computed from public data |
| `script+curated` | the script proposed candidates and the Task Author confirmed or rejected each (allowed for T2, FR-13.4; not used: the T2 keys are `script`) |

## Spot-checks (FR-13.5)

One instance per template is checked by a person and records `checked_by`, `checked_at` and a note:

| Instance | Version | Check |
|---|---|---|
| `T1@us-ca-kern` | `T1.v2+sha256:cfebf696c13c` | same 6 IDs from an independent Element 84 Earth Search query |
| `T2@us-tx-pecos` | `T2.v1+sha256:2ef1434beca2` | registry docs of `naip`, `usgs-lidar`, `sentinel-2` read and correct; `nasa-uars` noted as a false positive |
| `T5@us-nc-robeson` | `T5.v1+sha256:da748fe3bd16` | rules read; AOI values match `aois.yaml` |
| `T3@us-ca-kern` | `T3.v1+sha256:97d56a81784d` | 140 of 241 GRW sites (58%) have an OpenStreetMap solar plant within ~500 m, including the three largest; both controls are empty |
| `T4@us-nc-robeson` | `T4.v1+sha256:185c6f8b5199` | a live `similar_places` call over stdio with the prompt's arguments returned the same 10 chips in the same order |

`T1@us-ca-kern` also has `T1.v1+sha256:133e9754636d` (R0, whole county, 721 items). It is kept
because references are never deleted; `v2` is the latest.

## Data sources and licenses

| Source | Used by | License |
|---|---|---|
| Census TIGERweb county boundaries | `aois.yaml` | public domain |
| NAIP via Microsoft Planetary Computer STAC | T1 | public domain (USDA FSA) |
| Registry of Open Data on AWS, [awslabs/open-data-registry](https://github.com/awslabs/open-data-registry) @ `40c4313` | T2 | Apache-2.0 (metadata); each dataset has its own license |
| OpenStreetMap (solar check, OSM tools) | AOI selection, agents | ODbL 1.0 |
| Global Renewables Watch v1.0 (Microsoft, Planet, The Nature Conservancy) | T3, T4 query points | MIT |
| Clay v1.5 embeddings by LGND, Source Cooperative | T4, `clay-embeddings` | CC BY 4.0 |
