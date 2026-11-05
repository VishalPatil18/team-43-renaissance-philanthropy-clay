---
name: baseline
version: "1"
description: Control profile. No extra instructions, default guards, Strands loop (today's behaviour).
loop: strands
max_turns: 30
guardrails:
  max_steps: 15
  max_usd: 0.10
  max_seconds: 240
  loop_guard: {max_identical_calls: 3}
  on_tool_error: report
  require_final_json: false
---
<!-- Intentionally empty: the agent sees only the task's own system prompt and prompt. -->
