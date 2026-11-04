# Plan — Shivaani (WS3 Trace and store)

> **For agents — what this file is:** Shivaani's task plan for building the Clay agent-eval sandbox, release by release (R0 → R3). Sections 1–6 are shared by all five plans. Sections 7 onwards are Shivaani's own. Read it together with [srs.md](srs.md) (what to build) and [architecture.md](architecture.md) (how it fits together). Those two files plus this plan are all that's needed to do the work. Requirement IDs (FR-x.y, NFR-…) are the acceptance criteria. Decisions are in [design-decisions.md](design-decisions.md) (ownership: DD-044).

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

You own the record of what happened. Every run produces a trace in the schema you define. It's written by your tracers, stored and protected by your run store, and read back by your reader for replay, scoring and statistics. You also turn traces into plain language (the summarizers), and you curate the committed sample runs and the planted traces that prove the evaluator works. Principle P1, "the trace is the truth", rests on your code.

**Your files** (architecture §4, §13, §21):

```
claysandbox/contracts/trace.py, store.py, summary.py   (contracts session, incl. trace_digest)
claysandbox/tracing/   sink.py jsonl.py otel.py tee.py redact.py compare.py
claysandbox/store/     local.py s3.py reader.py query.py
claysandbox/summary/   deterministic.py llm.py citations.py
samples/runs/ samples/evals/ samples/planted/ samples/README.md
scripts/make_planted.py
ui/src/screens/Report.tsx                                (R3)
tests/unit/tracing/*, tests/unit/store/*, tests/unit/summary/*
tests/journeys/test_j3_tracer_swap.py
```

**Features:** F2 (trace capture), F3 (summary), F7 (loading side), F9 (tracer comparison).

## 8. Interfaces you own and consume

| Direction | Interface | With | Where defined |
|---|---|---|---|
| Own | `TraceEvent` types, `ErrorInfo`, `EventSink`, `Trace`, `trace_digest` | Everyone | arch §7.1 |
| Own | `Tracer` (`jsonl`, `otel`, `tee`) | Prithwish (wrappers emit through the sink), 5th member (worker opens and closes) | arch §7.4 |
| Own | `RunStore` (+ eval artefacts, open point 10), `query` helpers (`runs_for_eval`, `assessments_for_eval`, `token_history`, `list_runs`) | 5th member, Barath, Prithwish (estimate) | arch §7.4, §13 |
| Own | `Summarizer` (`llm`, `deterministic`), `Summary`, `Claim` | 5th member (worker) | arch §10.4 |
| Own | Tracer comparison result (`MeasurementComparison`, kind `tracer`) | Barath (eval report content), 5th member | arch §11 |
| Consume | `ModelAdapter`, `PriceTable` (summary model calls and cost) | Prithwish | arch §7.4, §12 |
| Consume | Live runs from the gate evals | Barath | §10 |

## 9. Tasks

### R0 — walking skeleton

#### SHI-R0-00 · Prepare the trace contract (hour 0)

| Effort | Refs |
|---|---|
| ~0.5 h | arch §7.1 · DD-011 |

Draft `contracts/trace.py` from arch §7.1 before the session starts, so the session only reviews it:
- event types with the discriminator
- `ErrorInfo`
- the `EventSink` protocol (open point 3)
- the `Trace` container (open point 4)
- the `trace_digest` signature (open point 12)

#### SHI-R0-01 · Event sink, JSONL tracer, redaction

| Effort | Refs |
|---|---|
| ~2 h | FR-2.1, FR-2.5, FR-2.6, FR-2.9, FR-2.10 · arch §7.1, §9.3, §18 |

**Steps:**

1. `tracing/sink.py`, `RunEventSink(run_id, run_dir, tracer)`:
   - assigns `seq` (from 0, strictly increasing) and `event_id = f"{run_id}:{seq}"`
   - fills `run_id`
   - passes every event through `redact()`
   - calls `tracer.emit`
   - `put_blob(bytes)` writes `blobs/<sha256>` once (dedupe) and returns `("blobs/<sha>", sha)`
   - `last_event_id` property
   - thread-safe (a lock), because tool calls may come from the MCP loop thread
2. `tracing/jsonl.py`, `@register("tracer", "jsonl") JsonlTracer`:
   - `open()` creates `trace.jsonl`
   - `emit()` writes one JSON line and flushes, and `os.fsync`s at `run_end` (FR-2.6)
   - `close()` flushes
   - `emit` never raises into the caller (arch §9.3): on I/O error it logs a sandbox error (DD-040) and sets `incomplete=True`, which the worker writes into `status.json`
3. `tracing/redact.py` applies redaction to `args`, previews, text and error messages:
   - AWS access key IDs (`AKIA`/`ASIA` + 16 characters)
   - 40-character secrets that follow `aws_secret_access_key`-like keys
   - `Authorization:` and `Bearer` headers
   - session tokens
   - the values of any env var whose name contains `SECRET`, `TOKEN`, `PASSWORD` or `KEY`

   Replace each with `"<redacted>"`.

**Tests:**
- Ordering and `seq` under concurrent emits.
- Blob dedupe.
- A tracer that raises doesn't break the sink.
- Redaction cases.
- `test_tracer.py` conformance: round-trip equality and flush on close.

**Acceptance:**

- [ ] Conformance passes for `jsonl` and `MemoryTracer`.

#### SHI-R0-02 · Local run store

| Effort | Refs |
|---|---|
| ~2.5 h | FR-5.1, FR-7.3, NFR-PROV-2 · arch §13.1, §13.2 · DD-022 |

**Steps:**

1. `store/local.py`, `@register("store", "local") LocalRunStore(root="./runs", evals_root="./evals")`, with the exact layout from arch §13.1.
2. Write rules (arch §13.2):
   - `create_run` fails if the folder exists, and writes `manifest.json` once
   - `trace.jsonl` belongs to the tracer
   - after `status.json` shows a terminal state, any write to `manifest.json` or `trace*.jsonl` raises `StoreWriteRefused`
   - `append_assessment` writes `assessments/<assessment_id>.json` and never overwrites
   - `write_summary` and `write_report(run_id, report, rendered)` may overwrite (they're views)
3. `status.json`: `{state, updated_at, attempt, incomplete}`. Use atomic writes (write to a temp file, then `os.replace`).
4. Eval artefacts (open point 10): `create_eval` writes `evals/<id>/spec.yaml`. Also `write_eval_artifact`, `read_eval_artifact` and `list_eval_runs` (read from `plan.json`).
5. Support a read-only root (e.g. `samples/`) for replay. Writes go to a second root, so samples stay untouched.

**Tests:**
- `test_store.py` conformance (shared with `MemoryRunStore`).
- Immutability after `run_end`.
- Atomic status.
- Read-only sample root.

**Acceptance:**

- [ ] The R0 live run leaves a complete, valid folder.
- [ ] Conformance passes.

#### SHI-R0-03 · Trace reader

| Effort | Refs |
|---|---|
| ~1 h | FR-2.9, FR-7.5 · arch §8.4 |

**Steps:**

1. `store/reader.py`, `read_trace(run_dir) -> Trace`:
   - parse each line with a `TypeAdapter(TraceEvent)`
   - set `incomplete=True` if there's no `run_end` or a line is truncated (crash case), and keep every valid event up to it
   - provide `blob(ref)`
2. Upgrades: a table `{"1.0": identity}` keyed by `schema_version`. A future 1.1 adds one function. Unknown newer versions raise a clear error.
3. In R2, add reading `trace.otlp.jsonl` (SHI-R2-01) back into the same `Trace`.

**Acceptance:**

- [ ] Reads the R0 run.
- [ ] A truncated-file test gives `incomplete=True` and keeps the earlier events.

### R1 — scored loop

#### SHI-R1-01 · Deterministic summarizer and citation checker

| Effort | Refs |
|---|---|
| ~1.5 h | FR-3.1–FR-3.4 · arch §10.4 · DD-007 |

**Steps:**

1. `contracts/trace.py` `trace_digest(trace, max_chars=12000)`: one line per event, in the form `[event_id] type tool(args≤200 chars) -> status/result≤200 chars | error kind`. Model calls are shown as tokens and the tools they requested. Keep the start and end and compress the middle when over budget.
2. `summary/citations.py`, `check(claims, trace)`:
   - keep claims whose `event_ids` are non-empty and all exist
   - count dropped claims
   - append a deterministic line for every error event not cited by any kept claim (FR-3.3)
3. `summary/deterministic.py`, `@register("summarizer", "deterministic")`:
   - one claim per step ("Step 3: called stac.search_items on Kern County bbox, 41 items", citing that event)
   - one claim per error ("Tool timeout on osm.geocode, retried at step 5 and succeeded", citing both)
   - a final line on the outcome
4. `Summary` holds the claims, `dropped_claims`, `summarizer` ref, `model_id`, `prompt_version`, `cost_usd`.

**Tests:** on Barath's fixture traces, every error is mentioned and every claim's events exist.

**Acceptance:**

- [ ] The deterministic summary of the R0 run reads correctly.
- [ ] Unit tests pass.

#### SHI-R1-02 · LLM summarizer (Nova Lite)

| Effort | Refs |
|---|---|
| ~2 h | FR-3.1, FR-3.2, FR-3.5 · DD-027 · arch §10.4 |

**Steps:**

1. `summary/llm.py`, `@register("summarizer", "llm")` with `Params(model_id, max_claims=12, temperature=0)`.
2. The prompt (versioned, e.g. `summary-prompt@1`) asks for JSON only: `{"claims": [{"claim": str, "event_ids": [str]}]}`. Claims should describe what was done, in order, and every failure, retry and dead end. Give it the digest.
3. Call the **uninstrumented** `ModelAdapter`, passed in by 5th member's worker. This is evaluation cost, not agent cost. Price it with `PriceTable`.
4. Parse the response with a strict schema. On parse failure, retry once, then fall back to the deterministic summarizer and record `fallback: true`.
5. Run `citations.check` on the result.

**Acceptance:**

- [ ] On a live R1 run, the summary mentions every error, and every remaining claim cites existing events.
- [ ] Cost is recorded.

#### SHI-R1-03 · Sample runs

| Effort | Refs |
|---|---|
| ~1 h | FR-12.8 · J2, J8 · C-09 |

**Steps:**

1. From Barath's R1 live-journey runs, pick at least one clean run per R1 template (T1, T2, T5) and the J4 error runs. Copy them to `samples/runs/<run_id>/`.
2. Check each for secrets (grep for key patterns; CI also runs a secret scan). Keep blobs under 1 MB each, and replace bigger ones with a truncated copy marked `truncated: true` in a sidecar file.
3. Write `samples/README.md`: an index of runs with task, configuration, state and what each demonstrates.
4. Check that `clay-sandbox replay samples/runs/<id> --offline` (5th member) works for each.

**Acceptance:**

- [ ] Samples committed.
- [ ] Replay of each works offline.
- [ ] 5th member's J2/J8 CI tests use them.

#### SHI-R1-04 · Planted-trace generator and R1 planted traces

| Effort | Refs |
|---|---|
| ~2.5 h | FR-10.6, FR-10.7, FR-13.7 · DD-038 · arch §11 |

**Steps:**

1. `scripts/make_planted.py` takes a clean sample run (T1, T2, T5) as the **good** trace and writes flawed variants to `samples/planted/<template>/<flaw>/`, each with `manifest.json`, `trace.jsonl` and `expected.json`. `expected.json` says which sub-score or metric must drop below the good trace's score.

   | Flaw | Transform | Expected drop |
   |---|---|---|
   | `unrecovered_tool_failure` | Turn a successful required call into `tool_error` and remove later successes of that capability | `recovery`, `required_coverage` |
   | `recovered_tool_failure` (control) | Insert an error before a success of the same capability | `recovery` drops less than in the unrecovered case |
   | `loop` | Repeat one call 4× identically, end with `guard_stop(loop)` | `success`, `step_efficiency` |
   | `wrong_order` | Swap the first calls of two capabilities with an ordering rule | `ordering` |
   | `forbidden_tool` | Insert a call to a forbidden capability (add a forbidden capability to that template if it has none, and agree it with Vishal) | `forbidden_tools` |
   | `unknown_tool` | Insert an `unknown_tool` error event | `tool_call_validity` |
   | `budget_stop` | Truncate after step 2 with `guard_stop(max_steps)` | `success`, `done_condition` |
   | `fabricated_output` | Replace output IDs with IDs not in any tool result | Output metric (and T5 rule b) |

2. Renumber `seq` and `event_id`s consistently, and give every planted run a fresh run ID with `planted: true` in the manifest environment.

**Acceptance:**

- [ ] Planted sets exist for T1, T2 and T5.
- [ ] Barath's evaluator v1 detects every flaw (his `validate-evaluator` in R2 formalises this).

### R2 — MVP complete

#### SHI-R2-01 · OpenTelemetry tracer (CloudWatch/X-Ray)

| Effort | Refs |
|---|---|
| ~3 h | D8, DD-011 · FR-2.7 · J3.2 · srs O-4 · arch §13.1 |

**Steps:**

1. **Decide O-4 first (30 min):** export OTLP over HTTP either (a) to a local ADOT collector that forwards to X-Ray, or (b) directly to the X-Ray OTLP traces endpoint with SigV4 signing. Pick whichever works in the sandbox in us-west-2 and record it in the PR and your README section. Tell Prithwish which IAM actions the task role needs.
2. `tracing/otel.py`, `@register("tracer", "otel")`. Map events to spans:
   - The run is the root span (`clay.run_id`, `clay.task_instance`, `clay.config`).
   - `model_call` becomes a child span: `gen_ai.operation.name="chat"`, `gen_ai.system="aws.bedrock"`, `gen_ai.request.model`, `gen_ai.usage.input_tokens`, `gen_ai.usage.output_tokens`.
   - `tool_call` becomes a child span: `gen_ai.operation.name="execute_tool"`, `gen_ai.tool.name`, status error on failures.
   - Errors and guard stops become span events.
   - Every span carries the full canonical event as the attribute `clay.event` (JSON), so it can be read back.
3. Use a `BatchSpanProcessor` with two exporters: OTLP (remote) and a file exporter writing OTLP-JSON lines to `trace.otlp.jsonl` in the run folder. Span start and end times come from the event timestamps.
4. Reader: `read_trace` falls back to `trace.otlp.jsonl` and rebuilds events from `clay.event`.
5. `tests/journeys/test_j3_tracer_swap.py`: the same scripted fake run with `jsonl` and with `otel` (file exporter only, no network) gives equal `TraceEvent` lists.

**Acceptance:**

- [ ] J3 step 2 passes in CI.
- [ ] A live run with `tracer: otel` shows a trace in the X-Ray console.

#### SHI-R2-02 · Tee tracer and tracer comparison

| Effort | Refs |
|---|---|
| ~2 h | FR-2.8, FR-9.6 · UC-06 · DD-026 · arch §11 |

**Steps:**

1. `tracing/tee.py`, `@register("tracer", "tee")` with `Params(tracers=["jsonl", "otel"])`. It emits each event to both tracers and measures each one's `emit` time with `time.perf_counter_ns`. It writes `tracer_metrics.json` to the run folder: per tracer, count, median and p95 emit ms, errors. The OTLP export time is measured separately from the processor's export callback.
2. `tracing/compare.py`, `compare_tracers(run_dirs) -> MeasurementComparison(kind="tracer")`:
   - overhead per tracer (median and p95)
   - events written vs read back from each format (events lost)
   - field-by-field equality of read-back events (fidelity, as a percentage of events equal)
3. 5th member calls it from `compare-tracers` and from evals whose tracer is `tee`. Barath puts the result into the eval report content.

**Acceptance:**

- [ ] A live T1 run with `tracer: tee` produces `tracer_metrics.json`.
- [ ] `clay-sandbox compare-tracers` prints overhead, loss and fidelity.

#### SHI-R2-03 · S3 mirror and DuckDB queries

| Effort | Refs |
|---|---|
| ~2.5 h | DD-022 · arch §13.3, §13.4 · NFR-PERF-3 |

**Steps:**

1. `store/s3.py`, `@register("store", "local+s3")`:
   - wraps `LocalRunStore`
   - `mirror_run(run_id)` uploads the run folder to `s3://<bucket>/runs/<run_id>/` after `run_end`
   - `mirror_eval(eval_id)` does the same for the eval folder
   - `sync_down(prefix)` pulls Fargate-written runs locally before scoring and stats
   - uses the bucket from the spec or `infra/outputs.json`
2. `store/query.py`, DuckDB helpers over `read_json_auto(..., union_by_name=true)`:
   - `runs_for_eval(eval_id)`: manifest essentials + state
   - `assessments_for_eval(eval_id, kind=None)`
   - `token_history(template, model_id, harness=None)`: median input and output tokens from `run_end` totals, for Prithwish's estimate
   - `list_runs(filters, limit, offset)`: for the API and the Runs screen
3. `RunStore.query(sql, params)` runs parameterised SQL only. Never build SQL from strings in callers.

**Tests:**
- Query helpers on a temp store with 50 fake runs.
- Mirror and `sync_down` against a moto-mocked S3 (or a live bucket, marked `live`).

**Acceptance:**

- [ ] Stats queries over 360 fake runs return in seconds.
- [ ] A mirrored eval appears in S3.

#### SHI-R2-04 · Planted traces for T3 and T4

| Effort | Refs |
|---|---|
| ~1 h | FR-13.7 · DD-038 |

Run `make_planted.py` on clean T3 and T4 runs from Barath's R2 live runs. If none is clean, hand-edit one good trace. Add `expected.json` for each flaw and update `samples/README.md`.

**Acceptance:**

- [ ] All five templates have planted sets.
- [ ] Barath's `validate-evaluator` covers them.

### R3 — UI

#### SHI-R3-01 · Report screen

| Effort | Refs |
|---|---|
| ~3 h | FR-8.3, FR-8.6, FR-8.7, FR-5.3 · srs §9.2 (P3) · wireframe screen 3 |

**Steps:**

1. Build `ui/src/screens/Report.tsx` from `GET /runs/{id}/report` (report JSON) via the generated client. It has these sections:
   - header pills: task instance, model, harness, tool set, tracer, evaluators, task-reference version (label "task reference", not "rubric")
   - two headline numbers: workflow composite and output metric
   - sub-score bars with evidence links
   - the summary, where each claim links to its events
   - the timeline: every event, errors in red with source and kind, and recovered errors marked
   - a per-step latency and cost table (agent and evaluation cost apart)
   - a collapsible provenance block with the full manifest
   - attribution notices
   - links to the raw trace and `report.html`
2. Clicking an evidence ID scrolls to that event in the timeline.

**Acceptance:**

- [ ] The screen shows the same content as `report.md` for a sample run, including errors and evidence links.
- [ ] The UI build passes.

## 10. Hand-offs

| When | You give | To | What they do with it |
|---|---|---|---|
| R0 hour 1 | `trace.py`, `store.py`, `summary.py`, fakes | Everyone | Build against them |
| R0 | `RunEventSink`, `JsonlTracer`, `LocalRunStore`, reader | Prithwish (wrappers), 5th member (worker) | R0 gate |
| R1 | Summarizers, samples, planted traces T1/T2/T5 | 5th member (worker, J2/J8 tests), Barath (validation) | J1, J2, J6.2 |
| R2 | OTel and tee tracers, tracer comparison, S3 mirror, query helpers, planted T3/T4 | 5th member (API, evals), Barath (stats), Prithwish (estimate, IAM) | J3.2, J5, J6 |

## 11. Risks and fallbacks

| Risk | Fallback |
|---|---|
| X-Ray OTLP path won't authenticate | Use the ADOT collector path, or export to CloudWatch through the collector. Keep the local OTLP file so J3.2 still passes |
| Strands fallback (A-4) produces events through hooks with different timing | Equivalence test with Prithwish on fakes. The schema stays the same |
| Sample blobs too big for git | Truncate with a sidecar marker. Full copies stay in S3 |
| DuckDB schema inference differs across files | `union_by_name=true` with explicit column casts in the helpers |
| LLM summary often drops claims | Tighten the prompt. The deterministic error lines still guarantee FR-3.3 |

## 12. Effort summary

| Release | Tasks | Hours (rough) |
|---|---|---|
| R0 | SHI-R0-00, contracts session, SHI-R0-01 to R0-03 | 7 |
| R1 | SHI-R1-01 to R1-04 | 7 |
| R2 | SHI-R2-01 to R2-04 | 8.5 |
| R3 | SHI-R3-01 | 3 |
| **Total** | | **≈ 25.5** |

## 13. Release checklists

**R0**
- [ ] `trace.py`, `store.py`, `summary.py`, fakes and conformance merged
- [ ] Sink, JSONL tracer and redaction
- [ ] Local run store with immutability
- [ ] Trace reader with incomplete handling

**R1**
- [ ] Deterministic and LLM summarizers with citation check
- [ ] Samples committed. Offline replay works
- [ ] Planted traces for T1, T2, T5

**R2**
- [ ] OTel tracer (J3.2 in CI). O-4 decided and documented
- [ ] Tee tracer and tracer comparison
- [ ] S3 mirror and DuckDB query helpers
- [ ] Planted traces for T3, T4
- [ ] README section on traces, store, replay, samples

**R3**
- [ ] Report screen
