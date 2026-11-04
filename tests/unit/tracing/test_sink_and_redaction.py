from __future__ import annotations

import threading

from claysandbox.contracts.fakes import MemoryTracer
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.trace import ErrorEvent, ErrorInfo, ToolCall
from claysandbox.tracing.redact import REDACTED, redact_event_dict, redact_text
from claysandbox.tracing.sink import RunEventSink


def test_seq_strictly_increasing_under_concurrent_emits(tmp_path):
    tracer = MemoryTracer()
    sink = RunEventSink("r", tmp_path, tracer)
    ev = scripted_events()[2]

    def burst():
        for _ in range(200):
            sink.emit(ev)

    threads = [threading.Thread(target=burst) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    seqs = [e.seq for e in tracer.events]
    assert seqs == list(range(1600))
    assert len({e.event_id for e in tracer.events}) == 1600
    assert sink.last_event_id == "r:1599"


def test_blob_dedupe(tmp_path):
    sink = RunEventSink("r", tmp_path, MemoryTracer())
    ref1, sha1 = sink.put_blob(b"x" * 5000)
    ref2, sha2 = sink.put_blob("x" * 5000)
    assert (ref1, sha1) == (ref2, sha2)
    assert ref1 == f"blobs/{sha1}"
    assert len(list((tmp_path / "blobs").iterdir())) == 1


def test_large_result_goes_to_blob_with_preview(tmp_path):
    sink = RunEventSink("r", tmp_path, MemoryTracer(), preview_chars=100)
    fields = sink.result_fields("y" * 1000)
    assert fields["result_ref"].startswith("blobs/") and fields[
        "result_preview"
    ].endswith("…")
    assert (tmp_path / fields["result_ref"]).read_text() == "y" * 1000
    assert sink.result_fields("short")["result_ref"] is None


class ExplodingTracer:
    incomplete = False

    def emit(self, event):
        raise OSError("disk full")


def test_tracer_failure_does_not_break_the_sink(tmp_path):
    sink = RunEventSink("r", tmp_path, ExplodingTracer())
    out = [sink.emit(e) for e in scripted_events()]
    assert out[-1].seq == len(out) - 1
    assert sink.incomplete is True


def test_redaction_patterns(monkeypatch):
    monkeypatch.setenv("MY_API_TOKEN", "tok-1234567890abcdef")
    text = (
        "key AKIAIOSFODNN7EXAMPLE and aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY "
        "Authorization: Bearer abc.def.ghi and token tok-1234567890abcdef"
    )
    out = redact_text(text)
    for secret in (
        "AKIAIOSFODNN7EXAMPLE",
        "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY",
        "abc.def.ghi",
        "tok-1234567890abcdef",
    ):
        assert secret not in out
    assert out.count(REDACTED) >= 4


def test_redaction_in_events(tmp_path):
    tracer = MemoryTracer()
    sink = RunEventSink("r", tmp_path, tracer)
    sink.emit(
        ToolCall(
            server="s",
            tool="t",
            status="error",
            args={
                "query": "naip",
                "api_key": "sk-live-abcdef123456",
                "nested": {"password": "hunter22"},
            },
            result_preview="ASIAABCDEFGHIJKLMNOP leaked",
            error=ErrorInfo(
                source="tool", kind="tool_error", message="Bearer abcdefghijkl failed"
            ),
        )
    )
    e = tracer.events[0]
    assert e.args["api_key"] == REDACTED and e.args["nested"]["password"] == REDACTED
    assert e.args["query"] == "naip"
    assert "ASIA" not in e.result_preview and "abcdefghijkl" not in e.error.message


def test_redaction_leaves_ids_and_numbers():
    d = ErrorEvent(
        run_id="r",
        seq=3,
        event_id="r:3",
        error=ErrorInfo(source="infra", kind="throttled", message="slow down"),
    ).model_dump(mode="json")
    assert redact_event_dict(d) == d
