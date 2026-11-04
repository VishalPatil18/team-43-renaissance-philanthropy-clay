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
| T3 | Candidate solar sites | Global Renewables Watch | precision/recall within a distance | R2 |
| T4 | Places similar to a given place | `clay_embeddings.core.similar_places` | recall@k | R2 |

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
| `us-ca-san-francisco` | San Francisco County, California | no solar (negative control) | central San Francisco |
| `us-ny-hamilton` | Hamilton County, New York | no solar (negative control) | Indian Lake |

Solar presence was checked against OpenStreetMap (`power=plant` + `plant:source=solar`); T3 checks
it against Global Renewables Watch in R2. All six have NAIP coverage for 2022.

### Add an AOI

1. Generate the entry from the Census boundary and paste it under `aois:` in `aois.yaml`:

   ```bash
   uv run python scripts/fetch_aoi.py 06029 --tag has_solar   # 5-digit county FIPS code
   ```

2. Add `template_params.T1` (`area_name` and a 0.1° `area_bbox` inside the county) and, from R2,
   the T4 query point.
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
- Building needs network access (STAC API, GitHub) but no AWS credentials.

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

`T1@us-ca-kern` also has `T1.v1+sha256:133e9754636d` (R0, whole county, 721 items). It is kept
because references are never deleted; `v2` is the latest.

## Data sources and licenses

| Source | Used by | License |
|---|---|---|
| Census TIGERweb county boundaries | `aois.yaml` | public domain |
| NAIP via Microsoft Planetary Computer STAC | T1 | public domain (USDA FSA) |
| Registry of Open Data on AWS, [awslabs/open-data-registry](https://github.com/awslabs/open-data-registry) @ `40c4313` | T2 | Apache-2.0 (metadata); each dataset has its own license |
| OpenStreetMap (solar check, OSM tools) | AOI selection, T1/T5 agents | ODbL 1.0 |
