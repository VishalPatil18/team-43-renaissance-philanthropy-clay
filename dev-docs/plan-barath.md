# Plan — Barath (WS4 Evaluation and statistics)

> **For agents — what this file is:** Barath's task plan for building the Clay agent-eval sandbox, release by release (R0 → R3). Sections 1–6 are shared by all five plans. Sections 7 onwards are Barath's own. Read it together with [srs.md](srs.md) (what to build) and [architecture.md](architecture.md) (how it fits together). Those two files plus this plan are all that's needed to do the work. Requirement IDs (FR-x.y, NFR-…) are the acceptance criteria. Decisions are in [design-decisions.md](design-decisions.md) (ownership: DD-044).

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

You turn traces into judgments the team can defend. You own:

- **Scoring:** every evaluator (deterministic workflow, deterministic output per template, and the optional LLM process evaluator).
- **Statistics:** the statistics that say whether a difference is real.
- **Comparisons:** agent-axis and evaluator comparisons, and the content of the eval report.
- **Evaluator validation:** the check that proves the evaluator separates good runs from bad ones.
- **Live gate runs:** the live journeys at each release gate, because those runs are your data.

**Your files** (architecture §4, §10, §11, §21):

```
claysandbox/contracts/assessment.py, stats.py          (contracts session)
claysandbox/evaluation/  workflow.py constraints.py llm_process.py
                         output/__init__.py t1.py t2.py t3.py t4.py t5.py
                         stats.py compare.py validate.py
scripts/live_journeys.sh, tests/live/*
tests/fixtures/traces/*                                 (hand-written fixture traces)
tests/unit/evaluation/*, tests/journeys/test_j6_validation.py
ui/src/screens/Comparison.tsx                           (R3)
```

**Features:** F4 (scoring), F9 (agent and evaluator comparisons), F10 (statistics). Journeys you run live: J1, J3, J4, J5, J6, J7.

## 8. Interfaces you own and consume

| Direction | Interface | With | Where defined |
|---|---|---|---|
| Own | `Evaluator`, `Assessment`, `SubScore` | 5th member (worker, replay), Shivaani (validation inputs) | arch §7.5 |
| Own | `ConfigStats`, `PairedComparison`, `MeasurementComparison` (kind `evaluator`), `ValidationReport`, eval report content | 5th member (eval report rendering, API), R3 UI | arch §11 |
| Consume | `Trace`, `trace_digest`, query helpers (`runs_for_eval`, `assessments_for_eval`) | Shivaani | arch §7.1, §13.3 |
| Consume | `TaskReference`, workflow vocabularies (open point 9), process rubrics | Vishal | arch §14 |
| Consume | `ModelAdapter`, `PriceTable` (LLM evaluator) | Prithwish | arch §7.4, §12 |
| Consume | Tracer comparison result | Shivaani | arch §11 |
| Consume | CLI commands for the live journeys | 5th member | srs §13.1 |

## 9. Tasks

### R0 — walking skeleton

#### BAR-R0-00 · Fixture traces (hour 0)

| Effort | Refs |
|---|---|
| ~0.5 h | arch §7.1 |

Hand-write three small fixture traces as JSONL (with a manifest and a T1-style reference) in `tests/fixtures/traces/`:
- `good_t1`: geocode → imagery search with the right bbox, collection and year → final output
- `errors_t1`: a tool timeout, then a successful retry, plus an unknown-tool call
- `loop_t1`: four identical calls → `guard_stop(loop)`

Schema changes after the session are rare. Update the fixtures if the contract moves.

#### BAR-R0-01 · Workflow evaluator v0

| Effort | Refs |
|---|---|
| ~2.5 h | FR-4.1 (partial), FR-4.2, FR-4.3, FR-4.8 · arch §10.1 |

**Steps:**

1. `evaluation/workflow.py`: `@register("evaluator", "workflow")` class with `version="0"`, `kind="workflow"`, `deterministic=True`.
2. Implement three sub-scores: `tool_call_validity`, `required_coverage` and `done_condition`, exactly as defined in arch §10.1. Each `SubScore` lists its evidence event IDs.
3. Composite = weighted mean using `reference.weights` (default equal) over the sub-scores present.
4. `success` per DD-042: done condition met and no `guard_stop` event.
5. Pure function: no I/O, no clock, no randomness. Same input, same output.

**Acceptance:**

- [ ] On the fixtures: `good_t1` composite 1.0. `errors_t1` validity < 1. `loop_t1` has `success=False`.

#### BAR-R0-02 · Evaluator conformance suite

| Effort | Refs |
|---|---|
| ~1 h | DD-035 · FR-4.8 · FR-7.4 |

`contracts/conformance/test_evaluator.py`, run for every registered evaluator:
- Assessment validates against the schema and records evaluator name, version and task-reference version.
- Every evidence ID exists in the trace.
- If `deterministic=True`: two calls give byte-identical JSON, ignoring `assessment_id` and `created_at`.
- Infra-error events change no score (inject an infra error into a copy of a fixture).

**Acceptance:**

- [ ] The suite runs in CI against `ConstantEvaluator` and `workflow@0`.

### R1 — scored loop

#### BAR-R1-01 · Workflow evaluator v1 with argument constraints and recovery

| Effort | Refs |
|---|---|
| ~3.5 h | FR-4.1–FR-4.4, FR-4.10, FR-4.11 · arch §10.1 · DD-012, DD-028, DD-041, DD-042 |

**Steps:**

1. `evaluation/constraints.py` implements each argument-constraint check from the vocabulary (open point 9) with shapely:
   - `bbox_intersects_aoi` (args bbox vs AOI geometry)
   - `point_within_aoi`
   - `collection_in`
   - `datetime_within_year` (accepts ISO dates, intervals, or a year)
   - `k_at_most`

   Each check is a function `(args, constraint, reference) -> bool | None`. `None` means not applicable, e.g. the argument is missing. Arg names vary between tools, so each check takes a list of candidate argument names from the constraint definition, with defaults like `["bbox", "bounds"]`.
2. Add the rest of the sub-scores from arch §10.1:
   - `argument_constraints`
   - `ordering` (rule shapes from the vocabulary, with `optional_first`)
   - `forbidden_tools`
   - `recovery`: penalty 1 for unrecovered, `recovered_penalty` (default 0.25) for recovered. Recovered = a later successful call of the same capability before `run_end`. Only `agent` and `tool` errors count, never `infra` (FR-4.4).
   - `step_efficiency`: 1 up to `expected_steps`, linear to 0 at `step_limit`
3. Tools are matched by **capability**, using `ToolCall.capability` and `reference.workflow` (FR-4.10). The same rule therefore works for T0 and T1.
4. Bump to `version="1"`. Keep `workflow@0` registered so old assessments still resolve.
5. Each sub-score's `notes` gets a one-line human reason, e.g. "imagery_search bbox missed AOI in event …:7".

**Tests:**
- One unit test per sub-score with crafted mini traces.
- Recovered vs unrecovered: the recovered case scores higher.
- T0 vs T1 capability mapping.

**Acceptance:**

- [ ] `good_t1` composite 1.0.
- [ ] Each of Shivaani's R1 planted flaws lowers its expected sub-score (`expected.json`).

#### BAR-R1-02 · Output evaluators T1, T2, T5

| Effort | Refs |
|---|---|
| ~2 h | FR-4.6, FR-4.7 · srs §12.3 · arch §10.2 · OQ12 |

**Steps:**

1. `evaluation/output/__init__.py`: `@register("evaluator", "output")` resolves to `output.t<k>` from the template in the instance ID. Also register each `output.t1` … `output.t5` directly.
2. Parse the final output against the template's output schema. Parse failure gives every metric 0, with the error as evidence.
3. Metrics:
   - `t1`, `t2`: precision, recall and F1 on ID sets (case-sensitive, trimmed).
   - `t5`: the pass rate over Vishal's rules. Rule (a): assumptions non-empty or a question present. Rule (b): every output ID appears in the text of some `tool_call` result or blob. Rule (c): if items are given, they're imagery items intersecting the AOI, checked against the T5 reference.
4. Output assessments never set `composite` from workflow data, and workflow assessments never read output metrics (FR-4.7).

**Acceptance:**

- [ ] A correct hand-made output scores 1.0 and a wrong one scores lower (J4.3).
- [ ] Conformance passes.

#### BAR-R1-03 · Live-journey script and R1 live runs

| Effort | Refs |
|---|---|
| ~1.5 h | DD-035 · J1, J4 · srs §2 R1 exit |

**Steps:**

1. `scripts/live_journeys.sh <release>` (bash, `set -euo pipefail`). It runs the CLI against small specs in `specs/live/`, with tight `budget.run.max_usd` on every spec, and prints the run IDs and report paths. For R1:
   - **J1:** T1, T2, T5 on two AOIs, Nova Lite + Strands + T1, N=1.
   - **J4:** the T1-faulty tool set (Vishal) on one T1 instance, plus a spec where the model is likely to call a wrong tool. If that's unreliable, rely on the fakes test from Prithwish and say so.
2. Check each run against J1 steps 1–5 and J4 steps 1–3 by hand, using the reports. Write the result in the PR.
3. Hand the clean runs and the error runs to Shivaani for `samples/`.

**Acceptance:**

- [ ] The R1 gate has a live run with a report and a live error run with its errors in the summary and a lower workflow score.

### R2 — MVP complete

#### BAR-R2-01 · Output evaluators T3 and T4

| Effort | Refs |
|---|---|
| ~1.5 h | srs §12.3 · arch §10.2 |

- **`t3`:** match predicted sites to reference polygons. A prediction matches if it's inside a polygon or within a tolerance (default 500 m, from the reference) of it, computed in a local metric CRS with pyproj. Use greedy one-to-one matching, then compute precision and recall. Empty reference and empty output = precision 1, recall 1. Empty reference with output = precision 0.
- **`t4`:** recall@k of predicted `chips_id`s against the reference top-k.

**Acceptance:**

- [ ] Unit tests including the negative-control AOIs.
- [ ] Vishal's hand-made correct outputs score 1.0.

#### BAR-R2-02 · LLM process evaluator

| Effort | Refs |
|---|---|
| ~2.5 h | FR-4.9 · arch §10.3 · DD-007, DD-027 |

**Steps:**

1. `evaluation/llm_process.py`: `@register("evaluator", "llm_process")`, `kind="process"`, `deterministic=False`, `Params(model_id, k=3, temperature=0)`.
2. The prompt (versioned) has three parts:
   - Shivaani's `trace_digest`
   - the template's process rubric (in the reference)
   - the workflow spec

   It asks for JSON only: `{"items": [{"name": str, "score": 0..1, "event_ids": [str], "reason": str}]}`.
3. Call the uninstrumented `ModelAdapter` k times. Validate each reply, retrying once on a parse failure. Store `repeats` (the k composite scores), mean, spread, and per-item means. Drop event IDs that don't exist and count them.
4. `cost_usd` = the sum of all k calls (evaluation cost).
5. Reject at spec validation if the judge model is in the same family as any agent model in the eval (DD-027). Family = the prefix before the first `.` in the model ID, after stripping a region prefix like `us.`. Coordinate with 5th member.
6. Offline mode: the evaluator is skipped and reported as skipped (5th member).

**Acceptance:**

- [ ] On five sample runs: k=3 scores stored, spread reported.
- [ ] Planted bad traces score lower on average than good ones.

#### BAR-R2-03 · Statistics engine

| Effort | Refs |
|---|---|
| ~3 h | FR-10.1–FR-10.5, FR-10.8 · arch §11 · DD-025 |

**Steps:**

1. `evaluation/stats.py`, numpy and scipy only, with a seeded `np.random.default_rng(seed)`.
2. Inputs: per-run rows of (configuration, task instance, trial_index, state, success, workflow composite, sub-scores, output metrics, steps, latency, cost, error counts), from Shivaani's query helpers. Leave out `infra_excluded` and `skipped_eval_cap` runs, and count them per configuration.
3. Per configuration:
   - success rate with a **Wilson 95% CI**
   - for every numeric metric: the mean with a **cluster bootstrap** CI, which resamples task instances with replacement and averages each instance's run mean. Iterations come from `stats.bootstrap_iterations` (default 5000).
4. Paired A vs B (variant vs baseline): use only task instances complete in both.
   - d_i = instance mean B − instance mean A
   - effect = mean(d_i) with a cluster-bootstrap CI
   - p-value from a **sign-flip permutation test**: exact (2^n) if n ≤ 15, else 10 000 random flips
   - **Holm** correction across variants per metric when there are more than two comparisons
5. Verdict strings, as in arch §11 ("better by Δ (CI…, p=…)" or "no meaningful difference"). Add warnings when the CI half-width is more than 50% of |effect| or there are fewer than 10 complete instances (FR-10.5).
6. Record the seed and iterations in the result.

**Tests:**
- Wilson against known values.
- The bootstrap is deterministic with a seed.
- A synthetic dataset with a planted effect is detected, and one with no effect isn't (at α=0.05, over a few seeds).
- Holm ordering.

**Acceptance:**

- [ ] Unit tests pass.
- [ ] 360 fake runs process in < 60 s (NFR-PERF-3).

#### BAR-R2-04 · Comparisons and eval report content

| Effort | Refs |
|---|---|
| ~2.5 h | FR-9.1–FR-9.5, FR-9.7 · UC-02, UC-06 · arch §8.5, §11 · DD-026 |

**Steps:**

1. `evaluation/compare.py`, `build_eval_report_content(eval_id, store) -> EvalReport` content:
   - per-configuration stats
   - paired comparisons against the baseline for each variant
   - the axis each variant changes (model, harness or tool set), taken from its override
   - exclusions
   - plain-language verdicts
   - links to every run
   - the tracer comparison (from Shivaani) when the tracer is `tee`
   - the evaluator comparison when the eval has more than one evaluator of the same kind, or when it's requested
2. `compare_evaluators(run_ids, evaluators) -> MeasurementComparison(kind="evaluator")`: Spearman correlation and mean absolute difference of composites between evaluators on the same runs, plus the LLM evaluator's self-agreement (mean spread over k).
3. 5th member renders `eval_report.md`/`.html` from this content and serves it at `GET /evals/{id}/report`. Agree the exact fields with 5th member in the R0 contracts session (`report.py`).

**Acceptance:**

- [ ] On a fake eval (4 configurations × 6 instances × 3 runs), the report content has all sections and correct verdicts for planted effects.

#### BAR-R2-05 · Planted-trace validation (`validate-evaluator`)

| Effort | Refs |
|---|---|
| ~1 h | FR-10.6, FR-10.7 · UC-08 · DD-038 · J6.2 |

**Steps:**

1. `evaluation/validate.py`, `validate(evaluators, planted_root="samples/planted", ci_halfwidth=None) -> ValidationReport`:
   - For each template and flaw: score the good and flawed traces, check the `expected.json` drop, and compute the detection rate per flaw type.
   - Margin = mean(good composite) − mean(bad composite), compared with the latest live eval's CI half-width when one is given.
   - For the LLM evaluator, skipped in CI: agreement over k.
2. `tests/journeys/test_j6_validation.py` runs it in CI for the deterministic evaluators. It fails if any expected drop is missing.

**Acceptance:**

- [ ] CI passes with 100% detection on the planted set.
- [ ] `clay-sandbox validate-evaluator` prints the report (after 5th member wires it).

#### BAR-R2-06 · R2 live gate evals

| Effort | Refs |
|---|---|
| ~1.5 h | J3, J5, J6, J7 · srs §2 R2 exit · DD-026, DD-031 |

**Steps:**

1. Run `clay-sandbox estimate specs/compare-default.yaml`. If it's over the team lead's limit, run a reduced version (fewer AOIs or N=2), say so in the report, and keep the full spec for later.
2. Through `live_journeys.sh r2`:
   - **J3:** swap model, harness and tracer on one instance, then re-score stored runs with `llm_process`.
   - **J5 and J6:** the comparison eval.
   - **J7:** `max_steps=2`, then no limits.
3. Check each journey's verification steps against the reports. Record pass or fail per step in the PR.
4. Hand the eval and its runs to Shivaani for `samples/evals/`. Give Prithwish the numbers for the demo.

**Acceptance:**

- [ ] The R2 exit journeys J3, J5, J6 and J7 have live evidence committed.

### R3 — UI

#### BAR-R3-01 · Comparison screen

| Effort | Refs |
|---|---|
| ~3 h | FR-8.4, FR-8.7 · FR-9.4 · FR-10.5 |

**Steps:**

1. Build `ui/src/screens/Comparison.tsx` from `GET /evals/{id}/report`. It has:
   - one row per configuration, with success rate and CI bars
   - workflow composite, output metric, cost and latency with CI bars
   - a paired-comparison table per variant: axis, metric, Δ with CI, p (Holm-adjusted), verdict text
   - warnings (wide CIs, few instances) and exclusions
   - measurement comparisons (evaluator agreement, tracer overhead) in their own section
2. Clicking a configuration filters the Runs screen to it.
3. Use simple SVG bars, with no heavy chart library unless 5th member already added one.

**Acceptance:**

- [ ] The screen shows the committed R2 sample eval correctly.
- [ ] The UI build passes.

## 10. Hand-offs

| When | You give | To | What they do with it |
|---|---|---|---|
| R0 hour 1 | `assessment.py`, `stats.py`, fixtures | Everyone | Build against them |
| R0 | `workflow@0` | 5th member | Wiring in R1 |
| R1 | `workflow@1`, output evaluators T1/T2/T5, live R1 runs | 5th member (worker, reports), Shivaani (samples, planted) | J1, J4 |
| R2 | Statistics, comparisons, eval report content, validation, LLM evaluator, live R2 evals | 5th member (eval reports, API), Prithwish (demo), Shivaani (samples) | J3, J5, J6, J7 |

## 11. Risks and fallbacks

| Risk | Fallback |
|---|---|
| Too few complete instances for paired tests | Report it with the warning. Prefer N=2 across more instances over N=3 on fewer (DD-025 reasoning) |
| LLM judge model not available | Ship without `llm_process`. J3.4 uses `workflow@0` vs `workflow@1` as the swapped evaluator pair, and the report says so |
| Argument names differ between tool servers | Candidate-name lists in constraints. Ask Vishal to add names to the reference, never to code |
| A live J4 "wrong tool" can't be provoked | Rely on the fakes test from Prithwish for J4.2 and record it |
| Bootstrap slow | Vectorise over iterations. Lower iterations to 2000 and record it |

## 12. Effort summary

| Release | Tasks | Hours (rough) |
|---|---|---|
| R0 | BAR-R0-00, contracts session, BAR-R0-01, R0-02 | 5 |
| R1 | BAR-R1-01 to R1-03 | 7 |
| R2 | BAR-R2-01 to R2-06 | 12 |
| R3 | BAR-R3-01 | 3 |
| **Total** | | **≈ 27** |

## 13. Release checklists

**R0**
- [ ] `assessment.py`, `stats.py`, fixtures, conformance merged
- [ ] `workflow@0` on fixtures

**R1**
- [ ] `workflow@1` with constraints, ordering, recovery, efficiency
- [ ] Output evaluators T1, T2, T5
- [ ] `live_journeys.sh r1` run. J1 and J4 evidence handed to Shivaani

**R2**
- [ ] Output evaluators T3, T4
- [ ] LLM process evaluator (or FUTURE-WORK row)
- [ ] Statistics engine
- [ ] Comparisons and eval report content
- [ ] `validate-evaluator` in CI
- [ ] Live R2 evals for J3, J5, J6, J7
- [ ] README section on scoring and statistics

**R3**
- [ ] Comparison screen
