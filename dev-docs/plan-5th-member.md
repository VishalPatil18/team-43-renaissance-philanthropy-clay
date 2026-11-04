# Plan — 5th member (WS5 Platform and presentation)

> **For agents — what this file is:** 5th member's task plan for building the Clay agent-eval sandbox, release by release (R0 → R3). Sections 1–6 are shared by all five plans. Sections 7 onwards are 5th member's own. Read it together with [srs.md](srs.md) (what to build) and [architecture.md](architecture.md) (how it fits together). Those two files plus this plan are all that's needed to do the work. Requirement IDs (FR-x.y, NFR-…) are the acceptance criteria. Decisions are in [design-decisions.md](design-decisions.md) (ownership: DD-044).

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

You hold the system together. You own:

- **The repo:** the scaffold everyone works in, and the CI that guards every merge.
- **The configuration:** the eval spec that holds every parameter, and the registry that turns names into components.
- **Orchestration:** the service layer and run worker, which compose everyone's parts into a run and an eval. This is the only place allowed to import every component.
- **Execution and access:** the local executor, the CLI and the API.
- **Presentation:** the report renderers, the README, and the R3 UI shell.

If a run doesn't go end to end, the fix usually starts in your wiring.

**Your files** (architecture §4, §16, §21, §22):

```
pyproject.toml, uv.lock, .importlinter, .gitignore, .github/workflows/ci.yml
claysandbox/contracts/spec.py manifest.py report.py execution.py registry.py ids.py interfaces.py
claysandbox/platform/  registry_bootstrap.py service.py worker.py executors/local.py
                       reports/assemble.py reports/templates/report.md.j2 report.html.j2 eval_report.*.j2
claysandbox/cli.py, claysandbox/api.py
api/openapi.json, scripts/export_openapi.py
specs/*.yaml (except specs/live/, Barath), specs/README.md (model table from Prithwish)
README.md
ui/ (shell, client, routing, New Run screen)                    (R3)
tests/journeys/test_j2_replay.py test_j3_evaluator_swap.py test_j8_fresh.py test_j9_schema.py
tests/unit/platform/*
```

**Features:** F5 (rendering, manifest), F6 (registry), F7 (service side), F8 (UI shell), F9 (orchestration), F12 (spec, API, reproducibility), F15 (local executor).

## 8. Interfaces you own and consume

| Direction | Interface | With | Where defined |
|---|---|---|---|
| Own | `EvalSpec` (and parts), `RunManifest`, `ComponentRef` | Everyone | arch §7.2, §7.3 |
| Own | `Report`, `EvalReport` | Barath (content), Shivaani and Barath and Vishal (UI screens) | arch §7.5 · DD-039 |
| Own | `RunRequest`, `RunStatus`, `Executor` (+ `local`) | Prithwish (Fargate) | arch §7.4 |
| Own | Registry (`register`, `resolve`, `list_components`) | Everyone | arch §7.6 |
| Own | Service layer methods, CLI, HTTP API, OpenAPI | UI, users | arch §16 · srs §13 |
| Consume | Harnesses, model adapter, wrappers, guards, prices, estimator | Prithwish | arch §9, §12 |
| Consume | `ToolSetProvider`, `TaskLibrary` | Vishal | arch §14 |
| Consume | Tracers, `RunEventSink`, `RunStore`, reader, summarizers, query helpers, tracer comparison | Shivaani | arch §13 |
| Consume | Evaluators, stats, comparisons, validation | Barath | arch §10, §11 |

## 9. Tasks

### R0 — walking skeleton

#### M5-R0-00 · Repository scaffold and CI (hour 0, before contracts)

| Effort | Refs |
|---|---|
| ~1 h | DD-020, DD-035, DD-036 · arch §4.1, §21, §22.2 · FR-12.6 |

**Steps:**

1. `pyproject.toml`:
   - project `claysandbox`, `requires-python = ">=3.12"`
   - console script `clay-sandbox = "claysandbox.cli:app"`
   - dependencies from arch §20.1. Pin `strands-agents` and `mcp` to exact versions, agreed with Prithwish and Vishal.
   - dev group: ruff, mypy, pytest, import-linter, moto
   - a second package `clay_embeddings` from `mcp_servers/clay_embeddings` (Vishal adds the code)
   - `uv lock`, and commit `uv.lock`.
2. Create the package skeleton with `__init__.py` files for every folder in arch §21 (`contracts`, `runtime`, `tools`, `tasks`, `tracing`, `store`, `summary`, `evaluation`, `platform`), plus `specs/`, `samples/`, `scripts/` and `tests/{unit,journeys,live,fixtures}`.
3. `.importlinter`: contracts from arch §4.1.
   - `contracts` imports no other `claysandbox` package.
   - Each component package is independent of the others.
   - Only `platform` imports components.
   - `cli` and `api` import only `platform` (and `contracts`).
4. `.gitignore`: add `runs/`, `evals/`, `data/`, `infra/cdk.out/`, `ui/node_modules/`, `ui/dist/`.
5. `.github/workflows/ci.yml` with steps 1–5 of arch §22.2 now. Add 6–8 when those parts land:
   - `uv sync --frozen`
   - ruff check and format check
   - mypy
   - `lint-imports`
   - a secret scanner (e.g. gitleaks action)
   - pytest

   Tests marked `live` are skipped in CI (`-m "not live"`).
6. Push to `main` before the contracts session.

**Acceptance:**

- [ ] A fresh clone runs `uv sync && uv run pytest` green.
- [ ] CI is green on `main`.

#### M5-R0-01 · Your contracts: spec, manifest, report, execution, registry, IDs

| Effort | Refs |
|---|---|
| ~1.5 h (session + finish) | FR-12.1, FR-6.1–FR-6.3, SC7 · arch §7.2, §7.3, §7.5, §7.6 · DD-021, DD-043 |

**Steps:**

1. `spec.py`: Pydantic models matching the YAML in arch §7.3:
   - `EvalSpec`
   - `ComponentChoice(name, version?, params)`
   - `Configuration`, `Variant(name, override)`
   - `TasksSelection(templates, aois | "all" | instances)`
   - `Budget(run: RunBudget, eval: EvalBudgetSpec)`, `LoopGuard`
   - `ExecutorChoice`, `StoreChoice`, `StatsParams`
   - `offline`, `seed`, `trials`, `infra_retries`, `summary`

   Every field has a description, because they become the schema docs.
2. `manifest.py`: `RunManifest` exactly as in arch §7.2, plus `ComponentRef`.
3. `report.py`: `Report` and `EvalReport` (arch §7.5). Agree the eval report fields with Barath in the session.
4. `execution.py`: `RunRequest` (spec hash, run ID, eval ID, configuration, task instance, trial index, attempt), `RunStatus`, and the `Executor` protocol.
5. `registry.py` (arch §7.6): `register(kind, name)`, `resolve`, `list_components(kind)`. Components declare `version` and a `Params` model, and `list_components` returns name, version and `Params.model_json_schema()`.
6. `ids.py`: `new_id()` (ULID), `instance_id(template, aoi)`, `short(id)`.
7. `interfaces.py`: re-export every Protocol.
8. Fakes and conformance: `ImmediateExecutor`, `test_executor.py`, `test_registry.py`.
9. Merge `contracts/v1` at the end of the session.

**Acceptance:**

- [ ] `contracts/v1` merged. Everyone's imports resolve. Conformance runs.

#### M5-R0-02 · Service layer, run worker, local executor

| Effort | Refs |
|---|---|
| ~3 h | UC-01 · srs §8.2 steps 2, 6–10 · arch §8.1, §16 · FR-5.1, FR-15.1 |

**Steps:**

1. `platform/registry_bootstrap.py`: import every plugin module (each owner adds their line) and call `register_toolsets("toolsets/")`.
2. `platform/worker.py`, `run_one(request: RunRequest) -> RunStatus`, following the order in arch §8.1:
   1. Resolve components from the registry with the configuration's params.
   2. `task = library.get_instance(...)` and `reference = library.get_reference(...)`.
   3. `session = toolset_provider.open(toolset)`, which gives `tools = session.list_tools()`.
   4. Build `RunManifest` (R0: the core fields; R1: all of them) and `store.create_run(manifest)`.
   5. Open the tracer, `sink = RunEventSink(...)`, and emit `run_start`.
   6. Build `InstrumentedModel` and `InstrumentedTools` (Prithwish) with the guard and price table.
   7. `outcome = harness.run(RunContext(...))`.
   8. Emit `final_output` (if any) and `run_end` (state and totals: steps, tokens, `cost_usd`, `wall_ms`) through the sink (open point 11).
   9. Close the tracer and the session, and write `status.json`.
3. `platform/executors/local.py`: `@register("executor", "local")` with a `ProcessPoolExecutor` (`mp_context="spawn"`), `max_parallel` workers, `submit` / `poll` / `cancel`. Worker processes call `registry_bootstrap` first.
4. `platform/service.py`:
   - `validate_spec(spec)`: schema, registered names, instances exist, every model priced (`PriceTable.has`)
   - `launch_eval(spec, confirm)`: R0 is one configuration on the given instances. Write `evals/<id>/spec.yaml` and `plan.json` and submit.
   - `eval_status(id)`
   - `registry()`
   - Structured JSON logging per DD-040: `eval_id` and `run_id` on every log record.

**Tests:** a worker run using only fakes (`FakeModelAdapter`, `FakeToolSession`, `MemoryTracer`, `MemoryRunStore`), checking the full event order and the manifest.

**Acceptance:**

- [ ] The worker on fakes passes.
- [ ] With Prithwish's and Vishal's real parts, the R0 gate passes.

#### M5-R0-03 · CLI `run` and `registry`, R0 spec

| Effort | Refs |
|---|---|
| ~1 h | FR-12.3 · srs §13.1 |

**Steps:**

1. `claysandbox/cli.py` (Typer):
   - `run <spec>`: validate, launch, wait, print run IDs and paths
   - `registry`: table of kinds, names and versions
   - `status <eval_id>`
2. Write `specs/r0.yaml`: Nova Lite (ID from Prithwish), `strands`, `T0`, `jsonl`, one T1 instance, N=1, `budget.run.max_usd: 0.25`.
3. Write `specs/README.md` with the model-role table from Prithwish.

**Acceptance:**

- [ ] `uv run clay-sandbox run specs/r0.yaml` produces the R0 run folder. **R0 gate.**

### R1 — scored loop

#### M5-R1-01 · Run post-processing and the full manifest

| Effort | Refs |
|---|---|
| ~2 h | FR-5.1, FR-5.2, SC7 · srs §8.2 steps 12–14, §12.2 · arch §10 |

**Steps:**

1. After `run_end`, for every terminal state except `skipped_eval_cap`, the worker runs:
   - **summary:** the summarizer from `spec.summary`. LLM summary and LLM evaluator get an **uninstrumented** model adapter (evaluation cost).
   - **assessments:** each evaluator in `spec.evaluators`, resolving `output` per template. Store each with `append_assessment`.
   - **report:** assemble and render (M5-R1-02).
2. Fill every manifest field from srs §12.2:
   - git SHA from `git rev-parse HEAD`, or the `GIT_SHA` env var in Docker
   - `uv.lock` sha256, spec sha256 (canonical JSON)
   - package version, price table version
   - executor and environment (OS, Python version, host or Fargate task ARN)
   - seed, budget and loop-guard settings
   - MCP servers with versions
   - tool list with schemas (from the session)
3. Status updates: `running` → the terminal state.

**Acceptance:**

- [ ] A live run produces `summary.json`, `assessments/*.json` and reports.
- [ ] J1 step 1 manifest check passes (every field listed in J1.1 is present).

#### M5-R1-02 · Report assembly and renderers

| Effort | Refs |
|---|---|
| ~3 h | FR-5.3–FR-5.6 · DD-039 · arch §7.5 · wireframe screen 3 |

**Steps:**

1. `platform/reports/assemble.py`: `build_report(manifest, trace, summary, assessments) -> Report` with:
   - header
   - headlines: latest workflow composite and output metric
   - sub-scores with evidence
   - summary claims with citations
   - timeline: events with error flags and a recovered mark, computed with the same rule as arch §10.1
   - per-step latency and cost table (agent vs evaluation)
   - totals
   - the full manifest
   - attribution notices (if the tool set includes osm or clay-embeddings; text from Vishal)
   - artefact paths
   - one section per assessment, with the evaluator version
2. Jinja templates:
   - `report.md.j2`: readable on GitHub. Tables, sub-score bars as text (`████░░ 0.67`), event IDs as anchors.
   - `report.html.j2`: one self-contained file with inline CSS and no external assets (FR-5.4). The layout follows the wireframe: header pills, two score cards, summary, signals, timeline, output section, provenance.
   - Use the label "task reference", never "rubric".
3. `store.write_report(run_id, report, {"report.md": ..., "report.html": ...})`.

**Acceptance:**

- [ ] A sample run's `report.md` renders on GitHub.
- [ ] `report.html` opens offline.
- [ ] All the J1 step 5 contents are present.

#### M5-R1-03 · `replay` and `rescore`, offline mode

| Effort | Refs |
|---|---|
| ~1.5 h | F7, FR-7.1–FR-7.4, FR-6.4 · UC-04, UC-05 · arch §8.4 · J2, J3.4, J8 |

**Steps:**

1. `service.replay(run_path, evaluators=None, offline=False, reference="manifest")`:
   - read-only source (local, `samples/`, or S3 via Shivaani's mirror), with writes going to `./runs`
   - read the manifest and trace
   - summary: reuse the stored one, or the deterministic summarizer if offline
   - evaluate against the reference version in the manifest (or `latest`, labelled)
   - append assessments and re-render
   - return the deterministic score diff against the previous assessments
2. Offline: never construct a Bedrock adapter. Skip `llm_process` and the LLM summary, and say so in the report. Log `offline=true` at start (FR-7.2).
3. `service.rescore(run_ids | eval_id, evaluator)`.
4. CLI: `replay`, `rescore`.
5. Journey tests in CI on Shivaani's samples:
   - `test_j2_replay.py`: offline replay produces a report, and deterministic scores equal the stored ones.
   - `test_j3_evaluator_swap.py`: re-score with `workflow@0` vs `@1`, both assessments present, trace unchanged.
   - `test_j8_fresh.py`: replay with AWS env vars removed.

**Acceptance:**

- [ ] The three journey tests pass in CI. **R1 gate (J2).**

#### M5-R1-04 · Infra retries and run lifecycle

| Effort | Refs |
|---|---|
| ~1 h | DD-012 · FR-15.2 · srs §8.3 · arch §8.3 |

**Steps:**

1. In the local executor, when a run ends with `infra_error` and attempts < `infra_retries + 1`, schedule a new attempt with a new run ID, linked in `manifest.attempts`. Otherwise mark it `infra_excluded` in `plan.json`.
2. `plan.json` holds every planned run with its state from srs §8.3: `planned`, `running`, `completed`, `budget_stopped`, `agent_failed`, `infra_retry`, `infra_excluded`, `skipped_eval_cap`.
3. A worker crash (process died) counts as `infra/executor_failure`. The partial trace is kept.

**Acceptance:**

- [ ] Unit tests with a fake harness that raises `InfraError` twice and then succeeds.

### R2 — MVP complete

#### M5-R2-01 · Full evals: expansion, variants, estimate, eval cap, eval reports

| Effort | Refs |
|---|---|
| ~3 h | F9, FR-9.1–FR-9.3, FR-11.6, FR-11.9 · UC-02, UC-03 · arch §8.5 |

**Steps:**

1. Expansion:
   - `aois: all` and template lists → instances
   - `baseline` + variants (deep-merge `override` into the baseline)
   - warn when a variant changes more than one of model, harness or tool set (FR-9.3)
   - × `trials` → run plan, ordered instance-major with configurations round-robin (arch §8.5)
2. `service.estimate(spec)` calls Prithwish's `CostEstimator`. `launch_eval` requires `confirm=True` and refuses when `exceeds_eval_cap`. Write `estimate.json`.
3. Eval driver: a background thread that submits up to `max_parallel` runs, calls `EvalBudget.add(cost)` after each run, stops launching when exhausted (`skipped_eval_cap`), and updates `plan.json`. `status --resume` re-attaches to an eval's plan after a restart (arch §24.2).
4. On completion:
   - Barath's `build_eval_report_content` gives the `EvalReport`
   - render `eval_report.md` and `eval_report.html`
   - optional S3 mirror
5. CLI and service: `eval`, `estimate`, `compare-evaluators` (Barath), `compare-tracers` (Shivaani), `validate-evaluator` (Barath), `tasks list`, `tasks build-references` (Vishal).
6. Spec validation adds the DD-027 judge-family check (rule from Barath).

**Acceptance:**

- [ ] A fake-component eval (4 configurations × 6 instances × 3) runs end to end and renders an eval report.
- [ ] The eval cap stops launches.
- [ ] `estimate` prints a breakdown.

#### M5-R2-02 · HTTP API and OpenAPI

| Effort | Refs |
|---|---|
| ~3 h | FR-12.2–FR-12.5, FR-12.9 · srs §13.2 · arch §16 · J9 |

**Steps:**

1. `claysandbox/api.py` (FastAPI): every route in srs §13.2 as a thin wrapper over the service.
   - `POST /evals` requires `"confirm": true`. `GET /evals/{id}` reads `plan.json`.
   - `GET /schema/eval-spec` returns `EvalSpec.model_json_schema()` **post-processed** so every component `name` field is an `enum` of registered names for its kind (FR-6.3).
   - `GET /registry` returns `list_components()`.
   - `GET /runs` is paged and filtered through Shivaani's `list_runs`.
   - Artefacts are returned as JSON. HTML reports are served with `text/html`.
2. `clay-sandbox serve` binds to `127.0.0.1:8000` by default (DD-034). Allow CORS from `http://localhost:5173` only (the UI dev server).
3. `scripts/export_openapi.py` writes `api/openapi.json`. `--check` fails if it differs (CI step 6).
4. `tests/journeys/test_j9_schema.py`:
   - every option used in J1–J7 appears in the schema (model, harness, tracer, evaluator, tool set, task, trials, every budget limit, executor)
   - an eval launched through the API with fakes completes

**Acceptance:**

- [ ] J9 passes in CI.
- [ ] `api/openapi.json` is committed.

#### M5-R2-03 · README, sample specs, CI additions

| Effort | Refs |
|---|---|
| ~1.5 h | FR-12.7 · `docs/05` · C-10, C-14 · J8 |

**Steps:**

1. Write `README.md` with these sections (owners supply their parts by the R2 gate):
   - what it is
   - quick start (offline replay with no AWS)
   - setup
   - live run
   - replay and re-score
   - swapping components (with spec snippets)
   - running a comparison
   - budget guard and estimate
   - tool sets and tasks (Vishal)
   - traces, store and samples (Shivaani)
   - scoring and statistics (Barath)
   - models, Docker and AWS deploy (Prithwish)
   - API
   - repo layout
   - license (MIT, plus the note on Clay's Apache-2.0 requirement, DD-037)
   - data attributions
2. Sample specs:
   - `specs/single-run.yaml`
   - `specs/compare-default.yaml` (arch §7.3, FR-9.7)
   - `specs/swap-model.yaml`, `swap-harness.yaml`, `swap-tracer.yaml` (J3)
   - `specs/budget-tight.yaml` and `budget-off.yaml` (J7)
3. CI: add the OpenAPI check, and `cdk synth` (with Prithwish).
4. Run J8 for real: a teammate (whoever is free) follows the README on a clean machine or container. Fix anything that needed help.

**Acceptance:**

- [ ] The J8 dry run succeeds with no outside help.
- [ ] The `docs/05` README item is ticked.

### R3 — UI

#### M5-R3-01 · UI shell, generated client, New Run screen, SSE

| Effort | Refs |
|---|---|
| ~4 h | F8, FR-8.1, FR-8.5, FR-8.7 · DD-016, DD-036 · srs O-5 · wireframe screen 1 |

**Steps:**

1. **First thing on Day 3 (or the evening before):** scaffold `ui/` with Vite + React + TypeScript and react-router, using a top bar like the wireframe (New Run, Runs, Reports/Comparison). Generate the typed client from `api/openapi.json`, for example with `openapi-typescript` + `openapi-fetch`. Commit empty screen stubs for Runs (Vishal), Report (Shivaani) and Comparison (Barath) so they can start in parallel.
2. **New Run screen:**
   - build the form from `GET /schema/eval-spec` and `GET /registry`: task templates and AOIs, model, harness, tool set, tracer, evaluators, trials, budget limits, executor
   - show the estimate (`POST /evals/estimate`), then launch with confirm
   - the team lead decides O-5 (whether the wireframe's "Input data" box maps to AOI selection). Default to AOI selection.
3. **SSE:** `GET /evals/{id}/events` streams state changes from `plan.json` and `status.json` (poll the files every second server-side, push only changes). The UI shows live progress.
4. **CI:** install, regenerate the client and fail on diff, type-check, build (arch §22.2 step 8).
5. Integrate the others' screens and run the R3 exit check with the team lead.

**Acceptance:**

- [ ] From the browser: launch a run, watch it, open its report, open a comparison. **R3 gate.**

## 10. Hand-offs

| When | You give | To | What they do with it |
|---|---|---|---|
| R0 hour 0 | Scaffold and CI on `main` | Everyone | Branch from it |
| R0 hour 1 | `spec.py`, `manifest.py`, `report.py`, `execution.py`, registry | Everyone | Build against them |
| R0 | Worker, local executor, CLI `run` | Prithwish, Vishal | R0 gate |
| R1 | Reports, replay and rescore, retries | Barath (live journeys), Shivaani (samples) | J1, J2, J4 |
| R2 | `eval`, `estimate`, API, OpenAPI, README, sample specs | Barath (R2 gate evals), Prithwish (demo) | J3, J5–J9 |
| R3 | UI shell, client, stubs | Vishal, Shivaani, Barath | Their screens |

## 11. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Contract churn after R0 | Hold the line: DD entry + version bump + owner approval. Absorb small mismatches in the worker, not in contracts |
| ProcessPool and MCP subprocesses misbehave together (spawn, signals) | `max_parallel=1` fallback. Or a thread pool, since runs are I/O-bound |
| Eval driver dies with the API process | `status --resume` from `plan.json`. Documented debt (arch §24.2) |
| Dynamic enum schema complicates client generation | Keep names as `string` in OpenAPI, serve enums only from `/schema/eval-spec` and `/registry` |
| UI runs late | The static `report.html` and `eval_report.html` carry the demo. The UI shows what's ready |

## 12. Effort summary

| Release | Tasks | Hours (rough) |
|---|---|---|
| R0 | M5-R0-00 to R0-03 | 6.5 |
| R1 | M5-R1-01 to R1-04 | 7.5 |
| R2 | M5-R2-01 to R2-03 | 7.5 |
| R3 | M5-R3-01 | 4 |
| **Total** | | **≈ 25.5** |

## 13. Release checklists

**R0**
- [ ] Scaffold and CI on `main` before the session
- [ ] `contracts/v1` merged
- [ ] Worker, service and local executor
- [ ] `clay-sandbox run specs/r0.yaml`. **R0 gate**

**R1**
- [ ] Post-processing and full manifest
- [ ] Reports (JSON, Markdown, HTML)
- [ ] `replay` and `rescore`. J2, J3.4, J8 tests in CI
- [ ] Infra retries and lifecycle states

**R2**
- [ ] `eval` with variants, estimate, eval cap, eval reports
- [ ] All CLI commands
- [ ] API, OpenAPI export and check. J9 in CI
- [ ] README and sample specs. J8 dry run

**R3**
- [ ] UI shell, client, stubs, New Run, SSE. **R3 gate**
