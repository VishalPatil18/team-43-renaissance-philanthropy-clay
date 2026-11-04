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
    assert fields["result_ref"].startswith("blobs/") and fields["result_preview"].endswith("…")
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
        "key AKIAIOSFODNN7EXAMPLE and "
        "aws_secret_access_key=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY "
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
            error=ErrorInfo(source="tool", kind="tool_error", message="Bearer abcdefghijkl failed"),
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


# ---------------------------------------------------------------- regression tests (review fixes)
def test_run_end_token_totals_are_not_redacted(tmp_path):
    """Counters under keys like input_tokens match the secret-key pattern but are not secrets."""
    tracer = MemoryTracer()
    sink = RunEventSink("r", tmp_path, tracer)
    for e in scripted_events():
        sink.emit(e)
    totals = tracer.events[-1].totals
    assert totals["input_tokens"] == 1830 and totals["output_tokens"] == 235
    assert totals["cost_usd"] == 0.0017


def test_redaction_json_and_header_forms():
    secret40 = "wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY"
    sig = "a" * 64
    cases = {
        secret40: f'{{"SecretAccessKey": "{secret40}"}}',
        "AKIAIOSFODNN7EXAMPLE": (
            f"Authorization: AWS4-HMAC-SHA256 Credential=AKIAIOSFODNN7EXAMPLE/20261104/"
            f"us-west-2/s3/aws4_request, SignedHeaders=host, Signature={sig}"
        ),
        "sk-url-token-123456": "GET https://x.example/data?access_token=sk-url-token-123456&page=2",
        "Bearer-json-secret": '{"Authorization": "Bearer Bearer-json-secret"}',
    }
    for needle, text in cases.items():
        out = redact_text(text, [])
        assert needle not in out, text
        assert sig not in out
    # surrounding structure survives
    assert "page=2" in redact_text("?access_token=sk-url-token-123456&page=2", [])


def test_values_under_secret_keys_are_redacted_whole_but_numbers_survive():
    from claysandbox.tracing.redact import redact_value

    out = redact_value(
        {
            "credentials": {"a": "x1", "b": ["y2", "z3"]},
            "api_key": ["k1", "k2"],
            "max_tokens": 4096,
            "input_tokens": 12,
            "password": None,
            "plain": ["keep", {"n": 1}],
        },
        [],
    )
    assert out["credentials"] == {"a": REDACTED, "b": [REDACTED, REDACTED]}
    assert out["api_key"] == [REDACTED, REDACTED]
    assert out["max_tokens"] == 4096 and out["input_tokens"] == 12
    assert out["password"] is None
    assert out["plain"] == ["keep", {"n": 1}]


def test_sink_fails_closed_when_an_event_cannot_be_validated(tmp_path):
    """If redaction/validation fails, the tracer must never see the original payload."""
    tracer = MemoryTracer()
    sink = RunEventSink("r", tmp_path, tracer)
    bad = ToolCall.model_construct(
        server="s",
        tool="t",
        status="not-a-valid-status",
        args={"q": "AKIAIOSFODNN7EXAMPLE"},
        schema_version="1.0",
        run_id="",
        seq=-1,
        event_id="",
        parent_id=None,
        ts_start=scripted_events()[0].ts_start,
        ts_end=None,
        latency_ms=None,
        error=None,
        type="tool_call",
        capability=None,
        result_preview=None,
        result_ref=None,
        result_sha256=None,
        cost_usd=0.0,
    )
    sink.emit(scripted_events()[0])
    out = sink.emit(bad)
    sink.emit(scripted_events()[1])
    assert out.type == "error" and out.error.kind == "trace_event_invalid"
    assert [e.seq for e in tracer.events] == [0, 1, 2]  # no gap in the sequence
    assert "AKIA" not in "".join(e.model_dump_json() for e in tracer.events)
    assert sink.incomplete is True


def test_put_blob_redacts_text_and_bytes_but_not_binary(tmp_path):
    sink = RunEventSink("r", tmp_path, MemoryTracer())
    for payload in ("key AKIAIOSFODNN7EXAMPLE here", b"key AKIAIOSFODNN7EXAMPLE here"):
        ref, sha = sink.put_blob(payload)
        stored = (tmp_path / ref).read_bytes()
        assert b"AKIA" not in stored
        import hashlib

        assert hashlib.sha256(stored).hexdigest() == sha  # hash is of what is stored
    binary = bytes([0xFF, 0xFE, 0x00, 0x80])
    ref, _ = sink.put_blob(binary)
    assert (tmp_path / ref).read_bytes() == binary


def test_secret_straddling_the_preview_cutoff_does_not_leak(tmp_path):
    sink = RunEventSink("r", tmp_path, MemoryTracer(), preview_chars=30)
    text = "x" * 20 + "AKIAIOSFODNN7EXAMPLE" + "y" * 50  # the key crosses character 30
    fields = sink.result_fields(text)
    assert "AKIA" not in fields["result_preview"]
    assert "AKIA" not in (tmp_path / fields["result_ref"]).read_text()
