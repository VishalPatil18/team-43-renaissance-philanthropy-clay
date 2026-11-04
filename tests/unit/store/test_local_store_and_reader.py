from __future__ import annotations

import json
import shutil
import stat

import pytest

from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.store import StoreWriteRefused
from claysandbox.contracts.trace import trace_digest
from claysandbox.store.local import LocalRunStore
from claysandbox.store.reader import UnsupportedTraceVersion, read_trace
from claysandbox.tracing.jsonl import JsonlTracer
from claysandbox.tracing.sink import RunEventSink

MANIFEST = {"run_id": "r1", "eval_id": "e1", "prompt": "find NAIP"}


def record(store: LocalRunStore, run_id: str = "r1", events=None, finish: bool = True):
    store.create_run({**MANIFEST, "run_id": run_id})
    d = store.run_dir(run_id)
    tracer = JsonlTracer()
    tracer.open(run_id, d)
    sink = RunEventSink(run_id, d, tracer)
    sent = [sink.emit(e) for e in (events if events is not None else scripted_events())]
    tracer.close()
    if finish:
        store.write_status(run_id, "completed")
    return sent


def test_live_like_run_leaves_a_complete_folder(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    sent = record(store)
    d = store.run_dir("r1")
    assert {p.name for p in d.iterdir()} >= {
        "manifest.json",
        "trace.jsonl",
        "status.json",
    }
    trace = store.read_trace("r1")
    assert trace.events == sent and trace.incomplete is False
    assert json.loads((d / "status.json").read_text())["state"] == "completed"


def test_trace_and_manifest_locked_after_run_end(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    record(store)
    with pytest.raises(StoreWriteRefused):
        store.assert_trace_writable("r1")
    for name in (
        "trace.jsonl",
        "manifest.json",
    ):  # read-only modes as a backstop (root ignores them)
        mode = (store.run_dir("r1") / name).stat().st_mode
        assert not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    with pytest.raises(StoreWriteRefused):
        store.create_run(MANIFEST)


def test_status_writes_are_atomic(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    store.create_run(MANIFEST)
    for state in ("running", "running", "completed"):
        store.write_status("r1", state)
    leftovers = [
        p.name for p in store.run_dir("r1").iterdir() if p.name.startswith(".")
    ]
    assert leftovers == []


def test_read_only_sample_root_stays_untouched(tmp_path):
    samples = tmp_path / "samples" / "runs"
    src = LocalRunStore(samples, tmp_path / "x")
    record(src, "sample1")
    before = sorted(p.relative_to(samples).as_posix() for p in samples.rglob("*"))
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals", read_roots=[samples])
    assert store.read_trace("sample1").events  # reads from the sample
    store.append_assessment("sample1", {"assessment_id": "a1", "composite": 1.0})
    store.write_report("sample1", {"ok": True}, {"report.md": "# replay"})
    after = sorted(p.relative_to(samples).as_posix() for p in samples.rglob("*"))
    assert before == after
    assert (tmp_path / "runs" / "sample1" / "assessments" / "a1.json").exists()
    assert store.list_assessments("sample1")[0]["assessment_id"] == "a1"


def test_reader_truncated_line_keeps_earlier_events(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    sent = record(store, finish=False)
    path = store.trace_path("r1")
    lines = path.read_text().splitlines()
    path.write_text(
        "\n".join(lines[:4]) + "\n" + lines[4][:30]
    )  # crash mid-write of event 4
    trace = read_trace(path.parent)
    assert trace.incomplete is True
    assert trace.events == sent[:4]


def test_reader_missing_run_end_is_incomplete(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    record(store, events=scripted_events()[:-1], finish=False)
    assert store.read_trace("r1").incomplete is True


def test_reader_rejects_newer_schema(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    record(store, finish=False)
    path = store.trace_path("r1")
    path.write_text(
        path.read_text().replace('"schema_version":"1.0"', '"schema_version":"9.0"', 1)
    )
    with pytest.raises(UnsupportedTraceVersion):
        read_trace(path.parent)


def test_blob_refs_cannot_escape_the_run(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    record(store)
    trace = store.read_trace("r1")
    with pytest.raises(ValueError):
        trace.blob("../../../etc/passwd")


def test_unsafe_ids_rejected(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    with pytest.raises(ValueError):
        store.create_run({"run_id": "../escape"})


def test_digest_compresses_middle(tmp_path):
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    many = scripted_events()[:1] + scripted_events()[1:6] * 40 + scripted_events()[-1:]
    record(store, events=many)
    trace = store.read_trace("r1")
    d = trace_digest(trace, max_chars=1500)
    assert len(d) <= 1500 and "events omitted" in d
    assert d.splitlines()[0].startswith("[r1:0] run_start")
    assert "run_end" in d.splitlines()[-1]
    shutil.rmtree(tmp_path / "runs")
