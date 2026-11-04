"""Tracer conformance (arch §7.7): every registered tracer round-trips events,
never raises into the caller, and flushes on close."""

from __future__ import annotations

from pathlib import Path

import pytest

import claysandbox.contracts.fakes
import claysandbox.tracing.jsonl  # noqa: F401  registers JsonlTracer (registry_bootstrap does this later)
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import _REGISTRY, resolve
from claysandbox.contracts.trace import parse_event
from claysandbox.tracing.sink import RunEventSink

TRACERS = sorted(name for kind, name in _REGISTRY if kind == "tracer")


def read_back(tracer, run_dir: Path):
    if hasattr(tracer, "events"):
        return list(tracer.events)
    path = Path(run_dir) / "trace.jsonl"
    return [parse_event(line) for line in path.read_text().splitlines() if line.strip()]


@pytest.mark.parametrize("name", TRACERS)
def test_round_trip_equal_events(name, tmp_path):
    tracer = resolve("tracer", name)()
    tracer.open("run-1", tmp_path)
    sink = RunEventSink("run-1", tmp_path, tracer)
    sent = [sink.emit(e) for e in scripted_events()]
    tracer.close()
    assert read_back(tracer, tmp_path) == sent
    assert [e.seq for e in sent] == list(range(len(sent)))


@pytest.mark.parametrize("name", TRACERS)
def test_emit_never_raises(name, tmp_path):
    tracer = resolve("tracer", name)()
    tracer.open("run-2", tmp_path)
    tracer.close()  # emitting after close must not raise
    sink = RunEventSink("run-2", tmp_path, tracer)
    for e in scripted_events():
        sink.emit(e)


@pytest.mark.parametrize("name", TRACERS)
def test_flush_on_close(name, tmp_path):
    tracer = resolve("tracer", name)()
    tracer.open("run-3", tmp_path)
    sink = RunEventSink("run-3", tmp_path, tracer)
    sink.emit(scripted_events()[0])
    tracer.close()
    assert len(read_back(tracer, tmp_path)) == 1
