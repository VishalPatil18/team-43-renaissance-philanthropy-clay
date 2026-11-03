# Team Scope — Clay agent-eval sandbox

> **For agents — what this file is:** The team's own scope: the problem, constraints, and solution requirements in the team's words, plus a decisions log from the scope interview (D1–D21). It is the **source of team intent**. Files 01–06 turn it into features, criteria, tests and risks, merged with Clay's vision doc. Every S-requirement below maps to items in 01/02/04/05. If you find a requirement with no matching item, or this file disagrees with a numbered file, raise it with the team and don't silently pick one. Build-time design questions are **parked** in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) until right before building (D17). Text marked *(interpretation)* is the assistant's reading and hasn't been confirmed by the team. Terms are defined in the [Glossary](#glossary) at the end.

## Problem

AI agents in Clay's dataset workflows are a **black box**. When an agent plans and runs a geospatial dataset build by calling tools, it's hard to observe what it did, and there's **no scoring**, so nobody can say whether to trust the run.

**Requirement:** make the agent's work visible and scored, following **Clay's ideology**. *(Interpretation, from Clay's vision doc:* open, reproducible, public/synthetic data only, and trust and provenance treated as first-class.*)*

## Usage

The product is an **agent evaluation** tool. Someone runs an agent on a known task, and the product shows what the agent did and how well it did it.

## Constraints (as listed by the team)

| Constraint | Meaning | Basis |
|---|---|---|
| Money | The **agent run's cost**, measured per run and per step | Team, D5 |
| Speed | The **agent run's latency**, measured per run and per step | Team, D5 |
| Compute | Modest instances only, no HyperPod or large Trainium | *(Interpretation, from Clay's service disallow list. Unconfirmed)* |
| Amazon Bedrock | The agent's model runs on Bedrock | Team |
| Python | Harness, MCP wiring, trace capture, scoring (Python 3.12+ per Clay's doc) | Team |
| Clay embedding model | Pre-computed LGND embeddings exposed to the agent as a tool. We don't run the model ourselves | Team, D4 |
| Agent comparison | Listed as a constraint, but it's also a requirement to build: see **S10** | Team, D3 |

**Project limits (from the event and source docs, not the team's list):** AWS sandbox capped at **$500**. The public repo must be up before judging (Thu Nov 5, prelims at 10:00 am). Official build hours don't bind us (D18).

## Solution requirements

| # | Requirement (team's words, cleaned up) | Feature (01) | Criterion (02) | Test (04) |
|---|---|---|---|---|
| S1 | AI models swap **without code changes** | F6 | SC5 | J3 |
| S2 | Tracing tooling is **swappable** | F6 | SC5 | J3 |
| S3 | Agent activity is **captured as traces** | F2 | SC2 | J1 |
| S4 | A **human-readable summary** | F3 | SC2 | J1 |
| S5 | **Include errors the model may run into.** All agent errors are logged (D12) | F2 | SC2 | J4 |
| S6 | **Trust kept after the run:** keep the traces, the input, and the rubric/reference | F5 | SC7 | J1 |
| S7 | **Open and reproducible** on other machines, beyond the engineer who made it | F12 | SC12 | J8 |
| S8 | **TypeScript or JavaScript UI.** Deferred until the backend is done (D11), but every parameter must already be available to it | F8, F12 | SC11 | J9 |
| S9 | **Verifiable statistics:** the sandbox shows, verifiably and truthfully, that it can evaluate agents (models and harnesses) statistically. The goal is not identical numbers (D1) | F10 | SC9 | J6 |
| S10 | **Compare harnesses, agents, and tooling** (D3) | F9 | SC8 | J5 |
| S11 | **Optional budget guard**, set per run or per eval (D6) | F11 | SC10 | J7 |
| S12 | **Output included as an evaluation metric** (D16) | F4 | SC3 | J1 |
| S13 | Must follow **Clay's ideology** (open, public/synthetic data, provenance) | F5, F12 | SC7, SC12 | J8 |

## Decisions log (scope interview, 2026-11-03)

The team's answers are recorded close to their own words. Anything the assistant added is marked *(recommended)* and points to OPEN-QUESTIONS.md.

### Round 1

| # | Decision |
|---|---|
| D1 | "Verifiable code/statistic" means the sandbox can show statistics that are verifiable and true: it can **evaluate the agent in a statistical way**, for both models and harnesses. It's not about getting the exact same numbers. *Method: (recommended) OQ2* |
| D2 | The **models, the harnesses, and the trace evaluator** are hot-swappable (the tracer too, per S2) |
| D3 | **Comparing harnesses, agents, and tooling is necessary for the event.** *What "tooling" covers is open: OQ15* |
| D4 | Clay embeddings: **pre-computed LGND embeddings**, exposed to the agent as a tool. We don't run the model |
| D5 | "Speed" and "Money" both refer to the **agent's run time** (its latency and cost) |
| D6 | The **budget guard is an option that can be switched on or off**: on any run or eval you can set a budget guard. *Limits: (recommended) OQ7* |
| D7 | Agent framework: Strands Agents behind our own interface. The team's answer was "yes, AWS integration is a judging score" *(read as a yes to Strands)* |
| D8 | Tracer: OpenTelemetry → local JSONL by default, with AWS CloudWatch/X-Ray as the second backend |
| D9 | *(Original answer to the LLM-judge question)* "The output quality doesn't matter. The actual judgement is the agent evaluation": tracking **the input, the context the agent was given, and the trace the agent took**. **Partly superseded by D16** |
| D10 | It should **run in different places**, with **some AWS integrations**. *Which services: (recommended) OQ9* |
| D11 | **Leave the UI for now.** Make sure **all available parameters** are exposed for the UI |
| D12 | **All agent errors are logged** |
| D13 | **We won't get ADB inputs.** We use **synthetic prompts**. *(Whether Clay sends an ADB rubric is unconfirmed: see 06)* |
| D14 | Team roles: ignored for now |

### Round 2

| # | Decision |
|---|---|
| D15 | The **PDFs stay out of the repo**, and **all md files are pushed**. *(The assistant also excluded the PDFs' text copies)* |
| D16 | **Include output as an evaluation metric.** This supersedes D9 to the extent that output *is* measured. Process (input, context, trace) is still the main judgment. *How output is scored (deterministic vs. LLM judge) is open: OQ12* |
| D17 | Detailed design questions are **parked until right before building**, in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md) |

### Round 3

| # | Decision |
|---|---|
| D18 | The team **can build outside the official build hours** |
| D19 | **We generate the synthetic tasks** ourselves. *What each task contains: (recommended) OQ1* |
| D20 | Team repo: [github.com/VishalPatil18/team-43-renaissance-philanthropy-clay](https://github.com/VishalPatil18/team-43-renaissance-philanthropy-clay) (public). These md files live in `docs/` |
| D21 | Post-build features we couldn't implement go in [FUTURE-WORK.md](FUTURE-WORK.md), kept current and shipped in the repo |
| D22 | Text from the AWS event guide may be kept in the md files (the PDFs themselves stay out) |

**Open from round 3:** the team said "we have it working". What exactly works is still to be confirmed (OQ14).

## Works under

Scope: **ADB agentic eval only.** Captions are a stretch, attempted after the ADB stretch goals. All MVP files apply: [01](01-features-in-scope.md) · [02](02-success-criteria.md) · [03](03-out-of-scope.md) · [04](04-user-journeys-tests.md) · [05](05-definition-of-done.md) · [06](06-risks-and-dependencies.md) · [EXTERNAL-DEPENDENCIES](EXTERNAL-DEPENDENCIES.md).

## Glossary

| Term | Meaning |
|---|---|
| **Clay** | The beneficiary: an open Earth foundation model project, building the "Earth Dataset Foundry" |
| **ADB** | Asian Development Bank, a Clay partner. The "ADB agentic eval" is the task of evaluating an agent on an ADB-style "how to use AI / build datasets" job |
| **Agent** | An LLM (on Bedrock) that plans and calls tools to do a task |
| **Harness** | The code that runs the agent loop: prompt → model → tool calls → result. Examples: Strands Agents, or a plain Bedrock Converse loop |
| **MCP** | Model Context Protocol, the standard way the agent reaches tools ("MCP servers") |
| **Tooling / tool set** | The set of MCP servers the agent can use in a run (see OQ15 for other meanings) |
| **RODA** | AWS Registry of Open Data. The RODA MCP server lets the agent search and sample it |
| **LGND embeddings** | Pre-computed Clay model embeddings of imagery, published on Source Cooperative |
| **NAIP / Requester-Pays** | US aerial imagery on S3. Requester-Pays means our account pays for each read |
| **USPVDB / USWTDB / GRW / OSM** | Public reference datasets of solar sites, wind turbines, renewables and map features, used as answer keys |
| **Trace** | The recorded log of one agent run: every step, tool call, argument, result, error, latency and cost |
| **Tracer** | The component that records traces (e.g. OpenTelemetry → JSONL). Swappable |
| **Trace evaluator** | The component that scores a trace (and the output) against a task reference. Swappable, and can re-score stored traces |
| **Task reference** (formerly "rubric version") | What a synthetic task is scored against: its expected-workflow spec plus its output reference, with a version number |
| **Configuration** | One combination of model + harness + tool set + evaluator under test |
| **Trial** | One run of one configuration on one task. Statistics come from repeated trials |
| **Budget guard** | Optional per-run limits (e.g. steps, tokens, $, time) that stop a run when it hits one |
| **Replay** | Feeding a stored trace back through summarize → score → report with no live model |
