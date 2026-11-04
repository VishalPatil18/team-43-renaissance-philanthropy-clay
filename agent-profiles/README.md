# Agent profiles

> **Status: draft. The loader is not implemented yet.** The design is in [`dev-docs/brief-model-router-and-harness-track.md`](../dev-docs/brief-model-router-and-harness-track.md), Part C.

An agent profile is one Markdown file that defines **how an agent under test behaves**: which code loop drives it, which guardrails the sandbox enforces on it, and the instructions the model reads. The model is **not** part of a profile. Holding the model fixed and swapping profiles shows what the agent design changes.

## File format

```markdown
---
name: careful-planner          # unique; becomes part of the configuration name
version: "1"                   # bump on any change; the manifest records version + sha256
description: one line
loop: converse_loop            # code loop: strands | converse_loop
max_turns: 12                  # the loop's own cap (Strands max_cycles / Converse max_turns)
guardrails:                    # ENFORCED by the sandbox, whatever the model does
  max_steps: 10                # budget guard (FR-11)
  max_tokens: 150000
  max_usd: 0.10
  max_seconds: 180
  loop_guard: {max_identical_calls: 3}
  on_tool_error: report        # report | retry_once | retry_twice
  require_final_json: true     # one reminder turn if the run ends with no final answer
---
Markdown body = the INSTRUCTIONS. Prepended to the task's own system prompt, never replacing it.
```

## What is enforced, and by what

| Field | Enforced by | Exists today? |
|---|---|---|
| `loop`, `max_turns` | Chooses the `strands` or `converse_loop` harness and sets its params | Yes (both harnesses) |
| `max_steps`, `max_tokens`, `max_usd`, `max_seconds` | `runtime.guard.RunBudgetGuard` | Yes |
| `loop_guard.max_identical_calls` | `runtime.guard` loop guard | Yes (note: it ignores rejected calls) |
| `on_tool_error` | The tool wrapper or harness adds a retry note, or retries in code | **New** |
| `require_final_json` | The harness sends one reminder turn if `end_turn` arrives with no answer | **New** (WS1 harnesses) |
| Body text | Prepended to the task's system prompt | Yes (it's only text) |

**Decided (2026-11-04):**
- **Profiles do not narrow the tool set.** Every profile sees the full tool set chosen by the spec (`toolset: T1`, `T0`, …), and the agent must pick the right tools from the task itself. Choosing tools well is part of what gets measured.
- **The body is prepended** to the task's system prompt. The task's output instructions always stay.
- **Profiles are versioned in the repo**, like `toolsets/`. Change a profile through a PR and bump `version`. Each run's manifest records `name`, `version` and the file's sha256, so every result traces back to the exact text.

**Enforced** guardrails (frontmatter) and **instructed** behaviour (the body) are scored separately. The gap between them is a result in its own right: for example, did "never invent IDs" actually stop fabrication on T5?

## The profiles

| File | Idea | Expected to show |
|---|---|---|
| `baseline.md` | No extra instructions, default guards, Strands. The control | Today's behaviour |
| `careful-planner.md` | Plan before acting, verify arguments, sequential loop | Fewer invalid calls and better ordering, more tokens |
| `fast-minimal.md` | Fewest steps, tight budget | Lower cost and latency; does accuracy drop? |
| `strict-recovery.md` | Retry once with fixed arguments, then report; loop guard at 2 | Recovery score on the `faulty` scenario |
| `honesty-first.md` | Never fabricate; say what's missing; ask on ambiguity | T5 pass rate and the `wrong_tools` scenario |

## Using one (after the loader exists)

```yaml
harness: {name: profile, params: {path: agent-profiles/careful-planner.md}}
```

Compare profiles on the same model as variants that override only `harness.params.path`. See Part C of the brief.
