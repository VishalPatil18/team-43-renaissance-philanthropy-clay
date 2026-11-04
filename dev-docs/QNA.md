# Clay Agent-Eval Sandbox — likely questions and answers (whole project)

Interview/demo prep covering every workstream, written from the actual code in this repository.
Grounded in what is implemented, with stubs and gaps called out honestly.

> **Where the code lives.** `main` has WS2 (tools/tasks), WS3 (trace/store/summary) and WS4
> (evaluation/stats) merged. The WS1 runtime (Bedrock adapter, wrappers, harnesses, guards,
> pricing, estimate, Docker, CDK, Fargate) is on `prithwish/PRI-runtime-and-cloud-execution`; the
> AgentCore deployment is on `prithwish/agentcore-observability` (this file's branch). Tags:
> **[main]**, **[WS1 branch]**, **[AgentCore branch]**, **[live in AWS]**.
>
> **Honesty note.** The WS5 glue — the composition root (`platform/service.py`), the run
> `worker`, the local executor, the CLI (`clay-sandbox`) and the API — is **not implemented**.
> Those appear in docstrings and the architecture doc but there is no such code. The library
> components are built and tested; the orchestration that stitches them into a running service is
> the main gap. Say so if asked, rather than claiming a working CLI.

---

## 1. The project

**Q: What does the sandbox do, in one sentence?**
It runs an LLM agent on a known geospatial data-building task on Amazon Bedrock, captures a full
trace of what the agent did, then summarizes, scores and statistically compares models, harnesses
and tool sets. The loop under test is harness → MCP tools → trace → summarize → score → report.

**Q: Who is it for, and why does it matter?**
It's built for Clay, an open Earth-foundation-model project. The point is to measure agent
*behaviour*, not just the final answer, so you can tell a lucky answer from a sound process and
compare approaches with real statistics rather than vibes.

**Q: What are the architecture principles?**
Nine (architecture.md §1). Worth memorizing: P1 the trace is the truth (scoring reads only the
trace, manifest and task reference); P3 everything that varies is a plugin chosen by name; P5
local-first, cloud additive; P6 instrument at the boundary (tracing and guards wrap the model and
tools, so every harness is traced identically); P7 measurement apart from the measured (evaluators
and tracers are compared on identical stored runs, never through new agent runs); P9 know the cost
first.

**Q: How is the work divided?**
Five workstreams against frozen contracts: WS1 runtime and cloud execution; WS2 tools and tasks;
WS3 trace, store and summary; WS4 evaluation and statistics; WS5 platform glue, CLI/API, UI.
import-linter enforces that every component imports only `contracts`; only `platform` may cross
components.

**Q: What's the plugin/registry model?**
`contracts/registry.py` holds a `(kind, name) → class` dict with a `@register(kind, name)`
decorator and `resolve`/`list_components`. Kinds: `model, harness, toolset, tracer, evaluator,
summarizer, executor, pricing, store`. Each plugin declares a Pydantic `Params` model that becomes
its schema. `platform/registry_bootstrap.py` imports every plugin module once so the registrations
fire, and calls `register_toolsets()` to register one entry per `toolsets/*.yaml`.

---

## 2. Contracts and testing

**Q: Why "contracts before code"?**
Five people needed to build in parallel. The `contracts/` package has the Pydantic schemas and
`Protocol` interfaces (trace events, manifest, spec, tools, runtime, store, assessment, stats,
execution), a fake per interface, and conformance suites. Everyone codes against those, so
integration isn't a surprise at the end.

**Q: What do the conformance suites actually check? [main]**
They're parametrized over every *registered* implementation. Examples: every evaluator's
Assessment is JSON-Schema-valid, cites only event IDs that exist, is byte-identical on repeat if it
claims to be deterministic, and — importantly — scores identically when infra-error events are
injected. Every harness must propagate `GuardStopped` and reach a final output on a two-step
script. Every tracer must round-trip events and never raise into the caller. Every tool session
must turn failures into error results, not exceptions.

**Q: What stops a contract from drifting after freeze?**
A change needs a design-decision entry, a `schema_version` bump and sign-off from affected owners.
The store's trace reader upgrades old schema versions on read (`store/reader.py:upgrade_event`), so
old traces stay readable.

---

## 3. Runtime — WS1

**Q: Walk me through one request end to end. [WS1 branch]**
Open the MCP tool set, write the manifest, open a tracer behind the event sink, build the guards,
wrap the Bedrock adapter and tool session in the instrumented wrappers, then call
`Harness.run(ctx)`. The harness loops model↔tools. Every model call emits a priced `ModelCall`;
every tool call emits a `ToolCall` with the full result stored as a hashed blob. At the end
`FinalOutput` and `RunEnd` are emitted. Summary, evaluators and report then read the stored trace.
(The worker that drives this is WS5 and not implemented; `runtime/testing.py:build_context` wires
the same pieces for tests.)

**Q: Why two harnesses, and how is the comparison kept fair? [WS1 branch]**
`strands` and `converse_loop`. Both get the *same* instrumented model adapter, tool session and
guards via `RunContext`, so they emit the same event types. Tracing and guards live at the boundary
(`runtime/instrument.py`), not inside either harness — principle P6.

**Q: How does the Strands harness avoid bypassing your wrappers? (A-4) [WS1 branch]**
A custom Strands model provider delegates to `ctx.model.converse`, and each MCP tool is a Strands
tool that calls `ctx.tools.call_blocking`. Strands never uses its own Bedrock or MCP clients; a
test counts botocore calls to prove it. Verified on `strands-agents==1.63`.

**Q: Which Bedrock models, and why the `us.` prefix on Claude? [live in AWS]**
Nova Lite (dev/summary), Nova Pro (baseline), Claude Sonnet 4.6 (variant), Llama 3.3 70B (judge),
confirmed with `scripts/check_models.py`. Claude needs a cross-region inference profile ID; the
bare ID is rejected by Bedrock. The judge is a different vendor family from the agents (DD-027).
Model IDs come only from the spec (FR-1.5), enforced in `bedrock.py:build_request`.

---

## 4. Guards and cost — WS1

**Q: What can stop a run, and when? [WS1 branch]**
`RunBudgetGuard` enforces optional `max_steps`, `max_tokens`, `max_usd`, `max_seconds`; `LoopGuard`
stops the 4th identical `(tool, args)` call in a row (default 3). Checks run *before* each call, so
a run overshoots by at most one call, and the `guard_stop` event records the observed value.

**Q: How do you enforce `max_seconds` on an in-flight Bedrock call? [WS1 branch]**
You can't interrupt it. A watchdog timer sets a flag; the flag is read at the next pre-call check,
so the stop lands at the next boundary.

**Q: Run budget vs eval budget?**
The run budget stops one run. `EvalBudget` is the eval-level dollar cap: the service adds each run's
cost and stops launching when `exhausted`; in-flight runs finish and unlaunched ones end
`skipped_eval_cap`.

**Q: How is the pre-flight estimate computed? [WS1 branch]**
`CostEstimator` uses a fallback chain: median tokens of completed runs with the same
(template, model, harness); else (template, model); else a per-template default flagged
`default_guess`. It adds summary and k judge calls, Requester-Pays reads, and Fargate compute if
that executor is used, and flags `exceeds_eval_cap`. History comes from WS3's `store.token_history`
or a DuckDB query over run folders.

---

## 5. Tools and tasks — WS2

**Q: How are MCP tools launched, and safely? [main]**
`McpStdioToolSession` (`tools/launcher.py`) spawns each server over stdio on a background event
loop, lists its tools, and exposes `call`/`call_blocking` with per-server timeouts. A failed or
crashed server is marked unavailable and its calls return `ToolResult(error_kind=...)` rather than
raising. Environment is scrubbed (`tools/env.py`): only PATH/HOME/locale/cache vars pass, and AWS
credentials pass only when a server sets `needs_aws: true` (P8/DD-034).

**Q: How are MCP server versions controlled? [main]**
`tools/toolsets.py:package_of` requires `uvx`/`npx` servers to be pinned as `name@1.2.3` and
rejects anything unpinned; our own `python -m` servers are exempt. Each tool set is registered with
a version that is the sha256 of its YAML.

**Q: What are the tasks? [main]**
Five templates (T1–T5) over six US-county AOIs (`tasks/aois.yaml`, four with solar sites, two
negative controls). T1 find NAIP imagery for an AOI/year; T2 discover RODA datasets; T3 find solar
sites; T4 find similar places (exercises clay-embeddings); T5 an ambiguous request that tests
honesty. `TaskLibrary` instantiates a template on an AOI with `{placeholder}` substitution (no
template engine), and references are content-hashed and versioned (`tasks/references.py`).

**Q: What is the clay-embeddings server? [main]**
A standalone MCP server over staged LGND Sentinel-2 embeddings with two tools: `embedding_at(lat,
lon, year, month)` returns the chip at a point, and `similar_places(...)` returns the k most similar
chips by cosine similarity. It's deterministic (ties broken by `chips_id`) and limited to six
counties and two months, which the tool descriptions state. Note: the staged `.parquet` data isn't
committed, so the server reports missing data as a tool error until staged.

---

## 6. Trace, store and summary — WS3

**Q: How are events recorded, and secrets kept out? [main]**
`RunEventSink` (`tracing/sink.py`) assigns `seq` (from 0) and `event_id = run_id:seq`, redacts the
event, then hands it to the tracer. It never raises into the agent loop: a bad event becomes a
payload-free `ErrorEvent` and the run is flagged `incomplete`. Redaction (`tracing/redact.py`)
covers AWS key IDs, secret keys, Authorization/Bearer headers, SigV4 signatures and the values of
env vars named like secrets. `put_blob` redacts before hashing, so no caller can store a secret by
skipping a step.

**Q: What tracers are there? [main]**
`jsonl` (append-only, flushed per event, fsync on `run_end`, refuses to append to a non-empty
trace), `otel` (OpenTelemetry spans with GenAI attributes, an always-on OTLP-JSON file copy and an
optional remote exporter to a local ADOT collector), and `tee` (runs two tracers on one run and
records per-event overhead). `tracing/compare.py` compares tracers on identical runs: overhead,
events lost, and field-by-field fidelity.

**Q: How is immutability enforced in the store? [main]**
`LocalRunStore` (`store/local.py`): `create_run` refuses an existing folder and writes the manifest
once; once `status.json` is terminal the manifest and trace are locked (via `StoreWriteRefused` and
read-only file modes); assessments are new files only; summaries and reports are regenerable.
Queries go through DuckDB (`store/query.py`) over the JSON/JSONL run folders, with file access
switched off once the tables load so no query can touch the filesystem.

**Q: How does the summarizer avoid making things up? [main]**
`summary/llm.py` asks the model for `{claim, event_ids[]}`; `summary/citations.py` drops claims
that cite no event or a non-existent one, and adds a deterministic line for every error event no
kept claim mentions, so no error is missing. It uses an uninstrumented adapter (summary cost is
evaluation cost, not agent cost) and falls back to the deterministic summarizer on any failure, so
a summary always exists.

---

## 7. Evaluation and statistics — WS4

**Q: What does the workflow evaluator score? [main]**
Eight deterministic sub-scores (`evaluation/workflow.py` V1): tool_call_validity,
argument_constraints, required_coverage, ordering, forbidden_tools, recovery, step_efficiency,
done_condition. Composite is their weighted mean; `success` = done condition met and no guard stop.
Tools are matched by capability, not name. Infra-error events are dropped before scoring, so infra
problems never move a score, and a run that ended `infra_error` has `success = None` (excluded, not
a failure).

**Q: How do argument constraints work? [main]**
`evaluation/constraints.py` has five checks: `bbox_intersects_aoi`, `point_within_aoi`,
`collection_in`, `datetime_within_year`, `k_at_most`. Geometry is EPSG:4326 via shapely; the AOI
comes from the reference's GeoJSON or bbox. A check returns True/False, or None when it doesn't
apply.

**Q: What does each output evaluator measure? [main]**
One per template (`evaluation/output/`): T1 NAIP item IDs and T2 RODA slugs give precision/recall/F1
(T2 supports recall@k); T3 matches solar sites within a distance tolerance in a local projection;
T4 is recall@k over chip IDs; T5 is a pass rate over honesty rules. Output that fails to parse or
the schema scores 0, with the parse error recorded.

**Q: How does the LLM process judge work? [main]**
`evaluation/llm_process.py` sends a trace digest, the process rubric and the workflow spec, and
requires JSON-only output with per-rubric scores and cited event IDs. It runs k times (default 3)
at temperature 0, drops cited IDs that aren't in the trace, retries once on bad JSON, and stores the
k composites, their mean and spread. It refuses a judge in the same model family as the agents
(DD-027), is skipped offline, and its tokens count as evaluation cost.

**Q: What statistics are produced? [main]**
`evaluation/stats.py`: Wilson intervals for success rates; cluster bootstrap (resample task
instances, keep each instance's runs together) for metric means; a sign-flip permutation test for
paired comparisons (exact up to 15 instances, else 10,000 random flips); Holm correction across
variants when there are more than two comparisons. Everything is seeded per quantity, so adding a
metric doesn't change other draws. Verdicts are plain language with a warning when the CI is wide or
instances are few.

**Q: How do you know the evaluators themselves are trustworthy? [main]**
Planted-trace validation (`evaluation/validate.py`): a deliberately flawed trace must score strictly
lower than the good trace of the same instance on the metrics the flaw targets. It reports a
detection rate per flaw type and a margin (good minus flawed composite) compared with the live CI
half-width. Evaluators are also compared against each other on identical runs (`compare.py`,
Spearman and mean absolute difference), never through new agent runs.

---

## 8. Cloud execution and AgentCore — WS1 and this branch

**Q: How does a run execute in the cloud? [WS1 branch]**
The Fargate executor writes each request to S3, starts an ECS task running `clay-sandbox worker
--request s3://…`, and reads `runs/<run_id>/status.json` when it stops. A stopped task with no
terminal status is reported `infra_retry`/`executor_failure`. (The `worker` subcommand it invokes is
WS5 and not implemented yet.) The CDK stack is least-privilege: Bedrock only on the configured
models, the sandbox bucket, NAIP read, X-Ray write, and a VPC with no NAT gateway.

**Q: Did you use AgentCore? The design doc rejected it. [AgentCore branch + live in AWS]**
The default path is Fargate; AgentCore was rejected as the core harness host because it would couple
the harness to AgentCore and skew the latency metric. Separately, the Strands agent is deployed to
AgentCore Runtime (direct code deployment, arm64 zip, least-privilege role) to satisfy two asks:
inbound OAuth and observability. It hosts the same stack, so it's additive.

**Q: Show observability / an end-to-end trace. [AgentCore branch + live in AWS]**
AgentCore Observability runs through CloudWatch Transaction Search. One request produced a 13-span
trace in `aws/spans`: `POST /invocations` → `invoke_agent` → event-loop cycles → `chat`/Converse
model calls → `execute_tool roda__search_datasets` with its MCP child. View it in CloudWatch GenAI
Observability → Bedrock AgentCore, or Transaction Search by trace ID. `scripts/observe_agent.py`
reproduces it.

---

## 9. Curveballs

**Q: What's the biggest gap?**
The WS5 glue: no service, worker, local executor, CLI or API, and no report renderer. The component
libraries are built and tested, but nothing orchestrates a full eval end to end yet. The demo
runbook depends on that CLI, so it's drafted, not rehearsed.

**Q: What else is unfinished?**
The clay-embeddings staged data isn't committed. The OTel remote exporter hasn't been exercised
against a real collector from CI. Cost is a price-table estimate, not the AWS bill. The Fargate
compute estimate uses a guessed run duration. These are in FUTURE-WORK.

**Q: Why trust the cost number?**
It's labelled an estimate everywhere; each model call is priced at trace time against a dated,
versioned table; the estimate labels each line's basis; and live runs confirmed real costs near the
predictions.

**Q: What makes a run reproducible?**
The manifest records model ID and params, harness, tool set with pinned MCP versions and hashes,
seed, price-table version, git SHA and lockfile hash. The harness is deterministic except for the
model (FR-1.11).

---

### Thirty-second pitch
"We run an agent on Bedrock against a known geospatial task, capture a full trace at the
model-and-tool boundary, and score the behaviour and the answer separately — eight deterministic
workflow sub-scores, per-template output metrics, and an out-of-family LLM judge — then compare
configurations with cluster-bootstrap CIs and permutation tests. Everything that varies is a
swappable plugin. Runs are budgeted and priced before they launch, run locally or on Fargate, and
the Strands agent is also deployed on AgentCore Runtime with full request tracing in CloudWatch."
