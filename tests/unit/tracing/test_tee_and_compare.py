from __future__ import annotations

import json

import pytest

from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import resolve
from claysandbox.store.reader import TRACE_FORMAT_READERS
from claysandbox.tracing.compare import compare_tracers, render_text
from claysandbox.tracing.jsonl import JsonlTracer
from claysandbox.tracing.otel import OTLP_FILE, OtelTracer
from claysandbox.tracing.sink import RunEventSink
from claysandbox.tracing.tee import METRICS_FILE, TeeTracer, percentile


def tee_run(run_dir, run_id="r", events=None, tee=None):
    tee = tee or TeeTracer()
    tee.open(run_id, run_dir)
    sink = RunEventSink(run_id, run_dir, tee)
    sent = [sink.emit(e) for e in (events if events is not None else scripted_events())]
    tee.close()
    return tee, sent


def metrics(run_dir):
    return json.loads((run_dir / METRICS_FILE).read_text())


def test_registered_and_records_the_same_run_in_both_formats(tmp_path):
    assert resolve("tracer", "tee") is TeeTracer
    _, sent = tee_run(tmp_path)
    assert (tmp_path / "trace.jsonl").exists() and (tmp_path / OTLP_FILE).exists()
    for fname, reader in TRACE_FORMAT_READERS.values():
        assert reader(tmp_path / fname)[0] == sent


def test_metrics_file_has_count_median_p95_errors_and_samples(tmp_path):
    _, sent = tee_run(tmp_path)
    m = metrics(tmp_path)["tracers"]
    assert set(m) == {"jsonl", "otel"}
    for entry in m.values():
        assert entry["count"] == len(sent) == len(entry["emit_ms"])
        assert 0 <= entry["median_ms"] <= entry["p95_ms"]
        assert entry["errors"] == 0
    assert "export_ms_total" in m["otel"] and "export_ms_total" not in m["jsonl"]


def test_percentile_is_nearest_rank():
    v = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]
    assert percentile(v, 95) == 10.0 and percentile(v, 50) == 5.0 and percentile([], 95) == 0.0


class Exploding:
    name = "exploding"
    version = "1"
    incomplete = False

    def open(self, run_id, run_dir):
        pass

    def emit(self, event):
        raise OSError("disk full")

    def close(self):
        pass


def test_one_failing_tracer_does_not_stop_the_other_or_raise(tmp_path):
    good = JsonlTracer()
    tee, sent = tee_run(tmp_path, tee=TeeTracer(tracers=[Exploding(), good]))
    m = metrics(tmp_path)["tracers"]
    assert m["exploding"]["errors"] == len(sent) and m["jsonl"]["errors"] == 0
    assert tee.incomplete is True
    assert len((tmp_path / "trace.jsonl").read_text().splitlines()) == len(sent)


def test_open_failure_closes_the_tracers_already_opened(tmp_path):
    class FailsToOpen(Exploding):
        name = "bad"

        def open(self, run_id, run_dir):
            raise RuntimeError("cannot open")

    first = JsonlTracer()
    tee = TeeTracer(tracers=[first, FailsToOpen()])
    with pytest.raises(RuntimeError):
        tee.open("r", tmp_path)
    assert first._fh is None  # closed, not leaked


def test_tee_needs_two_different_tracers():
    for names in (["jsonl"], ["jsonl", "jsonl"], ["jsonl", "tee"]):
        with pytest.raises(ValueError):
            TeeTracer({"tracers": names})


def test_a_finished_tee_run_cannot_be_reopened(tmp_path):
    tee_run(tmp_path)
    from claysandbox.contracts.store import StoreWriteRefused

    with pytest.raises(StoreWriteRefused):
        TeeTracer().open("r", tmp_path)


# ---------------------------------------------------------------- compare_tracers
def test_comparison_reports_no_loss_and_full_fidelity_for_a_clean_run(tmp_path):
    _, sent = tee_run(tmp_path / "r1")
    c = compare_tracers([tmp_path / "r1"], TRACE_FORMAT_READERS)
    assert c.kind == "tracer" and [t.tracer for t in c.tracers] == ["jsonl", "otel"]
    for t in c.tracers:
        assert t.events_written == len(sent) and t.events_read_back == len(sent)
        assert t.events_lost == 0 and t.fidelity_pct == 100.0
        assert t.emit_ms_median is not None and t.emit_ms_p95 is not None
    assert c.notes == []


def test_comparison_pools_several_runs(tmp_path):
    for i in (1, 2):
        tee_run(tmp_path / f"r{i}", run_id=f"r{i}")
    c = compare_tracers([tmp_path / "r1", tmp_path / "r2"], TRACE_FORMAT_READERS)
    n = len(scripted_events())
    assert c.run_ids == ["r1", "r2"]
    assert all(t.runs == 2 and t.events_written == 2 * n for t in c.tracers)


def test_a_truncated_otlp_copy_shows_up_as_loss_and_lower_fidelity(tmp_path):
    _, sent = tee_run(tmp_path)
    path = tmp_path / OTLP_FILE
    lines = path.read_text().splitlines()
    path.write_text("\n".join(lines[:5]) + "\n")  # keep 5 of the events
    c = compare_tracers([tmp_path], TRACE_FORMAT_READERS)
    jsonl, otel = c.tracers
    assert jsonl.events_lost == 0 and jsonl.fidelity_pct == 100.0
    assert otel.events_lost == len(sent) - 5 and otel.events_read_back == 5
    assert otel.fidelity_pct == pytest.approx(100 * 5 / len(sent), abs=0.01)


def test_a_corrupted_event_lowers_fidelity_without_counting_as_lost(tmp_path):
    tee_run(tmp_path)
    path = tmp_path / OTLP_FILE
    text = path.read_text().replace("fake-baseline", "tampered-name", 1)
    path.write_text(text)
    otel = {t.tracer: t for t in compare_tracers([tmp_path], TRACE_FORMAT_READERS).tracers}["otel"]
    assert otel.events_lost == 0 and otel.events_equal == otel.events_written - 1
    assert otel.fidelity_pct < 100.0


def test_a_run_without_tee_metrics_still_compares_but_says_overhead_is_unavailable(tmp_path):
    tee_run(tmp_path)
    (tmp_path / METRICS_FILE).unlink()
    c = compare_tracers([tmp_path], TRACE_FORMAT_READERS)
    assert all(t.emit_ms_median is None for t in c.tracers)
    assert any("overhead unavailable" in n for n in c.notes)


def test_a_run_with_one_format_is_flagged(tmp_path):
    t = OtelTracer()
    t.open("r", tmp_path)
    sink = RunEventSink("r", tmp_path, t)
    for e in scripted_events():
        sink.emit(e)
    t.close()
    c = compare_tracers([tmp_path], TRACE_FORMAT_READERS)
    assert any("need two formats" in n for n in c.notes)


def test_render_text_prints_overhead_loss_and_fidelity(tmp_path):
    tee_run(tmp_path)
    out = render_text(compare_tracers([tmp_path], TRACE_FORMAT_READERS))
    for word in ("median ms", "p95 ms", "lost", "fidelity", "jsonl", "otel", "100.00%"):
        assert word in out


def test_empty_input_is_an_error():
    with pytest.raises(ValueError):
        compare_tracers([], TRACE_FORMAT_READERS)


def test_converts_to_the_shape_of_ws4s_measurement_comparison(tmp_path):
    tee_run(tmp_path)
    m = compare_tracers([tmp_path], TRACE_FORMAT_READERS).to_measurement_comparison()
    assert set(m) == {"kind", "subjects", "n_runs", "values", "details", "notes"}
    assert m["kind"] == "tracer" and m["subjects"] == ["jsonl", "otel"] and m["n_runs"] == 1
    assert m["values"]["otel.fidelity_pct"] == 100.0 and m["values"]["jsonl.events_lost"] == 0.0
    assert all(v is None or isinstance(v, float) for v in m["values"].values())
    assert len(m["details"]["tracers"]) == 2
    json.dumps(m)  # plain data: serialisable as is
