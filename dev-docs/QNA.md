# Clay Agent-Eval Sandbox — likely questions and answers

Prep for demo/judging questions, written from the actual code. It covers the whole project but
leans on **Prithwish's workstream (WS1: agent runtime and cloud execution)**, which is what we own.

> **State note.** `main` has WS2/WS3/WS4 merged (up to PR #9). The WS1 runtime and the AgentCore
> deployment live on two feature branches:
>
> - `prithwish/PRI-runtime-and-cloud-execution` — Bedrock adapter, wrappers, harnesses, guards,
>   pricing, estimate, Docker, CDK, Fargate.
> - `prithwish/agentcore-observability` — AgentCore Runtime deploy + observability (this file lives
>   here).
>
> Answers are tagged **[main]**, **[WS1 branch]**, or **[AgentCore branch]** so you know where each
> lives. Items marked **[live in AWS]** were actually run in account `942922163732`, us-west-2.

---

## 1. What the project is

**Q: In one sentence, what does this project do?**
It's an evaluation sandbox that runs an LLM agent on a geospatial data-building task on Amazon
Bedrock, records everything the agent did as a trace, then summarizes, scores and statistically
compares models, harnesses and tool sets. The loop under test is: harness → MCP tools → trace
capture → summarize → score → report.

**Q: Why build a sandbox instead of just checking the agent's final answer?**
Because the answer alone hides *how* the agent got there. The sandbox scores the behaviour (tool
choice, argument validity, ordering, recovery from errors, honesty) separately from the output
metric, so you can tell a lucky answer from a sound process. That split is principle **P1: the
trace is the truth** — scoring reads only the trace, manifest and task reference, never the harness
internals.

**Q: What are the architecture principles?**
Nine (architecture.md §1). The ones worth memorizing: P1 the trace is the truth; P3 everything that
varies is a plugin chosen by name; P5 local-first, cloud additive (replay/scoring need no AWS); P6
instrument at the boundary (tracing and guards wrap the model and tools, so every harness is traced
identically); P9 know the cost first (every eval is estimated before launch, every model call is
priced at trace time).

**Q: How is the work split?**
Five workstreams: WS1 runtime (me), WS2 tools and tasks, WS3 trace and store, WS4 evaluation and
stats, WS5 platform glue, CLI/API and UI. Each builds against frozen contracts, fakes and
conformance tests (P4), so we could work in parallel. import-linter enforces that every component
imports only `contracts`; only `platform` may cross components.

---

## 2. The runtime (WS1) — my core

**Q: Walk me through one request end to end. [WS1 branch]**
A spec expands into run requests. For each: open the MCP tool set, write the manifest, open a
tracer behind an event sink, build the guards, wrap the Bedrock adapter and tool session in the
instrumented wrappers, then call `Harness.run(ctx)`. The harness loops between the model and its
tools. Every model call emits a priced `ModelCall` event; every tool call emits a `ToolCall` with
the full result stored as a hashed blob. At the end it emits `FinalOutput` and `RunEnd`, and the
trace is closed. Summary, evaluators and report then read the stored trace.

**Q: Why two harnesses, and how do you keep the comparison fair? [WS1 branch]**
`strands` (Strands Agents) and `converse_loop` (about 100 lines, no framework). Both receive the
*same* instrumented model adapter, tool session and guards through `RunContext`, so they produce
the same event types. That's principle P6 — tracing and guards sit at the boundary
(`InstrumentedModel`/`InstrumentedTools` in `runtime/instrument.py`), not inside either harness. A
fair harness comparison is the point.

**Q: How does the Strands harness avoid double-tracing or bypassing your wrappers? (A-4) [WS1 branch]**
A custom Strands model provider (`_BridgeModel`) delegates to `ctx.model.converse`, and each MCP
tool is registered as a Strands tool that calls `ctx.tools.call_blocking`. So Strands never uses
its own Bedrock or MCP clients; our wrappers see every call. A unit test counts botocore calls to
prove Strands makes none of its own. Verified on `strands-agents==1.63`.

**Q: Where do model IDs come from? Why does that matter?**
Only from the spec (`model.params.model_id`), never from code or env — requirement FR-1.5, enforced
in `bedrock.py:build_request`, which rejects a per-call model_id override. It matters because the
model is a comparison axis: you swap it by editing the spec, and the manifest records exactly which
ID ran.

**Q: Which Bedrock models did you confirm? [live in AWS]**
Checked live with `scripts/check_models.py`: Nova Lite `us.amazon.nova-lite-v1:0` (dev/summary),
Nova Pro `us.amazon.nova-pro-v1:0` (baseline), Claude Sonnet 4.6 `us.anthropic.claude-sonnet-4-6`
(variant), Llama 3.3 70B `us.meta.llama3-3-70b-instruct-v1:0` (judge). The judge is a different
model family from the agents under test (DD-027), so it isn't grading its own family.

**Q: Why the `us.` prefix on the Claude ID?**
Claude on Bedrock needs a cross-region inference profile ID. The bare
`anthropic.claude-sonnet-4-6` fails with "on-demand throughput isn't supported". The price table
handles this with `alias_of`, so a profile ID borrows the underlying model's price.

---

## 3. Guards and cost (WS1)

**Q: What can stop a run, and when is the check made? [WS1 branch]**
`RunBudgetGuard` enforces optional `max_steps`, `max_tokens`, `max_usd`, `max_seconds`. The
`LoopGuard` stops the 4th identical `(tool, args)` call in a row (default 3). Checks run *before*
each model and tool call, so a run can overshoot a limit by at most one call. The `guard_stop`
event records the observed value, so the overshoot is visible.

**Q: How can you enforce `max_seconds` if a Bedrock call is already running? [WS1 branch]**
You can't interrupt an in-flight Converse call. A watchdog timer sets a flag at `max_seconds`, and
the flag is read at the next pre-call check. So it stops at the next boundary, and the overshoot
shows up as `observed_value`.

**Q: With no limits set, what happens?**
Nothing is enforced (FR-11.4). There's a test for exactly this: the same script completes with no
limits and stops with each limit.

**Q: Difference between the run budget and the eval budget?**
The run budget stops one run. `EvalBudget` is the eval-level dollar cap: the service adds each run's
cost and stops launching new runs once `exhausted`. Runs already started finish. Those unlaunched
runs end as `skipped_eval_cap`.

**Q: How is cost computed? [WS1 branch, live-verified]**
From a versioned price table (`pricing/prices.yaml`), per 1,000 tokens. Every `ModelCall` stores
its `cost_usd` and the `price_table_version`. `scripts/refresh_prices.py` rebuilds the table from
the AWS Price List API and prints a diff; a human commits it. Claude prices are typed by hand,
because the Price List API doesn't list them. Live Nova Lite runs showed about $0.0003 per request.

**Q: How does the pre-flight estimate predict tokens for a run that hasn't happened? [WS1 branch]**
A fallback chain (`runtime/estimate.py`): median tokens of stored completed runs with the same
(template, model, harness); else the same (template, model); else a per-template default flagged
`default_guess`. It adds the summary and LLM-judge calls, Requester-Pays reads, and Fargate compute
if that executor is used, then flags `exceeds_eval_cap`. Every line is labelled with its basis so
you know what's measured versus guessed.

---

## 4. Errors, tracing and lifecycle

**Q: What's the error taxonomy? [main + WS1 branch]**
Four sources: `agent` (unknown_tool, invalid_args, malformed_call, no_final_output, refusal),
`tool` (tool_error, tool_timeout, server_unavailable), `budget` (budget_exceeded, loop_detected),
`infra` (throttled, service_error, network, executor_failure). The layer that catches the failure
sets the source. Agent and tool errors are returned to the model and the run continues; budget
stops the run; infra triggers a retry.

**Q: What are the run states? [main]**
`planned → running → {infra_retry} → completed | budget_stopped | agent_failed | infra_excluded |
skipped_eval_cap`. Everything except `skipped_eval_cap` gets scored. Infra retries never merge into
one trace: each attempt gets its own run folder.

**Q: What happens if a tracer fails mid-run?**
It must never raise into the agent loop (FR-2.6). The event sink turns a tracer failure into a
logged sandbox error and flags the run `incomplete`, keeping every event up to that point. The
trace is append-only and flushed per event, so a crash still leaves a usable partial trace.

**Q: What makes a run reproducible?**
The manifest records model ID and params, harness, tool set with pinned MCP versions and hashes,
seed, price-table version, git SHA and lockfile hash. The harness is deterministic except for the
model (FR-1.11): same tool order, same prompt assembly.

---

## 5. Cloud execution (WS1)

**Q: How does a run execute in the cloud? [WS1 branch]**
The Fargate executor writes each request to `s3://<bucket>/requests/<run_id>.json`, starts an ECS
task with `clay-sandbox worker --request s3://…`, and reads `runs/<run_id>/status.json` when the
task stops. A stopped task with no terminal status is reported as `infra_retry` /
`executor_failure`, and the service decides whether to retry.

**Q: What does the CDK stack create, and how is it least-privilege? [WS1 branch]**
S3 bucket (private, encrypted, versioned), ECR repo, a VPC with public subnets and no NAT gateway
(cost), an ECS cluster and Fargate task, and a 7-day log group. The task role allows
`bedrock:InvokeModel` only on the configured model and inference-profile ARNs, the sandbox bucket,
the NAIP Requester-Pays buckets (read), and X-Ray write. Nothing broad.

**Q: Is the Docker image portable? [WS1 branch, built locally]**
One image runs the CLI, worker and MCP servers on a laptop and on Fargate. MCP servers must be
pinned (`name@1.2.3`); the build fails on an unpinned one and pre-installs the rest, so the
container runs with `UV_OFFLINE=1`. It runs as non-root with no baked-in credentials.

---

## 6. AgentCore (this branch)

**Q: Did you use Bedrock AgentCore? The design doc rejected it. [AgentCore branch + live in AWS]**
The *default* execution path is Fargate; AgentCore was rejected as the core harness host because it
would couple the harness to AgentCore and skew the latency metric. Separately, I deployed the
Strands agent to **AgentCore Runtime** to satisfy two specific asks: inbound OAuth and
observability. It hosts the same stack (Bedrock adapter → instrumented wrappers and guards →
Strands harness → RODA MCP tools), so the deployment is additive, not a change to the sandbox core.

**Q: How is it deployed? [AgentCore branch + live in AWS]**
Direct code deployment: `scripts/agentcore_deploy.py` builds an arm64 zip pinned to `uv.lock`,
creates the S3 bucket and a least-privilege execution role, and calls `CreateAgentRuntime` with
Python 3.12 and entrypoint `opentelemetry-instrument main.py`. The runtime reached `READY` and a
real invocation completed with a `roda.search_datasets` tool call.

**Q: Show observability / an end-to-end trace. [AgentCore branch + live in AWS]**
AgentCore Observability runs through CloudWatch Transaction Search (enabled account-wide). One
request produced a 13-span trace in the `aws/spans` log group: `POST /invocations` → `invoke_agent`
→ event-loop cycles → `chat`/Converse model calls → `execute_tool roda__search_datasets` with its
MCP child. View it in CloudWatch GenAI Observability → Bedrock AgentCore, or Transaction Search by
trace ID. `scripts/observe_agent.py` reproduces the trace from the data.

**Q: Is the endpoint secured?**
Currently only by IAM (`InvokeAgentRuntime`). The inbound-OAuth piece adds a JWT authorizer
(`customJWTAuthorizer`) to the runtime, backed by an OIDC provider such as a Cognito user pool, so a
call with no token is rejected. That's the next step if asked.

---

## 7. Likely curveballs

**Q: What's the weakest part / what did you cut?**
The pre-flight Fargate compute estimate uses a default run duration (a guess), and cost is a
price-table estimate, not the AWS bill. Both are in FUTURE-WORK. The demo runbook is drafted but not
rehearsed end to end, because it depends on the WS5 CLI glue.

**Q: What breaks if a contract changes after freeze?**
A changed contract needs a design-decision entry, a `schema_version` bump, and sign-off from every
affected owner. Readers accept older versions, and the store reader upgrades old schema versions on
read, so existing traces stay valid.

**Q: How do you know your evaluators are any good?**
Planted-trace validation (WS4): a deliberately bad trace must score below the good trace of the
same instance, with a measurable margin. Evaluators are also compared against each other on
identical runs (P7), never through new agent runs.

**Q: Why trust the cost number?**
It's labelled an estimate everywhere. Each model call is priced at trace time against a dated,
versioned table; the estimate labels each line's basis (history vs default guess); and live runs
confirmed real costs near the predictions.

---

### Thirty-second pitch

"We run an agent on Bedrock against a known geospatial task, capture a full trace at the
model-and-tool boundary, and score the *behaviour* and the *answer* separately. Everything that
varies — model, harness, tools, evaluator — is a swappable plugin, so we can compare them fairly and
with statistics. Every run is budgeted and priced before it launches, it runs locally or on Fargate,
and the Strands agent is also deployed on AgentCore Runtime with full request tracing in CloudWatch."
