"""J3 step 2 (docs/04): change the tracer backend with no code change.

The same scripted run goes through ``jsonl`` and through ``otel`` (file exporter only, no
network). The trace keeps the same schema: reading either back gives equal ``TraceEvent``
lists (FR-2.7).
"""

from __future__ import annotations

import pytest

import claysandbox.tracing.jsonl  # noqa: F401  registers the tracers
import claysandbox.tracing.otel  # noqa: F401
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import resolve
from claysandbox.store.reader import read_trace
from claysandbox.tracing.sink import RunEventSink


def record(name: str, run_dir):
    tracer = resolve("tracer", name)()  # swapped by name only, as a spec would
    tracer.open("run-j3", run_dir)
    sink = RunEventSink("run-j3", run_dir, tracer)
    for event in scripted_events():
        sink.emit(event)
    tracer.close()
    return read_trace(run_dir)


def test_swapping_the_tracer_keeps_the_trace_schema(tmp_path):
    a = record("jsonl", tmp_path / "a")
    b = record("otel", tmp_path / "b")
    assert a.events and a.events == b.events
    assert a.incomplete is False and b.incomplete is False
    assert [e.seq for e in b.events] == list(range(len(b.events)))


@pytest.mark.parametrize("name", ["jsonl", "otel"])
def test_both_tracers_end_with_run_end_and_keep_the_error(tmp_path, name):
    trace = record(name, tmp_path)
    assert trace.events[-1].type == "run_end"
    assert [e.error.kind for e in trace.errors] == ["tool_timeout"]
