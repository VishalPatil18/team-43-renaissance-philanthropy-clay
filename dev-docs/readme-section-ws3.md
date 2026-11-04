# README section: traces, store, replay, samples (WS3)

> **For the README owner (WS5):** a ready-to-paste section written by WS3 (plan-shivaani.md §4.9).
> Everything below exists on `main` unless it says otherwise. Commands that belong to the CLI are
> shown as the Python call they wrap, because the CLI is yours.

## What a run leaves behind

Every run writes one folder. Nothing in it is edited after the run ends (NFR-PROV-2).

```
runs/<run_id>/
  manifest.json            written once, before the first model call
  trace.jsonl              one TraceEvent per line, flushed after every event
  trace.otlp.jsonl         the same events as OpenTelemetry spans (tracer: otel or tee)
  tracer_metrics.json      capture overhead per tracer (tracer: tee)
  blobs/<sha256>           full tool results; the trace keeps a short preview and the hash
  status.json              lifecycle state (created, running, completed, budget_stopped, ...)
  summary.json             readable account of the run; every claim cites trace event IDs
  assessments/<id>.json    one file per score, never overwritten
  report.json / .md / .html
evals/<eval_id>/           spec.yaml, plan.json, estimate.json, eval_report.*
```

Secrets are redacted before any tracer sees an event (AWS keys, tokens, `Authorization`
headers, env values). A finished run's trace and manifest cannot be reopened for writing.

## Choose or swap the tracer (J3 step 2)

The trace schema is ours (`claysandbox/contracts/trace.py`); tracers only serialise it. Swap by name
in the eval spec, no code change:

```yaml
tracer: {name: jsonl}                                  # default
tracer: {name: otel}                                   # also writes trace.otlp.jsonl
tracer: {name: tee, params: {tracers: [jsonl, otel]}}  # both, plus tracer_metrics.json
```

Reading back gives the same events whichever tracer wrote them
(`tests/journeys/test_j3_tracer_swap.py`).

## Replay with no AWS (J2, J8)

```python
from claysandbox.store.local import LocalRunStore
from claysandbox.summary.deterministic import DeterministicSummarizer

store = LocalRunStore("runs", "evals", read_roots=["samples/runs"])  # samples stay untouched
trace = store.read_trace("<run_id>")            # old schema versions are upgraded on read
print(DeterministicSummarizer().summarize(trace).text())   # no model call
```

Scores and reports written for a sample go to `runs/`, never into `samples/`.
`summarizer: llm` writes a nicer summary through Bedrock; if the model's answer is unusable it falls
back to the deterministic one and sets `fallback: true`. Its cost is recorded as evaluation cost.

## Sample runs

`samples/` is committed because the sandbox is wiped after the event (C-09).

```bash
uv run python scripts/add_sample.py --run runs/<run_id> --demonstrates "clean T1 run, Kern County"
uv run python scripts/add_sample.py --reindex     # rebuild samples/README.md
```

It refuses an unfinished or incomplete run, anything that looks like a secret (it names the file and
line, never the value) and a run that already exists. Blobs over 1 MB are truncated with a
`.truncated.json` sidecar; the full copy stays in S3.

## Planted traces: proving the evaluator works (J6 step 2)

```bash
uv run python scripts/make_planted.py --good samples/runs/<clean_run> --template T1 --out samples/planted
```

Writes `good/` plus eight flawed variants (unrecovered and recovered tool failure, loop, wrong order,
forbidden tool, unknown tool, budget stop, fabricated output), built from the run's own task
reference. Run `claysandbox.evaluation.validate.validate(planted_root="samples/planted")` to see
which flaws the evaluators catch. A flaw the reference gives no material for is skipped, not faked.

## Query the store (DuckDB)

```python
from claysandbox.store.query import runs_for_eval, assessments_for_eval, token_history, list_runs

runs_for_eval(store, "<eval_id>")
token_history(store, "T1", "<model_id>", harness="strands")   # median tokens, for the cost estimate
store.query("SELECT model_id, count(*) AS n FROM manifests WHERE eval_id = $e GROUP BY 1", {"e": "<eval_id>"})
```

Tables: `manifests`, `status`, `assessments`, `run_ends`. Pass values as `$name` parameters. Once the
tables are loaded, file access is switched off, so a query cannot read or write files. 360 runs
query in under a second. Needs the `duckdb` package (see "Known gaps").

## Mirror to S3 (`local+s3`)

```yaml
store: {name: local+s3, params: {bucket: my-bucket}}   # or leave bucket out: infra/outputs.json, then $CLAYSANDBOX_BUCKET
```

`mirror_run(run_id)` uploads a finished run to `s3://<bucket>/runs/<run_id>/`; `mirror_eval` does the
same for an eval. `sync_down("runs/")` pulls Fargate-written runs before scoring. Manifests, traces and
specs are never overwritten, in S3 or locally, and keys coming back from S3 are checked so they cannot
write outside the local folder.

## Compare tracers

Record with `tee`, then (the composition root passes the readers in, so `tracing` never imports `store`):

```python
from claysandbox.store.reader import TRACE_FORMAT_READERS
from claysandbox.tracing.compare import compare_tracers, render_text

result = compare_tracers(["runs/<run_id>", ...], TRACE_FORMAT_READERS)
print(render_text(result))                       # overhead, events lost, fidelity per tracer
result.to_measurement_comparison()               # WS4's MeasurementComparison shape
```

## Decision O-4: how traces reach X-Ray

Spans go over OTLP/HTTP to a **local ADOT collector** that forwards to X-Ray/CloudWatch (option a),
not straight to the X-Ray endpoint with SigV4 (option b). Request signing and AWS credentials stay out
of this process, and the collector config holds the region and role. Set
`tracer: {name: otel, params: {endpoint: "http://localhost:4318/v1/traces"}}`. The task role needs
`xray:PutTraceSegments` and `xray:PutTelemetryRecords` (WS1: add them to the CDK task role if the
collector runs in the task). Trace IDs start with the epoch time, which X-Ray requires.

## Known gaps

- **The remote OTel export has not been run against a real collector or X-Ray.** Only the local file
  copy is tested. Acceptance "a live run with `tracer: otel` shows a trace in the X-Ray console" is open.
- **Two packages are not project dependencies yet:** `opentelemetry-exporter-otlp-proto-http` (only
  needed when an `endpoint` is set) and `duckdb` (currently in the dev group only; the Docker image
  installs `--no-dev`, so workers are safe because it is imported lazily, but whatever runs
  statistics needs it as a normal dependency).
- `tracing.compare` reads only `trace.jsonl` and `trace.otlp.jsonl`; `token_history` reads only
  `trace.jsonl`.
- Task-instance IDs are assumed to look like `T1:<aoi>` (the template is the part before `:`).
