# Plan — Prithwish (WS1 Agent runtime and cloud execution)

> **For agents — what this file is:** Prithwish's task plan for building the Clay agent-eval sandbox, release by release (R0 → R3). Sections 1–6 are shared by all five plans. Sections 7 onwards are Prithwish's own. Read it together with [srs.md](srs.md) (what to build) and [architecture.md](architecture.md) (how it fits together). Those two files plus this plan are all that's needed to do the work. Requirement IDs (FR-x.y, NFR-…) are the acceptance criteria. Decisions are in [design-decisions.md](design-decisions.md) (ownership: DD-044).

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

You make the agent run. You own everything between "here is a prompt, a model and some tools" and "here is a final output and a full trace of how we got there". That means the Bedrock model adapter, the instrumented wrappers that trace and guard every call, both harnesses, the budget and loop guards, and the price table. You also own cost: the pre-flight estimate. And you own running the agent in the cloud: the Docker image, the CDK stack and the Fargate executor.

**Your files** (architecture §4, §21):

```
claysandbox/contracts/runtime.py, errors.py     (contracts session)
claysandbox/runtime/models/bedrock.py
claysandbox/runtime/instrument.py
claysandbox/runtime/harness/strands_harness.py
claysandbox/runtime/harness/converse_loop.py
claysandbox/runtime/harness/_checks.py
claysandbox/runtime/guard.py
claysandbox/runtime/pricing.py
claysandbox/runtime/estimate.py
claysandbox/platform/executors/fargate.py
pricing/prices.yaml
scripts/check_models.py, scripts/refresh_prices.py
docker/Dockerfile, infra/ (CDK app)
DEMO.md (R3)
tests/unit/runtime/*, tests/journeys/test_j7_budget_fakes.py
```

**Features:** F1 (harness side), F11 (budget guard, pre-flight estimate), F15 (Docker, CDK, Fargate).

## 8. Interfaces you own and consume

| Direction | Interface | With | Where defined |
|---|---|---|---|
| Own | `ModelAdapter`, `ModelResponse` | Shivaani (summarizer), Barath (LLM evaluator), 5th member (worker) | arch §7.4 |
| Own | `Harness`, `RunContext`, `RunOutcome` | 5th member (worker) | arch §7.4 |
| Own | `BudgetGuard`, `GuardStopped`, `InfraError`, `ConfigError` | 5th member (worker, executor) | arch §7.4, §9 |
| Own | `PriceTable`, `CostEstimate`, `CostEstimator`, `EvalBudget` | 5th member (service), Shivaani (summary cost), Barath (LLM evaluator cost) | arch §12 |
| Own | Fargate implementation of `Executor` | 5th member owns the interface | arch §8.6 |
| Consume | `ToolSession`, `ToolSpec`, `ToolResult` | Vishal | arch §7.4 |
| Consume | `TraceEvent` types, `EventSink` | Shivaani | arch §7.1 |
| Consume | `RunStore.query` (token history) | Shivaani | arch §13.3 |
| Consume | `EvalSpec.budget`, `loop_guard`, `RunRequest`, `Executor` | 5th member | arch §7.3 |

## 9. Tasks

### R0 — walking skeleton

#### PRI-R0-00 · Bedrock model access and model IDs (hour 0, before contracts)

| Effort | Refs |
|---|---|
| ~1 h | srs X-01, O-1, A-1 · DD-010, DD-027 |

**Goal:** confirm which Bedrock models the sandbox account can call with tool use in us-west-2, so specs can name real IDs.

**Steps:**

1. In the Bedrock console (us-west-2), request access to Nova Lite, Nova Pro, a Claude Sonnet-class model, and one Llama- or Mistral-class model (for the LLM evaluator, which must be from a family not under test).
2. Write `scripts/check_models.py`. For each candidate ID, call `bedrock-runtime` `converse` with a one-line prompt and one dummy tool in `toolConfig`. Print ID, ok/fail, whether a `toolUse` came back, latency and tokens.
3. Claude-family models may need a cross-region inference profile ID (for example a `us.`-prefixed ID). Try both the base ID and the profile ID.
4. Post the working IDs to the team lead and 5th member (for the sample specs). Add them to `specs/README.md` as a table: role (dev, baseline, variant, summary, judge) → model ID.

**Acceptance:**

- [ ] `uv run python scripts/check_models.py` prints a result for every candidate.
- [ ] Every role (dev, baseline, variant, summary, judge) has a confirmed ID, or the team lead has been told which one is missing.

#### PRI-R0-01 · Bedrock model adapter

| Effort | Refs |
|---|---|
| ~2 h | FR-1.4, FR-1.5, FR-1.11 · arch §7.4, §8.3, §13.3 (external interfaces in srs §13.3) |

**Goal:** one `ModelAdapter` that wraps Bedrock Converse and returns a harness-neutral `ModelResponse`.

**Steps:**

1. In `runtime/models/bedrock.py`, create `@register("model", "bedrock") class BedrockModelAdapter` with a Pydantic `Params`: `model_id`, `temperature`, `max_tokens`, optional `top_p`, `region="us-west-2"`, `max_attempts=3`.
2. `converse(messages, system, tools, params)` builds the request:
   - `modelId`, `messages`, `system=[{"text": system}]`, `inferenceConfig`.
   - `toolConfig={"tools": [{"toolSpec": {"name": t.model_name, "description": t.description, "inputSchema": {"json": t.input_schema}}}]}`. Omit `toolConfig` when there are no tools.
3. Parse the response into `ModelResponse`:
   - text blocks
   - `tool_uses` (`toolUseId`, `name`, `input`)
   - `stop_reason`
   - `input_tokens`, `output_tokens` from `usage`
   - `latency_ms` from `metrics.latencyMs` (also measure wall time)
4. Configure botocore retries: `Config(retries={"mode": "adaptive", "max_attempts": max_attempts})`.
5. Classify errors that survive the retries:
   - `ThrottlingException` → `InfraError(kind="throttled", retryable=True)`.
   - `ServiceUnavailableException`, `InternalServerException`, `ModelTimeoutException`, `ModelNotReadyException` → `InfraError(kind="service_error", retryable=True)`.
   - Connection errors → `InfraError(kind="network", retryable=True)`.
   - `AccessDeniedException`, `ResourceNotFoundException`, `ValidationException` → `ConfigError`. Not retried, and the eval stops fast.
6. Never read model IDs from code or env (FR-1.5). They come only from `Params`.

**Tests:** `tests/unit/runtime/test_bedrock_adapter.py` using `botocore.stub.Stubber`. Cover:
- a text reply
- a `tool_use` reply
- throttling → `InfraError`
- access denied → `ConfigError`
- a request built with no tools omits `toolConfig`

**Acceptance:**

- [ ] Unit tests and `test_model_adapter.py` conformance pass.
- [ ] `scripts/check_models.py` uses the adapter and still works live with Nova Lite.

#### PRI-R0-02 · Instrumented wrappers (tracing and guards at the boundary)

| Effort | Refs |
|---|---|
| ~2 h | FR-2.1–FR-2.3, FR-2.6 · arch §9.1, §9.2, §7.1 |

**Goal:** every model call and tool call produces the same `TraceEvent`s, whatever the harness (principle P6).

**Steps:**

1. `InstrumentedModel(inner: ModelAdapter, sink: EventSink, guard: BudgetGuard, prices: PriceTable)`. `converse()` does:
   - `guard.before_model_call()`
   - time the call to `inner.converse`
   - build a `ModelCall` event: tokens, `cost_usd = prices.model_cost(...)`, `price_table_version`, `tool_use_requests`, `text_preview` (≤ 500 chars), `stop_reason`
   - `sink.emit(event)` and `guard.record(event)`
   - return the response
2. On `InfraError` or `ConfigError`: emit a `ModelCall` (or `ErrorEvent`) with `error.source="infra"` and the kind, then re-raise.
3. `InstrumentedTools(inner: ToolSession, sink, guard)`. `call` and `call_blocking` do:
   - `guard.before_tool_call(tool, args)`
   - time the call to `inner.call` (with timeout)
   - build a `ToolCall` event: server, tool, capability, args, status (`ok`, `error`, `timeout`), `result_preview` (≤ 1 000 chars)
   - store the full result with `sink.put_blob(...)` and set `result_ref` and `result_sha256`
   - set `error` with `source="tool"` for errors and timeouts
4. Set `parent_id` on each `ToolCall` to the `event_id` of the `ModelCall` that requested it, matched through `toolUseId`.
5. In R0, use `NoopGuard` and `FixedPriceTable(0)`. The real ones arrive in R1/R2 without changing the wrappers.
6. `GuardStopped` must propagate. Never catch it in the wrappers.

**Tests:** `FakeModelAdapter` + `FakeToolSession` + `MemoryTracer`. Check:
- event order and `seq`
- `parent_id` links
- latency and cost fields present
- the blob stored for a large result
- `TripGuard` makes `GuardStopped` reach the caller

**Acceptance:**

- [ ] Unit tests pass.
- [ ] Shivaani has reviewed the event fields.

#### PRI-R0-03 · Strands harness (and verify assumption A-4)

| Effort | Refs |
|---|---|
| ~2.5 h | FR-1.1–FR-1.3, FR-1.6 · arch §9.1 · srs A-4 · D7 |

**Goal:** Strands Agents runs the agent, but every model call and tool call goes through our instrumented wrappers.

**Steps:**

1. Agree the `strands-agents` version with 5th member and pin it in `pyproject.toml`.
2. Read that version's docs for: custom model providers, defining tools programmatically, hooks or callbacks, and loop or cycle limits.
3. **Model bridge:** a Strands custom model provider that converts Strands' messages to Converse format and calls `ctx.model.converse(...)`. Strands' own Bedrock client must never be used.
4. **Tools:** register each `ToolSpec` as a Strands tool. The handler calls `ctx.tools.call_blocking(server, tool, args)` and returns the content. A tool error is returned as an error result, not raised.
5. Run the agent with `system_prompt=ctx.system_prompt`, `prompt=ctx.prompt`. Turn the final text into `RunOutcome(state="completed", output=<JSON if it parses, else text>)`.
6. Map exceptions:
   - `GuardStopped` → `RunOutcome(state="budget_stopped")`
   - `InfraError` → `RunOutcome(state="infra_error")`
   - anything else → `ErrorEvent` (agent) + `RunOutcome(state="agent_failed")`
7. If Strands has its own cycle limit, set it higher than our guards so ours fire first.
8. Add a test that counts Bedrock calls through a botocore event hook. Only the bridge may call Bedrock.
9. `@register("harness", "strands")`.
10. **If A-4 fails** (no custom provider, or tools can't be wrapped), switch to the fallback in arch §9.1: Strands' own Bedrock and MCP clients, plus a hook adapter that emits the same events. Tell the team lead and Shivaani the same hour, and note it in the PR.

**Acceptance:**

- [ ] `test_harness.py` conformance passes on fakes: scripted two-step tool use, `GuardStopped` propagation, final output captured.
- [ ] Together with 5th member: `clay-sandbox run specs/r0.yaml` (Nova Lite + Strands + T0 on one T1 instance) produces a trace with ≥1 real MCP tool call. This is the **R0 gate**.

### R1 — scored loop

#### PRI-R1-01 · Harness-side error capture (both harnesses)

| Effort | Refs |
|---|---|
| ~2 h | FR-1.7, FR-1.8 · srs §12.4 · arch §9.3 |

**Goal:** agent-side mistakes become typed error events and never crash a run.

**Steps:**

1. Write the shared helper `runtime/harness/_checks.py`, used by both harnesses before any tool call:
   - **Unknown tool:** the name isn't a known `model_name` → emit `ErrorEvent(source="agent", kind="unknown_tool")` and return an error tool result to the model.
   - **Invalid arguments:** validate the args against `ToolSpec.input_schema` with `jsonschema`. On failure, emit `ToolCall(status="rejected")` with `error.kind="invalid_args"`, return the validation message to the model as an error result, and don't call the server.
   - **Malformed call:** tool-use input that isn't a JSON object → `malformed_call`.
2. At run end:
   - empty final text and no output → `no_final_output`, state `agent_failed`
   - Bedrock `stop_reason` of `content_filtered` or `guardrail_intervened` → `refusal`
3. Don't guess "gave up" from text. The workflow evaluator's done condition covers that.
4. Strands: map its unknown-tool and validation behaviour (hooks or callbacks) onto the same kinds.

**Tests:** `tests/journeys/test_j4_errors_fakes.py` with scripted `FakeModelAdapter` replies covering every kind above, for both harnesses. Each error appears once, with the right `source` and `kind`, and the run continues where srs §12.4 says it should.

**Acceptance:**

- [ ] J4 step 2 passes on fakes for both harnesses.

#### PRI-R1-02 · Plain Converse-loop harness

| Effort | Refs |
|---|---|
| ~2 h | DD-009 · FR-1.1–FR-1.3, FR-1.11 · arch §9.1 |

**Goal:** the second harness, about 150 lines, with no framework.

**Steps:**

1. Start with `messages = [user(prompt)]`. Loop:
   - call `ctx.model.converse(messages, system, tools, params)` and append the assistant message
   - if `stop_reason == "tool_use"`: run each tool use **in the order given** (deterministic, FR-1.11) through `_checks` and then `ctx.tools.call_blocking`. Append one user message with all the `toolResult` blocks (`status: "error"` for errors) and loop again
   - if `stop_reason == "end_turn"`: the final output
   - if `stop_reason == "max_tokens"` with no text: `no_final_output`
2. Same exception mapping as the Strands harness.
3. `@register("harness", "converse_loop")`. It's registered now, but only part of the exit criteria in R2.

**Tests:**
- Conformance.
- An equivalence test: the same scripted fake on both harnesses gives the same sequence of event types, tool names and args.

**Acceptance:**

- [ ] Conformance and equivalence tests pass.

#### PRI-R1-03 · Price table v1, cost on events, loop guard

| Effort | Refs |
|---|---|
| ~2 h | FR-2.3, FR-11.5, FR-11.10 · arch §9.2, §12 · DD-032 |

**Steps:**

1. Write `pricing/prices.yaml`:
   ```yaml
   version: "2026-11-04.1"
   retrieved_at: "2026-11-04"
   currency: USD
   models:
     "<model-or-profile-id>": {input_per_1k: 0.0, output_per_1k: 0.0, source: manual}
   data: {s3_requester_pays_per_gb: 0.0}
   fargate: {vcpu_hour: 0.0, gb_hour: 0.0}
   defaults: {tokens_per_run: {T1: 20000, T2: 20000, T3: 30000, T4: 20000, T5: 15000}}
   ```
   Fill the prices by hand from the public Bedrock pricing page for the confirmed IDs. The default token counts are guesses and are labelled as such.
2. In `runtime/pricing.py`, `YamlPriceTable` implements `PriceTable`: `model_cost`, `data_cost`, `version`, and `has(model_id)`. 5th member's spec validation uses `has` so an unknown model fails early with `ConfigError`.
3. Loop guard in `runtime/guard.py`:
   - canonicalise the args (`json.dumps(sort_keys=True)`) and track consecutive identical `(tool, args)` calls
   - allow N (default 3, `loop_guard.max_identical_calls`)
   - block the (N+1)th: emit a `GuardStop(limit="loop")` with `error.source="agent"`, `kind="loop_detected"`, and raise `GuardStopped`
4. Replace `FixedPriceTable` in the worker wiring (tell 5th member).

**Acceptance:**

- [ ] Unit tests for prices and the loop guard pass.
- [ ] A live Nova Lite run shows a non-zero `cost_usd` and `price_table_version` on every `model_call`.
- [ ] Barath's planted `loop` trace (4 identical calls) matches these semantics.

### R2 — MVP complete

#### PRI-R2-01 · Full budget guard and eval-level budget

| Effort | Refs |
|---|---|
| ~2 h | FR-11.1–FR-11.4, FR-11.6 · arch §9.2 · J7 · DD-013 |

**Steps:**

1. `RunBudgetGuard(max_steps, max_tokens, max_usd, max_seconds)` (each optional, None = off). Before each model call, check:
   - steps so far ≥ `max_steps`
   - cumulative tokens ≥ `max_tokens`
   - cumulative agent `cost_usd` ≥ `max_usd`
   - elapsed ≥ `max_seconds`
2. Before each tool call, check `max_usd` and `max_seconds`. Pass `min(tool_timeout, remaining_seconds)` as the tool timeout.
3. On violation:
   - emit `GuardStop(limit, limit_value, observed_value)` with `error={source: budget, kind: budget_exceeded}`
   - raise `GuardStopped`
4. Watchdog: a timer that sets a flag at `max_seconds`. The flag is checked at the next call, because an in-flight Bedrock call can't be interrupted. The overshoot is visible as `observed_value`.
5. `EvalBudget(max_usd)` has `add(cost_usd)` and `exhausted` (bool). 5th member's service calls `add` after each run and stops launching when `exhausted`. Agree the call site with 5th member.
6. With the guard off (no limits), nothing is applied (FR-11.4).

**Tests:** `tests/journeys/test_j7_budget_fakes.py`:
- `max_steps=1` stops with the right event and state `budget_stopped`
- with no limits the same script completes
- each of the four limits fires once
- `EvalBudget` becomes exhausted at the cap

**Acceptance:**

- [ ] J7 passes on fakes.
- [ ] Barath's live J7 run (R2) shows the stop.

#### PRI-R2-02 · Sonnet-class configuration and price refresh

| Effort | Refs |
|---|---|
| ~1.5 h | DD-010, DD-032 · FR-11.10 · arch §12 |

**Steps:**

1. Confirm the Sonnet-class model works through the adapter, using an inference profile ID if one is needed. Add its price entry keyed by the exact ID used in specs.
2. Write `scripts/refresh_prices.py`:
   - use the boto3 `pricing` client (Price List API, us-east-1 endpoint) with service code `AmazonBedrock`, filtered to us-west-2 and the configured models
   - write a new `version` and `retrieved_at`
   - print a diff
   - keep `source: manual` entries the API doesn't return
   - never commit automatically; a person reviews the diff
3. Note the IAM consequence for the CDK task role (PRI-R2-05): inference profiles need permission on the profile ARN and on the underlying foundation-model ARNs in every region the profile routes to.

**Acceptance:**

- [ ] One live Sonnet-class T1 run completes with non-zero cost.
- [ ] `refresh_prices.py --dry-run` prints a diff.

#### PRI-R2-03 · Pre-flight cost estimate

| Effort | Refs |
|---|---|
| ~2 h | FR-11.7–FR-11.9 · UC-03 · arch §12 · DD-013 |

**Steps:**

1. Write `runtime/estimate.py` with `CostEstimator(store: RunStore, prices: PriceTable)` and `estimate(requests: list[RunRequest], spec: EvalSpec) -> CostEstimate`.
2. Per request, estimate tokens with this fallback chain:
   - the median input and output tokens of stored completed runs with the same (template, model, harness), via `store.query` over `run_end` totals and manifests. Shivaani provides the helper `token_history(...)`.
   - else the same (template, model)
   - else `defaults.tokens_per_run[template]`, labelled `basis: "default_guess"`
3. Add evaluation cost:
   - one summary call (summary model, median or default tokens)
   - k LLM-evaluator calls if configured
4. Return per-run, per-configuration and total estimates, plus `price_table_version`, the basis label for each line, and `exceeds_eval_cap` (bool) against `spec.budget.eval.max_usd`.
5. 5th member wires `clay-sandbox estimate` and `POST /evals/estimate`, and blocks launch when `exceeds_eval_cap` (FR-11.9).

**Tests:** a `MemoryRunStore` seeded with fake runs. Check the median path, both fallbacks, the default-guess label, and the cap flag.

**Acceptance:**

- [ ] Unit tests pass.
- [ ] `clay-sandbox estimate specs/compare-default.yaml` prints a breakdown (after 5th member wires it).

#### PRI-R2-04 · Docker image

| Effort | Refs |
|---|---|
| ~1.5 h | FR-15.3 · arch §17.2 · DD-006 |

**Steps:**

1. `docker/Dockerfile`:
   - `python:3.12-slim`
   - copy `uv` from the official uv image
   - `uv sync --frozen --no-dev`
   - copy `claysandbox/`, `toolsets/`, `tasks/`, `pricing/`, `specs/`, `mcp_servers/`
2. Pre-install every MCP server at its pinned version (from Vishal's tool sets) so no network install happens at run time. For example, run `uv tool install <pkg>==<ver>` for Python servers and set `UV_OFFLINE=1` at runtime. If any server is a Node package, add Node and install it pinned. Ask Vishal for the list.
3. Bake in `GIT_SHA` as a build arg, so the manifest records it (5th member reads `GIT_SHA` when there's no `.git`).
4. Entry point: `clay-sandbox`.
5. Check: `docker run --rm -v $PWD/samples:/app/samples <image> replay samples/runs/<id> --offline` works with no AWS credentials.

**Acceptance:**

- [ ] The image builds.
- [ ] Offline replay works inside it.
- [ ] A live R0 spec works inside it with credentials passed as env vars.

#### PRI-R2-05 · CDK stack

| Effort | Refs |
|---|---|
| ~1.5 h | FR-15.5, FR-15.6 · arch §17.3 · DD-024 · DD-034 |

**Steps:**

1. Python CDK app in `infra/` (`app.py`, `stack.py`, its own `requirements` or uv group). One stack holds the resources in arch §17.3:
   - an S3 bucket (block public access, SSE-S3, versioned, `RemovalPolicy.DESTROY` with `auto_delete_objects=True`)
   - an ECR repository (scan on push)
   - a VPC with public subnets and **no NAT gateway**
   - an ECS cluster
   - a Fargate task definition (1 vCPU / 2 GB, overridable) with the awslogs driver and a log group (7-day retention)
2. Task role (least privilege):
   - `bedrock:InvokeModel` on the configured foundation-model and inference-profile ARNs only (take them from a CDK context value)
   - `s3:GetObject`, `PutObject`, `ListBucket` on the sandbox bucket
   - `s3:GetObject` on the NAIP buckets (Requester-Pays)
   - X-Ray write permissions for the OTLP path Shivaani picks (O-4)
3. Execution role: ECR pull and CloudWatch Logs write.
4. `CfnOutput`s for bucket, cluster, task definition, subnets and security group. A script writes them to `infra/outputs.json` for the Fargate executor.
5. 5th member adds `cdk synth` to CI.

**Acceptance:**

- [ ] `cdk synth` passes.
- [ ] `cdk deploy` works in the sandbox after `cdk bootstrap`.
- [ ] Deploy steps are written in your README section.

#### PRI-R2-06 · Fargate executor (Should)

| Effort | Refs |
|---|---|
| ~1.5 h | FR-15.2, FR-15.4, FR-15.7 · UC-11 · arch §8.6 |

**Steps:**

1. `platform/executors/fargate.py`, `@register("executor", "fargate")`, implementing 5th member's `Executor` interface.
2. `submit`:
   - write each `RunRequest` to `s3://<bucket>/requests/<run_id>.json`
   - call `ecs.run_task(cluster, taskDefinition, launchType="FARGATE", networkConfiguration={"awsvpcConfiguration": {subnets, securityGroups, "assignPublicIp": "ENABLED"}}, overrides={"containerOverrides": [{"name": ..., "command": ["worker", "--request", "s3://…"]}]})`
   - limit concurrent tasks to `max_parallel`
3. `poll`: read `status.json` under `s3://<bucket>/runs/<run_id>/`. A task that stopped without a terminal status → `infra/executor_failure`, so 5th member's retry logic applies.
4. Record the task ARN in the run's environment (FR-15.7). 5th member's worker supports `worker --request s3://…`. Agree the CLI shape with 5th member.
5. **If time is short, cut this task first.** Add the FUTURE-WORK row (item 6, batch trials on AWS).

**Acceptance:**

- [ ] A two-run eval with `executor: {name: fargate}` completes.
- [ ] Its run folders appear in S3 and sync down for stats.

### R3 — UI and demo

#### PRI-R3-01 · Final demo eval and demo runbook

| Effort | Refs |
|---|---|
| ~2.5 h | srs §2 audience goal · J1, J2, J3, J5, J7 |

**Steps:**

1. With Barath, define `specs/demo.yaml`: small enough to finish live in a few minutes (for example 2 configurations × 2 instances × N=1), plus the full R2 comparison eval as the result to show.
2. Run it live (on Fargate if PRI-R2-06 shipped, otherwise locally). Hand the runs to Shivaani to commit under `samples/`.
3. Write `DEMO.md` at the repo root:
   - timed script for prelims
   - live command sequence
   - replay fallback if Bedrock or the network fails
   - component-swap demo (J3)
   - budget-stop demo (J7)
   - which UI screens to show, and in what order
4. Rehearse once with the team. Fix anything that takes longer than planned.

**Acceptance:**

- [ ] The rehearsal runs from `DEMO.md` without improvising.
- [ ] The fallback replay works offline.

## 10. Hand-offs

| When | You give | To | What they do with it |
|---|---|---|---|
| R0 hour 0 | Confirmed model IDs | 5th member, team lead | Sample specs |
| R0 | Adapter, wrappers, Strands harness | 5th member | Worker wiring, R0 gate |
| R1 | Error capture, Converse loop, price table | Barath (scoring), Shivaani (summary errors), 5th member (wiring) | J4, J1 |
| R2 | `RunBudgetGuard`, `EvalBudget`, `CostEstimator` | 5th member | Spec budget, eval cap, `estimate` command |
| R2 | Docker image, `infra/outputs.json`, Fargate executor | 5th member (README), Barath (gate evals) | J8, UC-11 |
| R3 | Demo spec, runbook | Whole team | Prelims |

## 11. Risks and fallbacks

| Risk | Fallback |
|---|---|
| A-4 fails: Strands can't run through our wrappers | arch §9.1 fallback: hook-based adapter. Prove event equivalence with the Converse loop on fakes |
| Sonnet-class model or judge model not enabled | Use the closest available model. Tell the team lead to update DD-010/DD-027 |
| Bedrock throttling during evals | Adaptive retries. Ask 5th member to lower `max_parallel`. Infra retries keep stats clean (DD-012) |
| Price unknown for a model | `source: manual` entry with a dated note. Reports already label $ as an estimate |
| CDK or Fargate eats the afternoon | Ship the Docker image. Cut Fargate, then CDK, and add FUTURE-WORK rows |

## 12. Effort summary

| Release | Tasks | Hours (rough) |
|---|---|---|
| R0 | Contracts session, PRI-R0-00 to R0-03 | 8.5 |
| R1 | PRI-R1-01 to R1-03 | 6 |
| R2 | PRI-R2-01 to R2-06 | 10 |
| R3 | PRI-R3-01 | 2.5 |
| **Total** | | **≈ 27** |

Team totals are 24–28 hours each.

## 13. Release checklists

**R0**
- [ ] Model IDs confirmed and shared
- [ ] `contracts/runtime.py`, `errors.py`, fakes and conformance merged
- [ ] Adapter, wrappers and Strands harness merged
- [ ] R0 live run with ≥1 MCP tool call (with 5th member)

**R1**
- [ ] Error kinds captured for both harnesses (J4 on fakes)
- [ ] Converse loop registered and conformant
- [ ] Price table v1 and loop guard merged. Costs show on live traces

**R2**
- [ ] Budget guard and eval budget (J7 on fakes)
- [ ] Sonnet-class config and price refresh script
- [ ] Pre-flight estimate wired by 5th member
- [ ] Docker image builds, offline replay works in it
- [ ] CDK deploys (or FUTURE-WORK row)
- [ ] Fargate executor (or FUTURE-WORK row)
- [ ] README section: models, budget, estimate, Docker, AWS deploy

**R3**
- [ ] Demo eval committed (via Shivaani)
- [ ] `DEMO.md` rehearsed
