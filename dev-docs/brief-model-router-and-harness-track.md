# Brief: automatic model selection and the harness track

> **What this is:** a build brief for three additions on top of the merged sandbox. **Part A** picks a Bedrock model automatically from a performance matrix (health, reply time, accuracy, cost). **Part B** runs the same model through different harnesses and compares how they behave, including guardrails and loops. **Part C** turns agent behaviour into swappable **Markdown agent profiles** (`agent-profiles/*.md`) that the evals load and compare. Nothing here is implemented yet. Part B can already be tried with a stand-in script (§B.4). The Part C example profiles are drafted.
>
> **Status:** draft, 2026-11-04. The design was reviewed with Codex; the review is in `Maestro/.maestro/research/clay-model-router-codex.md`.
> **Owner:** Kirtan (WS4 cover). Parts touch WS1 (runtime), WS3 (store), WS4 (statistics) and WS5 (composition, CLI), so agree contract changes with those owners first. The rules are in plan §4: a new DD entry, a `schema_version` bump, and every affected owner's approval.

---

## Part A: automatic model selection (`route` mode)

### A.1 The rule that shapes everything

The sandbox **measures** models; a router **chooses** them. Keep the two apart:

| Mode | Behaviour |
|---|---|
| `eval` (default, unchanged) | Models fixed in the spec, balanced task instances and trials, no substitution. Compared with the existing statistics (Wilson, cluster bootstrap, sign-flip, Holm) |
| `route` (new) | For each task, choose **one concrete model before the run starts**, from past evidence plus current health. Record every decision and its reasons. Never switch models inside a run |

The router is itself evaluated like any other configuration: a frozen policy against fixed-model baselines, on held-out task instances. "auto" is never a model that a run executes. The manifest still records the concrete `bedrock` model ID (FR-1.5 and reproducibility both still hold).

### A.2 The performance matrix

One cell per **model × harness × template**. The cohort key also includes the tool-set and tool-schema hash, prompt version, reference, evaluator and rubric versions, and region. Per-AOI (area) results are kept.

| Signal | Source | Window (starting value) |
|---|---|---|
| Workflow success (DD-042) | `Assessment.success` from `workflow@1` | Compatible runs, last 7 days |
| Output accuracy | Output assessment composite per template (F1, recall@k, pass rate) | Same |
| Tool-use detail | Workflow sub-scores: validity, argument constraints, recovery, loops and guard stops | Same (diagnostics) |
| Reply time | `model_call.latency_ms`; end to end `run_end.totals.wall_ms` including tools and retries | 24 h, falling back to 7 d (labelled) |
| Health | Recent run outcomes (infra errors, throttles, `ModelErrorException`), plus CloudWatch `AWS/Bedrock` `InvocationLatency`, `InvocationThrottles` and client/server errors | 5 min; stale after 5 min |
| Cost per full task | Tokens × `runtime/pricing.py` (versioned), including failed attempts and judge or summary cost | Price table at most 7 days old |
| Capability | A tool-use smoke test per model × harness (a real tool call, then the tool result, then the next turn) | Expires after 24 h or any schema change |

Rules:
- **Missing data is unknown, never good.** Each signal is in one of four states: `known`, `unknown`, `stale` or `incompatible`.
- **Minimum evidence before ranking automatically:** at least 20 runs across at least 5 task instances. Below that, show the raw cells and mark the decision `provisional`.
- **Re-scoring must not inflate N.** Keep one assessment per run and kind, at a pinned evaluator version.

### A.3 Selection policy: gates first, then optimise

There is no blended score. A cheap model that gets answers wrong must not win on price.

```
eligible = { m in spec.candidates :
      allowed(m)                       # spec ∩ infra/cdk.json bedrockModelIds ∩ verified access
  and capable(m, harness, toolset)     # tool-use smoke test passed
  and judge_compatible(m)              # DD-027: not the LLM judge's family
  and healthy(m)                       # no open circuit breaker, error rate below the cap
  and enough_evidence(m)               # ≥ 20 runs, ≥ 5 instances (or provisional mode)
  and WilsonLower95(success_m) >= success_floor[template]
  and BootstrapLower95(output_m) >= output_floor[template]
  and est_time(m) <= deadline
  and est_cost_with_reserve(m) <= remaining_budget }

objective = "cheapest_adequate" (default) | "best_within_budget" | "fastest_adequate"
choose = argmin / argmax by objective, ties -> latency -> spec order
if eligible is empty: return no_eligible_model (never guess)
```

- **Set the floors per template before you look at any rankings,** and save them in the policy file.
- **Fallback (route mode only):** after 3 retry-exhausted transient failures within 5 minutes, open that model's circuit for 60 s, then allow one half-open probe. The task restarts as a new linked attempt on the next eligible model, with a fresh tool session. All attempts count toward that request's cost and latency.
- **Configuration and authentication errors quarantine the configuration.** They are never retried.
- **No exploration in the hackathon MVP.** Fill the matrix with a planned calibration batch instead (§A.6). A Thompson-sampling or UCB bandit with propensity logging can come later.

### A.4 Contracts and where the code goes (respecting the §4.1 import rules)

| Piece | Location | Owner | Notes |
|---|---|---|---|
| `SelectionPolicy`, `SelectionSnapshot`, `CandidateEvidence`, `SelectionDecision`, `ModelSelector` (Protocol) | `claysandbox/contracts/selection.py` (new) | WS4 + WS1 | Pure data and an interface. Contract change, so it needs a DD |
| `ConstrainedCostSelector` (registry kind `selector`, name `constrained_cost`) | `claysandbox/runtime/router.py` (new) | WS1 | Pure function `select(context, candidates, snapshot, policy) -> SelectionDecision`. Imports only `contracts` |
| `build_matrix(rows, policy) -> SelectionSnapshot` | `claysandbox/evaluation/matrix.py` (new) | WS4 | Reuses `stats.wilson_interval` and `cluster_bootstrap_mean`, and the `RunRow`s from `compare.rows_from_records` |
| Health reader (recent runs plus CloudWatch) | `claysandbox/runtime/health.py` (new) | WS1 | Read-only `cloudwatch:GetMetricData`, which must be added to the developer role |
| Wiring: spec → matrix → selector → concrete `RunRequest` | `platform/service.py` | WS5 | Resolves the model **before** estimate, dispatch and manifest. The worker always receives `model.name=bedrock` with a concrete `model_id` |
| CLI | `clay-sandbox route <spec>` and `clay-sandbox matrix` | WS5 | `matrix` prints the table; `route --explain` prints the gate reasons |

Spec shape (new and versioned; `model: {name: auto}` is only sugar on top of it):

```yaml
selection:
  name: constrained_cost
  version: "1"
  params:
    objective: cheapest_adequate
    candidates:
      - {model_id: us.amazon.nova-lite-v1:0}
      - {model_id: us.amazon.nova-pro-v1:0}
      - {model_id: us.anthropic.claude-sonnet-4-6}
    floors:
      T1: {success: 0.6, output: 0.7}
      T4: {success: 0.6, output: 0.6}
    deadline_s: 180
    min_runs: 20
    min_instances: 5
    provisional: false
judge: {model_id: us.meta.llama3-3-70b-instruct-v1:0}   # so Llama is not a routing candidate
```

**Recorded before launch, in an immutable `selection.json` referenced from the manifest:**
- the policy name, version and hash, plus the original and the resolved spec
- the snapshot cutoff and hash, with its input records kept
- for every candidate: gate results with reasons, N and instance counts, intervals, and cost and time estimates
- the chosen model, the ordered fallbacks, the health observations, and the seed or tie-break

Decision replay must reproduce the same choice from that file.

### A.5 Prerequisites, which are blockers today

1. **Store bug (WS3).** `store/query.py:37` sets `TEMPLATE_SEP = ":"`, but instance IDs are `T1@us-ca-kern` (DD-043). Every per-template history query returns the whole ID as the template, so the cost estimator silently falls back to guesses. Fix this first and add a fixture test.
2. **Estimator history (WS1).** It uses only *completed* runs, accepts a single matching row, and has no recency filter. Add failed-attempt costs and a minimum N.
3. **WS5 service, worker and CLI:** they don't exist yet, so `route` has nowhere to plug in.
4. **`ModelErrorException` classification (WS1).** Every case is currently counted as retryable infra. Keep that classification, but add a signature keyed on model × harness × tool schema, so that a repeatable "invalid sequence as part of ToolUse" quarantines that combination instead of burning retries.

### A.6 MVP plan and acceptance checks

| Step | Deliverable | Check |
|---|---|---|
| 1 | Calibration batch: 3 candidates × 2 harnesses × T1, T2, T4 × 6 AOIs × N=2. About $3–6 with Nova; Claude costs more | Every cell has ≥ 5 instances. Runs go through the real pipeline (or `run_task.py` until the CLI exists) |
| 2 | `build_matrix` plus `clay-sandbox matrix` table | Re-scoring doesn't change N; stale and missing values show as unknown |
| 3 | `ConstrainedCostSelector` | Unit tests for: each gate excludes with a reason; empty set → `no_eligible_model`; judge family rejected across all fallbacks; same snapshot → same decision |
| 4 | Service wiring plus `selection.json` | The manifest holds a concrete model; import-linter passes |
| 5 | Demo: the same snapshot picks **different** models under `cheapest_adequate`, `best_within_budget` and `fastest_adequate` | Shown from saved data and replayable |
| 6 | The frozen policy against fixed models on held-out instances | Reported as a configuration in the eval report. The model mix is a diagnostic only |

**Decisions still open:**
1. The default objective. Recommended: `cheapest_adequate`.
2. Whether the LLM judge stays on. If yes, Llama is reserved for judging and the router picks among three models.
3. The calibration budget.
4. Who owns the service integration.

### A.7 AWS-native options (checked against AWS docs on 2026-11-04)

- **Bedrock Intelligent Prompt Routing:** routes only between two models of one family (for example Nova Lite and Nova Pro, which are supported in us-west-2), and *"can't adjust routing decisions based on application-specific performance data"*. Add it as **one competitor** in a comparison, not as our selector. Its multi-turn tool-use behaviour with our harnesses is **unverified**.
- **CloudWatch `AWS/Bedrock` metrics:** the health signal only, never accuracy. `Invocations` counts successful calls, so don't divide throttles by it and call the result an error rate.
- **Bedrock model evaluation jobs:** they can't run our MCP agent loop. At most a later cross-check of final answers.
- **AWS AppConfig:** later, to roll out policy versions with rollback. A file is enough for the hackathon.

---

## Part B: the harness track (same model, different harnesses)

### B.1 Question

Holding the model fixed, how much do the agent loop and its guardrails change the outcome? This covers success and scores, steps, invalid tool calls, error recovery, loops, budget stops, cost and time. It fills in the "harness" axis of DD-026 next to the model axis.

### B.2 What exists

| Harness | Registry name | Loop | Params |
|---|---|---|---|
| Strands Agents | `strands` | Strands' own event loop. Tools run **concurrently** by default (`ConcurrentToolExecutor`) | `max_cycles` (set above the sandbox guards) |
| Plain Converse loop | `converse_loop` | Our own sequential Bedrock Converse loop | `max_turns` |

Both run through the same instrumented model and tool wrappers, so the guards are identical:
- **Budget guard:** `max_steps`, `max_tokens`, `max_usd`, `max_seconds`.
- **Loop guard:** `max_identical_calls`, default 3.

### B.3 Scenarios (in `harness_matrix.py`)

| Scenario | Setup | What it reveals |
|---|---|---|
| `normal` | T1@us-ca-kern, tool set T1 | Baseline behaviour, steps and cost |
| `embeddings` | T4@us-ca-kern, tool set T1 | Multi-step chain (`embedding_at` → `similar_places`) and whether a final answer gets written |
| `faulty` | T1, tool set **T1-faulty** (STAC errors, OSM timeouts, dead server), loop guard 2 | Recovery behaviour, retry storms, loop-guard trips |
| `tight_budget` | T1, `max_steps=2` | Clean `budget_stopped` handling, and no crash or swallowed `GuardStopped` |
| `wrong_tools` | T1, tool set **T0** (no imagery search) | Gives up honestly vs. made-up item IDs vs. looping |

Metrics per scenario × harness:
- outcomes: final-state mix, DD-042 success rate, workflow and output composites
- activity: mean steps, tool calls, invalid calls, tool errors, recovery sub-score
- guardrails: guard stops by limit (`max_steps`, `loop`, …)
- spend: $ and seconds per run

### B.4 Run it now (stand-in, before the CLI exists)

From the repo root, signed in, in `us-west-2`:

```bash
S=/private/tmp/claude-501/-Users-kirtan-Projects-Maestro/74b36d23-21b5-48e8-aba0-e998ff15c764/scratchpad/clay_try
uv run --with "botocore[crt]" python $S/harness_matrix.py --model-id us.amazon.nova-pro-v1:0 --trials 2
uv run python $S/harness_matrix.py --summarize-only          # print the table again
uv run --with "botocore[crt]" python $S/harness_matrix.py --only faulty tight_budget --trials 3
```

5 scenarios × 2 harnesses × 2 trials = 20 runs, each capped at $0.10 and costing about $0.005 with Nova Pro. Run folders land in `$S/harness-runs/<scenario>/<harness>/<run_id>/`. The folder is temporary, so move it somewhere permanent if you want to keep it. Dry-run check: both harnesses, the guards, scoring and the summary all worked end to end with AWS hidden (0 dollars).

### B.5 Run it in the real pipeline (once the WS5 CLI exists)

A new spec, `specs/harness-same-model.yaml`. Variants change only the harness axis, so FR-9.3 raises no warning:

```yaml
spec_version: 1
name: harness-same-model
tasks: {templates: [T1, T2, T4, T5], aois: all}
baseline:
  name: novapro-strands
  model:   {name: bedrock, params: {model_id: us.amazon.nova-pro-v1:0, temperature: 0.2, max_tokens: 2048}}
  harness: {name: strands, params: {}}
  toolset: T1
  tracer:  {name: jsonl}
variants:
  - name: novapro-converse
    override: {harness: {name: converse_loop}}
evaluators:
  - {name: workflow, version: "1"}
  - {name: output, version: "1"}
trials: 3
seed: 42
budget: {run: {max_steps: 15, max_usd: 0.10, max_seconds: 240}, eval: {max_usd: 15}}
loop_guard: {max_identical_calls: 3}
stats: {bootstrap_iterations: 5000, alpha: 0.05}
```

Guardrail scenarios such as faulty tools and a tight budget are separate small specs, because they change the tool set or the limits. With 4 templates × 6 AOIs = 24 instances, there's enough to detect differences after the Holm correction (at least 7 complete instances are needed; plan §11 and the README).

### B.6 What to watch for (known from code review)

- **Strands runs tool calls in parallel by default.** Events then land in completion order, which can lower its `ordering` score unfairly against `converse_loop`. Report it as found, or add a `strands` variant with `SequentialToolExecutor()` (a WS1 change behind a new `Params` field) so the comparison is fair.
- **The loop guard ignores rejected calls** (invalid arguments, unknown tool). A harness that repeats an invalid call never trips it. `faulty` and `wrong_tools` will show this.
- **`ModelErrorException` ("invalid sequence as part of ToolUse")** is classified as retryable infra. See whether it clusters in one harness.
- **No final answer** (the T4 runs with Nova Lite): check whether one harness drops the closing text turn more often.

### B.7 Extensions

1. **A third harness**, for example a text-only ReAct loop with no native tool-use blocks. It's a new `@register("harness", …)` class and passes the existing harness conformance suite. It would help with the Nova `ModelErrorException` issue.
2. **Harness parameters as variants:** `strands` sequential vs. concurrent tools, and `converse_loop` with different `max_turns`.
3. **A per-harness guardrail section in the eval report:** guard-stop rate by limit, loop trips, retry counts, and steps to first valid call. That's a WS5 rendering task, using data the trace already holds.
4. **Feed Part B into Part A.** Harness is part of the matrix key, so the router can choose model *and* harness together.

---

## Part C: agent profiles as Markdown files

### C.1 Idea

Part B compares the two **code** loops. Part C makes the whole **agent design** swappable as a file: the loop, the enforced guardrails, and the behaviour instructions all live in one Markdown file per profile. With the model held fixed, a spec swaps profiles and the existing evaluators score each one. Anyone on the team can add a profile without writing Python. The format, field table and five example profiles are in [`agent-profiles/`](../agent-profiles/README.md):

| Profile | Loop | Key guardrails | Behaviour |
|---|---|---|---|
| `baseline` | strands | 15 steps, loop 3 | None (control, today's behaviour) |
| `careful-planner` | converse_loop | 10 steps, retry once, final-JSON reminder | Plan first, check arguments, one call at a time |
| `fast-minimal` | strands | 5 steps, $0.03, loop 2 | Fewest calls, no double-checking |
| `strict-recovery` | converse_loop | 12 steps, loop 2, retry once | One corrected retry, then report |
| `honesty-first` | strands | 12 steps | Never fabricate; assumptions or a question on ambiguity |

### C.2 What to build

| Piece | Location | Owner | Notes |
|---|---|---|---|
| `AgentProfile` model (frontmatter schema) plus parser | `claysandbox/contracts/profile.py` (new) | WS1 | Pydantic, `extra="forbid"`. Strip HTML comments from the body. Compute sha256 of the whole file |
| `ProfileHarness`, `@register("harness", "profile")`, `Params(path: str)` | `claysandbox/runtime/harness/profile.py` (new) | WS1 | Loads the file, picks `strands` or `converse_loop` with `max_turns`, **prepends** the body to `ctx.system_prompt` (never replaces it), applies the guardrails. **No tool filtering:** the agent sees the spec's full tool set |
| Guardrails from profile → `build_guard(RunLimits, LoopGuardSpec)` | Service (WS5) or the harness | WS1/WS5 | **Precedence:** the stricter of spec `budget.run` and profile `guardrails` wins, so a profile can tighten limits but never loosen the eval's cap |
| `on_tool_error: retry_once \| retry_twice` | Harness, as a retry note on the tool result or an automatic retry | WS1 | Each retry is a real `tool_call` event, so recovery scoring stays honest |
| `require_final_json` | Both harnesses: on `end_turn` with no parseable answer, one reminder turn | WS1 | Counts as a step. Would have fixed the Nova Lite T4 "no final answer" run |
| Manifest fields `harness.params.path`, plus profile `name`, `version` and `sha256` | `manifest.json` (WS5) | WS5 | Editing a profile without bumping `version` is caught by the hash |
| Conformance | `contracts/conformance/test_harness.py` already runs over every registered harness | WS1 | Add a fixture profile per loop |

### C.3 How to compare profiles

```yaml
name: profiles-same-model
baseline:
  name: novapro-baseline
  model:   {name: bedrock, params: {model_id: us.amazon.nova-pro-v1:0}}
  harness: {name: profile, params: {path: agent-profiles/baseline.md}}
  toolset: T1
variants:
  - {name: novapro-careful, override: {harness: {params: {path: agent-profiles/careful-planner.md}}}}
  - {name: novapro-fast,    override: {harness: {params: {path: agent-profiles/fast-minimal.md}}}}
  - {name: novapro-strict,  override: {harness: {params: {path: agent-profiles/strict-recovery.md}}}}
  - {name: novapro-honest,  override: {harness: {params: {path: agent-profiles/honesty-first.md}}}}
tasks: {templates: [T1, T2, T4, T5], aois: all}
trials: 2
```

- **Same model, five profiles, 24 instances × 2 trials,** compared with paired statistics and Holm correction across the 4 variants. That's 240 runs, about $1–2 with Nova Pro.
- **Run the Part B guardrail scenarios** (`faulty`, `tight_budget`, `wrong_tools`) per profile as well. That's where `strict-recovery` and `honesty-first` should separate from the rest.
- **Read results on two levels:**
  - *enforced*: guard stops, loop trips, retry counts
  - *instructed*: did the behaviour the body asks for show up in the sub-scores, such as recovery, validity and T5 rule b?
- **Holding profiles fixed across models** (Part A) shows whether a profile helps a weak model, for example Nova Lite, more than a strong one.

### C.4 Before the loader exists

The stand-in runner can approximate a profile for a quick test by passing `--harness <loop>`, `--max-steps`, `--max-usd` and `--loop-max` from the frontmatter. The instructions (body), `on_tool_error` and `require_final_json` need the loader, so real profile comparisons wait for C.2.

### C.5 Open questions

1. ~~Should a profile narrow the tool set?~~ **Decided: no.** Every profile gets the full tool set from the spec, and the agent must choose tools from the task inputs. Tool choice is measured (by `tool_call_validity`, `required_coverage`, `forbidden_tools`, `argument_constraints` and the LLM judge's tool-choice item), not pre-filtered. Tool sets stay a separate spec axis (`toolset`).
2. ~~Prepend or replace?~~ **Decided: prepend.** The profile body goes in front of the task's system prompt, and the template's output instructions always stay.
3. ~~Where should profiles live?~~ **Decided: in the repo, versioned like `toolsets/`.** `agent-profiles/*.md` is committed and reviewed by PR. Any change bumps `version`. The manifest records `name`, `version` and the file's sha256, and the loader refuses a profile whose content changed while `version` stayed the same, compared with a committed `agent-profiles/versions.lock`. Old versions stay reproducible through git history plus the recorded hash.

---

## References

- `dev-docs/architecture.md`: §4 (components and import rules), §7 (contracts), §9 (guards and error classification), §11 (statistics), §12 (cost model), §17 (deployment).
- `dev-docs/srs.md`: FR-1.5, FR-4.11, FR-9.*, FR-10.*, §12.4.
- `dev-docs/design-decisions.md`: DD-025, DD-026, DD-027, DD-042, DD-043, DD-046, DD-047.
- Code: `claysandbox/runtime/{guard.py, instrument.py, estimate.py, pricing.py, models/bedrock.py, harness/}`, `claysandbox/evaluation/{stats.py, compare.py}`, `claysandbox/store/query.py`, `infra/cdk.json`.
- Sponsor framing: GeoAI Evaluations Inception Report, §5.7 (metrics) and §5.8 (agentic evaluation).
