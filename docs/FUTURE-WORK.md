# Future Work

> **For agents — what this file is:** The record of post-build features we didn't implement but would if we had more time (SCOPE D21). It ships in the repo so Clay, judges, and future contributors can see where the project goes next. **Keep it current:** whenever a feature is cut or deferred during the build, add a row to "Cut during the build" with what it is, why it was cut, and how we'd do it. Nothing in this file is promised in the MVP.

## Cut during the build

Fill this in as the build goes. Start empty, and add a row the moment something is dropped.

| Feature | Why it was cut | How we would build it | Effort guess |
|---|---|---|---|
| Interrupt a Bedrock call already in flight when `max_seconds` runs out | The guard checks before each call (architecture §9.2), so a long call finishes first and the overshoot is recorded. Good enough for the MVP | Use `converse_stream` and stop reading the stream when the watchdog fires, or run the call in a worker thread with cancellation | ~3 h |
| Reconcile estimated cost with the real AWS bill | Costs come from a price table and are labelled estimates (DD-032). The bill lags by a day and Claude is billed under Marketplace product names | Turn on Bedrock model invocation logging and join token counts to Cost Explorer usage types; report the difference per eval | ~4 h |
| LGND Geo MCP as an optional tool set (`toolsets/lgnd.yaml`) | Whitelist access to the commercial LGND Geo MCP was not confirmed by Clay during the build (X-06, DD-015). Our own open `clay-embeddings` server covers embeddings for T4 | Once access arrives: add `toolsets/lgnd.yaml` with the server's pinned command, credentials passed through its `env:` from the user's environment (never committed), and a capability map entry for `embedding_similarity`; then run T4 on both tool sets to compare | ~2 h |
| Clay embeddings beyond the six staged counties and two months | Staging every geohash partition is ~350 MB per partition-month; the server only searches what `scripts/stage_embeddings.py` staged (Jan and Jul 2024) | Serve directly from the Source Cooperative partitions with DuckDB per query, or index all US partitions in a vector store (S3 Vectors) | ~1 day |
| Measured Fargate run time in the pre-flight estimate | The estimate uses a default of 120 s per run (flagged as a guess) because the stored traces' `wall_ms` is not read yet | Add `wall_ms` to the token-history query and use its median per (template, model, harness) | ~1 h |

## Planned stretch (would implement next, roughly in this order)

| # | Feature | What it adds | Source |
|---|---|---|---|
| 1 | Sensitivity analysis | Re-run tasks while varying inputs and prompts (beyond the required model/harness/tooling comparisons, D3), and measure how stable both the agent and the eval are | Clay vision doc, Journey 2 (stretch) |
| 2 | Multi-agent traces | Planner / executor / checker agents, each traced, scored, and summarized | Clay stretch goal |
| 3 | Dynamic MCP tool discovery | The agent chooses tools from Clay's ~99-server catalog instead of a fixed tool set | Clay stretch goal |
| 4 | Richer trace-summary dashboard | Full UI on top of the parameter-complete API (UI deferred, D11) | Clay stretch goal · D11 |
| 5 | Agent-written verification code | The agent writes code that computes a dataset statistic, and the sandbox runs it to check the agent's claim | Team discussion (round 1, Q1 option b) |
| 6 | Batch trials on AWS (Lambda/ECS) | Run large N-trial evals in parallel in the cloud | OPEN-QUESTIONS OQ9 |
| 7 | Second Clay task: caption generation | Five-criterion caption rubric, fixed/change tasks, retrieval answer keys. Full reference in [03-out-of-scope.md](03-out-of-scope.md) | Clay vision doc, task 2 |
| 8 | Third Clay task | The vision doc mentions three tasks but defines only two. Build it once Clay defines it | Clay vision doc |

## Beyond the hackathon (outside our 2-day mandate, natural next steps for Clay)

| Feature | Why it's not MVP |
|---|---|
| Run Clay's wider eval backlog through the sandbox | The MVP proves the loop on one task |
| Partner-account deployment (e.g. ADB's own account) | Single sandbox account only |
| Production observability and warehouse (Snowflake/Iceberg/Athena, Managed Grafana) | A lightweight trace store is enough to prove the loop |
| Continental-scale builds | Too big for a 2-day sandbox |
