"""Tracer conformance (arch §7.7): every registered tracer round-trips events,
never raises into the caller, and flushes on close."""

from __future__ import annotations

from pathlib import Path

import pytest

import claysandbox.contracts.fakes
import claysandbox.tracing.jsonl  # noqa: F401  registers JsonlTracer
import claysandbox.tracing.otel  # noqa: F401  registers OtelTracer
import claysandbox.tracing.tee  # noqa: F401  registers TeeTracer
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import _REGISTRY, resolve
from claysandbox.store.reader import read_trace
from claysandbox.tracing.sink import RunEventSink

TRACERS = sorted(name for kind, name in _REGISTRY if kind == "tracer")


def read_back(tracer, run_dir: Path):
    """Events as a replay would see them: the in-memory list, or the store's reader."""
    if hasattr(tracer, "events"):
        return list(tracer.events)
    return list(read_trace(run_dir).events)


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
