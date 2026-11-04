# team-43-renaissance-philanthropy-clay

## Agent runtime, budgets, cost and cloud execution

This section covers the parts that make the agent run (workstream WS1). The rest of the README
(overall structure, quick start for live runs, replay and comparisons) is written by WS5.

### Setup

```bash
curl -LsSf https://astral.sh/uv/install.sh | sh   # uv
uv python install 3.12
uv sync                                           # add `--group infra` for the CDK app
uv run pytest                                     # unit, conformance and journey tests, no AWS
export AWS_REGION=us-west-2 AWS_PROFILE=<your sandbox profile>
```

### Models

Model IDs and inference parameters come only from the spec (`model.params.model_id`), never from
code or the environment. The IDs confirmed for the sandbox account are in
[`specs/README.md`](specs/README.md). Re-check them (and your own access) any time with:

```bash
uv run python scripts/check_models.py              # tries every role and prints the confirmed IDs
uv run python scripts/smoke_live.py                # Nova Lite + Strands, one canned tool, < $0.001
uv run python scripts/smoke_live.py --harness converse_loop
```

Claude models need a cross-region inference profile ID (`us.anthropic.claude-sonnet-4-6`); the bare
ID is rejected by Bedrock.

### Harnesses

| Name | What it is |
|---|---|
| `strands` | Strands Agents runs the loop. Its model provider and every tool are bridged to our instrumented wrappers, so Strands never calls Bedrock or an MCP server itself |
| `converse_loop` | About 100 lines, no framework: call the model, run its tools in order, repeat |

Both receive the same model adapter, tool session and guards, and produce the same events. Swap
them with `harness: {name: converse_loop}` in the spec. Each stops after `max_cycles` /
`max_turns` (default 100) as a last resort, well above the budget guards.

### Budget guard and loop guard

Per-run limits go in `budget.run`. Any limit you leave out is off:

```yaml
budget:
  run:  {max_steps: 25, max_tokens: 150000, max_usd: 0.75, max_seconds: 300}
  eval: {max_usd: 120}          # no new runs start once this is spent; running ones finish
loop_guard: {max_identical_calls: 3}   # the 4th identical call in a row stops the run
```

- Limits are checked **before** each model call and tool call, so a run can overshoot by at most one
  call. The `guard_stop` event records the limit and the observed value.
- A stop ends the run as `budget_stopped` (it counts as a failure and is still scored). The loop
  guard is on by default; set `max_identical_calls` higher to relax it.
- `max_seconds` also starts a watchdog timer. A Bedrock call already in flight can't be
  interrupted, so the stop happens at the next call.
- Always set `budget.run.max_usd` on live specs. Tell the team lead before any eval estimated over
  $20; the sandbox cap is $500 for everything.

### Prices and the cost estimate

`pricing/prices.yaml` is a versioned price table. Every `model_call` event stores its `cost_usd`
and the `price_table_version`. To refresh it from the AWS Price List API:

```bash
uv run python scripts/refresh_prices.py --dry-run   # prints the diff, writes nothing
uv run python scripts/refresh_prices.py             # writes a new version; review and commit it
```

Claude prices are not in the Price List API, so those entries are typed by hand and kept as they
are. Costs are estimates, not the bill.

The pre-flight estimate (`runtime/estimate.py`) predicts tokens per run from the median of stored
completed runs with the same template, model and harness, then the same template and model, then a
default per template that is **flagged as a guess**. It adds the summary and LLM-evaluator calls
and Requester-Pays reads (plus Fargate compute time when `executor` is `fargate`), and sets
`exceeds_eval_cap` against `budget.eval.max_usd`. Launching an
eval over its cap must be blocked by the service.

### Docker

One image runs the CLI, the run worker and the MCP servers, on a laptop and on Fargate.

```bash
docker build -f docker/Dockerfile --build-arg GIT_SHA=$(git rev-parse HEAD) -t clay-sandbox .
# add --build-arg WITH_NODE=true if a tool set uses npx servers
```

- MCP servers listed in `toolsets/*.yaml` must be pinned (`name@1.2.3`). The build fails on an
  unpinned one and pre-installs the pinned ones, so the container runs with `UV_OFFLINE=1`.
- The image runs as a non-root user and holds no credentials. Pass `AWS_*` variables, or use the
  Fargate task role.
- The entry point is `clay-sandbox`, provided by the CLI workstream.

### Running on AWS (CDK and Fargate)

The CDK app in `infra/` creates the S3 bucket, ECR repository, VPC (public subnets, no NAT), ECS
cluster, Fargate task definition, a least-privilege task role (Bedrock on the listed models only,
the sandbox bucket, the NAIP Requester-Pays buckets, X-Ray) and a 7-day log group.

```bash
uv sync --group infra
cd infra
cdk synth                         # no AWS account needed; this is what CI runs
cdk bootstrap                     # once per account and region
cdk deploy                        # creates real resources; the sandbox account only
cd ..
uv run python infra/write_outputs.py     # writes infra/outputs.json for the Fargate executor

# push the worker image
aws ecr get-login-password | docker login --username AWS --password-stdin <RepositoryUri host>
docker tag clay-sandbox <RepositoryUri>:latest && docker push <RepositoryUri>:latest
```

Allowed models and NAIP buckets are context values in `infra/cdk.json` (`bedrockModelIds`,
`naipBuckets`). An inference profile ID needs permission on the profile and on the underlying model
in every region it routes to; the stack handles that. Use it in a spec with
`executor: {name: fargate, params: {max_parallel: 4}}`. The Fargate executor writes each request to
`s3://<bucket>/requests/<run_id>.json`, starts a task with
`clay-sandbox worker --request s3://...`, and reads `runs/<run_id>/status.json` when it stops.
`cdk destroy` removes everything (the bucket is emptied automatically).

## Tools and tasks

This section covers what the agent can call and what it's asked to do (workstream WS2). Details:
[`toolsets/README.md`](toolsets/README.md) and [`tasks/README.md`](tasks/README.md).

### Tool sets

A tool set is a YAML file in `toolsets/`: pinned MCP servers plus a map from capabilities
(`dataset_discovery`, `imagery_search`, `geocode`, `embedding_similarity`) to concrete tools.
Choose one with `toolset: T1` in the spec.

| Tool set | Servers |
|---|---|
| `T0` | Registry of Open Data on AWS (`awslabs.roda-mcp-server@0.1.7`) |
| `T1` | T0 + `stac-mcp@6.5.0` (NAIP and other STAC imagery) + `@cyanheads/openstreetmap-mcp-server@0.7.0` (Node ≥ 24) + our `clay-embeddings` |
| `T1-faulty` | test only: failing STAC, timing-out OSM and a dead server, for journey J4 |

Every server starts as a fresh subprocess per run with a scrubbed environment; no server in these
tool sets gets AWS credentials. Failed calls come back to the agent as error results
(`tool_error`, `tool_timeout`, `server_unavailable`), never as crashes.

```bash
uv run python scripts/smoke_mcp.py --schemas      # start each server, list tools, make one call
```

### Tasks

Five templates over six US counties give 30 task instances (`T1@us-ca-kern`, ...), each with a
versioned, script-built answer key in `tasks/references/`:

| Template | Task |
|---|---|
| T1 | NAIP items for 2022 in a small box in the county |
| T2 | Up to 10 open imagery, elevation or land-cover datasets covering the county |
| T3 | Existing utility-scale solar sites in the county (two counties have none) |
| T4 | The 10 places most similar to a given point, by Clay embeddings |
| T5 | "Get me good imagery for <county>" (deliberately ambiguous) |

```bash
uv run python -m claysandbox.tasks list                         # instances and reference versions
uv run python -m claysandbox.tasks build --template T1          # rebuild references (new version only if changed)
```

### Clay embeddings (`clay-embeddings` MCP server)

T4 and tool set T1 need the staged embeddings (gitignored, about 160 MB):

```bash
uv run python scripts/stage_embeddings.py          # Jan + Jul 2024 for the six counties, no credentials
uv run python -m clay_embeddings                   # the server alone (stdio)
```

If your environment was created before this server was added, run
`uv sync --reinstall-package claysandbox` once so `python -m clay_embeddings` resolves.

### Data attribution

- Contains Clay v1.5 embeddings by LGND (Sentinel-2 L2A, monthly aggregated), licensed CC BY 4.0,
  https://source.coop/clay/lgnd-embeddings. Sentinel-2 data: Copernicus Sentinel data, processed by
  ESA.
- Contains data © OpenStreetMap contributors, available under the Open Database License (ODbL)
  1.0, https://www.openstreetmap.org/copyright.
- Solar PV reference sites from Global Renewables Watch v1.0 (Microsoft, Planet and The Nature
  Conservancy), MIT License, https://github.com/microsoft/global-renewables-watch.
- NAIP imagery courtesy of the USDA Farm Service Agency (public domain). County boundaries: U.S.
  Census Bureau TIGERweb (public domain).
