# MVP Features in Scope

> **For agents — what this file is:** The MVP feature list (F1–F12). Each feature has a priority, a pass check, and the SCOPE requirement (S#) or decision (D#) it comes from. Use it to decide what to build and in what order. The F-numbers are referenced from SCOPE.md, 02, 04 and 05. Terms are defined in the [SCOPE glossary](SCOPE.md#glossary). How each feature works in detail (thresholds, statistics, schemas) is parked in [OPEN-QUESTIONS.md](OPEN-QUESTIONS.md).

> Scope: **ADB agentic eval only**. Captions are a stretch after the ADB stretch goals. Index: [README.md](README.md)

| # | Feature | What it must do | From | Priority | Pass check |
|---|---|---|---|---|---|
| F1 | LLM harness over MCP tools | An agent on Amazon Bedrock performs a synthetic ADB-style task by calling geospatial MCP tools: RODA MCP, 1–2 servers from Clay's shortlist, and an **LGND embeddings tool** | Clay · D4 · D13 | Must | One run completes with ≥1 real MCP tool call recorded |
| F2 | Trace capture | Record every step: tool name, arguments, order, result, retries, latency, token/$ cost. **Log every error**: tool-side (failure, timeout), model-side (nonexistent tool, malformed call, refusal, giving up, looping), budget stops, and infra (throttling, network) | S3 · S5 · D5 · D12 | Must | The trace for a run holds every step and every error, in order, with timing and cost |
| F3 | Trace summarization | Turn raw traces into a readable account of what the agent did and where it struggled | S4 | Must | A person can tell what happened from the summary alone. Every claim in it maps to a trace event |
| F4 | Scoring (workflow + output) | Score the **workflow** (from the trace: tool correctness and order, error recovery, steps, latency, cost) and the **output** (an evaluation metric), both against the task's **task reference** | Clay · D9 · D16 · S12 | Must | Each run gets workflow scores and an output metric, each with its reasoning or evidence |
| F5 | Evaluation report + provenance | A per-run report with the summary, scores, output metric, **per-run and per-step latency and cost**, and the full **context the agent was given** (prompt, system prompt, tool list and schemas, model, harness, tool set, budget settings, evaluator, task-reference version) | S6 · D5 · D9 | Must | A report exists for every run, and anyone can see from it exactly what the agent was given |
| F6 | Hot-swappable components | **Model, harness, tracer, and trace evaluator** each sit behind an interface and swap through config | S1 · S2 · D2 | Must | Changing one config value swaps each component with no code edits, and the run still produces a report |
| F7 | Replay and re-score | Stored traces replay through summarize → score → report with no live agent. A swapped evaluator can **re-score stored traces** | Clay · D2 | Must | Replay with Bedrock access off still produces a report |
| F8 | UI (TypeScript or JavaScript) | Thin view to launch runs and evals and read reports and comparisons. **Built after the backend** (D11) | S8 · D11 | Should | Launch a run and open its report from the browser |
| F9 | Comparison eval | Run the same tasks across configurations that differ in **harness, agent (model), or tooling**, and report them side by side | S10 · D3 | Must | One eval yields a comparison report covering at least two configurations |
| F10 | Statistical evaluation | Run repeated trials per configuration and report aggregate statistics with uncertainty, so differences between agents can be shown to be real (method: OQ2) | S9 · D1 | Must | The comparison report shows statistics with uncertainty for each configuration, plus A-vs-B tests |
| F11 | Optional budget guard | Per-run or per-eval limits that can be switched on or off (limits: OQ7). A run that hits a limit stops and logs it as an error | S11 · D6 | Must | With the guard on, a run that exceeds a limit stops, and the trace shows why. With it off, there's no limit |
| F12 | Run/eval spec + reproducibility | One spec holds **every parameter**, and an API exposes it (for the CLI and the future UI). Anyone can set the project up from the README on another machine | S7 · S8 · D11 | Must | Every parameter can be set through the spec. A teammate on a fresh machine runs replay from the README alone |

**Build order (from Clay's Day-1 guidance):**
1. Stand up F1 on Bedrock with RODA MCP plus 1–2 shortlist servers.
2. Get a **single trace captured end to end** (F2) **before adding scoring**.
3. Prove observe → summarize → score → report (F3–F5) on one task.
4. Then add the swaps (F6, F7), comparisons and statistics (F9, F10), the budget guard (F11), and the spec (F12). The UI (F8) comes last.

**Judging note:** "Design" (UX, interface, architecture) is 1 of 4 equally weighted judging criteria, so F8 matters once the backend works.
