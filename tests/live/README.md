# Live journeys

These run the real `clay-sandbox` CLI against real AWS Bedrock in `us-west-2`. **They spend money.**
Every spec in `specs/live/` has a tight `budget.run.max_usd` and an `eval.max_usd`, but the
journeys still bill your account. `estimate` runs before each spec; read it first.

## Run

```bash
export AWS_PROFILE=<your-sso-profile>   # aws sso login --profile $AWS_PROFILE first
export AWS_REGION=us-west-2
scripts/live_journeys.sh r1   # J1, J4
scripts/live_journeys.sh r2   # J3, J5, J6, J7
```

The script prints the run IDs and report paths. Never put credentials in a spec or the script.

## Before the first run

- Replace every `<placeholder>` in `specs/live/*.yaml` (Nova Lite and alternative model IDs, AOI IDs,
  the judge ID for `llm_process`, the faulty toolset name, the non-JSONL tracer name). The script
  refuses to run while placeholders remain.
- The judge model must be out of family with every agent model (DD-027).
- The script needs the `clay-sandbox` CLI (srs §13.1: `estimate`, `run`, `eval`, `rescore`).

## Check the results by hand

Compare each report with the journey steps in `docs/04-user-journeys-tests.md` (J1, J3-J7) and
record pass or fail per step in the PR.

### J4: tool failures and wrong-tool calls

Run both `specs/live/j4.yaml` (J4.1, faulty tools) and
`specs/live/j4-wrong-tool.yaml` (J4.2, model-side errors); `live_journeys.sh r1` runs both.
The second spec gives the T1 NAIP imagery task to Nova Lite at temperature 1.0 with the
RODA-only T0 tool set. Removing T1's STAC/OSM tools is intended to provoke an attempted
unavailable tool call. Check the manifest's exposed tool list first: the attempted name
must actually be absent. A valid call of an undesired capability is not an `unknown_tool` error.

For J4.2, look for `error.source=agent` and `error.kind=unknown_tool` (or `malformed_call`)
in the trace, and the corresponding event in the summary and workflow evidence. Record the
run ID, event ID, attempted name, and result in the PR. If the model uses the available tools
or refuses cleanly, this attempt did not exercise wrong-tool handling. Do not claim a live pass.
If a wrong-tool call cannot be provoked reliably, J4.2 relies on WS1's fakes test from
Prithwish (scripted nonexistent/malformed tool calls); record that fallback and its test result
in the PR. The planted evaluator test alone does not verify the runtime's error logging.
