# Plan — Vishal (WS2 Tools and tasks)

> **For agents — what this file is:** Vishal's task plan for building the Clay agent-eval sandbox, release by release (R0 → R3). Sections 1–6 are shared by all five plans. Sections 7 onwards are Vishal's own. Read it together with [srs.md](srs.md) (what to build) and [architecture.md](architecture.md) (how it fits together). Those two files plus this plan are all that's needed to do the work. Requirement IDs (FR-x.y, NFR-…) are the acceptance criteria. Decisions are in [design-decisions.md](design-decisions.md) (ownership: DD-044).

---

## 1. Read this first

This plan is one of five: [plan-prithwish.md](plan-prithwish.md), [plan-vishal.md](plan-vishal.md), [plan-shivaani.md](plan-shivaani.md), [plan-barath.md](plan-barath.md), [plan-5th-member.md](plan-5th-member.md).

**Reading list before you start (about 45 minutes):**

- srs.md §1 (problem), §2 (releases), §5 (roles), §8 (workflow and run states), §12 (data, error taxonomy), §18 (glossary).
- architecture.md §1 (principles), §4 (components and import rules), §5 (fixed vs changing parts), §7 (contracts), §23 (deliverables per release).
- The extra sections listed under each of your tasks.

**Rules:**

- If this plan disagrees with srs.md or architecture.md, those win. Tell the team lead.
- Every task cites the requirements it satisfies. A task is done when those requirements pass.
- Words like *run*, *assessment*, *eval*, *task reference* mean exactly what the srs glossary says.

## 2. Team at a glance

| Developer | Workstream | Owns (summary) | Reviews PRs from | R3 deliverable |
|---|---|---|---|---|
| **Prithwish** | WS1 Agent runtime and cloud execution | Bedrock adapter, instrumented wrappers, Strands and Converse-loop harnesses, guards, prices, pre-flight estimate, Docker, CDK, Fargate executor | Vishal | Final demo eval + demo runbook |
| **Vishal** | WS2 Tools and tasks | MCP tool-set launcher, tool sets, task templates T1–T5, AOIs, references, `clay-embeddings` MCP server | 5th member | Runs screen |
| **Shivaani** | WS3 Trace and store | Trace schema, tracers (JSONL, OTel, tee) and tracer comparison, run store, S3 mirror, DuckDB queries, summarizers, samples, planted traces | Prithwish | Report screen |
| **Barath** | WS4 Evaluation and statistics | Workflow, output and LLM evaluators, statistics, agent and evaluator comparisons, evaluator validation, live-journey script and gate evals | Shivaani | Comparison screen |
| **5th member** | WS5 Platform and presentation | Scaffold, CI, eval spec, manifest, registry, service layer, local executor, CLI, API, report renderers, README, UI shell | Barath | UI shell, client, New Run screen, SSE |

The reviewer is the developer who consumes most of your output. A PR that changes `contracts/` also needs approval from every affected owner.

## 3. Release calendar

| Gate | Target | Exit criteria (srs §2) | Who checks |
|---|---|---|---|
| **R0** Walking skeleton | Tue Nov 3, end of day | `clay-sandbox run specs/r0.yaml` writes `manifest.json` and `trace.jsonl` with ≥1 real MCP tool call. CI green | Team lead |
| **R1** Scored loop | Wed Nov 4, 12:00 | J1, J2, J4 pass. A live run and its report are committed under `samples/` | Team lead |
| **R2** MVP complete | Wed Nov 4, 17:30 | J3, J5, J6, J7, J8, J9 pass. `docs/05` ticked except license and UI. FUTURE-WORK current | Team lead |
| **R3** UI | Thu Nov 5, 09:00 (prelims at 10:00) | Launch a run, watch status, open its report and a comparison from the browser | Team lead |

- Merge freeze 30 minutes before each gate: only fixes for the exit criteria.
- If a gate slips, the team lead moves the time. The order of work stays the same.
- Anything that won't make its release goes to `docs/FUTURE-WORK.md` the same day (D21).

## 4. Working agreement

1. **Branches:** `<name>/<task-id>-<slug>` from `main` (e.g. `prithwish/PRI-R0-01-bedrock-adapter`). At least one PR per task. Keep PRs small.
2. **PR checklist:**
   - CI green: ruff, mypy, import-linter, pytest including conformance.
   - Reviewer approval (§2).
   - The task's acceptance boxes copied into the PR description and ticked.
3. **Ownership:** only edit files you own (architecture §4 and §21). If you need a change elsewhere, ask the owner. Exception: adding your module's import line to `claysandbox/platform/registry_bootstrap.py`, with 5th member reviewing.
4. **Contracts are frozen** once `contracts/v1` merges. A change needs all three of these, in the same PR:
   - a new DD entry in design-decisions.md,
   - a `schema_version` bump,
   - approval from every affected owner.
5. **Fakes first:** build and test against `claysandbox/contracts/fakes/` until the real neighbour has merged. Never wait on someone else's code to start.
6. **Secrets:** use your own AWS profile (`AWS_PROFILE`, `AWS_REGION=us-west-2`). Never commit keys, tokens or `.env` files.
7. **Model IDs** live only in specs, never in code (FR-1.5).
8. **Money:**
   - Use Nova Lite for development.
   - Always set `budget.run.max_usd` on live specs.
   - Tell the team lead before any eval estimated over $20. The sandbox cap is $500 for everything (C-03).
9. **README:** write your section by the R2 gate. 5th member owns the overall structure.
10. **FUTURE-WORK:** if you cut or defer something, add its row the same day.

## 5. One-time setup

```bash
# tools
curl -LsSf https://astral.sh/uv/install.sh | sh     # uv
uv python install 3.12
# Node 20+ (needed by: CDK CLI for Prithwish, UI for everyone in R3)
# Docker (Prithwish), AWS CLI v2 with sandbox credentials

git clone https://github.com/VishalPatil18/team-43-renaissance-philanthropy-clay.git
cd team-43-renaissance-philanthropy-clay
uv sync                       # after 5th member's scaffold is on main
uv run pytest                 # must pass before you branch
export AWS_REGION=us-west-2   # and AWS_PROFILE=<your sandbox profile>
```

## 6. Contracts session (R0 hour 1, everyone)

The goal is a merged `claysandbox/contracts/` package that every workstream builds against. Sketches are in architecture §7. Work on one branch, `contracts/v1`. 5th member merges it.

**Agenda:**

1. (5 min) 5th member shows the scaffold and opens the branch.
2. (35 min) Each person writes their modules, fakes and conformance skeletons (table below).
3. (10 min) Settle the open points (below).
4. (10 min) `uv run pytest claysandbox/contracts` passes. 5th member merges. **Contracts are frozen.**

| Owner | Modules | Fakes (`contracts/fakes/`) | Conformance (`contracts/conformance/`) |
|---|---|---|---|
| Prithwish | `runtime.py` (ModelAdapter, ModelResponse, Harness, RunContext, RunOutcome, BudgetGuard, PriceTable, CostEstimate), `errors.py` (GuardStopped, InfraError, ConfigError) | `FakeModelAdapter` (scripted replies), `FixedPriceTable`, `NoopGuard`, `TripGuard` (stops at call n) | `test_harness.py`, `test_model_adapter.py` |
| Vishal | `task.py` (TaskTemplate, WorkflowSpec, OrderingRule, ArgumentConstraint, AOI, TaskInstance, TaskReference), `tools.py` (ToolSpec, ToolResult, ToolSession, ToolSetProvider, ToolSetDef, ServerDef, EnvPolicy) | `FakeToolSession` (canned results, errors, timeouts), a fixture T1 instance + reference | `test_toolsession.py` |
| Shivaani | `trace.py` (all TraceEvent types, ErrorInfo, EventSink, Trace), `store.py` (RunStore), `summary.py` (Claim, Summary, Summarizer) | `MemoryTracer`, `MemoryRunStore`, `EchoSummarizer` | `test_tracer.py`, `test_store.py` |
| Barath | `assessment.py` (SubScore, Assessment, Evaluator), `stats.py` (ConfigStats, PairedComparison, MeasurementComparison, ValidationReport) | `ConstantEvaluator` | `test_evaluator.py` |
| 5th member | `spec.py` (EvalSpec and parts), `manifest.py` (RunManifest, ComponentRef), `report.py` (Report, EvalReport), `execution.py` (RunRequest, RunStatus, Executor), `registry.py`, `ids.py`, `interfaces.py` (re-exports all Protocols) | `ImmediateExecutor` | `test_executor.py`, `test_registry.py` |

**Open contract points to settle in step 3.** The recommendations below are consistent with architecture §7 and §9.

| # | Point | Recommendation |
|---|---|---|
| 1 | Sync/async boundary for tools | `ToolSession.call` is async. Add `call_blocking(...)`, which runs the call on the session's background event loop. Harnesses are sync and use `call_blocking` |
| 2 | Tool names the model sees | `ToolSpec.model_name = "<server>__<tool>"`, limited to `[A-Za-z0-9_-]`, max 64 characters (Bedrock's tool-name rule), with a short hash suffix if truncated. Produced by the tool session |
| 3 | `EventSink` (in `trace.py`) | `emit(event)` assigns `seq`, `event_id`, `run_id` and never raises. `put_blob(data) -> (ref, sha256)`. `last_event_id` |
| 4 | `Trace` container | `events`, `incomplete: bool`, `blob(ref) -> bytes` |
| 5 | `TaskReference` contents | Resolved workflow spec, output reference, weights, output schema, and the template's `process_rubric` text |
| 6 | Step | One `model_call` plus the tool calls it requested |
| 7 | Writing reports | `RunStore.write_report(run_id, report: Report, rendered: dict[str, str])`, where keys are file names (`report.md`, `report.html`) |
| 8 | Loop guard | Allow N identical consecutive calls (default 3). Block the (N+1)th and stop the run |
| 9 | Workflow-spec vocabularies | `task.py` declares `Literal`s for ordering-rule shapes, argument-constraint checks (`bbox_intersects_aoi`, `point_within_aoi`, `collection_in`, `datetime_within_year`, `k_at_most`) and done conditions (`output_matches_schema_nonempty`, `output_present`, `assumptions_or_question`). Vishal declares them, Barath implements them. Adding one later is a contract change |
| 10 | Eval artefacts in the store | `RunStore` also gets `create_eval(eval_id, spec)`, `write_eval_artifact(eval_id, name, data)`, `read_eval_artifact(eval_id, name)` and `list_eval_runs(eval_id)` |
| 11 | Who writes `final_output` and `run_end` | The run worker (5th member), from the harness's `RunOutcome`, through the same `EventSink` |
| 12 | Trace digest | A pure helper `trace_digest(trace, max_chars)` lives in `contracts/trace.py` (Shivaani), so the summarizer and the LLM evaluator build the same compact view without importing each other |

---

## 7. Your mission and ownership

You give the agent its tools and its work. You own everything the agent can call (the MCP tool sets, how their servers are launched, and the open `clay-embeddings` server) and everything it's asked to do (the task templates, the six counties, and the task references every run is scored against). You're also the **Task Author** persona (P2). Fairness and provenance of the references are your responsibility.

**Your files** (architecture §4, §14, §15, §21):

```
claysandbox/contracts/task.py, tools.py          (contracts session)
claysandbox/tools/        toolsets.py launcher.py env.py names.py
claysandbox/tasks/        library.py render.py references.py
tasks/templates/T1.yaml … T5.yaml
tasks/aois.yaml
tasks/builders/t1_naip_items.py … t5_rules.py
tasks/curation/T2/<aoi>.yaml
tasks/process_rubrics/T1.md … T5.md
tasks/references/<template>/<aoi>/<version>.json
toolsets/T0.yaml T1.yaml T1-faulty.yaml (lgnd.yaml optional) README.md
mcp_servers/clay_embeddings/                      (server + core library)
scripts/smoke_mcp.py, scripts/stage_embeddings.py
ui/src/screens/Runs.tsx                           (R3)
tests/unit/tools/*, tests/unit/tasks/*, tests/unit/clay_embeddings/*
```

**Features:** F1 (tool side), F13 (task library), F14 (`clay-embeddings`).

## 8. Interfaces you own and consume

| Direction | Interface | With | Where defined |
|---|---|---|---|
| Own | `ToolSpec`, `ToolResult`, `ToolSession` (+ `call_blocking`), `ToolSetProvider`, `ToolSetDef`, `ServerDef`, `EnvPolicy` | Prithwish (harnesses, wrappers), 5th member (worker) | arch §7.4, §14.3 |
| Own | `TaskTemplate`, `WorkflowSpec`, `AOI`, `TaskInstance`, `TaskReference`, workflow vocabularies (open point 9) | Barath (evaluators), 5th member (service, CLI) | arch §14 |
| Own | `TaskLibrary` functions: `list_templates`, `list_aois`, `instances(templates, aois)`, `get_instance(id)`, `get_reference(instance_id, version=None)`, `build_references(template, aoi=None)` | 5th member | arch §14 |
| Own | `clay_embeddings.core` library (`embedding_at`, `similar_places`) | Your T4 builder, the server | arch §15 |
| Consume | `register` from the registry | 5th member | arch §7.6 |
| Consume | `trace` and `run` data for the Runs screen via the API client (R3) | 5th member | srs §13.2 |

## 9. Tasks

### R0 — walking skeleton

#### VIS-R0-00 · MCP smoke tests (hour 0, before contracts)

| Effort | Refs |
|---|---|
| ~1.5 h | srs X-02, X-03, X-04, A-2 · DD-033 · arch §14.3 |

**Goal:** know the real package names, versions, tool names and argument schemas of RODA, stac-mcp and openstreetmap-mcp-server before anyone codes against them.

**Steps:**

1. Find each server's package and launch command. RODA is `awslabs.roda-mcp-server` (`uvx`). For stac-mcp and openstreetmap-mcp-server, check the Clay catalog (`docs/reference/geomcp-catalog.csv`) and the projects' READMEs. Note whether each is Python (`uvx`) or Node (`npx`).
2. Write `scripts/smoke_mcp.py`. Using the MCP Python SDK (`StdioServerParameters`, `stdio_client`, `ClientSession`), it should for each server:
   - start it
   - `initialize`
   - `list_tools`
   - make one realistic call
   - print tool names, input schemas, the result shape, startup time, and whether it needed AWS credentials
3. Find a public STAC API with a `naip` collection for stac-mcp (A-2). Candidates are Microsoft Planetary Computer and Element 84 Earth Search. Pick the one that returns NAIP items for a test county and year.
4. Record the results in `toolsets/README.md`:
   - pinned versions
   - real tool names
   - which capability each tool provides (`dataset_discovery`, `imagery_search`, `geocode`; `embedding_similarity` later)
   - known quirks
5. Tell Prithwish the list of servers and versions (he needs it for the Docker image in R2).

**Acceptance:**

- [ ] Each of the three servers lists its tools and answers one call from `smoke_mcp.py`. Or the team lead knows which one fails, and the fallback from srs §7.1 is chosen.

#### VIS-R0-01 · Tool-set loader, stdio launcher, environment scrubbing

| Effort | Refs |
|---|---|
| ~3 h | FR-1.2, FR-1.9, FR-1.10 · arch §9.3, §14.3, §18 · DD-034 |

**Goal:** `ToolSetProvider.open("T0")` returns a live `ToolSession` with every tool from every server in the set, launched safely.

**Steps:**

1. `tools/toolsets.py`: load `toolsets/*.yaml` into `ToolSetDef` (servers, capabilities). Validate it, and register each tool set name under registry kind `toolset` at bootstrap (`register_toolsets(dir)`).
2. `tools/env.py` builds `EnvPolicy`. The base allowlist is `PATH`, `HOME`, `LANG`, `LC_ALL`, `TMPDIR` and uv cache variables. Add the server's own `env:` entries. If `needs_aws: true`, also pass the AWS variables:
   - `AWS_PROFILE`, `AWS_REGION`, `AWS_DEFAULT_REGION`
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`, `AWS_SESSION_TOKEN`
   - `AWS_CONTAINER_CREDENTIALS_RELATIVE_URI` and `AWS_CONTAINER_CREDENTIALS_FULL_URI` (needed on Fargate)
   - the `~/.aws` path

   Nothing else is passed through.
3. `tools/launcher.py` (`McpStdioToolSession`):
   - Start every server as a fresh subprocess per run (arch §24.1) with `StdioServerParameters(command, args, env=policy)`. Call `initialize` and `list_tools` on each.
   - Build `ToolSpec`s with `server`, `name`, `description`, `input_schema` and `capability` (from the capability map). Set `model_name` per open point 2 (`<server>__<tool>`, Bedrock-safe, ≤ 64 characters, hash suffix if truncated).
   - Run all sessions on one background asyncio loop in a dedicated thread. `call()` is async, and `call_blocking()` submits to that loop with `asyncio.run_coroutine_threadsafe` and waits.
   - Map results to `ToolResult`:
     - text content blocks joined
     - `isError` → `status="error"`
     - timeout (`timeout_s` from the server entry, default 60) → `status="timeout"`
     - server process died or failed to start → `status="error"` with `error_kind="server_unavailable"`. Other servers stay usable.
   - `aclose()` closes every session and kills leftover processes.
4. `toolsets/T0.yaml`: RODA only, `needs_aws: true`, pinned version.

**Tests:**
- `test_toolsession.py` conformance passes for `FakeToolSession`, and for the real session against RODA (marked `live`).
- Unit tests:
  - env scrubbing: a fake `SECRET_X` variable is not passed, and AWS variables only reach `needs_aws` servers
  - name mangling
  - a crashing server (`command: ["false"]`) gives `server_unavailable` and doesn't raise

**Acceptance:**

- [ ] `open("T0")` lists RODA tools.
- [ ] `call_blocking` returns a real result.
- [ ] Prithwish's Strands harness can use the session (R0 gate).

#### VIS-R0-02 · Task library, T1 template, first instance and reference

| Effort | Refs |
|---|---|
| ~2.5 h | FR-13.1, FR-13.3, FR-13.5, FR-13.6 · arch §14.1, §14.2, §14.4 · DD-028, DD-029, DD-043 |

**Steps:**

1. `tasks/library.py` implements the `TaskLibrary` functions (§8). It loads `tasks/templates/*.yaml` into `TaskTemplate` and `tasks/aois.yaml` into `AOI`s (id, name, state, FIPS, bbox, simplified geometry, tags such as `has_solar`).
2. `tasks/render.py` renders prompts with simple `{placeholder}` substitution through `str.format_map` over a read-only namespace (`aoi.name`, `aoi.state`, `year`, …). No template engine, no evaluation (arch §18). Template `defaults:` supply parameters like `year`.
3. Instance IDs are `<template>@<aoi>` (DD-043).
4. `tasks/references.py`:
   - `TaskReference` = resolved workflow spec (AOI values filled in) + output reference + weights + output schema + process rubric text.
   - Version = `<template>.v<n>+sha256:<first 12 hex of sha256(canonical JSON of workflow, output_reference, weights)>`. `n` increments only when the hash changes.
   - Write to `tasks/references/<template>/<aoi>/<version>.json` and never overwrite an existing version. `get_reference(id)` returns the latest, and `get_reference(id, version)` returns that exact one.
5. Write `tasks/templates/T1.yaml` from arch §14.2, using the real tool capabilities from VIS-R0-00.
6. `tasks/builders/t1_naip_items.py`:
   - use `pystac-client` against the chosen STAC API: collection `naip`, bbox of the AOI, datetime = the year
   - collect all item IDs (paginate)
   - write them sorted, with `inputs` (API URL, collection, year) and `method: script`
7. Put one AOI in `aois.yaml` and build its T1 reference. This is the R0 instance.

**Tests:**
- Rendering.
- Version hashing: same content gives the same version, and a change gives v(n+1).
- `get_reference` with and without a version.

**Acceptance:**

- [ ] `TaskLibrary.get_instance("T1@<aoi>")` and `get_reference(...)` work.
- [ ] 5th member's `specs/r0.yaml` runs on that instance.

### R1 — scored loop

#### VIS-R1-01 · Tool set T1, faulty tool set, six AOIs

| Effort | Refs |
|---|---|
| ~1.5 h | DD-031, DD-033 · srs O-2 · FR-4.10 · J4 |

**Steps:**

1. Write `toolsets/T1.yaml` from arch §14.3: RODA + stac + osm. Add `clay-embeddings` in R2. Pin every version and fill the capability map with the real tool names.
2. Write `toolsets/T1-faulty.yaml`, a copy of T1 for J4 that injects tool-side failures: an unreachable STAC URL for stac (tool errors), a 0.5 s timeout on osm (timeouts), and one server entry whose command fails (server unavailable). Barath uses it in the live J4 run. Mark it `test_only: true` so it's excluded from comparisons.
3. Choose the six counties (O-2) with the team lead: **four with known solar sites and two without** (DD-031). Example candidates to check: Kern CA, Maricopa AZ, Pecos TX, Robeson NC for solar, and two dense urban or forested counties for the negative controls.
4. Verify each county has:
   - NAIP coverage for the chosen year
   - GRW polygons or none, as expected (needed in R2)
   - LGND embedding partitions for the staging months (R2)
5. Record FIPS, a bbox and a simplified geometry (from the Census TIGER county file or OSM). Get the team lead's approval.

**Acceptance:**

- [ ] T1 opens with all three servers.
- [ ] T1-faulty produces each of `tool_error`, `tool_timeout` and `server_unavailable` in a smoke call.
- [ ] `aois.yaml` has six approved counties.

#### VIS-R1-02 · T2 and T5 templates, builders and process rubrics

| Effort | Refs |
|---|---|
| ~2.5 h | FR-13.1, FR-13.2, FR-13.4 · srs §12.3 · arch §10.2 · DD-029, DD-030 |

**Steps:**

1. **T2 "open datasets covering the AOI".**
   - Template: required `dataset_discovery`. Optional ordering: `geocode` before `dataset_discovery`. Done: `output_matches_schema_nonempty`. Output schema: `{"datasets": [<RODA slug>]}`.
   - Builder `t2_open_datasets.py`: read the Registry of Open Data metadata (the `awslabs/open-data-registry` dataset YAMLs, pinned to a commit) and list candidate datasets that are US- or global-coverage geospatial (by tags and keywords). Write `tasks/curation/T2/<aoi>.yaml` with the candidates.
   - You confirm or reject each candidate per AOI. The reference records `method: script+curated` and the curator (FR-13.4).
2. **T5 "ambiguous request"** (e.g. "Get me good imagery for {aoi.name}").
   - Output schema: `{"assumptions": [str], "clarifying_question": str|null, "items": [str]}`.
   - Done condition: `assumptions_or_question` (assumptions non-empty or a question present).
   - Output rules (scored by Barath's `output.t5`): (a) states assumptions or asks, (b) no fabricated IDs (every ID in `items` appears in some tool result), (c) if `items` are given, they are NAIP or other imagery items intersecting the AOI.
   - Builder `t5_rules.py` writes the rule list and any per-AOI values.
3. Write `tasks/process_rubrics/T1.md`, `T2.md` and `T5.md` for Barath's LLM process evaluator. Each covers planning, tool choice, error recovery, and honesty about uncertainty, with each item scored 0–1 and examples of good and bad behaviour.
4. Set argument constraints per template (vocabulary from open point 9), `expected_steps` and `step_limit`.

**Acceptance:**

- [ ] All three templates validate against `TaskTemplate`.
- [ ] Barath has reviewed the workflow specs (he scores against them).

#### VIS-R1-03 · Build the R1 references and spot-check them

| Effort | Refs |
|---|---|
| ~1.5 h | FR-13.5, FR-13.8 · DD-029 · UC-07 |

**Steps:**

1. Run `build_references` for T1, T2 and T5 × six AOIs (18 references). 5th member's CLI `clay-sandbox tasks build-references` calls your function. Until it's wired, use `python -m claysandbox.tasks build`.
2. Spot-check one instance per template by hand. For T1, open the STAC search in a browser and compare. For T2, read three datasets' docs. For T5, read the rules. Record `checked_by` and `checked_at` in that reference.
3. Commit all reference files.
4. Write `tasks/README.md`: how to add an AOI, how to rebuild references, what `method` means, and the data sources with their licenses.

**Acceptance:**

- [ ] 18 references are committed, each with a version, inputs and build date. Three have spot-check records.
- [ ] `clay-sandbox tasks list` shows 18 instances (after 5th member wires it).

### R2 — MVP complete

#### VIS-R2-01 · Embeddings staging and the clay-embeddings MCP server

| Effort | Refs |
|---|---|
| ~4 h | F14, FR-14.1–FR-14.6 · arch §15 · DD-015 · C-14 |

**Steps:**

1. **Packaging:** the server lives in `mcp_servers/clay_embeddings/` as an importable package `clay_embeddings` (`__main__.py`, `core.py`, `server.py`). Agree with 5th member on adding it to `pyproject.toml` as a second package, so `python -m clay_embeddings` works in the venv and in Docker.
2. **Staging** (`scripts/stage_embeddings.py`):
   - Source: `s3://us-west-2.opendata.source.coop/clay/lgnd-embeddings/monthly-aggregated/model_version=v1.5/collection=sentinel-2-l2a/chip_size=1280m/dims=256/`. It's public, so use `--no-sign-request` or an anonymous boto3 config.
   - Compute the precision-2 geohashes that cover each AOI bbox. Use a small geohash helper or the `pygeohash` package.
   - For two fixed months (e.g. one summer and one winter month of 2024; record the choice), use DuckDB to read only those partitions. Filter rows by `bbox` to each AOI plus a 10 km buffer.
   - Write one compact GeoParquet `data/embeddings/staged.parquet` and `staging_manifest.json` (partitions read, months, row counts, sha256).
   - `data/` is gitignored. Upload both files to the sandbox bucket under `data/embeddings/` and document the command.
3. **Core library** (`core.py`):
   - Load the staged file once with DuckDB, keeping the embeddings as a numpy float32 matrix with L2-normalised rows.
   - `embedding_at(lat, lon, year, month)` returns the chip whose geometry contains the point (`chips_id`, `cell_id`, `datetime`, `bbox`).
   - `similar_places(lat, lon, year, month, k=10, search_bbox=None)` takes the query chip's vector and computes cosine similarity against chips in `search_bbox` (default: all staged chips for that month). It returns the top-k, excluding the query chip, with ties broken by `chips_id` (FR-14.5).
4. **Server** (`server.py`, MCP Python SDK `FastMCP` over stdio): two tools wrapping the core functions. Each tool description states that it uses Clay v1.5 embeddings from LGND (Sentinel-2 L2A, 1280 m chips), covers only the staged areas and months, and is licensed CC BY 4.0 (FR-14.6).
5. Add `clay-embeddings` to `toolsets/T1.yaml` with capability `embedding_similarity`.

**Tests:**
- Core functions on a tiny synthetic GeoParquet: containment, top-k order, deterministic ties, empty results.
- One stdio round-trip through `McpStdioToolSession`.

**Acceptance:**

- [ ] `similar_places` returns 10 chips for each AOI's query point.
- [ ] T1 opens with four servers.

#### VIS-R2-02 · T3 and T4 templates and references

| Effort | Refs |
|---|---|
| ~3 h | FR-13.1–FR-13.8 · srs §12.3 · arch §10.2, §15 · DD-030 |

**Steps:**

1. **T3 "candidate solar sites in the AOI".**
   - Template: required `geocode` or bbox given, `dataset_discovery`. Done: `output_matches_schema_nonempty` (an empty list is valid). Output schema: `{"sites": [{"lat": float, "lon": float}]}`.
   - The prompt tells the agent it may use any dataset it finds, and that it should return an empty list if there are none.
   - Builder `t3_solar_sites.py`: download Global Renewables Watch v1.0 from its GitHub release (MIT). Check the asset format and pick the solar layer. Clip to the AOI geometry with shapely and write polygon centroids plus geometries. The two negative-control AOIs must give `[]`.
   - If USPVDB becomes reachable, it can be added later as a second builder input (new version).
2. **T4 "places similar to a given place".**
   - Each AOI gets a query point (e.g. a known solar farm or a distinctive field) and a month, set in `aois.yaml` under `t4`.
   - Template: required `embedding_similarity`. Argument constraints: `point_within_aoi`, `k_at_most`. Output schema: `{"chips": [<chips_id>]}`.
   - Builder `t4_similar_places.py` calls `clay_embeddings.core.similar_places` with the same parameters the prompt gives, so the key and the tool agree by construction (DD-030).
3. Write process rubrics T3 and T4. Build 12 references, spot-check one per template, and commit.

**Acceptance:**

- [ ] 30 references in total are committed (5 templates × 6 AOIs).
- [ ] Barath's `output.t3` and `output.t4` score a hand-made correct output at 1.0.

#### VIS-R2-03 · Optional LGND tool set, tool-set docs, attribution

| Effort | Refs |
|---|---|
| ~1 h | DD-015 · C-14 · FR-5.6 |

**Steps:**

1. If Clay confirms the LGND Geo MCP whitelist, add `toolsets/lgnd.yaml` (credentials via `env:` from the user's environment, never committed). If not, add a FUTURE-WORK row.
2. Finish `toolsets/README.md`: each tool set, its servers and versions, capabilities, and which servers get AWS credentials.
3. Give 5th member the attribution text for the README and reports: LGND embeddings CC BY 4.0, OSM ODbL, GRW MIT, NAIP public domain.

**Acceptance:**

- [ ] Docs are merged.
- [ ] Attribution appears in the README and in a report that used OSM or embeddings.

### R3 — UI

#### VIS-R3-01 · Runs screen

| Effort | Refs |
|---|---|
| ~2.5 h | FR-8.2, FR-8.7 · srs §9.2 · wireframe screen 2 |

**Steps:**

1. In 5th member's UI shell, build `ui/src/screens/Runs.tsx` using only the generated API client (`GET /runs` with filters).
2. Columns: run ID (short), task instance, configuration (model, harness, tool set), state, workflow composite, output metric, cost, started at.
3. Add filters for eval, template, AOI, configuration and state. A row opens the Report screen. State badges match srs §8.3, and `infra_excluded` / `skipped_eval_cap` are visibly different from failures.

**Acceptance:**

- [ ] The screen lists runs of the demo eval.
- [ ] Filters work and clicking opens the report.
- [ ] The UI build passes in CI.

## 10. Hand-offs

| When | You give | To | What they do with it |
|---|---|---|---|
| R0 hour 0 | Server list, versions, real tool names | Prithwish, Barath | Docker image, capability-based rules |
| R0 | `ToolSession` for T0, `TaskLibrary` with one T1 instance | Prithwish, 5th member | R0 gate |
| R1 | T1 and T1-faulty tool sets, six AOIs, 18 references, process rubrics | Barath (evaluators, live J4), 5th member (CLI) | J1, J4 |
| R2 | `clay-embeddings`, 30 references | Barath (T3/T4 evaluators), Prithwish (Docker) | Full comparison eval |
| R2 | Attribution text | 5th member | README, reports |

## 11. Risks and fallbacks

| Risk | Fallback |
|---|---|
| stac-mcp or OSM server won't run | T1 = RODA + whichever works. Prompts give the AOI bbox directly so `geocode` is optional. Note it in DD-033 follow-up |
| No STAC API serves NAIP for the chosen years | Change the year. Or T1 uses RODA's NAIP dataset listing with a coarser metric (record a new task-reference version) |
| GRW asset hard to use | Build T3 from OSM `power=plant` + `plant:source=solar` via Overpass for the AOIs, recorded as `method: script` with the new source |
| Embedding partitions too large | Fewer months, a smaller buffer, or only the four solar AOIs for T4 |
| Curation for T2 takes too long | Curate three AOIs fully. Mark the other three's references `method: script` with a note, and tell Barath to report T2 separately |

## 12. Effort summary

| Release | Tasks | Hours (rough) |
|---|---|---|
| R0 | Contracts session, VIS-R0-00 to R0-02 | 8 |
| R1 | VIS-R1-01 to R1-03 | 5.5 |
| R2 | VIS-R2-01 to R2-03 | 8 |
| R3 | VIS-R3-01 | 2.5 |
| **Total** | | **≈ 24** |

## 13. Release checklists

**R0**
- [ ] Smoke results in `toolsets/README.md`. Server list sent to Prithwish
- [ ] `contracts/task.py`, `tools.py`, fakes and conformance merged
- [ ] Launcher with env scrubbing. T0 live
- [ ] Task library + T1 template + one instance and reference

**R1**
- [ ] T1 and T1-faulty tool sets
- [ ] Six AOIs approved
- [ ] T2 and T5 templates, rubrics, 18 references, three spot-checks
- [ ] `tasks/README.md`

**R2**
- [ ] `clay-embeddings` server and staging (data uploaded to the bucket)
- [ ] T3 and T4, 30 references in total
- [ ] LGND tool set or FUTURE-WORK row
- [ ] Attribution text delivered. README section on tools and tasks

**R3**
- [ ] Runs screen
