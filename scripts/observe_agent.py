#!/usr/bin/env python3
"""Run one agent request with AgentCore Observability and print its end-to-end trace.

This is the "agents not hosted on AgentCore Runtime" path of AgentCore Observability: the
sandbox's Strands harness runs here, instrumented by the AWS Distro for OpenTelemetry (ADOT),
and its spans go to CloudWatch (log group ``aws/spans``), where the CloudWatch GenAI
Observability dashboard and the AgentCore console show them.

One request = Nova Lite + the Strands harness + the real ``T0`` MCP tool set (RODA), through the
sandbox's instrumented model/tool wrappers and guards. The prompt makes the agent call a tool.

    uv sync --group observability
    uv run python scripts/observe_agent.py            # run, then fetch and print the trace
    uv run python scripts/observe_agent.py show <trace-id>   # print a trace again

One-time account setup (already done in the sandbox account): CloudWatch Transaction Search,
see https://docs.aws.amazon.com/bedrock-agentcore/latest/devguide/observability-get-started.html
The run costs well under $0.01 (``budget.run.max_usd`` is capped at $0.05).
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import UTC, datetime, timedelta
from typing import Any

REGION = os.environ.get("AWS_REGION", "us-west-2")
SERVICE_NAME = "clay-sandbox-strands"
LOG_GROUP = "/clay-sandbox/agent-observability"
LOG_STREAM = "runtime-logs"
METRIC_NAMESPACE = "ClaySandbox/Agents"
SPANS_LOG_GROUP = "aws/spans"
_MARKER = "CLAYSANDBOX_OBSERVED"

SYSTEM = "You are a geospatial data assistant. Use the tools provided. Return JSON only."
PROMPT = (
    "Search the Registry of Open Data on AWS for datasets about NAIP aerial imagery. "
    'Return {"datasets": [<dataset slug>, ...]} with at most 3 entries.'
)


# -- setup ---------------------------------------------------------------------------------


def otel_environment() -> dict[str, str]:
    """The ADOT settings from the AgentCore Observability guide (non-runtime agents)."""
    return {
        "AGENT_OBSERVABILITY_ENABLED": "true",
        "OTEL_PYTHON_DISTRO": "aws_distro",
        "OTEL_PYTHON_CONFIGURATOR": "aws_configurator",
        "OTEL_EXPORTER_OTLP_PROTOCOL": "http/protobuf",
        "OTEL_EXPORTER_OTLP_LOGS_HEADERS": (
            f"x-aws-log-group={LOG_GROUP},x-aws-log-stream={LOG_STREAM},"
            f"x-aws-metric-namespace={METRIC_NAMESPACE}"
        ),
        "OTEL_RESOURCE_ATTRIBUTES": f"service.name={SERVICE_NAME}",
        "OTEL_TRACES_SAMPLER": "always_on",
        "AWS_REGION": REGION,
        "AWS_DEFAULT_REGION": REGION,
    }


def ensure_log_group() -> None:
    """Create the agent's log group and stream for OTel logs (idempotent, 7-day retention)."""
    import boto3

    logs = boto3.client("logs", region_name=REGION)
    try:
        logs.create_log_group(logGroupName=LOG_GROUP)
        logs.put_retention_policy(logGroupName=LOG_GROUP, retentionInDays=7)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass
    try:
        logs.create_log_stream(logGroupName=LOG_GROUP, logStreamName=LOG_STREAM)
    except logs.exceptions.ResourceAlreadyExistsException:
        pass


def run_instrumented(model_id: str) -> str | None:
    """Run the request in a child process under ``opentelemetry-instrument``.

    Only the agent request is instrumented. Reading the trace back happens in this (plain)
    process, so the Logs Insights polling does not create traces of its own.
    """
    import shutil
    import subprocess
    import tempfile

    venv_bin = os.path.join(os.path.dirname(sys.executable), "opentelemetry-instrument")
    launcher = venv_bin if os.path.exists(venv_bin) else shutil.which("opentelemetry-instrument")
    if launcher is None:
        print(
            "opentelemetry-instrument not found: run `uv sync --group observability`",
            file=sys.stderr,
        )
        return None
    with tempfile.TemporaryDirectory() as tmp:
        out = os.path.join(tmp, "trace_id")
        env = {**os.environ, **otel_environment(), _MARKER: out}
        code = subprocess.call(
            [launcher, sys.executable, __file__, "run", "--model-id", model_id], env=env
        )
        if code != 0 or not os.path.exists(out):
            print(f"instrumented run failed (exit {code})", file=sys.stderr)
            return None
        with open(out, encoding="utf-8") as f:
            return f.read().strip()


# -- the instrumented request ---------------------------------------------------------------


def run_request(model_id: str) -> str:
    """Run one request inside a root span. Returns the trace ID (32 hex characters)."""
    from opentelemetry import baggage, context, trace

    import claysandbox.platform.registry_bootstrap  # noqa: F401  (registers the plugins)
    from claysandbox.contracts.fakes.sink import MemoryEventSink
    from claysandbox.contracts.ids import new_id
    from claysandbox.contracts.registry import resolve
    from claysandbox.contracts.runtime import RunContext
    from claysandbox.contracts.spec import RunLimits
    from claysandbox.runtime.guard import build_guard
    from claysandbox.runtime.instrument import InstrumentedModel, InstrumentedTools, ParentLinks
    from claysandbox.runtime.pricing import YamlPriceTable
    from claysandbox.tools.launcher import McpToolSetProvider

    run_id = new_id()
    tracer = trace.get_tracer("claysandbox")
    token = context.attach(baggage.set_baggage("session.id", run_id))
    sink = MemoryEventSink(run_id)
    guard = build_guard(RunLimits(max_usd=0.05, max_steps=8, max_seconds=180))
    links = ParentLinks()
    session = McpToolSetProvider("toolsets").open_blocking("T0")
    try:
        with tracer.start_as_current_span(
            "clay_sandbox.run",
            attributes={
                "clay.run_id": run_id,
                "clay.harness": "strands",
                "clay.toolset": "T0",
                "gen_ai.request.model": model_id,
                "session.id": run_id,
            },
        ) as root:
            ctx = RunContext(
                run_id=run_id,
                prompt=PROMPT,
                system_prompt=SYSTEM,
                model=InstrumentedModel(
                    resolve("model", "bedrock")({"model_id": model_id, "max_tokens": 800}),
                    sink,
                    guard,
                    YamlPriceTable(),
                    links,
                ),
                tools=InstrumentedTools(session, sink, guard, links),
                events=sink,
            )
            outcome = resolve("harness", "strands")({}).run(ctx)
            root.set_attribute("clay.outcome", outcome.state)
            trace_id = format(root.get_span_context().trace_id, "032x")
    finally:
        guard.close()
        session.close()
        context.detach(token)

    print(f"run_id={run_id} outcome={outcome.state}")
    print(f"output: {json.dumps(outcome.output)[:300]}")
    print("sandbox events:")
    for e in sink.events:
        if e.type == "model_call":
            print(
                f"  {e.seq} model_call in={e.input_tokens} out={e.output_tokens} "
                f"cost=${e.cost_usd:.6f} stop={e.stop_reason}"
            )
        elif e.type == "tool_call":
            print(f"  {e.seq} tool_call  {e.server}.{e.tool} -> {e.status}")
        else:
            print(f"  {e.seq} {e.type} {getattr(e, 'error', None)}")
    print(f"totals: {guard.totals()}")

    provider = trace.get_tracer_provider()
    if hasattr(provider, "force_flush"):
        provider.force_flush(30_000)
    print(f"TRACE_ID={trace_id}")
    return trace_id


# -- reading the trace back from CloudWatch -------------------------------------------------


def fetch_spans(trace_id: str, wait_s: int) -> list[dict[str, Any]]:
    """Query ``aws/spans`` with Logs Insights until the trace's spans arrive."""
    import boto3

    logs = boto3.client("logs", region_name=REGION)
    deadline = time.monotonic() + wait_s
    start = int((datetime.now(UTC) - timedelta(hours=3)).timestamp())
    spans: list[dict[str, Any]] = []
    while True:
        end = int(datetime.now(UTC).timestamp()) + 60
        query_id = logs.start_query(
            logGroupName=SPANS_LOG_GROUP,
            startTime=start,
            endTime=end,
            queryString=f"fields @message | filter traceId = '{trace_id}' | limit 200",
        )["queryId"]
        while True:
            result = logs.get_query_results(queryId=query_id)
            if result["status"] in ("Complete", "Failed", "Cancelled", "Timeout"):
                break
            time.sleep(1)
        spans = [
            json.loads(next(f["value"] for f in row if f["field"] == "@message"))
            for row in result.get("results", [])
        ]
        if spans or time.monotonic() > deadline:
            return spans
        print(f"  waiting for spans in {SPANS_LOG_GROUP}... ({len(spans)} so far)")
        time.sleep(15)


def print_tree(spans: list[dict[str, Any]]) -> None:
    by_id = {s["spanId"]: s for s in spans}
    children: dict[str | None, list[dict[str, Any]]] = {}
    for s in spans:
        parent = s.get("parentSpanId") if s.get("parentSpanId") in by_id else None
        children.setdefault(parent, []).append(s)
    for group in children.values():
        group.sort(key=lambda s: int(s.get("startTimeUnixNano", 0)))
    t0 = min(int(s.get("startTimeUnixNano", 0)) for s in spans)

    def show(span: dict[str, Any], depth: int) -> None:
        a = span.get("attributes", {})
        start = (int(span.get("startTimeUnixNano", 0)) - t0) / 1e6
        dur = (int(span.get("endTimeUnixNano", 0)) - int(span.get("startTimeUnixNano", 0))) / 1e6
        labels = {
            "gen_ai.operation.name": "op",
            "gen_ai.tool.name": "tool",
            "gen_ai.request.model": "model",
            "gen_ai.usage.input_tokens": "in",
            "gen_ai.usage.output_tokens": "out",
            "rpc.method": "aws",
            "clay.outcome": "outcome",
        }
        extras = [f"{label}={a[key]}" for key, label in labels.items() if key in a]
        status = span.get("status", {}).get("code", "")
        print(
            f"  {'  ' * depth}{span['name']:<{48 - 2 * depth}} +{start:8.0f} ms  "
            f"{dur:8.0f} ms  {status:<6} {' '.join(extras)}"
        )
        for child in children.get(span["spanId"], []):
            show(child, depth + 1)

    for root in children.get(None, []):
        show(root, 0)


def show_trace(trace_id: str, wait_s: int) -> int:
    print(f"\nFetching trace {trace_id} from CloudWatch ({SPANS_LOG_GROUP}, {REGION})")
    spans = fetch_spans(trace_id, wait_s)
    if not spans:
        print(
            "No spans yet. Transaction Search can take ~10 minutes after it is first enabled; "
            f"retry with: uv run python scripts/observe_agent.py show {trace_id}"
        )
        return 1
    services = sorted(
        {s.get("resource", {}).get("attributes", {}).get("service.name", "?") for s in spans}
    )
    print(f"{len(spans)} spans, service {services}\n")
    print(f"  {'span':<48} {'start':>10}  {'duration':>11}  status")
    print_tree(spans)
    tools = [
        s for s in spans if s.get("attributes", {}).get("gen_ai.operation.name") == "execute_tool"
    ]
    print(f"\ntool-call spans: {[s['name'] for s in tools]}")
    print(
        "Console: CloudWatch > GenAI Observability > Bedrock AgentCore > Traces, or "
        f"CloudWatch > Transaction Search, filter traceId = {trace_id}"
    )
    return 0 if tools else 1


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    sub = parser.add_subparsers(dest="cmd")
    run = sub.add_parser("run", help="run one request and show its trace (default)")
    run.add_argument("--model-id", default="us.amazon.nova-lite-v1:0")
    run.add_argument("--wait", type=int, default=600, help="seconds to wait for spans")
    show = sub.add_parser("show", help="print the trace of an earlier run")
    show.add_argument("trace_id")
    show.add_argument("--wait", type=int, default=60)
    args = parser.parse_args(sys.argv[1:] or ["run"])

    if args.cmd == "show":
        return show_trace(args.trace_id, args.wait)

    marker = os.environ.get(_MARKER)
    if marker:  # we are the instrumented child: run the request, hand back the trace ID
        trace_id = run_request(args.model_id)
        with open(marker, "w", encoding="utf-8") as f:
            f.write(trace_id)
        return 0

    ensure_log_group()
    trace_id = run_instrumented(args.model_id)
    if trace_id is None:
        return 1
    return show_trace(trace_id, args.wait)


if __name__ == "__main__":
    sys.exit(main())
