# MVP User Journeys as Tests

> **For agents — what this file is:** Acceptance tests written as user journeys (J1–J9). Each step has a check, and a journey passes only if every check passes. Each journey proves the success criteria in [02](02-success-criteria.md) noted beside it. Turn these into automated tests where possible. Terms are in the [SCOPE glossary](SCOPE.md#glossary).

> Scope: **ADB agentic eval only**. Captions are a stretch after the ADB stretch goals. Index: [README.md](README.md)

### J1. Evaluate one live run (SC1–SC4, SC7)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Developer picks a synthetic task and a configuration (model, harness, tool set, evaluator, optional budget) | The run manifest records the task ID, task-reference version, prompt, system prompt, tool list with schemas, model ID and settings, harness, tracer, evaluator, and budget settings |
| 2 | Harness runs on Bedrock and calls MCP tools | Trace has ≥1 MCP tool call. Every call has a name, arguments, result or error, latency and cost. The run ends with a final output |
| 3 | Sandbox summarizes the trace | Summary lists the steps in order and points out the failures, retries or dead ends in the trace. Every claim maps to a trace event |
| 4 | Evaluator scores the workflow and the output | Workflow scores cover tool correctness and order, error recovery, steps, latency and cost. The output metric is checked against the task's output reference. Each score has its evidence |
| 5 | Sandbox emits a report | Report contains the summary, scores, output metric, per-run and per-step latency and cost, the full context from step 1, and a path to the raw trace |

### J2. Replay a recorded trace (SC6)

> Not the same as the source's "Journey 2" (sensitivity analysis), which is a stretch goal listed in [FUTURE-WORK.md](FUTURE-WORK.md).

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Turn off live model access (or run in offline mode) | No Bedrock call is made, confirmed by logs |
| 2 | Point the sandbox at a stored trace from J1 | A report is produced from the stored trace |
| 3 | Compare with the live report | Scores from deterministic evaluators match exactly. If an LLM-based evaluator is used, any variance is reported |

### J3. Hot-swap every component (SC5)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Change the **model** ID in config | J1 passes with no code change. The report records the new model |
| 2 | Change the **tracer** backend (local JSONL → CloudWatch/X-Ray) | J1 passes with no code change. The trace keeps the same schema |
| 3 | Change the **harness** (e.g. Strands → plain Converse loop) | J1 passes with no code change. The report records the new harness |
| 4 | Change the **trace evaluator** and re-score stored traces | New scores appear for old runs without re-running the agent. The report records the evaluator version |

### J4. Errors are caught and logged (SC2)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Make a tool call fail (bad args, unreachable server, timeout) | The trace records a tool-side error. The summary mentions it. The workflow score is lower than in a clean run |
| 2 | Trigger model-side errors (a nonexistent tool name, a malformed call, a looping or giving-up agent) | Each one is logged as an error in the trace and shows up in the summary |
| 3 | Feed a deliberately wrong final output into scoring | The output metric is lower than for the correct output |

### J5. Compare configurations (SC8)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Define a baseline plus at least one variant that differs in harness, model, or tool set | Both configurations run on the same tasks |
| 2 | Run the comparison eval | A comparison report shows the configurations side by side for each metric, saying which one is better and by how much |

### J6. Statistical verification (SC9)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Run N trials per configuration (N set in the spec) | The report shows aggregate statistics with uncertainty for each configuration |
| 2 | Evaluate a known-good and a known-bad configuration (or planted traces) | The evaluator separates them by more than the reported uncertainty, so the eval can be trusted |
| 3 | A-vs-B comparison | The report says whether the difference between two configurations is statistically meaningful, or not |

### J7. Budget guard (SC10)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Run with the guard on and a tight limit | The run stops at the limit. The trace logs a budget-stop error showing which limit was hit |
| 2 | Run the same task with the guard off | No limit is applied, and the run completes normally |

### J8. Reproducible on another machine (SC12)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | A teammate who didn't build it clones the repo on a fresh machine and follows the README | Setup works from pinned dependencies with no one else's help |
| 2 | They run replay on the committed sample traces with no AWS credentials | Reports are produced |

### J9. Every parameter exposed (SC11)

| Step | Action | Verify (test) |
|---|---|---|
| 1 | Read the run/eval spec schema from the API | Every option used in J1–J7 (model, harness, tracer, evaluator, tool set, task, trials, budget limits) appears in the schema |
| 2 | Launch a run using only the API | The run completes. No option needs a code edit |
