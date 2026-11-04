# Demo runbook

> **Status: draft, not rehearsed.** Written by WS1 (PRI-R3-01) before the CLI, the tool sets, the
> evaluators and the UI had merged. The commands follow the CLI table in `dev-docs/srs.md` §13.1.
> Items marked **[check]** depend on another workstream and must be confirmed in the rehearsal.
> Tick the checklist at the end after one full run from this file.

## What we show

One idea: *the sandbox measures an agent's behaviour, not just its answer, and you can swap any part
and compare fairly.* The live part is small (4 runs on Nova Lite). The result part is the full R2
comparison committed under `samples/`.

## Before the demo (do the day before and again 30 minutes before)

```bash
uv sync && uv run pytest                           # everything green, no AWS needed
uv run python scripts/check_models.py              # every role prints ok (live Bedrock access)
uv run python scripts/smoke_live.py                # one real model + tool round trip, < $0.001
clay-sandbox estimate specs/demo.yaml              # [check] expect about $0.01 (default guesses)
```

Have ready: the AWS profile exported, `runs/` empty or ignored, the browser on the UI **[check]**,
and `samples/` containing the live comparison run and its reports.

## Timed script (proposal, 8 minutes; adjust to the real slot)

| Min | Say / do | Command or screen | Proves |
|---|---|---|---|
| 0:00 | The problem in one sentence: agents are judged by their answer; we judge the path too | slide / README | Why |
| 0:45 | Show the spec: model, harness, tool set, budgets, all in YAML | `specs/demo.yaml` | J9 |
| 1:30 | Cost first: estimate and confirm | `clay-sandbox estimate specs/demo.yaml` | UC-03, FR-11.7 |
| 2:15 | Launch the live eval and watch it | `clay-sandbox eval specs/demo.yaml` (4 runs, ~3 min) | J1, J5 |
| 2:15–5:00 | While it runs: open a finished sample report. Timeline, an error highlighted, per-step cost, summary with citations | Report screen / `samples/runs/<id>/report.html` | J1, J4 |
| 5:00 | Comparison: harness vs harness with confidence intervals and a plain-language verdict | Comparison screen / `eval_report.html` | J5, J6 |
| 6:00 | Swap one part: change `harness` to `converse_loop`, re-run one instance | see "Component swap" | J3 |
| 6:45 | Safety net: budget stop | see "Budget stop" | J7 |
| 7:30 | Close: replay works offline, so the demo survives a dead network | see "Fallback" | J2 |

## Live command sequence

```bash
export AWS_REGION=us-west-2 AWS_PROFILE=<sandbox profile>
clay-sandbox estimate specs/demo.yaml          # shows total, per-configuration, price table version
clay-sandbox eval specs/demo.yaml              # confirm the estimate; shows progress  [check]
clay-sandbox status <eval_id>                  # from a second terminal                  [check]
```

Expected: 4 runs complete (2 configurations x 2 task instances). The eval report lists both
configurations with success rate, scores and cost, and a paired comparison. With only 2 instances the
verdict will say the sample is too small to separate them; that honesty is part of the demo.

## Component swap (J3, ~1 minute)

Change one line and run a single instance. Only the harness differs between the two runs:

```bash
sed 's/name: strands/name: converse_loop/' specs/demo.yaml > /tmp/swap.yaml
clay-sandbox run /tmp/swap.yaml                # [check] `run` takes one config and one instance
```

Point out that both traces have the same event types and the same tool calls, because tracing and
guards sit at the model and tool boundary, not inside either harness.

## Budget stop (J7, ~1 minute)

```bash
sed 's/max_usd: 0.10/max_usd: 0.001/' specs/demo.yaml > /tmp/tight.yaml
clay-sandbox run /tmp/tight.yaml               # [check]
```

The run ends `budget_stopped`. In the report, the `guard_stop` event shows the limit, the value and
the observed value (it can overshoot by one call). Then say what is *not* stopped: with no
`max_*` limits in the spec, nothing is applied.

## Fallback if Bedrock or the network fails

Everything below needs no AWS and no network:

```bash
clay-sandbox replay samples/runs/<run_id> --offline             # [check] re-score a stored run
open samples/evals/<eval_id>/eval_report.html                   # the committed comparison
docker run --rm -v $PWD/samples:/app/samples clay-sandbox \
  replay samples/runs/<run_id> --offline                        # same, inside the image
```

Decision rule: if the live run has not shown progress after 60 seconds, say so, switch to the
committed `samples/` run, and continue the script from the "Comparison" row.

## Screens, in order (UI, R3) [check]

1. New Run: pick a spec, see the estimate, confirm.
2. Runs: status of the 4 runs as they finish.
3. Report: one run's timeline, errors, per-step cost, summary.
4. Comparison: both configurations, intervals, verdict.

## If we run on Fargate instead of locally

Only if `cdk deploy` and the image push were done beforehand (README, "Running on AWS"). Set
`executor: {name: fargate, params: {max_parallel: 4}}` in a copy of the spec. Runs then appear in
the S3 bucket and are synced down before scoring. Do not try this for the first time on stage.

## Rehearsal checklist

- [ ] Run the whole script from this file once, with a timer, without improvising
- [ ] Every **[check]** item confirmed or the line fixed
- [ ] Offline fallback run works with the network off
- [ ] Live eval finished inside the time shown in the table
- [ ] The comparison under `samples/` was committed by WS3 and opens offline
