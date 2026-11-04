from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

import pytest

from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.store.local import LocalRunStore
from claysandbox.tracing.jsonl import JsonlTracer
from claysandbox.tracing.sink import RunEventSink

_spec = importlib.util.spec_from_file_location(
    "add_sample", Path(__file__).resolve().parents[3] / "scripts" / "add_sample.py"
)
assert _spec and _spec.loader
sample = importlib.util.module_from_spec(_spec)
sys.modules["add_sample"] = sample
_spec.loader.exec_module(sample)

MANIFEST = {
    "run_id": "run-1",
    "eval_id": "e1",
    "task_instance_id": "T1:kern",
    "model": {"params": {"model_id": "nova-pro"}},
    "harness": {"name": "strands"},
}


def finish_run(root: Path, run_id="run-1", *, blob: bytes | None = None, state="completed"):
    store = LocalRunStore(root / "runs", root / "evals")
    store.create_run({**MANIFEST, "run_id": run_id})
    d = store.run_dir(run_id)
    tracer = JsonlTracer()
    tracer.open(run_id, d)
    sink = RunEventSink(run_id, d, tracer)
    for e in scripted_events():
        sink.emit(e)
    if blob is not None:
        sink.put_blob(blob)
    tracer.close()
    if state:
        store.write_status(run_id, state)
    return d


@pytest.fixture
def samples(tmp_path):
    return tmp_path / "samples" / "runs"


def test_adds_a_finished_run_with_its_sidecar_and_an_index_row(tmp_path, samples):
    src = finish_run(tmp_path)
    dest = sample.add_sample(src, samples, "clean T1 run, Kern County")
    assert dest == samples / "run-1"
    for name in ("manifest.json", "trace.jsonl", "status.json", "sample.json"):
        assert (dest / name).exists()
    assert (dest / "trace.jsonl").read_bytes() == (src / "trace.jsonl").read_bytes()
    side = json.loads((dest / "sample.json").read_text())
    assert side["demonstrates"] == "clean T1 run, Kern County" and side["truncated_blobs"] == []
    index = (samples.parent / "README.md").read_text()
    assert (
        "| run-1 | T1:kern | nova-pro / strands | completed | 3 | clean T1 run, Kern County |"
        in index
    )
    assert "do not edit it by hand" in index


def test_a_stored_sample_replays_through_the_store_as_a_read_only_root(tmp_path, samples):
    src = finish_run(tmp_path)
    sample.add_sample(src, samples, "demo")
    store = LocalRunStore(
        tmp_path / "other" / "runs", tmp_path / "other" / "evals", read_roots=[samples]
    )
    trace = store.read_trace("run-1")
    assert trace.incomplete is False and trace.events[-1].type == "run_end"
    assert store.read_status("run-1").state == "completed"


def test_samples_are_immutable_a_second_add_is_refused(tmp_path, samples):
    src = finish_run(tmp_path)
    sample.add_sample(src, samples, "first")
    before = (samples / "run-1" / "sample.json").read_text()
    with pytest.raises(sample.SampleError, match="already exists"):
        sample.add_sample(src, samples, "second")
    assert (samples / "run-1" / "sample.json").read_text() == before


def test_refuses_a_run_that_is_not_finished(tmp_path, samples):
    src = finish_run(tmp_path, state="running")
    with pytest.raises(sample.SampleError, match="not finished"):
        sample.add_sample(src, samples, "x")
    assert not (samples / "run-1").exists()


def test_refuses_a_run_with_an_incomplete_trace(tmp_path, samples):
    src = finish_run(tmp_path)
    trace = src / "trace.jsonl"
    trace.chmod(0o644)
    trace.write_text("\n".join(trace.read_text().splitlines()[:-1]) + "\n")  # drop run_end
    with pytest.raises(sample.SampleError, match="incomplete trace"):
        sample.add_sample(src, samples, "x")


def test_refuses_a_run_missing_its_files(tmp_path, samples):
    src = finish_run(tmp_path)
    (src / "status.json").unlink()
    with pytest.raises(sample.SampleError, match="no status.json"):
        sample.add_sample(src, samples, "x")


def test_a_secret_stops_everything_and_the_message_never_contains_it(tmp_path, samples):
    secret = "AKIAIOSFODNN7EXAMPLE"
    src = finish_run(tmp_path)
    # A leak that got past redaction (the sink itself would have redacted this), written directly.
    (src / "blobs").mkdir(exist_ok=True)
    (src / "blobs" / "leaky").write_text(f"line one\nleaked {secret} here\n")
    with pytest.raises(sample.SampleError) as err:
        sample.add_sample(src, samples, "x")
    message = str(err.value)
    assert "possible secrets" in message and "blobs/" in message and ":2" in message
    assert secret not in message
    assert not (samples / "run-1").exists()


def test_a_secret_in_the_manifest_is_found_too(tmp_path, samples):
    src = finish_run(tmp_path)
    manifest = src / "manifest.json"
    manifest.chmod(0o644)
    manifest.write_text(json.dumps({**MANIFEST, "note": "Authorization: Bearer abcdefgh12345678"}))
    with pytest.raises(sample.SampleError, match=r"manifest\.json:1"):
        sample.add_sample(src, samples, "x")


def test_oversized_blobs_are_truncated_with_a_sidecar_and_small_ones_kept(tmp_path, samples):
    big = b"0123456789" * 50  # 500 bytes
    src = finish_run(tmp_path, blob=big)
    small_ref = RunEventSink("run-1", src, JsonlTracer()).put_blob(b"tiny blob")[0]  # same dir
    dest = sample.add_sample(src, samples, "x", max_blob_bytes=100)
    big_name = hashlib.sha256(big).hexdigest()
    kept = dest / "blobs" / big_name
    assert kept.read_bytes() == big[:100]
    meta = json.loads((dest / "blobs" / f"{big_name}.truncated.json").read_text())
    assert meta == {
        "truncated": True,
        "original_bytes": 500,
        "original_sha256": big_name,
        "kept_bytes": 100,
    }
    assert (dest / small_ref).read_bytes() == b"tiny blob"
    assert not (dest / f"{small_ref}.truncated.json").exists()
    assert json.loads((dest / "sample.json").read_text())["truncated_blobs"] == [
        f"blobs/{big_name}"
    ]


def test_a_failed_replay_check_leaves_no_partial_sample(tmp_path, samples, monkeypatch):
    src = finish_run(tmp_path)

    def fail(_):
        raise sample.SampleError("the copied trace does not read back complete")

    monkeypatch.setattr(sample, "check_replayable", fail)
    with pytest.raises(sample.SampleError):
        sample.add_sample(src, samples, "x")
    assert not (samples / "run-1").exists()
    assert not (samples.parent / "README.md").exists()  # and the index was not touched


def test_the_replay_check_rejects_a_summary_that_cites_missing_events(tmp_path, monkeypatch):
    src = finish_run(tmp_path)

    class BadSummarizer:
        def summarize(self, trace):
            from claysandbox.contracts.summary import Claim, Summary

            return Summary(run_id="r", claims=[Claim(claim="x", event_ids=["nope"])])

    monkeypatch.setattr(sample, "DeterministicSummarizer", BadSummarizer)
    with pytest.raises(sample.SampleError, match="cites events that do not exist"):
        sample.check_replayable(src)


def test_index_lists_every_sample_sorted_and_escapes_pipes(tmp_path, samples):
    sample.add_sample(finish_run(tmp_path, "run-b"), samples, "second | with a pipe")
    sample.add_sample(finish_run(tmp_path, "run-a", state="budget_stopped"), samples, "first")
    rows = [
        line
        for line in (samples.parent / "README.md").read_text().splitlines()
        if line.startswith("| run-")
    ]
    assert [r.split(" | ")[0] for r in rows] == ["| run-a", "| run-b"]
    assert "budget_stopped" in rows[0] and "second / with a pipe" in rows[1]


def test_reindex_alone_rebuilds_the_index_and_an_empty_folder_says_so(tmp_path, samples):
    samples.mkdir(parents=True)
    assert sample.main(["--reindex", "--samples", str(samples)]) == 0
    assert "_No samples yet._" in (samples.parent / "README.md").read_text()


def test_cli_adds_and_reports_a_refusal_with_exit_code_1(tmp_path, samples, capsys):
    src = finish_run(tmp_path)
    assert (
        sample.main(["--run", str(src), "--demonstrates", "demo", "--samples", str(samples)]) == 0
    )
    assert "added" in capsys.readouterr().out
    assert (
        sample.main(["--run", str(src), "--demonstrates", "again", "--samples", str(samples)]) == 1
    )
    assert "not added: " in capsys.readouterr().err


def test_cli_requires_a_reason_for_the_sample(tmp_path, samples):
    src = finish_run(tmp_path)
    with pytest.raises(SystemExit) as err:
        sample.main(["--run", str(src), "--samples", str(samples)])
    assert err.value.code == 2
