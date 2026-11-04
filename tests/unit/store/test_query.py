from __future__ import annotations

import json
import time

import duckdb
import pytest

from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.trace import RunEnd
from claysandbox.store.local import LocalRunStore
from claysandbox.store.query import (
    assessments_for_eval,
    list_runs,
    runs_for_eval,
    token_history,
)
from claysandbox.tracing.jsonl import JsonlTracer
from claysandbox.tracing.sink import RunEventSink


def make_run(
    store,
    run_id,
    *,
    eval_id="e1",
    task="T1:kern",
    model="nova-pro",
    harness="strands",
    state="completed",
    tokens=(1830, 235),
    started="2026-11-04T10:00:00Z",
    trial=0,
):
    store.create_run(
        {
            "run_id": run_id,
            "eval_id": eval_id,
            "trial_index": trial,
            "attempt": 1,
            "task_instance_id": task,
            "model": {"kind": "model", "name": "bedrock", "params": {"model_id": model}},
            "harness": {"kind": "harness", "name": harness},
            "toolset": {"kind": "toolset", "name": "T1"},
            "started_at": started,
        }
    )
    events = scripted_events()[:-1] + [
        RunEnd(
            state=state if state != "created" else "completed",
            totals={"steps": 3, "input_tokens": tokens[0], "output_tokens": tokens[1]},
        )
    ]
    tracer = JsonlTracer()
    tracer.open(run_id, store.run_dir(run_id))
    sink = RunEventSink(run_id, store.run_dir(run_id), tracer)
    for e in events:
        sink.emit(e)
    tracer.close()
    store.write_status(run_id, state)


@pytest.fixture
def store(tmp_path):
    return LocalRunStore(tmp_path / "runs", tmp_path / "evals")


def test_runs_for_eval_joins_manifest_and_status(store):
    make_run(store, "r1", trial=1)
    make_run(store, "r2", trial=0, task="T2:fresno", state="budget_stopped")
    make_run(store, "r3", eval_id="other")
    rows = runs_for_eval(store, "e1")
    assert [r["run_id"] for r in rows] == ["r2", "r1"]  # ordered by trial
    r2 = rows[0]
    assert (r2["template"], r2["model_id"], r2["harness_name"], r2["toolset_name"]) == (
        "T2",
        "nova-pro",
        "strands",
        "T1",
    )
    assert r2["state"] == "budget_stopped" and r2["incomplete"] is False


def test_assessments_for_eval_filters_by_kind(store):
    make_run(store, "r1")
    make_run(store, "r2", eval_id="other")
    for aid, kind, score in (("a1", "workflow", 0.8), ("a2", "output", 0.6)):
        store.append_assessment(
            "r1",
            {
                "assessment_id": aid,
                "run_id": "r1",
                "kind": kind,
                "composite": score,
                "success": kind == "workflow",
                "evaluator": {"name": kind, "version": "1"},
            },
        )
    store.append_assessment(
        "r2", {"assessment_id": "a3", "run_id": "r2", "kind": "workflow", "composite": 0.1}
    )
    both = assessments_for_eval(store, "e1")
    assert sorted(a["assessment_id"] for a in both) == ["a1", "a2"]  # a3 belongs to another eval
    only = assessments_for_eval(store, "e1", kind="output")
    assert [(a["assessment_id"], a["evaluator_name"], a["composite"]) for a in only] == [
        ("a2", "output", 0.6)
    ]
    assert only[0]["template"] == "T1" and only[0]["model_id"] == "nova-pro"


def test_token_history_uses_only_completed_runs_of_that_model_and_template(store):
    make_run(store, "r1", tokens=(1000, 100))
    make_run(store, "r2", tokens=(3000, 300))
    make_run(store, "r3", tokens=(2000, 200))
    make_run(store, "stopped", state="budget_stopped", tokens=(99999, 9999))
    make_run(store, "other-model", model="nova-lite", tokens=(7, 7))
    make_run(store, "other-template", task="T2:x", tokens=(8, 8))
    make_run(store, "other-harness", harness="converse", tokens=(500, 50))
    h = token_history(store, "T1", "nova-pro")
    assert h["n"] == 4  # r1, r2, r3 and other-harness
    assert h["input_tokens"] == 1500.0  # median of 500, 1000, 2000, 3000
    only = token_history(store, "T1", "nova-pro", harness="strands")
    assert only["n"] == 3 and only["input_tokens"] == 2000.0 and only["output_tokens"] == 200.0


def test_token_history_with_no_history_says_so(store):
    make_run(store, "r1")
    assert token_history(store, "T9", "nova-pro") == {
        "n": 0,
        "input_tokens": None,
        "output_tokens": None,
    }


def test_list_runs_filters_orders_and_pages(store):
    for i in range(5):
        make_run(store, f"r{i}", started=f"2026-11-04T10:0{i}:00Z", model="a" if i % 2 else "b")
    ids = [r["run_id"] for r in list_runs(store)]
    assert ids == ["r4", "r3", "r2", "r1", "r0"]  # newest first
    assert [r["run_id"] for r in list_runs(store, limit=2, offset=1)] == ["r3", "r2"]
    assert [r["run_id"] for r in list_runs(store, {"model_id": "a"})] == ["r3", "r1"]
    assert list_runs(store, {"model_id": "a", "state": "agent_failed"}) == []


def test_list_runs_rejects_unknown_filters_so_columns_never_come_from_callers(store):
    make_run(store, "r1")
    with pytest.raises(ValueError, match="unknown filter"):
        list_runs(store, {"run_id; DROP TABLE manifests": "x"})


def test_values_are_bound_so_quotes_in_a_value_cannot_inject_sql(store):
    make_run(store, "r1")
    assert runs_for_eval(store, "e1' OR '1'='1") == []
    assert list_runs(store, {"eval_id": "' OR true --"}) == []
    assert len(runs_for_eval(store, "e1")) == 1  # nothing was dropped or changed


def test_sql_cannot_read_or_write_files(store, tmp_path):
    make_run(store, "r1")
    secret = tmp_path / "secret.txt"
    secret.write_text("a,b\n1,2\n")
    for sql in (
        f"SELECT * FROM read_csv('{secret}')",
        f"SELECT * FROM read_json('{store.run_dir('r1') / 'manifest.json'}')",
        f"COPY manifests TO '{tmp_path / 'out.csv'}'",
        "SET enable_external_access = true",
    ):
        with pytest.raises(duckdb.Error):
            store.query(sql)
    assert not (tmp_path / "out.csv").exists()


def test_query_takes_named_parameters_and_returns_dicts(store):
    make_run(store, "r1")
    rows = store.query("SELECT run_id, template FROM manifests WHERE eval_id = $e", {"e": "e1"})
    assert rows == [{"run_id": "r1", "template": "T1"}]


def test_an_empty_store_still_queries(store):
    assert runs_for_eval(store, "e1") == []
    assert assessments_for_eval(store, "e1") == []
    assert token_history(store, "T1", "m")["n"] == 0
    assert store.query("SELECT count(*) AS n FROM run_ends") == [{"n": 0}]


def test_manifests_of_different_shapes_load_with_nulls_for_missing_keys(store):
    make_run(store, "r1")
    store.create_run({"run_id": "bare", "eval_id": "e1", "extra_key": {"x": [1, 2]}})
    rows = {r["run_id"]: r for r in runs_for_eval(store, "e1")}
    assert rows["bare"]["model_id"] is None and rows["bare"]["template"] is None
    assert rows["r1"]["model_id"] == "nova-pro"


def test_a_crashed_runs_truncated_trace_does_not_break_queries(store):
    make_run(store, "good")
    make_run(store, "crashed")
    path = store.trace_path("crashed")
    path.chmod(0o644)
    path.write_text(path.read_text() + '{"type": "tool_call", "run_id": "crashed", "ser')
    assert token_history(store, "T1", "nova-pro")["n"] == 2


def test_read_only_sample_runs_are_merged_and_the_overlay_status_wins(tmp_path):
    samples = LocalRunStore(tmp_path / "samples" / "runs", tmp_path / "x")
    make_run(samples, "sample1", eval_id="demo")
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals", read_roots=[samples.root])
    make_run(store, "mine", eval_id="demo")
    store.append_assessment(
        "sample1", {"assessment_id": "a1", "run_id": "sample1", "kind": "workflow", "composite": 1}
    )
    assert sorted(r["run_id"] for r in runs_for_eval(store, "demo")) == ["mine", "sample1"]
    assert [a["assessment_id"] for a in assessments_for_eval(store, "demo")] == ["a1"]
    # overlay status for a sample run overrides the sample's own
    (store.root / "sample1").mkdir(exist_ok=True)
    (store.root / "sample1" / "status.json").write_text(
        json.dumps({"state": "agent_failed", "updated_at": "x", "attempt": 1, "incomplete": False})
    )
    states = {r["run_id"]: r["state"] for r in runs_for_eval(store, "demo")}
    assert states["sample1"] == "agent_failed"


def test_statistics_queries_over_360_runs_return_in_seconds(tmp_path):
    """NFR-PERF-3 / SHI-R2-03 acceptance: 360 runs, a stats-shaped query, well under a minute."""
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    for i in range(360):
        make_run(
            store,
            f"run-{i:03d}",
            task=f"T{i % 5 + 1}:aoi{i % 6}",
            model="nova-pro" if i % 2 else "sonnet",
            harness="strands" if i % 3 else "converse",
            trial=i % 3,
        )
        if i % 2 == 0:
            store.append_assessment(
                f"run-{i:03d}",
                {
                    "assessment_id": f"a-{i:03d}",
                    "run_id": f"run-{i:03d}",
                    "kind": "workflow",
                    "composite": (i % 10) / 10,
                    "success": i % 4 == 0,
                    "evaluator": {"name": "workflow", "version": "1"},
                },
            )
    t0 = time.perf_counter()
    rows = store.query(
        "SELECT m.model_id, m.harness_name, count(*) AS n, avg(a.composite) AS mean_score "
        "FROM manifests m JOIN assessments a USING (run_id) "
        "WHERE m.eval_id = $e AND a.kind = 'workflow' GROUP BY ALL ORDER BY ALL",
        {"e": "e1"},
    )
    elapsed = time.perf_counter() - t0
    assert sum(r["n"] for r in rows) == 180
    assert len(runs_for_eval(store, "e1")) == 360
    assert elapsed < 10, f"stats query took {elapsed:.1f}s"


def test_the_store_works_without_duckdb_and_only_queries_need_it(tmp_path, monkeypatch):
    """The Docker image installs with --no-dev, so duckdb may be absent on workers."""
    import sys

    from claysandbox.contracts.errors import ConfigError

    monkeypatch.setitem(sys.modules, "duckdb", None)  # `import duckdb` now raises ImportError
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    make_run(store, "r1")  # writing, status, reading all work
    assert store.read_trace("r1").events and store.read_status("r1").state == "completed"
    with pytest.raises(ConfigError) as err:
        store.query("SELECT 1")
    assert err.value.kind == "missing_dependency" and "duckdb" in err.value.message
