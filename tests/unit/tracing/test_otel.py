from __future__ import annotations

import json
import sys
import time

import pytest
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.store import StoreWriteRefused
from claysandbox.contracts.trace import GuardStop, RunEnd
from claysandbox.store.reader import read_otlp_events, read_trace
from claysandbox.tracing.otel import OTLP_FILE, OtelTracer
from claysandbox.tracing.sink import RunEventSink


def run(tmp_path, events=None, params=None):
    tracer = OtelTracer(params)
    tracer.open("r", tmp_path)
    sink = RunEventSink("r", tmp_path, tracer)
    sent = [sink.emit(e) for e in (events if events is not None else scripted_events())]
    tracer.close()
    return tracer, sent


def spans(tmp_path):
    out = []
    for line in (tmp_path / OTLP_FILE).read_text().splitlines():
        for rs in json.loads(line)["resourceSpans"]:
            for ss in rs["scopeSpans"]:
                out.extend(ss["spans"])
    return out


def attrs(span):
    return {a["key"]: a["value"] for a in span["attributes"]}


def test_registered_and_events_round_trip_exactly(tmp_path):
    assert resolve("tracer", "otel") is OtelTracer
    _, sent = run(tmp_path)
    trace = read_trace(tmp_path)  # falls back to trace.otlp.jsonl
    assert trace.events == sent and trace.incomplete is False


def test_every_event_is_a_child_of_one_root_run_span(tmp_path):
    _, sent = run(tmp_path)
    all_spans = spans(tmp_path)
    roots = [s for s in all_spans if not s["parentSpanId"]]
    kids = [s for s in all_spans if s["parentSpanId"]]
    assert len(roots) == 1 and len(kids) == len(sent)
    assert {k["parentSpanId"] for k in kids} == {roots[0]["spanId"]}
    assert len({s["traceId"] for s in all_spans}) == 1
    root = attrs(roots[0])
    assert root["clay.run_id"]["stringValue"] == "r"
    assert root["clay.task_instance"]["stringValue"] == "T1:kern"
    assert root["clay.config"]["stringValue"] == "fake-baseline"


def test_trace_id_starts_with_a_recent_timestamp_for_xray(tmp_path):
    run(tmp_path)
    trace_id = spans(tmp_path)[0]["traceId"]
    assert len(trace_id) == 32
    assert abs(int(trace_id[:8], 16) - time.time()) < 60


def test_model_and_tool_spans_use_genai_attributes(tmp_path):
    run(tmp_path)
    by_type = {}
    for s in spans(tmp_path):
        a = attrs(s)
        if "clay.event_type" in a:
            by_type.setdefault(a["clay.event_type"]["stringValue"], []).append((s, a))
    chat, a = by_type["model_call"][0]
    assert chat["name"] == "chat fake-model"
    assert a["gen_ai.operation.name"]["stringValue"] == "chat"
    assert a["gen_ai.system"]["stringValue"] == "aws.bedrock"
    assert a["gen_ai.usage.input_tokens"]["intValue"] == "420"
    assert a["gen_ai.usage.output_tokens"]["intValue"] == "60"
    tool, a = by_type["tool_call"][0]
    assert a["gen_ai.operation.name"]["stringValue"] == "execute_tool"
    assert a["gen_ai.tool.name"]["stringValue"] == "search_items"


def test_failed_tool_call_is_an_error_span_with_an_error_event(tmp_path):
    run(tmp_path)
    tools = [s for s in spans(tmp_path) if s["name"].startswith("execute_tool")]
    failed, ok = tools[0], tools[1]
    assert failed["status"]["code"] == "ERROR"
    ev = failed["events"][0]
    assert ev["name"] == "clay.error"
    kinds = {a["key"]: a["value"] for a in ev["attributes"]}
    assert kinds["error.kind"]["stringValue"] == "tool_timeout"
    assert kinds["error.source"]["stringValue"] == "tool"
    assert kinds["error.retryable"]["boolValue"] is True
    assert ok["status"]["code"] == "UNSET" and ok["events"] == []


def test_guard_stop_becomes_a_span_event(tmp_path):
    events = scripted_events()[:2] + [
        GuardStop(limit="max_usd", limit_value=0.75, observed_value=0.78),
        RunEnd(state="budget_stopped"),
    ]
    run(tmp_path, events)
    stop = next(s for s in spans(tmp_path) if s["name"] == "guard_stop")
    assert stop["status"]["code"] == "ERROR"
    assert stop["events"][0]["name"] == "clay.guard_stop"
    assert attrs(stop)["clay.guard.limit"]["stringValue"] == "max_usd"


def test_span_times_come_from_event_timestamps(tmp_path):
    _, sent = run(tmp_path)
    model = next(s for s in spans(tmp_path) if s["name"].startswith("chat"))
    first = next(e for e in sent if e.type == "model_call")
    assert int(model["startTimeUnixNano"]) == int(first.ts_start.timestamp() * 1e9)
    assert int(model["endTimeUnixNano"]) == int(first.ts_end.timestamp() * 1e9)


def test_a_crash_before_the_root_ends_keeps_every_event_and_is_incomplete(tmp_path):
    tracer = OtelTracer()
    tracer.open("r", tmp_path)
    sink = RunEventSink("r", tmp_path, tracer)
    sent = [sink.emit(e) for e in scripted_events()[:4]]  # no run_end, tracer never closed
    trace = read_trace(tmp_path)
    assert trace.events == sent and trace.incomplete is True
    tracer.close()


def test_truncated_last_line_keeps_earlier_events(tmp_path):
    _, sent = run(tmp_path)
    path = tmp_path / OTLP_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:4]) + "\n" + lines[4][:40])
    events, incomplete = read_otlp_events(path)
    # one line per event, written as its span ends: 4 whole lines = events 0-3
    assert incomplete is True and events == sent[:4]


def test_garbage_envelope_marks_incomplete_instead_of_crashing(tmp_path):
    _, sent = run(tmp_path)
    path = tmp_path / OTLP_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:2] + ['{"resourceSpans": 5}'] + lines[2:]) + "\n")
    events, incomplete = read_otlp_events(path)
    assert incomplete is True and events == sent[:2]


def test_a_finished_trace_cannot_be_reopened(tmp_path):
    run(tmp_path)
    with pytest.raises(StoreWriteRefused):
        OtelTracer().open("r", tmp_path)


def test_emit_never_raises_even_if_mapping_fails(tmp_path, monkeypatch):
    tracer = OtelTracer()
    tracer.open("r", tmp_path)
    monkeypatch.setattr(tracer, "_emit", lambda e: (_ for _ in ()).throw(RuntimeError("boom")))
    RunEventSink("r", tmp_path, tracer).emit(scripted_events()[0])
    assert tracer.incomplete is True
    tracer.close()


def test_endpoint_without_the_exporter_package_is_a_clear_config_error(tmp_path, monkeypatch):
    monkeypatch.setitem(sys.modules, "opentelemetry.exporter.otlp.proto.http.trace_exporter", None)
    with pytest.raises(ConfigError) as err:
        OtelTracer({"endpoint": "http://localhost:4318/v1/traces"}).open("r", tmp_path)
    assert err.value.kind == "missing_dependency"


def test_remote_exporter_receives_every_span_and_its_time_is_measured(tmp_path, monkeypatch):
    remote = InMemorySpanExporter()
    monkeypatch.setattr(OtelTracer, "_remote_exporter", lambda self: remote)
    tracer, sent = run(tmp_path, params={"endpoint": "http://collector.invalid/v1/traces"})
    exported = remote.get_finished_spans()
    assert len(exported) == len(sent) + 1  # one per event, plus the run's root span
    assert tracer.export_batches >= 1 and tracer.export_ns_total > 0
    assert read_trace(tmp_path).events == sent  # the local file copy is complete too
