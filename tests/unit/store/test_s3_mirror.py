from __future__ import annotations

import json
import stat
from pathlib import Path

import pytest
from botocore.exceptions import ClientError

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.store import StoreWriteRefused
from claysandbox.store.s3 import S3MirrorRunStore
from claysandbox.tracing.jsonl import JsonlTracer
from claysandbox.tracing.sink import RunEventSink


class FakeS3:
    """The few S3 calls the mirror uses, in memory. Pages of 2 keys to exercise pagination."""

    def __init__(self, page_size: int = 2):
        self.objects: dict[tuple[str, str], bytes] = {}
        self.uploads: list[str] = []
        self.page_size = page_size

    def upload_file(self, Filename, Bucket, Key):  # noqa: N803  (boto3 argument names)
        self.objects[(Bucket, Key)] = Path(Filename).read_bytes()
        self.uploads.append(Key)

    def head_object(self, Bucket, Key):  # noqa: N803
        if (Bucket, Key) not in self.objects:
            raise ClientError({"Error": {"Code": "404", "Message": "Not Found"}}, "HeadObject")
        return {}

    def list_objects_v2(self, Bucket, Prefix, ContinuationToken=None):  # noqa: N803
        keys = sorted(k for (b, k) in self.objects if b == Bucket and k.startswith(Prefix))
        start = int(ContinuationToken or 0)
        page = keys[start : start + self.page_size]
        more = start + self.page_size < len(keys)
        out = {"Contents": [{"Key": k} for k in page], "IsTruncated": more}
        if more:
            out["NextContinuationToken"] = str(start + self.page_size)
        return out

    def download_file(self, Bucket, Key, Filename):  # noqa: N803
        Path(Filename).write_bytes(self.objects[(Bucket, Key)])


def make_store(tmp_path, name="a", s3=None, **kw):
    return S3MirrorRunStore(
        tmp_path / name / "runs",
        tmp_path / name / "evals",
        bucket=kw.pop("bucket", "sandbox-bucket"),
        client=s3 if s3 is not None else FakeS3(),
        **kw,
    )


def finished_run(store, run_id="r1", with_blob=True):
    store.create_run({"run_id": run_id, "eval_id": "e1", "prompt": "find NAIP"})
    d = store.run_dir(run_id)
    tracer = JsonlTracer()
    tracer.open(run_id, d)
    sink = RunEventSink(run_id, d, tracer)
    for e in scripted_events():
        sink.emit(e)
    if with_blob:
        sink.put_blob(b"a full tool result " * 50)
    tracer.close()
    store.write_summary(run_id, {"claims": []})
    store.write_status(run_id, "completed")


def test_registered_and_still_a_run_store(tmp_path):
    assert resolve("store", "local+s3") is S3MirrorRunStore
    s = make_store(tmp_path)
    finished_run(s)
    assert s.read_trace("r1").events and s.read_status("r1").state == "completed"


def test_mirror_run_uploads_the_whole_folder_under_runs_prefix(tmp_path):
    s3 = FakeS3()
    s = make_store(tmp_path, s3=s3)
    finished_run(s)
    result = s.mirror_run("r1")
    keys = {k for (_, k) in s3.objects}
    assert {
        "runs/r1/manifest.json",
        "runs/r1/trace.jsonl",
        "runs/r1/status.json",
        "runs/r1/summary.json",
    } <= keys
    assert any(k.startswith("runs/r1/blobs/") for k in keys)
    assert result["bucket"] == "sandbox-bucket" and result["prefix"] == "runs/r1/"
    assert sorted(result["uploaded"]) == sorted(keys)
    assert not any("/." in k or ".tmp" in k for k in keys)  # no temp files


def test_mirror_run_refuses_a_run_that_is_not_finished(tmp_path):
    s = make_store(tmp_path)
    s.create_run({"run_id": "live"})
    s.write_status("live", "running")
    with pytest.raises(StoreWriteRefused, match="not finished"):
        s.mirror_run("live")
    with pytest.raises(FileNotFoundError):
        s.mirror_run("nope")


def test_immutable_files_are_never_overwritten_in_s3_but_views_are_refreshed(tmp_path):
    s3 = FakeS3()
    s = make_store(tmp_path, s3=s3)
    finished_run(s)
    s.mirror_run("r1")
    s3.objects[("sandbox-bucket", "runs/r1/manifest.json")] = b"already-in-s3"
    s3.uploads.clear()
    s.write_summary("r1", {"claims": ["new"]})
    second = s.mirror_run("r1")
    assert s3.objects[("sandbox-bucket", "runs/r1/manifest.json")] == b"already-in-s3"
    assert "runs/r1/manifest.json" in second["skipped"]
    assert "runs/r1/trace.jsonl" in second["skipped"]
    assert any(k.startswith("runs/r1/blobs/") for k in second["skipped"])
    assert "runs/r1/summary.json" in second["uploaded"]  # a view: refreshed
    assert json.loads(s3.objects[("sandbox-bucket", "runs/r1/summary.json")])["claims"] == ["new"]


def test_mirror_eval(tmp_path):
    s3 = FakeS3()
    s = make_store(tmp_path, s3=s3)
    s.create_eval("e1", {"name": "demo"})
    s.write_eval_artifact("e1", "plan.json", json.dumps({"runs": ["r1"]}))
    out = s.mirror_eval("e1")
    assert {k for (_, k) in s3.objects} == {"evals/e1/spec.yaml", "evals/e1/plan.json"}
    assert out["prefix"] == "evals/e1/"
    with pytest.raises(FileNotFoundError):
        s.mirror_eval("missing")


def test_sync_down_brings_fargate_written_runs_to_another_machine(tmp_path):
    s3 = FakeS3()
    worker = make_store(tmp_path, "worker", s3=s3)
    finished_run(worker, "r1")
    finished_run(worker, "r2")
    worker.mirror_run("r1")
    worker.mirror_run("r2")
    laptop = make_store(tmp_path, "laptop", s3=s3)
    written = laptop.sync_down("runs/")  # 2 runs x several files: spans several pages
    assert len(written) >= 8
    for rid in ("r1", "r2"):
        assert laptop.read_trace(rid).events == worker.read_trace(rid).events
        assert laptop.read_manifest(rid)["prompt"] == "find NAIP"
        assert laptop.read_status(rid).state == "completed"
        blob_ref = next(p for p in (laptop.run_dir(rid) / "blobs").iterdir()).name
        assert laptop.read_trace(rid).blob(f"blobs/{blob_ref}").startswith(b"a full tool")


def test_sync_down_one_run_only(tmp_path):
    s3 = FakeS3()
    worker = make_store(tmp_path, "worker", s3=s3)
    finished_run(worker, "r1")
    finished_run(worker, "r2")
    worker.mirror_run("r1")
    worker.mirror_run("r2")
    laptop = make_store(tmp_path, "laptop", s3=s3)
    laptop.sync_down("runs/r2/")
    assert laptop.list_runs() == ["r2"]


def test_a_synced_finished_run_is_locked_like_a_local_one(tmp_path):
    s3 = FakeS3()
    worker = make_store(tmp_path, "worker", s3=s3)
    finished_run(worker)
    worker.mirror_run("r1")
    laptop = make_store(tmp_path, "laptop", s3=s3)
    laptop.sync_down("runs/r1/")
    mode = laptop.trace_path("r1").stat().st_mode
    assert not mode & (stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH)
    with pytest.raises(StoreWriteRefused):
        laptop.assert_trace_writable("r1")


def test_sync_down_never_replaces_local_protected_files(tmp_path):
    s3 = FakeS3()
    worker = make_store(tmp_path, "worker", s3=s3)
    finished_run(worker)
    worker.mirror_run("r1")
    laptop = make_store(tmp_path, "laptop", s3=s3)
    laptop.sync_down("runs/r1/")
    local_manifest = laptop.run_dir("r1") / "manifest.json"
    local_manifest.chmod(0o644)
    local_manifest.write_text('{"run_id": "r1", "local": true}')
    s3.objects[("sandbox-bucket", "runs/r1/manifest.json")] = b"remote change"
    laptop.sync_down("runs/r1/", overwrite=True)
    assert json.loads(local_manifest.read_text())["local"] is True


def test_sync_down_refreshes_views_only_when_asked_and_keeps_a_terminal_status(tmp_path):
    s3 = FakeS3()
    worker = make_store(tmp_path, "worker", s3=s3)
    finished_run(worker)
    worker.mirror_run("r1")
    laptop = make_store(tmp_path, "laptop", s3=s3)
    laptop.sync_down("runs/r1/")
    s3.objects[("sandbox-bucket", "runs/r1/summary.json")] = b'{"claims": ["remote"]}'
    laptop.sync_down("runs/r1/")
    assert json.loads((laptop.run_dir("r1") / "summary.json").read_text())["claims"] == []
    laptop.sync_down("runs/r1/", overwrite=True)
    assert json.loads((laptop.run_dir("r1") / "summary.json").read_text())["claims"] == ["remote"]
    s3.objects[("sandbox-bucket", "runs/r1/status.json")] = json.dumps(
        {"state": "running", "updated_at": "x", "attempt": 1, "incomplete": False}
    ).encode()
    laptop.sync_down("runs/r1/", overwrite=True)
    assert laptop.read_status("r1").state == "completed"  # terminal stays terminal


@pytest.mark.parametrize(
    "bad_key",
    [
        "runs/../../escape.txt",
        "runs/r1/../../../escape.txt",
        "runs//abs.txt",
        "runs/.hidden/x.json",
        "runs/r1\\..\\evil.txt",
        "runs/only-an-id",
        "runs/r1/",
    ],
)
def test_sync_down_ignores_hostile_or_malformed_keys(tmp_path, bad_key):
    s3 = FakeS3()
    s3.objects[("sandbox-bucket", bad_key)] = b"pwned"
    laptop = make_store(tmp_path, "laptop", s3=s3)
    assert laptop.sync_down("runs/") == []
    outside = [p for p in tmp_path.rglob("*") if p.is_file() and "pwned" in p.read_text("latin-1")]
    assert outside == []


def test_sync_down_rejects_a_prefix_outside_runs_and_evals(tmp_path):
    with pytest.raises(ValueError):
        make_store(tmp_path).sync_down("requests/")


def test_sync_down_evals(tmp_path):
    s3 = FakeS3()
    worker = make_store(tmp_path, "worker", s3=s3)
    worker.create_eval("e1", {"name": "demo"})
    worker.write_eval_artifact("e1", "plan.json", json.dumps({"runs": ["r1"]}))
    worker.mirror_eval("e1")
    laptop = make_store(tmp_path, "laptop", s3=s3)
    laptop.sync_down("evals/")
    assert laptop.list_eval_runs("e1") == ["r1"]


def test_bucket_resolution_order(tmp_path, monkeypatch):
    outputs = tmp_path / "outputs.json"
    outputs.write_text(json.dumps({"BucketName": "from-outputs"}))
    monkeypatch.setenv("CLAYSANDBOX_BUCKET", "from-env")
    explicit = S3MirrorRunStore(
        tmp_path / "r1", tmp_path / "e1", bucket="explicit", outputs_path=outputs
    )
    from_file = S3MirrorRunStore(tmp_path / "r2", tmp_path / "e2", outputs_path=outputs)
    from_env = S3MirrorRunStore(
        tmp_path / "r3", tmp_path / "e3", outputs_path=tmp_path / "none.json"
    )
    assert (explicit.bucket, from_file.bucket, from_env.bucket) == (
        "explicit",
        "from-outputs",
        "from-env",
    )
    monkeypatch.delenv("CLAYSANDBOX_BUCKET")
    unconfigured = S3MirrorRunStore(
        tmp_path / "r4", tmp_path / "e4", outputs_path=tmp_path / "none.json"
    )
    with pytest.raises(ConfigError) as err:
        _ = unconfigured.bucket
    assert err.value.kind == "missing_bucket"


def test_local_use_needs_no_bucket_or_aws(tmp_path, monkeypatch):
    monkeypatch.delenv("CLAYSANDBOX_BUCKET", raising=False)
    s = S3MirrorRunStore(tmp_path / "r", tmp_path / "e", outputs_path=tmp_path / "none.json")
    finished_run(s)  # everything except mirror/sync works without a bucket
    assert s.read_status("r1").state == "completed"


def test_works_against_a_real_boto3_client_under_moto(tmp_path):
    """Skipped unless moto is installed (`uv run --with moto pytest ...`)."""
    moto = pytest.importorskip("moto")
    import boto3

    with moto.mock_aws():
        boto3.client("s3", region_name="us-west-2").create_bucket(
            Bucket="sandbox-bucket",
            CreateBucketConfiguration={"LocationConstraint": "us-west-2"},
        )
        worker = S3MirrorRunStore(
            tmp_path / "w" / "r", tmp_path / "w" / "e", bucket="sandbox-bucket"
        )
        finished_run(worker)
        worker.mirror_run("r1")
        worker.mirror_run("r1")  # second time: immutables skipped via a real head_object 404
        keys = [
            o["Key"]
            for o in boto3.client("s3", region_name="us-west-2")
            .list_objects_v2(Bucket="sandbox-bucket")
            .get("Contents", [])
        ]
        assert "runs/r1/manifest.json" in keys and "runs/r1/trace.jsonl" in keys
        laptop = S3MirrorRunStore(
            tmp_path / "l" / "r", tmp_path / "l" / "e", bucket="sandbox-bucket"
        )
        laptop.sync_down("runs/")
        assert laptop.read_trace("r1").events == worker.read_trace("r1").events
