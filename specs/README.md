# Specs

Eval specs (`*.yaml`) describe what to run: tasks, configurations, evaluators, trials and
budgets. The schema is served by the API (`GET /schema/eval-spec`); the architecture sketch is in
`dev-docs/architecture.md` §7.3.

## Confirmed Bedrock model IDs (us-west-2)

Checked on 2026-11-04 with `uv run python scripts/check_models.py`, which calls each model through
the sandbox's own adapter with a one-line prompt and one dummy tool. Model IDs live only in specs,
never in code (FR-1.5).

| Role | Model | Model ID to put in the spec | Tool use | Price (per 1M in / out) |
|---|---|---|---|---|
| dev | Nova Lite | `us.amazon.nova-lite-v1:0` (the bare `amazon.nova-lite-v1:0` also works) | yes | $0.06 / $0.24 |
| baseline | Nova Pro | `us.amazon.nova-pro-v1:0` | yes | $0.80 / $3.20 |
| variant | Claude Sonnet 4.6 | `us.anthropic.claude-sonnet-4-6` | yes | $3.30 / $16.50 |
| summary | Nova Lite | `us.amazon.nova-lite-v1:0` | yes | $0.06 / $0.24 |
| judge | Llama 3.3 70B | `us.meta.llama3-3-70b-instruct-v1:0` | no (the judge only returns JSON) | $0.72 / $0.72 |

Notes:

- **Claude needs the inference profile ID.** The bare `anthropic.claude-sonnet-4-6` fails with
  "on-demand throughput isn't supported". Use the `us.` profile (or `global.`).
- The judge is from a different family (Meta) than the agents under test (Amazon, Anthropic), as
  DD-027 requires.
- Claude Sonnet 4.5 (`us.anthropic.claude-sonnet-4-5-20250929-v1:0`) also works but AWS lists it as
  legacy with end of life on 2027-04-08, so Sonnet 4.6 is the variant model.
- Prices come from `pricing/prices.yaml`. Claude prices are typed by hand (the Price List API does
  not list them); the US profile costs 10% more than the global one.

## Specs in this folder

| File | Purpose |
|---|---|
| `demo.yaml` | The live demo eval: 2 configurations x 2 instances x 1 trial on Nova Lite (see `DEMO.md`) |
