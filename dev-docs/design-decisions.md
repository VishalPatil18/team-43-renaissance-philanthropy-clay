# Design Decisions — Clay agent-eval sandbox

> **For agents — what this file is:** Every design decision taken while writing [srs.md](srs.md) and [architecture.md](architecture.md), one entry per decision, in the order they were made. The team lead is the sole decision maker; the options were proposed by the architect. The problem statement lives in [../docs/](../docs/README.md) and is ground truth (DD-001). Do not change a decision in place: add a new entry with `Status: accepted` and `Supersedes: DD-xxx`, then set the old entry to `superseded`.

<!-- Template for each decision. Copy below this line for new entries. -->

## Decision - _<short title>_

| Field           | Value                              |
| --------------- | ---------------------------------- |
| Date            | _<YYYY-MM-DD>_                     |
| Cycle / Feature | _<feature name>_                   |
| Status          | proposed · accepted · superseded   |
| Supersedes      | _<link to prior decision, if any>_ |

### Context

_<Why was this decision needed? What forces were in play?>_

### Options considered

1. _<option A>_ - pros / cons
2. _<option B>_ - pros / cons
3. _<option C>_ - pros / cons

### Decision

_<The chosen option, stated as a sentence.>_

### Rationale

_<Why this option won. What evidence or constraint tipped it.>_

### Consequences

- _<positive consequence>_
- _<negative consequence or tradeoff accepted>_

---

## DD-001 - Decision - docs/ is ground truth; D1–D22 settled; OQs decided here

| Field           | Value                            |
| --------------- | -------------------------------- |
| Date            | 2026-11-03                       |
| Cycle / Feature | Project ground rules             |
| Status          | accepted                         |
| Supersedes      | —                                |

### Context

The problem statement is spread over `docs/` (SCOPE, 01–06, OPEN-QUESTIONS, EXTERNAL-DEPENDENCIES, FUTURE-WORK). The team's scope interview already settled D1–D22. OQ1–OQ15 were parked until right before building (D17). Two decisions (D7 Strands, D8 OpenTelemetry) were recorded as interpretations. The Clay vision PDF is gitignored and not on disk. A wireframe exists at `/workshop/wireframe.html`, outside the repo.

### Options considered

1. **docs/ binding, D1–D22 settled, OQs decided in this session, wireframe as UI reference only** - fast, respects prior work / locks in the D7 interpretation.
2. Same, but re-open D7 and D8 - removes the two shakiest assumptions / one more round of questions.
3. Re-open all of D1–D22 - clean slate / throws away the scope interview, slow, SRS drifts from 01–06.
4. Option 1 plus the vision PDF pasted into chat - catches gaps / PDF text can't be committed (D15).
5. Only SCOPE.md binding, 01–06 overridable - single source / 01–06 hold the test detail, traceability weakens.

### Decision

`docs/` is ground truth, D1–D22 are settled and not re-opened, OQ1–OQ15 are decided in this session, and the wireframe is a UI reference only.

### Rationale

The team already ran a scope interview. Re-litigating it costs time on Day 1 of a 2-day build.

### Consequences

- Every SRS requirement traces back to S#, F#, SC# and J# IDs in `docs/`.
- Strands (D7) stays the primary harness, even though it was an interpretation.
- Where the wireframe disagrees with `docs/` (it says "rubric", and it has a "synthetic prompts upload" box), `docs/` wins.

---

## DD-002 - Decision - Output format and location of the dev docs

| Field           | Value                 |
| --------------- | --------------------- |
| Date            | 2026-11-03            |
| Cycle / Feature | Documentation         |
| Status          | accepted              |
| Supersedes      | —                     |

### Context

The three deliverables (srs.md, architecture.md, design-decisions.md) need a home and a decision format. D15 says all md files are pushed. Two formats were on the table: a long template and a short ADR style.

### Options considered

1. **`dev-docs/` inside the repo, long template per decision (DD-001…), glossary inside srs.md** - pushed with the repo, full detail / long file.
2. Same, short ADR style - easy to skim / loses the options and pros/cons.
3. Long template plus an index table - easy to skim / index has to be kept current.
4. `/workshop/dev-docs/` outside the repo - private / breaks D15 and Clay's openness rule.
5. Option 3 plus a separate GLOSSARY.md - glossary has one clear home / a fourth file.
6. Option 3 plus one file per ADR in `dev-docs/adr/` - standard ADR practice / many files.

### Decision

The docs live in `dev-docs/` inside the repo, every decision uses the long template, and the glossary lives in srs.md.

### Rationale

Exactly three files, pushed with the code, and each decision keeps its full option analysis.

### Consequences

- design-decisions.md is long. Readers find entries by the DD-nnn heading.
- The glossary lives in srs.md, and its terms override the `docs/SCOPE.md` glossary where they differ (see DD-018).

---

## DD-003 - Decision - Incremental releases R0–R4 that follow Clay's build order

| Field           | Value                   |
| --------------- | ----------------------- |
| Date            | 2026-11-03              |
| Cycle / Feature | Release planning        |
| Status          | accepted                |
| Supersedes      | —                       |

### Context

Today is Day 1 (Tue Nov 3). Official build ends Wed Nov 4 at 17:30. Prelims are Thu Nov 5 at 10:00. Clay's guidance: one trace captured end to end before any scoring, then observe → summarize → score, then swaps, comparisons and statistics. The UI comes last (D11).

### Options considered

1. Two releases (MVP, stretch) - simple / no checkpoint that catches a slipping schedule early.
2. **R0 walking skeleton → R1 scored loop → R2 MVP complete → R3 UI → R4 stretch** - each gate is demo-able and matches Clay's order / more release bookkeeping.
3. One release with everything - / high risk of ending with nothing working.
4. Milestones per success criterion, no dates - flexible / ignores a real deadline.
5. Option 2 plus R5, a post-hackathon hand-off to Clay - shows impact / scope beyond the 2-day mandate.

### Decision

The product ships in five increments: R0 (F1+F2, Day 1 evening), R1 (F3–F5, F7, Day 2 noon), R2 (F6, F9–F12, Day 2 17:30), R3 (F8 UI, Day 3 morning), and R4 (stretch, in FUTURE-WORK order). The dates are targets, not commitments.

### Rationale

This mirrors Clay's Day-1 guidance. It gives the five developers (DD-005) a merge point after every increment, and the team has something demo-able from R1 on.

### Consequences

- Each release has its own goals and exit criteria in srs.md.
- Anything that misses its release moves to FUTURE-WORK.md (D21) and is not carried over silently.

---

## DD-004 - Decision - Four personas

| Field           | Value              |
| --------------- | ------------------ |
| Date            | 2026-11-03         |
| Cycle / Feature | Requirements       |
| Status          | accepted           |
| Supersedes      | —                  |

### Context

The journeys in `docs/04` say "Developer" throughout, which hides two different needs: authoring task references and reading reports to decide on trust.

### Options considered

1. One generic Developer - simplest / hides authoring and reading needs.
2. Eval Engineer + Contributor - covers the MVP tests / nobody owns task references.
3. **Eval Engineer, Task Author, Report Reader, Contributor** - each maps to a journey / —.
4. Option 3 plus Hackathon Judge - matches demo reality / temporary persona that would shape the product around a demo.
5. Option 3 plus Agent Developer and Sandbox Operator - most complete / six personas is heavy for an MVP.

### Decision

The SRS uses four personas: Eval Engineer, Task Author, Report Reader and Contributor.

### Rationale

Each persona owns at least one journey (J1–J9). Judges are treated as an audience in the release goals, not as a persona.

### Consequences

- Task authoring (templates, references, answer keys) gets first-class requirements.
- No dedicated ops persona, so sandbox and IAM needs are written as constraints, not as user stories.

---

## DD-005 - Decision - Five developers in isolated workstreams, merged per release

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | Team and delivery model  |
| Status          | accepted                 |
| Supersedes      | D14 (team roles parked)  |

### Context

The team has five developers. After the SRS, the team lead will write a `plan.md` that gives each developer one or two tasks per release. Each developer works in isolation on a feature and merges it. When everyone has merged, the application builds and runs. Work goes incrementally: walking skeleton first, then R1 and R2, then MVP complete, and so on.

### Options considered

1. Solo - fewer modules / scope doesn't fit.
2. Two people - two workstreams / slow.
3. Three or four people, four workstreams - interfaces frozen early / under-uses the team.
4. **Five people** - one workstream per developer, interfaces have to be frozen before R0 / more coordination.
5. Keep roles parked - / no basis for plan.md.

### Decision

Five developers each own one workstream and build in isolation against frozen interfaces, merging at every release gate (R0, R1, R2, R3).

### Rationale

This is the team's actual size and its chosen way of working.

### Consequences

- architecture.md has to define five workstream boundaries, and contract-first interfaces (schemas plus Python protocols) that are frozen before R0 work starts.
- Every module needs fakes or stubs for its neighbours, so each developer can test alone before merging.
- A change to a shared contract after R0 needs a new design decision entry.

---

## DD-006 - Decision - Local-first package plus one Docker image that also runs on ECS Fargate

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Deployment (D10, OQ9)     |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

D10: it should run in different places, with some AWS integrations. AWS integration is a judging criterion. The sandbox has a $500 cap and is wiped after the event. J8 needs replay with no AWS credentials. The MCP servers run as `uvx` stdio subprocesses, so they need a real process environment.

### Options considered

1. Local Python package + CLI + FastAPI; AWS for Bedrock, S3, CloudWatch/X-Ray; small CDK stack - cheapest / "different places" means only laptops.
2. **Option 1 plus one Docker image that runs locally and as ECS Fargate tasks for batch trials** - same artifact everywhere, stdio MCP works in a container, strong AWS story / Docker and ECR build needed.
3. Serverless: API Gateway + Lambda + Step Functions - visible AWS integration / MCP subprocesses awkward in Lambda, 15-minute limit, cold starts skew a scored metric (latency).
4. ECS Fargate service + SQS + workers - production-shaped / more infrastructure than 2 days allow.
5. Bedrock AgentCore Runtime + Gateway - AWS-native agent hosting / couples the harness to AgentCore, weakens SC5, platform overhead in latency.
6. EKS - / overkill.

### Decision

The sandbox is a local-first Python package (CLI + FastAPI) shipped as one Docker image, which runs on a laptop or as ECS Fargate tasks for batch trials.

### Rationale

One artifact runs everywhere. Stdio MCP works inside a container. Replay needs no AWS access. Fargate shows AWS integration without leaving the $500 budget.

### Consequences

- The Fargate runner is delivered in R2 if time allows. Otherwise it moves to FUTURE-WORK (#6, batch trials on AWS).
- IaC must cover the bucket, IAM roles, ECR repository, ECS cluster and task definition.
- Latency in remote runs includes Fargate network paths, so the run manifest records the executor.

---

## DD-007 - Decision - LLMs allowed for summaries (with checked citations) and as an optional second evaluator

| Field           | Value                          |
| --------------- | ------------------------------ |
| Date            | 2026-11-03                     |
| Cycle / Feature | F3 Summary, F4 Scoring, D2     |
| Status          | accepted                       |
| Supersedes      | —                              |

### Context

D9 made process the main judgment. D16 added output as a metric. D2 needs a swappable trace evaluator, which means at least two evaluators to swap. F3 requires every summary claim to map to a trace event. OQ12 recommends deterministic output scoring.

### Options considered

1. Deterministic only - exact replay, free / stiff summaries, only one kind of evaluator.
2. Deterministic scoring + LLM summary with event-ID citations checked by code - readable, F3 holds / summary costs tokens.
3. **Option 2 plus an optional LLM process evaluator (planning and recovery against a written rubric), reported separately, re-scored k times for agreement** - real second evaluator, rates planning quality / noisy, adds cost.
4. LLM judge for everything - fastest / contradicts D9/D16, can't be checked.
5. Deterministic workflow, LLM judge for output only - / conflicts with OQ12.

### Decision

Workflow and output scores are deterministic. An LLM writes the summary, and code drops any claim that lacks a valid trace-event citation. An optional LLM process evaluator scores planning and recovery, reported separately and re-scored k times to measure agreement.

### Rationale

This gives D2/J3 two genuinely different evaluators to swap, keeps the main judgment checkable, and meets F3's traceability rule.

### Consequences

- Replay (J2) matches exactly for deterministic scores. LLM evaluator variance is reported, not hidden.
- An LLM score is never blended into the deterministic workflow or output scores.
- Summary and LLM evaluation cost tokens. The budget guard and cost reports must include them as evaluation cost, kept separate from agent cost.

---

## DD-008 - Decision - "Tooling" covers MCP tool sets, tracers and evaluators

| Field           | Value                          |
| --------------- | ------------------------------ |
| Date            | 2026-11-03                     |
| Cycle / Feature | F9 Comparison (D3, OQ15)       |
| Status          | accepted                       |
| Supersedes      | —                              |

### Context

D3: compare harnesses, agents and tooling. OQ15 asked what tooling means. The architect warned that putting the tracer and evaluator on the same axis as the agent's tools mixes the measuring instrument with the thing measured.

### Options considered

1. MCP tool sets only - clean comparison axes / tracer and evaluator never compared.
2. Tool sets plus tool exposure strategy - interesting / adds a variable.
3. **Tool sets plus tracer plus evaluator** - compares every swappable component / mixes measurement with what is measured.
4. Tool sets plus MCP transport - / mostly measures infrastructure.
5. Everything except model and harness, including prompts - / too many variables for the trials we can afford.

### Decision

Comparisons cover three kinds of tooling: MCP tool sets, tracers, and trace evaluators.

### Rationale

The team wants every swappable component (SC5) to be comparable, not just swappable.

### Consequences

- The comparison design has to keep the axes apart. Only tool sets change agent behaviour. A tracer comparison measures capture overhead and fidelity. An evaluator comparison re-scores the same stored runs. How exactly is a round-2 decision.
- More comparison kinds to report, so the comparison report needs a per-axis layout.

---

## DD-009 - Decision - Second harness is a plain Bedrock Converse tool loop

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F1 Harness, F6 (OQ4)      |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

D7 makes Strands Agents the primary harness. S10/SC8 need at least two harnesses to compare.

### Options considered

1. **Plain Bedrock Converse tool loop (about 150 lines, ours)** - biggest contrast with Strands, full control of trace hooks / we maintain it.
2. LangGraph ReAct agent - credible comparison / heavy dependency, tracing has to be mapped.
3. Bedrock Agents (managed) - AWS-native / no native MCP, needs Lambda action groups.
4. PydanticAI or OpenAI Agents SDK on Bedrock - modern / Bedrock and MCP support vary by version.
5. Strands on AgentCore Runtime - AWS showcase / a runtime comparison, not a harness comparison.

### Decision

The second harness is a plain Bedrock Converse tool loop that we write ourselves.

### Rationale

Framework vs no framework is the clearest harness contrast, and it is the lowest-risk build.

### Consequences

- The Converse loop emits our trace events directly. Strands needs an adapter from its hooks or callbacks.
- LangGraph is a candidate third harness (stretch).

---

## DD-010 - Decision - us-west-2; Nova Pro baseline vs a Claude Sonnet-class variant; Nova Lite for development

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | F1 Model, F9             |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

NAIP and the LGND embeddings are both in us-west-2. The comparison needs a gap between models that is large enough to show up with few trials.

### Options considered

1. Nova Lite vs Nova Pro - cheap / small differences, hard to prove they're real.
2. **Nova Pro baseline vs Claude Sonnet-class variant, Nova Lite for development** - two vendors, likely a clear gap, cheap iteration / Sonnet costs more per token.
3. Claude Haiku vs Sonnet - strong tool use / one vendor.
4. Nova Lite vs Claude Haiku - cheapest pair across vendors / both weak at long tool chains.
5. Three models - richer / fewer trials per model under the same budget.
6. Llama or Mistral vs Nova - open-weight story / uneven tool-use reliability on Converse.

### Decision

The sandbox runs in us-west-2, compares Nova Pro (baseline) with a Claude Sonnet-class model (variant), and uses Nova Lite for development runs.

### Rationale

Two vendors give a contrast likely to be statistically visible, and Nova Lite keeps iteration cheap.

### Consequences

- Exact model IDs are confirmed against sandbox model access on Day 1 and stored only in config.
- Sonnet trials dominate agent cost, so the pre-flight estimate (DD-013) matters.

---

## DD-011 - Decision - Our own versioned TraceEvent schema is canonical; OpenTelemetry is an exporter

| Field           | Value                          |
| --------------- | ------------------------------ |
| Date            | 2026-11-03                     |
| Cycle / Feature | F2 Trace capture, F6, F7       |
| Status          | accepted                       |
| Supersedes      | Refines D8                     |

### Context

D8: OpenTelemetry → local JSONL by default, CloudWatch/X-Ray as the second backend. J3 step 2 needs the trace schema to stay the same when the tracer changes. Two different harnesses have to produce the same trace. The OTel GenAI semantic conventions are still marked experimental.

### Options considered

1. OTel spans with GenAI conventions as *the* format - standard, X-Ray-native / unstable conventions, Converse loop emits nothing by default, replay from spans is clumsy.
2. **Own versioned `TraceEvent` schema (Pydantic, JSONL) as source of truth; OTel/GenAI mapping as one exporter** - harness-neutral, stable replay, J3 holds by construction / we maintain the mapping.
3. OpenInference conventions - agent-focused / extra ecosystem.
4. Strands native traces - free for Strands / the Converse loop can't produce them.
5. Langfuse format - ships a UI / external service, off-AWS.

### Decision

A versioned `TraceEvent` schema that we own is the canonical trace format. The JSONL and OpenTelemetry (CloudWatch/X-Ray) tracers are backends that serialise it.

### Rationale

Replay, re-scoring and the tracer swap all depend on a schema that doesn't change when the harness or tracer changes.

### Consequences

- D8 still holds (OTel is used), but OTel is not the source of truth.
- The schema is a frozen cross-team contract (DD-005). Changes bump `schema_version`, and the reader must accept older versions.

---

## DD-012 - Decision - Error attribution with recovery credit and automatic infra retries

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F2, F4, F10 (OQ8, D12)    |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

D12: all errors are logged. The question is which errors lower the agent's score, and how infra noise is kept out of the statistics.

### Options considered

1. OQ8 default: agent and tool errors count, infra excluded, budget stop = failure - simple / no credit for recovery.
2. Only agent errors count - / hides poor tool choice.
3. Everything counts - / Bedrock throttling pollutes the comparison.
4. Infra failures retried automatically up to n times, flagged, excluded from stats - N stays honest / longer evals.
5. Option 1 plus recovery credit - matches F4's error-recovery signal / more scoring logic.
6. **Options 5 + 4 together** - fair, and the stats stay clean / most logic.

### Decision

Every error is tagged by source (agent, tool, budget, infra). Agent and tool errors count against the agent, but a tool error costs less if the agent recovers from it. Budget stops count as failures. Runs that fail on infra errors are retried automatically up to a configurable limit, flagged, and excluded from the statistics.

### Rationale

This keeps the score fair to the agent and keeps sandbox noise out of the comparison.

### Consequences

- Recovery has to be detectable from the trace (for example, a later successful call to the same tool or an equivalent one). The exact rule goes into the workflow spec.
- Reports show how many attempts were excluded for infra reasons, per configuration.

---

## DD-013 - Decision - Budget guard: four per-run limits, an eval-level $ cap, and a pre-flight cost estimate

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | F11 (D6, OQ7)            |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

D6: the budget guard is optional and can be set per run or per eval. The sandbox has a $500 cap.

### Options considered

1. OQ7 default: four per-run limits (steps, tokens, $, wall-clock), hard stop, `budget_exceeded`, counted as failure - meets SC10 / no eval-level protection.
2. Option 1 plus an eval-level total $ cap - protects the $500 / —.
3. Soft limits that warn and continue - / fails J7.
4. Only $ and wall-clock - fewer knobs / no protection against loops.
5. **Option 2 plus a pre-flight cost estimate before an eval launches** - tells you the cost before you spend it / needs pricing data and per-task token history.

### Decision

The budget guard has four optional per-run limits, an optional eval-level total $ cap that stops new runs from launching, and a pre-flight cost estimate shown before an eval starts.

### Rationale

With Sonnet in the matrix and NAIP being Requester-Pays, knowing the cost before launch protects the shared $500 cap.

### Consequences

- The pre-flight estimate is in MVP scope (R2), not stretch.
- The estimate is only as good as its pricing source and token history (round-2 decision). The first eval on a new task template uses a default assumption, and the report says so.

---

## DD-014 - Decision - Synthetic tasks are templates instantiated per area of interest

| Field           | Value                           |
| --------------- | ------------------------------- |
| Date            | 2026-11-03                      |
| Cycle / Feature | Synthetic tasks (D13, D19, OQ10) |
| Status          | accepted                        |
| Supersedes      | —                               |

### Context

No ADB inputs are coming (D13), and the team generates the tasks (D19). OQ10 proposed five hand-written tasks. Statistics (D1) improve with more task instances. USPVDB was unreachable on 2026-11-03.

### Options considered

1. OQ10 default: five fixed tasks - covers three difficulty levels / USPVDB blocked, few instances.
2. Three tasks - low risk / weak difficulty spread, drops D4.
3. Five tasks with Global Renewables Watch as the solar key - removes a blocked dependency / still few instances.
4. **Task templates parameterised by area of interest (AOI), e.g. 5 templates × several counties** - many instances, better statistics / needs an answer key per AOI.
5. Ten or more hand-written tasks - breadth / too many references to write in 2 days.

### Decision

Synthetic tasks are task templates, each instantiated over a set of areas of interest, and every instance gets its own task reference.

### Rationale

More task instances let the statistics separate configurations, which is what D1/SC9 asks for.

### Consequences

- Answer keys have to be built per AOI, preferably by scripts from public data. How, and which AOIs, are round-2 decisions.
- The statistics have to account for variation between task instances, not just between repeated runs.
- The run count grows (templates × AOIs × configurations × N), so DD-013's pre-flight estimate is needed.

---

## DD-015 - Decision - Embeddings via our own open MCP server; LGND Geo MCP as an optional tool set

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | F1 Tooling (D4)          |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

D4: pre-computed LGND embeddings exposed to the agent as a tool. The LGND Geo MCP is commercial, and whitelist access is unconfirmed. Facts checked on 2026-11-03: the LGND embeddings are Clay v1.5 embeddings of **Sentinel-2 L2A** chips (Major TOM grid), not of NAIP. They are published as GeoParquet 1.1, hive-partitioned by model version / collection / chip size / dims / geohash / year / month. The bucket is `s3://us-west-2.opendata.source.coop/clay/lgnd-embeddings/` (public, us-west-2). The available configurations are 1280 m chips with 256 dims, and 2560 m chips with 1024 dims. A partition file is about 20 MB. License: CC BY 4.0. They can be queried with DuckDB.

### Options considered

1. Our own small MCP server over a pre-staged subset - open, no whitelist / we build and test it.
2. LGND Geo MCP - real product / whitelist unconfirmed, not open.
3. **Option 1 as default, option 2 as an optional tool set if the whitelist arrives** - resilient / two paths.
4. Drop embeddings - simpler / breaks D4.
5. Option 1 backed by a vector store (S3 Vectors or OpenSearch) - scales, more AWS / extra infrastructure and cost.

### Decision

We build an open `clay-embeddings` MCP server over a pre-staged subset of the LGND monthly-aggregated embeddings, and add the LGND Geo MCP as an optional tool set if access arrives.

### Rationale

This keeps D4 working without depending on a commercial whitelist, and it fits Clay's openness rule.

### Consequences

- The similar-places template is limited to the staged geohash partitions and months.
- Embeddings are Sentinel-2-based, so "similar places" is defined at 1280 m chip scale, not at NAIP resolution.
- Attribution (CC BY 4.0) has to appear in the README and in reports that use embedding results.

---

## DD-016 - Decision - Static per-run reports in the MVP; TypeScript UI in R3

| Field           | Value                 |
| --------------- | --------------------- |
| Date            | 2026-11-03            |
| Cycle / Feature | F5 Report, F8 UI (D11, S8) |
| Status          | accepted              |
| Supersedes      | —                     |

### Context

D11 defers the UI but requires every parameter to be exposed for it. S8 requires TypeScript or JavaScript. "Design" is a quarter of the judging score.

### Options considered

1. Backend only, UI as an API contract - / weak on Design.
2. Wireframe's three screens plus a Comparison screen as a TS app in R3 - full F8 / only after the backend.
3. Generated static report per run (Markdown + HTML), no app - cheap, works offline / no launch screen.
4. **Option 3 in the MVP, option 2 in R3** - viewable reports from R1, UI built on the API / two presentation paths.
5. Streamlit - fast / breaks S8.

### Decision

The MVP generates static reports per run and per comparison. A TypeScript UI with New Run, Runs, Report and Comparison screens comes in R3, built only on the public API.

### Rationale

Reports are needed from R1 on. A UI that only uses the API proves SC11.

### Consequences

- The report renderer and the UI both read the same report JSON, so the report schema is a frozen contract.
- The UI can't use any backend feature the API doesn't expose.

---

## DD-017 - Decision - Keep the MIT license

| Field           | Value                 |
| --------------- | --------------------- |
| Date            | 2026-11-03            |
| Cycle / Feature | Open source (05, 06)  |
| Status          | accepted              |
| Supersedes      | —                     |

### Context

The repo LICENSE is MIT. `docs/05` and `docs/06` record that Clay's doc requires Apache-2.0 and leave it as a team decision.

### Options considered

1. Switch to Apache-2.0 now - meets Clay's requirement / —.
2. **Keep MIT** - no change, permissive / does not meet Clay's stated requirement.
3. Dual license - / confusing.
4. Apache-2.0 for code, CC-BY-4.0 for docs - precise / more to explain.
5. Switch just before submission - / easy to forget.

### Decision

The repository keeps the MIT license.

### Rationale

Team lead's decision.

### Consequences

- This departs from Clay's stated Apache-2.0 requirement. The DoD item in `docs/05` can't be ticked as written. How to handle that is a round-2 question.
- Third-party data licenses still apply to the data (for example, CC BY 4.0 on the LGND embeddings, ODbL on OSM), whatever the code license.

---

## DD-018 - Decision - Core vocabulary: Run, Assessment, Eval, Report, Task reference

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Domain model              |
| Status          | accepted                  |
| Supersedes      | Refines the `docs/SCOPE.md` glossary ("Trial", "rubric") |

### Context

The SCOPE glossary uses *Trial*. The wireframe uses *Run* and *rubric*. Re-scoring a stored trace with a new evaluator had no name, and a replay was ambiguous: did it create a new run or not?

### Options considered

1. **Run / Assessment / Eval / Report / Task reference; retire "Trial" (becomes `trial_index`) and "rubric"** - one term per concept, replay is unambiguous / renames a glossary term.
2. Same, keep Trial, retire Run - / the wireframe and common usage say Run.
3. Run = any execution, Trial = a run counted in stats - / two words for nearly the same thing.
4. Option 1 with "Score" instead of "Assessment" - / "score" is also a number inside an assessment.
5. Keep current wording and fix the wireframe - / re-scoring stays unnamed.

### Decision

A **Run** is one agent execution of one configuration on one task instance, and its trace is immutable. An **Assessment** is one evaluator version applied to one run, and a run can have many. An **Eval** is a spec of task instances × configurations × N runs. A **Report** is the rendered view of assessments. A **Task reference** is a workflow spec plus an output reference. "Trial" and "rubric" are retired.

### Rationale

Replay and hot-swapping the evaluator create a new Assessment, never a new Run. That keeps "runs are immutable" true and makes provenance simple.

### Consequences

- The srs.md glossary defines these terms and overrides the SCOPE glossary where they differ.
- The wireframe's "rubric" label becomes "task reference" in the R3 UI.

---

## DD-019 - Decision - Five component workstreams, with task authoring in WS2

| Field           | Value                          |
| --------------- | ------------------------------ |
| Date            | 2026-11-03                     |
| Cycle / Feature | Team and delivery model        |
| Status          | superseded (by DD-044)         |
| Supersedes      | —                              |

### Context

Five developers each build in isolation and merge at release gates (DD-005). The split has to minimise shared files and give every interface one owner.

### Options considered

1. By component (harness, tools, trace, evaluation, platform) - clear ownership / evaluation workstream is the heaviest.
2. By feature F1–F12 - easy to assign / several people edit the same modules.
3. By release slice - everyone sees the whole system / ownership unclear, contracts drift.
4. **By component, with evaluation trimmed and task templates and answer keys moved into the tools workstream** - balanced load, task authoring has an owner / tools workstream is broad.
5. A contracts owner plus four builders - strict contracts / one person becomes a bottleneck.

### Decision

The work is split into five component workstreams, with the shared `contracts/` package written jointly in the first hour of R0 and then frozen:

| WS | Name | Owns |
| -- | ---- | ---- |
| WS1 | Agent runtime | Harness interface, Strands harness, Converse-loop harness, Bedrock model adapter, runtime budget guard and loop guard, price table and refresh script |
| WS2 | Tools and tasks | MCP tool-set launcher, tool sets T0/T1, `clay-embeddings` MCP server, task templates T1–T5, AOI list, answer-key scripts, task-reference versioning |
| WS3 | Trace and store | `TraceEvent` schema, JSONL and OpenTelemetry tracers, tee tracer, run store (local + S3), DuckDB queries, replay loader, summarizer with citation check, sample traces |
| WS4 | Evaluation and statistics | Deterministic workflow evaluator, output-metric evaluators, LLM process evaluator, planted-trace validation, statistics, comparison analysis, pre-flight cost estimate |
| WS5 | Platform and presentation | Eval spec schema, component registry, service layer, executors (local, Fargate) and infra retries, CLI, FastAPI, report renderer, CDK stack, Dockerfile, CI, README, R3 UI |

### Rationale

Each interface in `contracts/` has exactly one owning workstream. Option 4 as proposed left the summarizer and the report renderer unassigned. The architect assigned the summarizer to WS3 (it reads traces and cites trace events) and the report renderer to WS5 (presentation, together with the R3 UI).

### Consequences

- architecture.md lists the deliverables per workstream per release, which is the input for `plan.md`.
- WS2 is broad. If it slips, the `clay-embeddings` server (T4) is the first thing to drop to R2 or FUTURE-WORK.

---

## DD-020 - Decision - One Python package with subpackages and enforced import boundaries

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | Repository layout        |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

Five isolated workstreams need boundaries that stop them from importing each other's internals, without packaging overhead.

### Options considered

1. One package `claysandbox/` with a subpackage per workstream and a shared `contracts/` - simple, one lockfile / boundaries by convention only.
2. uv workspace with 5–6 packages - hard boundaries / packaging overhead.
3. Polyrepo - full isolation / integration hell.
4. **Option 1 plus an import-boundary check in CI (import-linter)** - isolation enforced cheaply / one more CI tool.
5. Flat scripts - fastest start / can't swap or test components alone.

### Decision

The code is one Python package, `claysandbox`, with one subpackage per component and a `contracts` subpackage, and import-linter in CI enforces that components only depend on `contracts` (plus the explicit exceptions in architecture.md).

### Rationale

Boundaries are enforced at merge time for the cost of one config file.

### Consequences

- `mcp_servers/clay_embeddings/` and `ui/` are sibling top-level folders, outside the Python package.
- A component that needs another component's behaviour goes through a contract interface, or through the service layer.

---

## DD-021 - Decision - Components swap through a name-keyed registry

| Field           | Value              |
| --------------- | ------------------ |
| Date            | 2026-11-03         |
| Cycle / Feature | F6 (SC5), F12 (SC11) |
| Status          | accepted           |
| Supersedes      | —                  |

### Context

SC5: swap model, harness, tracer and evaluator with no code changes. SC11: every option must be visible in one schema.

### Options considered

1. **Registry keyed by name, filled by decorators** - simple, typed, valid names can be listed in the schema / new plugins must be imported.
2. Python entry points - third-party plugins / packaging ceremony.
3. Dotted import paths in config - flexible / unsafe, can't be listed in the schema.
4. Hydra/OmegaConf - powerful composition / heavy, duplicates Pydantic.
5. Registry seeded from entry points - extensible later / more code.

### Decision

Every swappable component registers itself under a name in a typed registry, and the eval spec selects components by name.

### Rationale

The registry is the one place that knows which names are valid, so the API can publish them (J9).

### Consequences

- `GET /registry` lists every registered component with its parameter schema.
- Entry-point plugins go to FUTURE-WORK.

---

## DD-022 - Decision - File-based run store, mirrored to S3, queried with DuckDB

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F5, F7, F10 (OQ9)         |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

Runs, traces and assessments must survive the sandbox wipe (sample runs committed to git), replay with no AWS credentials (J8), and be listed and aggregated for statistics. DuckDB is already a dependency for the embeddings tool.

### Options considered

1. Files only - git-committable, readable / slow listing.
2. **Files as source of truth, same layout mirrored to S3, DuckDB queries JSON/JSONL directly** - no index to keep in sync, same layout everywhere / DuckDB over S3 needs credentials.
3. Files plus a SQLite index - fast queries / index drift.
4. DynamoDB + S3 - AWS-native / needs AWS locally, breaks J8.
5. Postgres/RDS - full SQL / cost and ops.

### Decision

Each run is a folder of JSON/JSONL files. The local folder is the default store, S3 is an optional mirror with the same layout, and lists and statistics come from DuckDB reading those files directly.

### Rationale

One layout works offline, in git, and in S3, with no index to drift.

### Consequences

- Committed sample runs are just folders under `samples/runs/`.
- Queries over thousands of runs are slower than a database. That's acceptable at hackathon scale (hundreds of runs).

---

## DD-023 - Decision - One service layer behind CLI and API, with pluggable executors

| Field           | Value                  |
| --------------- | ---------------------- |
| Date            | 2026-11-03             |
| Cycle / Feature | F12, Execution (DD-006) |
| Status          | accepted               |
| Supersedes      | —                      |

### Context

Evals take minutes to hours. The CLI and the API must behave the same (SC11). DD-006 needs runs to execute locally or on ECS Fargate.

### Options considered

1. FastAPI runs evals inside the request - trivial / requests time out.
2. **One service layer for CLI and API; `POST /evals` returns an id; an Executor (`local` process pool or `fargate` ECS RunTask) runs the runs; status comes from the run store** - one code path, executor is swappable / status is polled.
3. Option 2 plus SQS - durable / more infrastructure.
4. Celery + Redis - mature / not AWS-native, extra service.
5. Step Functions - visible AWS / local runs need a different path.

### Decision

The CLI and FastAPI both call one service layer. Evals run asynchronously through a registered Executor (`local` by default, `fargate` optional), and status is read from the run store.

### Rationale

One code path, and the executor becomes one more swappable component.

### Consequences

- Infra retries (DD-012) live in the executor, so they behave the same locally and on Fargate.
- A server-sent-events status stream is added in R3 for the UI.

---

## DD-024 - Decision - AWS CDK in Python for infrastructure

| Field           | Value              |
| --------------- | ------------------ |
| Date            | 2026-11-03         |
| Cycle / Feature | Infrastructure as code |
| Status          | accepted           |
| Supersedes      | —                  |

### Context

The event asks for infrastructure as code where it applies, and the sandbox is wiped afterwards. DD-006 needs S3, IAM, ECR, ECS and CloudWatch resources.

### Options considered

1. **AWS CDK in Python** - same language as the code, L2 constructs for ECS/ECR/S3/IAM / needs a bootstrap step.
2. CDK in TypeScript - matches the UI / second IaC toolchain.
3. Terraform - portable / state file, less AWS-native for judging.
4. Raw CloudFormation - no tooling / verbose.
5. SAM - good for Lambda / we aren't Lambda-based.

### Decision

All AWS resources are defined in one CDK app written in Python under `infra/`.

### Rationale

One language for the whole backend, and anyone can redeploy into a fresh account.

### Consequences

- The README documents `cdk bootstrap` and `cdk deploy`, and the stack must deploy into an empty account.
- AWS resources are optional: local runs and replay need no stack.

---

## DD-025 - Decision - Task-instance-aware statistics with paired comparisons, N=3

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F10 (D1, OQ2)             |
| Status          | accepted                  |
| Supersedes      | OQ2 default N=5           |

### Context

D1: show statistically, verifiably and truthfully that the sandbox can evaluate agents. DD-014 creates many task instances (templates × AOIs), so runs are grouped by instance and aren't independent.

### Options considered

1. OQ2 default (Wilson, bootstrap, permutation, N=5) - standard / treats runs as independent, CIs too narrow.
2. **Option 1, but bootstrap resamples whole task instances, A-vs-B is paired by task instance, effect size plus p-value, Holm correction for more than 2 comparisons, N=3** - accounts for task variation, paired tests need fewer runs / slightly more code.
3. Bayesian beta-binomial - clear posteriors / harder to explain.
4. Mixed-effects models - rigorous / new dependency, needs more data.
5. Mean ± SD - simple / fails SC9.

### Decision

Success rates get Wilson 95% CIs. Means get 95% CIs from a bootstrap over task instances. A-vs-B comparisons are paired by task instance (sign-flip permutation test on per-instance differences, with mean paired difference and its CI as the effect size). Holm correction applies when there are more than two comparisons. The default is N=3 runs per configuration per task instance, settable in the spec.

### Rationale

More task instances with fewer repeats gives better coverage per dollar, and pairing removes task difficulty from the comparison.

### Consequences

- Every configuration in a comparison must run on the same task instances.
- The report states plainly when CIs are wide.
- numpy and scipy only.

---

## DD-026 - Decision - One-factor agent comparisons; tracers and evaluators compared without re-running agents

| Field           | Value                       |
| --------------- | --------------------------- |
| Date            | 2026-11-03                  |
| Cycle / Feature | F9 (D3, OQ4, DD-008)        |
| Status          | accepted                    |
| Supersedes      | —                           |

### Context

DD-008 put tool sets, tracers and evaluators on the comparison list, alongside model and harness. Comparing measurement instruments through fresh agent runs would mix agent randomness into the result.

### Options considered

1. **Agent axes (model, harness, tool set): baseline plus one-change variants on the same task instances. Evaluators: re-score the same stored runs. Tracers: record the same runs with both at once** - clean experiments, cheap / two comparison mechanisms.
2. Full factorial over five axes - / 32 configurations, unaffordable.
3. Option 1 but tracers compared through separate agent runs - / agent noise mixed into tracer differences.
4. Only agent axes, measurement axes just listed - / weak reading of DD-008.
5. Option 1 plus a 2×2 model × harness interaction - more insight / about 2× agent cost.

### Decision

The comparison uses a baseline (Nova Pro + Strands + tool set T1) and three one-change variants (Sonnet-class model, Converse-loop harness, tool set T0). Evaluators are compared by re-scoring the same stored runs (agreement, plus separation of planted good and bad traces). Tracers are compared by recording the same runs through both at once with a tee tracer (capture overhead in ms, events lost, schema round-trip fidelity).

### Rationale

Each comparison changes one thing, and measurement instruments are judged on identical input.

### Consequences

- Four agent configurations. Their cost drives the budget (see DD-031).
- WS3 builds a tee tracer. WS4 builds the evaluator-agreement and tracer-fidelity analyses.
- The 2×2 interaction goes to stretch.

---

## DD-027 - Decision - Nova Lite writes summaries; an out-of-family model is the LLM evaluator

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | F3, F4 (DD-007)          |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

DD-007 allows an LLM summary (with code-checked citations) and an optional LLM process evaluator. The models under test are Nova Pro and a Claude Sonnet-class model (DD-010). LLM judges tend to favour outputs from their own family.

### Options considered

1. Sonnet-class for both - strongest / self-preference bias, costly.
2. Nova Pro for both - cheap / same bias for Nova runs.
3. **Summary: Nova Lite. Evaluator: a model family not under test (Llama- or Mistral-class), temperature 0, k=3** - no self-preference bias, cheap / weaker judge, agreement must be measured.
4. Same model as the agent in each run - simple / bias on every run.
5. Configurable, no default - flexible / pushes the decision off.

### Decision

Summaries use Nova Lite. The LLM process evaluator uses a Bedrock model from a family not under test, at temperature 0, scoring each trace k=3 times. Both are configurable in the spec.

### Rationale

Summary claims are checked by code, so a cheap model is enough. The judge must not share a family with any agent under test.

### Consequences

- Exact model IDs are confirmed against sandbox model access on Day 1.
- LLM evaluator agreement is reported with every LLM assessment.

---

## DD-028 - Decision - Expected-workflow spec with argument constraints and a recovery rule

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F4 (OQ1, DD-012)          |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

The deterministic workflow evaluator needs a spec to check traces against. Geospatial agents often call the right tool with the wrong area, year or collection.

### Options considered

1. OQ1 default: required/forbidden tools, ordering rules, step limit, done condition - simple / misses wrong arguments.
2. **Option 1 plus argument constraints plus the DD-012 recovery rule** - catches "right tool, wrong call" / more spec per template.
3. Golden trajectory with edit distance - intuitive / punishes valid alternative paths.
4. Final state only - robust / ignores process, contradicts D9.
5. Temporal-logic rules - expressive / over-engineered.

### Decision

Each task template declares, in YAML, its required and forbidden tools, ordering rules, argument constraints, step limit, done condition and recovery rule. AOI values are filled in when the template is instantiated.

### Rationale

Argument constraints catch the most common geospatial mistakes, and the rest is cheap to check.

### Consequences

- Rules refer to tools by capability (e.g. "a catalog search tool"), so a rule still applies when the tool set changes. architecture.md defines how capabilities map to concrete tools.
- The spec schema is a frozen contract owned by WS2 and read by WS4.

---

## DD-029 - Decision - Answer keys generated by scripts, with one human spot-check per template

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Task references (DD-014)  |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

Templated tasks need an output reference for every AOI. Provenance is a Clay principle.

### Options considered

1. Scripts from public data, versioned and committed - reproducible, scales / script bugs become key bugs.
2. Hand-curated - trustworthy / doesn't scale.
3. LLM-generated, checked by a human - fast / circular, weak provenance.
4. **Option 1 plus a human spot-check of one instance per template, recorded in the reference metadata** - reproducible and checked / some human time.
5. Taken from the best agent runs - / circular, invalid.

### Decision

Answer keys are generated by committed scripts from public data, versioned by content hash, and a human spot-checks one instance per template and records who checked it and when in the reference metadata.

### Rationale

Anyone can regenerate and audit the keys, and the spot-check catches script bugs.

### Consequences

- T2 (open datasets for an AOI) can't be fully scripted, because dataset coverage isn't structured in the registry. Its script produces a candidate list and the Task Author confirms it. The metadata records this as `method: script+curated`.
- Regenerating a key creates a new task-reference version. Old assessments keep the version they were scored against.

---

## DD-030 - Decision - Five task templates, staged across R1 and R2

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Synthetic tasks (DD-014)  |
| Status          | accepted                  |
| Supersedes      | OQ10 task list            |

### Context

DD-014 makes tasks templates. Two of the five candidate templates depend on riskier inputs (Global Renewables Watch clipping, staged embeddings).

### Options considered

1. All five at once - covers D4 and J4 / all the risk lands at once.
2. T1, T2, T5 only - lowest risk / drops D4.
3. T1–T4 - / no deliberately ambiguous task for J4.
4. All five plus a multi-step T6 - closest to ADB / hardest to build.
5. **T1, T2, T5 in R1; T3, T4 added in R2** - staged risk, ends with all five.

### Decision

The task library has five templates: T1 NAIP imagery for an AOI and year, T2 open datasets covering an AOI, T3 candidate solar sites (Global Renewables Watch key), T4 places similar to a given place (embeddings), and T5 a deliberately ambiguous request. T1, T2 and T5 ship in R1, and T3 and T4 in R2.

### Rationale

R1 gets a working scored loop on low-risk tasks. R2 completes the set.

### Consequences

- T4's metric measures faithful tool use (did the agent query the right place and report the tool's results), not the quality of the embeddings.
- T6 (multi-step dataset build) goes to FUTURE-WORK.

---

## DD-031 - Decision - Six US counties: four with solar sites, two without

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Synthetic tasks (DD-014)  |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

NAIP covers the US only. T3 needs areas with and without solar. T4 needs staged embedding partitions.

### Options considered

1. 3 counties (15 instances) - cheap / weak statistics.
2. **6 counties, 4 with solar (e.g. in CA, AZ, TX, NC) and 2 without (30 instances)** - balanced, includes negative controls.
3. 10 counties (50 instances) - better statistics / about 2× cost.
4. 6 counties plus 2 non-US areas - tests "data doesn't exist" / more references.
5. Random sampling - / unpredictable keys.

### Decision

The AOI set is six US counties, four with known solar sites and two without, chosen by the Task Author.

### Rationale

30 task instances × 4 configurations × N=3 = 360 agent runs. At a rough $0.10–0.40 per run, that's about $36–144, within the $500 cap. Day-1 measurements replace this guess.

### Consequences

- Counties without solar are negative controls for T3 (the right answer is an empty list).
- Non-US AOIs go to stretch.

---

## DD-032 - Decision - Static, dated price table with a refresh script

| Field           | Value                   |
| --------------- | ----------------------- |
| Date            | 2026-11-03              |
| Cycle / Feature | F2 cost, F11 (DD-013)   |
| Status          | accepted                |
| Supersedes      | —                       |

### Context

Cost is a first-class metric (D5), and the pre-flight estimate (DD-013) needs prices before any run. Replay must work offline.

### Options considered

1. Static dated YAML table - offline, versioned / goes stale.
2. AWS Price List API at runtime - current / needs AWS, breaks offline replay.
3. Cost Explorer - real billed cost / delayed by hours, can't attribute to a run.
4. **Option 1 plus a refresh script that uses the Price List API; table version and date recorded in every manifest** - offline and refreshable / extra script.
5. Tokens only - simple / fails D5.

### Decision

Run cost is computed from a versioned price table in the repo, refreshed by a script that uses the AWS Price List API. The table version is recorded in each run manifest. Requester-Pays S3 reads are counted as an estimated $ per GB and labelled as an estimate.

### Rationale

Works offline, cost can be attributed to each step, and anyone can audit it.

### Consequences

- Reported $ is an estimate, not the bill. Reports say so.
- The pre-flight estimate is price table × median tokens per template from past runs × number of runs. With no history, it uses a default token count and labels the result as a guess.

---

## DD-033 - Decision - Shortlist: stac-mcp and openstreetmap-mcp-server; tool sets T0 and T1

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F1 Tooling                |
| Status          | accepted (Clay has final say) |
| Supersedes      | —                         |

### Context

F1 needs RODA plus 1–2 shortlist servers from Clay's catalog. The tool-set comparison (DD-026) needs at least two tool sets.

### Options considered

1. **stac-mcp + openstreetmap-mcp-server. T0 = RODA only; T1 = RODA + stac + OSM + clay-embeddings** - NAIP through STAC, geocoding for AOIs.
2. earthdata-mcp + GeoLens - NASA focus / earthdata may need a login.
3. gis-mcp (98 tools) - tests tool overload / too many tools for a baseline.
4. Overture Maps + stac-mcp - strong vector data / no geocoding.
5. Option 1 plus gis-mcp as a third set T2 - richer comparison / more runs.

### Decision

The shortlist is stac-mcp and openstreetmap-mcp-server. Tool set T0 is RODA only, and T1 is RODA + stac-mcp + openstreetmap-mcp-server + clay-embeddings. Every server version is pinned.

### Rationale

These cover the five templates: dataset discovery, NAIP search, geocoding AOIs, and embeddings.

### Consequences

- None of these servers is install-tested yet. WS2's first task is a smoke test of each.
- T3 and T4 can't be solved well with T0. That's intended, and it gives the tool-set comparison a real effect to detect.
- If Clay names other shortlist servers, a new decision supersedes this one.

---

## DD-034 - Decision - Scrubbed MCP environments, pinned versions, least-privilege IAM, localhost API

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Security (cross-cutting)  |
| Status          | accepted                  |
| Supersedes      | —                         |

### Context

Community MCP servers are third-party code running next to our AWS credentials.

### Options considered

1. Full environment inherited - / credentials leak to third-party code.
2. Scrubbed environment, AWS credentials only for servers that need them - limits damage.
3. Each MCP server in its own container - strong isolation / heavy.
4. **Option 2 plus pinned versions and hashes, a least-privilege IAM role per executor, the API bound to localhost with no auth in MVP, no secrets in the repo** - practical, reproducible.
5. Option 4 plus a Fargate egress allowlist - strongest / time-consuming.

### Decision

MCP subprocesses start with a scrubbed environment and only get AWS credentials when their tool-set entry says so. Server versions and hashes are pinned. Each executor has a least-privilege IAM role. The API binds to localhost with no auth in the MVP. No secrets go in the repo.

### Rationale

Covers the realistic risks within two days.

### Consequences

- Exposing the API beyond localhost (for example, the UI hosted remotely) needs an auth decision first.
- Egress allowlisting goes to FUTURE-WORK.

---

## DD-035 - Decision - Unit tests, replay journey tests in CI, and a conformance suite per interface

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | Quality (cross-cutting)  |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

Five developers merge independently (DD-005). The sandbox account is wiped after the event, so CI can't depend on it.

### Options considered

1. Manual only - / breaks at merge time.
2. Unit tests only - / misses integration.
3. Unit tests plus replay journey tests (J2, J3 evaluator swap, J8) in GitHub Actions, no AWS - proves SC6 and SC12.
4. Option 3 plus live tests through OIDC - / dies with the sandbox.
5. **Option 3 plus a conformance suite per interface in `contracts/`; live journeys (J1, J4–J7) run manually from a script** - each developer proves their part alone.

### Decision

CI runs unit tests, replay-based journey tests on committed sample runs with no AWS access, import-boundary checks, and a conformance suite that every harness, tracer, evaluator, executor and run store must pass. Live journeys run from a script against the sandbox.

### Rationale

A developer can show their component works before merging, without anyone else's code.

### Consequences

- The conformance suites are part of the R0 contracts work.
- Live-journey results are committed as sample runs, so CI keeps proving them after the sandbox is gone.

---

## DD-036 - Decision - Python 3.12 with uv, ruff, mypy, pytest; React + Vite + TypeScript UI with a generated client

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | Tooling                  |
| Status          | accepted                 |
| Supersedes      | —                        |

### Context

S7/SC12 need pinned, reproducible setup. uv is already required for `uvx` MCP servers. S8 requires a TS/JS UI.

### Options considered

1. **Python 3.12, uv lockfile, ruff, mypy, pytest; React + Vite + TypeScript UI with a client generated from OpenAPI** - one toolchain, UI can't drift from the API.
2. Poetry instead of uv - / second tool next to uvx.
3. pip + requirements.txt - / weak pinning.
4. Option 1 with Next.js - / server runtime not needed.
5. Option 1 with SvelteKit - / smaller ecosystem for the team.

### Decision

The backend uses Python 3.12, uv with a committed lockfile, ruff, mypy and pytest. The R3 UI uses React, Vite and TypeScript, with an API client generated from the OpenAPI spec.

### Rationale

One package manager for code and MCP servers, and a generated client proves SC11.

### Consequences

- The OpenAPI spec is committed and checked in CI, so the UI build fails if the API changes without regenerating.

---

## DD-037 - Decision - Record MIT as a known deviation and ask Clay at kickoff

| Field           | Value                 |
| --------------- | --------------------- |
| Date            | 2026-11-03            |
| Cycle / Feature | Open source (DD-017)  |
| Status          | accepted              |
| Supersedes      | —                     |

### Context

DD-017 keeps MIT. `docs/05` lists Apache-2.0 as Clay's requirement, and DD-001 says `docs/` is not rewritten.

### Options considered

1. Keep MIT, record the deviation, leave `docs/` alone - honest / DoD item stays unticked.
2. **Option 1, plus ask Clay at kickoff whether MIT is acceptable; switch (one file) if they insist** - keeps the door open.
3. Edit `docs/05`/`06` to drop the requirement - / rewrites ground truth.
4. Reverse to Apache-2.0 - / supersedes DD-017.
5. MIT for code, CC BY for docs - / doesn't solve Clay's requirement.

### Decision

The SRS records MIT as a known deviation from Clay's Apache-2.0 requirement, and the team asks Clay at kickoff whether MIT is acceptable, switching the LICENSE file if they insist.

### Rationale

Respects DD-017 and DD-001 while keeping a cheap way back.

### Consequences

- If Clay insists, a new decision supersedes DD-017.

---

## DD-038 - Decision - Prove the evaluator with a library of planted traces

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | F10 (SC9, OQ3)           |
| Status          | proposed                 |
| Supersedes      | —                        |

### Context

SC9 and J6 step 2 need the evaluator to separate good from bad runs by more than the reported uncertainty. Live "bad" agents are unreliable to produce on demand.

### Options considered

1. **Planted traces: one known-good trace per template, plus known-bad variants (unrecovered tool failure, loop, wrong order, forbidden tool, unknown tool, budget stop, fabricated output). Report detection rate per flaw and the good-vs-bad score margin against the CI** - deterministic, runs in CI / synthetic flaws may be cleaner than real ones.
2. A deliberately crippled live configuration (tiny model, no tools) - realistic / costs money, flaky.
3. Both - strongest / more work.
4. Human-labelled live runs - ground truth / slow.
5. No validation - / fails SC9.

### Decision

The evaluator is validated against a committed library of planted good and bad traces, and the report shows the detection rate per flaw type and the good-vs-bad margin. For the LLM evaluator, the same traces are scored k=3 times to report agreement.

### Rationale

Deterministic and cheap, and it keeps working in CI after the sandbox is wiped.

### Consequences

- WS3 creates the planted traces (they're traces), and WS4 runs the validation.
- The crippled live configuration (option 2) is a stretch addition.

---

## DD-039 - Decision - Report JSON is canonical; Markdown and HTML are renderings

| Field           | Value                    |
| --------------- | ------------------------ |
| Date            | 2026-11-03               |
| Cycle / Feature | F5, F9, F8 (DD-016)      |
| Status          | proposed                 |
| Supersedes      | —                        |

### Context

DD-016 needs static reports in the MVP and a UI in R3 that reads the same data. Committed sample reports should be readable on GitHub.

### Options considered

1. **`report.json` canonical; `report.md` (renders on GitHub) and a self-contained `report.html` generated from it** - one data source, viewable everywhere.
2. HTML only - pretty / not diffable, not rendered on GitHub.
3. Markdown only - simple / weak visuals for the Design criterion.
4. PDF - printable / extra dependency.
5. Notebook - exploratory / not a product artifact.

### Decision

Every run and every eval gets a canonical `report.json`, plus `report.md` and a self-contained `report.html` rendered from it.

### Rationale

The UI, the Markdown and the HTML all read the same JSON, so they can't disagree.

### Consequences

- The report JSON schema is a frozen contract owned by WS5, with WS4 producing its content.

---

## DD-040 - Decision - Sandbox self-observability through structured logs

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Operations (cross-cutting) |
| Status          | proposed                  |
| Supersedes      | —                         |

### Context

The sandbox's own failures (executor crashes, MCP server start failures) must be visible separately from agent traces.

### Options considered

1. **Structured JSON logs with `eval_id`/`run_id` on every line; stdout locally, CloudWatch Logs on Fargate (awslogs driver)** - simple, searchable.
2. Full OTel for the sandbox itself - consistent / doubles tracer work.
3. Print statements - / unsearchable.
4. CloudWatch metrics and alarms - / overkill for 2 days.
5. Option 1 plus a CloudWatch dashboard - nice for the demo / extra IaC.

### Decision

The sandbox writes structured JSON logs tagged with `eval_id` and `run_id`, to stdout locally and to CloudWatch Logs on Fargate.

### Rationale

Enough to debug a failed eval, and kept separate from the agent traces being measured.

### Consequences

- Sandbox logs are never mixed into agent traces.
- A CloudWatch dashboard is a stretch addition.

---

## DD-041 - Decision - Workflow score: sub-scores always reported, composite is a weighted mean

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F4 (SC3)                  |
| Status          | proposed                  |
| Supersedes      | —                         |

### Context

SC3 asks for workflow scores covering tool correctness and order, recovery, steps, latency and cost. The wireframe shows one workflow number plus bars per signal.

### Options considered

1. **Sub-scores in [0,1] (tool-call validity, argument constraints, required-tool coverage, ordering, forbidden tools, recovery, step efficiency, done condition), always reported; composite = weighted mean with weights in the task reference (default equal); latency and cost reported as raw metrics, not folded in** - transparent, configurable / composite depends on weights.
2. Sub-scores only, no composite - most honest / harder to rank.
3. Composite only - simple / hides the evidence.
4. Composite including normalised latency and cost - one number / mixes efficiency with correctness.
5. Pass/fail per rule only - binary / loses gradation.

### Decision

The deterministic workflow evaluator reports every sub-score with its evidence (trace event IDs) and a composite weighted mean, with weights declared in the task reference. Latency and cost are reported as raw metrics next to the scores.

### Rationale

Matches the wireframe and SC3, and every number can be traced to evidence.

### Consequences

- Changing weights creates a new task-reference version, so composites from different versions aren't compared directly.

---

## DD-042 - Decision - Definition of a successful run

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | F10 (SC9)                 |
| Status          | proposed                  |
| Supersedes      | —                         |

### Context

The statistics report a success rate (OQ2), but no document defines success. OQ12 says the output metric is never blended into workflow scores.

### Options considered

1. **Success = the workflow spec's done condition is met and the run wasn't stopped by the budget or loop guard. Infra-excluded runs are neither success nor failure** - process-based, consistent with D9.
2. Success = output metric above a threshold - / blends output into the process judgment.
3. Success = both - strict / blends the two.
4. Success = run ended without an error - / ignores whether the task got done.
5. No success rate, only scores - / drops the Wilson CI from OQ2.

### Decision

A run succeeds when its done condition is met and no budget or loop guard stopped it. Runs excluded for infra errors don't count either way.

### Rationale

Keeps the success rate a process measure, with the output metric reported next to it.

### Consequences

- A run can "succeed" with a poor output metric. Reports show both side by side.

---

## DD-043 - Decision - Identifier and versioning scheme

| Field           | Value                     |
| --------------- | ------------------------- |
| Date            | 2026-11-03                |
| Cycle / Feature | Provenance (SC7)          |
| Status          | proposed                  |
| Supersedes      | —                         |

### Context

Provenance needs stable, sortable IDs for runs and evals, and exact versions for task references, evaluators and schemas.

### Options considered

1. **ULIDs for evals, runs and assessments; task instances as `<template>@<aoi>`; task references as `<template>.v<n>+sha256:<12 hex>`; evaluators and schemas as `<name>@<semver>`** - sortable, content-addressed where it matters.
2. UUID4 everywhere - unique / not sortable.
3. Sequential integers - readable / collide across machines.
4. Content hashes everywhere - immutable / unreadable.
5. Timestamps - sortable / collide in parallel runs.

### Decision

Evals, runs and assessments use ULIDs. Task instances are `<template>@<aoi>`. Task-reference versions combine a version number with a content hash. Evaluators and schemas carry semantic versions.

### Rationale

IDs sort by time, don't collide between five machines, and a reference version proves exactly which answer key was used.

### Consequences

- The UI shows short forms of IDs, and the manifest stores the full ones.

---

## DD-044 - Decision - Rebalanced workstreams and developer assignment

| Field           | Value                          |
| --------------- | ------------------------------ |
| Date            | 2026-11-03                     |
| Cycle / Feature | Team and delivery model (plans) |
| Status          | accepted                       |
| Supersedes      | DD-019                         |

### Context

The team lead asked for one plan per developer with the tasks divided evenly. Under DD-019, WS5 (spec, registry, service, executors, CLI, API, reports, CI, README, Docker, CDK, Fargate, UI) carried far more work than WS1 (model adapter, wrappers, two harnesses, guards, pricing). The developers are Prithwish, Vishal, Shivaani, Barath and 5th member.

### Options considered

1. Keep DD-019 as is - no doc changes / WS5 overloaded, WS1 underloaded.
2. **Move the pre-flight estimate (from WS4) and the Docker image, CDK stack and Fargate executor (from WS5) to WS1; share the R3 UI screens across all five** - even load, each move follows a natural seam (WS1 already owns pricing and the Bedrock runtime) / WS1 becomes "runtime and cloud execution".
3. Split WS5 into two people and merge WS1 into WS2 - / WS2 is already the broadest workstream.
4. Rotate tasks per release regardless of workstream - / ownership of interfaces becomes unclear.
5. Assign by personal preference - / not known to the architect.

### Decision

Workstreams are rebalanced as option 2, and developers are assigned in the order the team lead listed them:

| WS | Developer | Owns |
| -- | --------- | ---- |
| WS1 Agent runtime and cloud execution | **Prithwish** | Bedrock model adapter, instrumented wrappers, Strands and Converse-loop harnesses, budget and loop guards, price table and refresh script, pre-flight cost estimate (`runtime/estimate.py`), Dockerfile, CDK stack, Fargate executor |
| WS2 Tools and tasks | **Vishal** | MCP tool-set launcher and env scrubbing, tool sets T0/T1, task templates T1–T5, AOIs, reference builders and spot-checks, `clay-embeddings` MCP server and staging |
| WS3 Trace and store | **Shivaani** | `TraceEvent` schema, JSONL/OTel/tee tracers, tracer comparison analysis, redaction, run store (local + S3 mirror), trace reader, DuckDB queries, summarizers, sample runs, planted traces |
| WS4 Evaluation and statistics | **Barath** | Workflow evaluator, output evaluators T1–T5, LLM process evaluator, statistics, comparisons (agent axes, evaluators), planted-trace validation, eval report content, live-journey script and the live release-gate evals |
| WS5 Platform and presentation | **5th member** | Project scaffold and CI, eval spec, run manifest, registry, service layer, local executor and infra retries, CLI, FastAPI and OpenAPI, report renderers, README, UI shell |

R3 UI screens are shared: 5th member builds the shell, the generated client, the New Run screen and the SSE endpoint. Vishal builds Runs, Shivaani builds Report, Barath builds Comparison, and Prithwish runs the final demo eval and writes the demo runbook.

### Rationale

Each moved item sits next to code the new owner already writes: the estimate uses the price table, and the Fargate executor and image run the runtime Prithwish builds.

### Consequences

- The `Executor` interface stays with 5th member. Prithwish implements the Fargate executor against it.
- The tracer comparison (DD-026) moves from WS4 to WS3, next to the tee tracer that produces its data. The evaluator comparison stays with WS4.
- The live-journey script and the live release-gate evals go to WS4, since Barath needs those runs for the statistics.
- srs.md §5.1 and architecture.md §4, §21 and §23 reflect this split. The per-developer plans are `dev-docs/plan-<name>.md`.
- The name-to-workstream mapping follows the order of the team lead's list. Swapping two people means swapping their plan files, with no other change.

---

## DD-045 - Decision - `ToolResult` carries `status` and `error_kind`

| Field           | Value                                   |
| --------------- | --------------------------------------- |
| Date            | 2026-11-04                              |
| Cycle / Feature | F1 Tooling, F2 error capture (contracts) |
| Status          | accepted                                |
| Supersedes      | —                                       |

### Context

The first `contracts/tools.py` (written by WS1 so the wrappers could be built before WS2 merged) gave `ToolResult` only `text`, `structured` and `is_error`. A session had to signal a timeout by raising `TimeoutError` and a dead server by raising `ConnectionError`/`OSError`, and `InstrumentedTools` turned those exceptions into `tool_timeout` and `server_unavailable`. Plan VIS-R0-01 instead has the MCP session return `status="timeout"` and `error_kind="server_unavailable"` in the result, so a failed call never raises out of the session.

### Options considered

1. Keep the exception-only contract. The session raises, the wrapper maps - no contract change / the session's result alone can't say why a call failed, and every caller of a bare session must catch exceptions.
2. **Add `status` (`ok`, `error`, `timeout`) and `error_kind` (`tool_error`, `tool_timeout`, `server_unavailable`) to `ToolResult`, with defaults and a validator that keeps them consistent with `is_error`. `InstrumentedTools` reads them. Raising stays allowed** - additive and backward compatible / one small change in a WS1 file.
3. Replace `is_error` with `status` - cleanest / breaks every existing caller and test.

### Decision

`ToolResult` gains `status` and `error_kind`. `ToolResult(text=..., is_error=True)` still means a plain `tool_error`. `InstrumentedTools._completed` uses the result's `status` and `error_kind` when it traces the call. Sessions may still raise `TimeoutError` or `ConnectionError`/`OSError` instead, and the wrapper maps those as before.

### Rationale

Vishal (WS2, contract owner) chose to add the fields. Defaults and the validator keep every existing constructor call valid, so WS1's tests and fakes keep working without edits.

### Consequences

- `claysandbox/runtime/instrument.py` (WS1) changes in one method, with a test in `tests/unit/runtime/test_instrument.py`. Prithwish reviews that change.
- `ToolResult` has no `schema_version` field. The contract change is recorded here instead, and the contracts package version doesn't change.
- `ToolCall.status` in the trace is unchanged (`ok`, `error`, `timeout`, `rejected`). Trace readers see no difference.

---
