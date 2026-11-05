from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

from claysandbox.contracts.trace import (
    FinalOutput,
    ModelCall,
    RunEnd,
    RunStart,
    ToolCall,
    parse_event,
)
from claysandbox.store.reader import read_trace
from claysandbox.tracing.jsonl import JsonlTracer
from claysandbox.tracing.sink import RunEventSink

_spec = importlib.util.spec_from_file_location(
    "make_planted", Path(__file__).resolve().parents[3] / "scripts" / "make_planted.py"
)
assert _spec and _spec.loader
mp = importlib.util.module_from_spec(_spec)
sys.modules["make_planted"] = mp  # @dataclass looks its module up here
_spec.loader.exec_module(mp)

REFERENCE = {
    "template": "T1",
    "version": "T1.v1+sha256:test",
    "workflow": {
        "required": ["imagery_search"],
        "forbidden": ["dataset_discovery"],
        "ordering": [{"before": "geocode", "after": "imagery_search", "optional_first": True}],
        "done": "output_matches_schema_nonempty",
    },
    "output_reference": {"items": ["naip-1", "naip-2"]},
}


def model(parent_tools=True, tokens=(100, 10)):
    return ModelCall(
        model_id="fake-model",
        input_tokens=tokens[0],
        output_tokens=tokens[1],
        cost_usd=0.001,
        price_table_version="p1",
        stop_reason="tool_use" if parent_tools else "end_turn",
    )


def tool(capability, name, args, result):
    return ToolCall(
        server="srv",
        tool=name,
        capability=capability,
        args=args,
        status="ok",
        result_preview=result,
    )


def write_good(tmp_path, *, reference=None, steps=3, name="good-src", extra_events=None):
    """A clean completed run recorded through the real stack: geocode, then imagery search."""
    run_id = "run-good"
    d = tmp_path / name
    d.mkdir()
    events = [RunStart(task_instance_id="T1@kern", config_name="baseline")]
    # event ids are "<run>:<seq>"; a tool call's parent is the model call before it
    events += [model()]  # seq 1
    events += [tool("geocode", "geocode", {"q": "Kern County"}, '{"bbox": [1, 2, 3, 4]}')]  # seq 2
    events[2].parent_id = f"{run_id}:1"
    if steps >= 2:
        events += [model()]  # seq 3
        events += [
            tool(
                "imagery_search",
                "search_items",
                {"bbox": [1, 2, 3, 4]},
                '{"ids": ["naip-1", "naip-2"]}',
            )
        ]  # seq 4
        events[4].parent_id = f"{run_id}:3"
    if steps >= 3:
        events += [model(parent_tools=False)]
    events += [FinalOutput(output={"items": ["naip-1", "naip-2"], "count": 2})]
    events += extra_events or []
    events += [RunEnd(state="completed", totals={"steps": steps})]
    tracer = JsonlTracer()
    tracer.open(run_id, d)
    sink = RunEventSink(run_id, d, tracer)
    for e in events:
        sink.emit(e)
    tracer.close()
    (d / "manifest.json").write_text(
        json.dumps({"run_id": run_id, "eval_id": "e1", "task_instance_id": "T1@kern"})
    )
    (d / "reference.json").write_text(json.dumps(reference if reference is not None else REFERENCE))
    return d


def events_of(folder: Path):
    return [json.loads(line) for line in (folder / "trace.jsonl").read_text().splitlines()]


def caps(events):
    return [e.get("capability") for e in events if e["type"] == "tool_call"]


@pytest.fixture
def planted(tmp_path):
    good = write_good(tmp_path)
    out = tmp_path / "planted"
    results = mp.build(good, "T1", out)
    return out / "T1", results, good


def test_every_flaw_is_built_from_a_complete_reference(planted):
    base, results, _ = planted
    assert results == {name: "written" for name in mp.FLAW_NAMES}
    for name in mp.FLAW_NAMES:
        assert (base / name / "expected.json").exists()
    assert (base / "good" / "trace.jsonl").exists() and not (
        base / "good" / "expected.json"
    ).exists()


def test_planted_traces_are_valid_consistent_traces(planted):
    base, _, _ = planted
    for name in mp.FLAW_NAMES:
        folder = base / name
        events = events_of(folder)
        parsed = [parse_event(e) for e in events]  # the real schema accepts every event
        run_id = f"run-good-{name}"
        assert [e["seq"] for e in events] == list(range(len(events)))
        assert [e["event_id"] for e in events] == [f"{run_id}:{i}" for i in range(len(events))]
        assert {e["run_id"] for e in events} == {run_id}
        assert events[0]["type"] == "run_start" and events[-1]["type"] == "run_end"
        ids = [e["event_id"] for e in events]
        for i, e in enumerate(events):  # parents exist and come earlier
            if e.get("parent_id"):
                assert e["parent_id"] in ids[:i], (name, e["event_id"], e["parent_id"])
        totals = events[-1]["totals"]
        assert totals["steps"] == sum(1 for e in events if e["type"] == "model_call"), name
        assert totals["input_tokens"] == sum(e.get("input_tokens", 0) for e in events), name
        trace = read_trace(folder)  # and the store's reader reads it as a complete trace
        assert trace.incomplete is False and len(trace.events) == len(parsed)


def test_manifests_mark_planted_runs_and_point_back_to_the_good_run(planted):
    base, _, _ = planted
    good = json.loads((base / "good" / "manifest.json").read_text())
    assert good["run_id"] == "run-good" and "environment" not in good
    for name in mp.FLAW_NAMES:
        m = json.loads((base / name / "manifest.json").read_text())
        assert m["run_id"] == f"run-good-{name}"
        assert m["environment"] == {
            "planted": True,
            "planted_flaw": name,
            "source_run_id": "run-good",
        }
        assert m["eval_id"] == "e1"
        assert (base / name / "reference.json").read_text() == (
            base / "good" / "reference.json"
        ).read_text()


def test_expected_json_uses_the_validators_vocabulary(planted):
    base, _, _ = planted
    for name in mp.FLAW_NAMES:
        exp = json.loads((base / name / "expected.json").read_text())
        assert exp["good"] == "../good" and exp["drops"] and exp["description"]
        assert all(
            d == "success" or d.split(".")[0] in ("workflow", "output") for d in exp["drops"]
        )
    recovered = json.loads((base / "recovered_tool_failure" / "expected.json").read_text())
    assert recovered["less_than"] == {
        "flaw": "unrecovered_tool_failure",
        "metric": "workflow.recovery",
    }
    assert "less_than" not in json.loads((base / "loop" / "expected.json").read_text())


def test_good_run_is_copied_unchanged(planted):
    base, _, good = planted
    assert events_of(base / "good") == events_of(good)


def test_unrecovered_tool_failure_breaks_the_required_call_for_good(planted):
    events = events_of(planted[0] / "unrecovered_tool_failure")
    imagery = [
        e for e in events if e["type"] == "tool_call" and e["capability"] == "imagery_search"
    ]
    assert [e["status"] for e in imagery] == ["error"]
    assert imagery[0]["error"]["source"] == "tool" and imagery[0]["error"]["kind"] == "tool_error"
    assert caps(events).count("geocode") == 1  # unrelated calls untouched


def test_recovered_tool_failure_fails_once_then_succeeds(planted):
    events = events_of(planted[0] / "recovered_tool_failure")
    imagery = [
        e for e in events if e["type"] == "tool_call" and e["capability"] == "imagery_search"
    ]
    assert [e["status"] for e in imagery] == ["error", "ok"]
    assert imagery[0]["error"]["retryable"] is True
    assert imagery[0]["parent_id"] == imagery[1]["parent_id"]  # a retry of the same request


def test_loop_repeats_one_call_then_the_guard_stops_the_run(planted):
    events = events_of(planted[0] / "loop")
    calls = [e for e in events if e["type"] == "tool_call"]
    assert (
        len(calls) == 3
        and len({(c["server"], c["tool"], json.dumps(c["args"])) for c in calls}) == 1
    )
    stop = next(e for e in events if e["type"] == "guard_stop")
    assert stop["limit"] == "loop" and stop["error"]["kind"] == "loop_detected"
    assert events[-1]["state"] == "budget_stopped"
    assert not any(e["type"] == "final_output" for e in events)
    assert events[-3]["type"] == "model_call"  # the blocked fourth attempt


def test_loop_expects_success_to_drop_and_step_efficiency_only_when_steps_exceed_expected(tmp_path):
    base = json.loads(json.dumps(REFERENCE))
    # no expected_steps in the reference: a guard-stopped loop is only claimed to lose `success`
    mp.build(write_good(tmp_path, name="a", reference=base), "T1", tmp_path / "a")
    exp = json.loads((tmp_path / "a" / "T1" / "loop" / "expected.json").read_text())
    assert exp["drops"] == ["success"]
    # the loop makes 4 model calls: with 4 expected steps there is nothing to penalise...
    base["workflow"]["expected_steps"] = 4
    mp.build(write_good(tmp_path, name="b", reference=base), "T1", tmp_path / "b")
    exp = json.loads((tmp_path / "b" / "T1" / "loop" / "expected.json").read_text())
    assert exp["drops"] == ["success"]
    # ...but with 3 expected steps the loop is over budget, so step_efficiency must drop too
    base["workflow"]["expected_steps"] = 3
    mp.build(write_good(tmp_path, name="c", reference=base), "T1", tmp_path / "c")
    exp = json.loads((tmp_path / "c" / "T1" / "loop" / "expected.json").read_text())
    assert exp["drops"] == ["success", "workflow.step_efficiency"]


def test_wrong_order_swaps_what_the_ordering_rule_sequences(planted):
    assert caps(events_of(planted[0] / "wrong_order")) == ["imagery_search", "geocode"]


def test_forbidden_tool_calls_the_capability_the_task_forbids(planted):
    events = events_of(planted[0] / "forbidden_tool")
    assert "dataset_discovery" in caps(events)
    assert events[-1]["state"] == "completed"  # only the workflow is flawed


def test_unknown_tool_adds_an_agent_error(planted):
    events = events_of(planted[0] / "unknown_tool")
    err = next(e for e in events if e["type"] == "error")
    assert (err["error"]["source"], err["error"]["kind"]) == ("agent", "unknown_tool")


def test_budget_stop_cuts_after_step_two(planted):
    events = events_of(planted[0] / "budget_stop")
    assert sum(1 for e in events if e["type"] == "model_call") == 2
    stop = next(e for e in events if e["type"] == "guard_stop")
    assert (stop["limit"], stop["error"]["kind"]) == ("max_steps", "budget_exceeded")
    assert events[-1]["state"] == "budget_stopped"
    assert not any(e["type"] == "final_output" for e in events)


def test_fabricated_output_names_items_no_tool_returned(planted):
    events = events_of(planted[0] / "fabricated_output")
    output = next(e for e in events if e["type"] == "final_output")["output"]
    results = " ".join(e.get("result_preview") or "" for e in events if e["type"] == "tool_call")
    assert output["count"] == 2  # structure and numbers are kept
    assert output["items"] and all(item.startswith("fabricated-") for item in output["items"])
    assert not any(item in results for item in output["items"])


def test_output_is_reproducible_byte_for_byte(tmp_path):
    good = write_good(tmp_path)
    mp.build(good, "T1", tmp_path / "a")
    mp.build(good, "T1", tmp_path / "b")
    for path in sorted((tmp_path / "a").rglob("*")):
        if path.is_file():
            twin = tmp_path / "b" / path.relative_to(tmp_path / "a")
            assert path.read_bytes() == twin.read_bytes(), path


def test_flaws_the_reference_gives_no_material_for_are_skipped_not_faked(tmp_path):
    bare = {"template": "T1", "workflow": {"required": ["imagery_search"]}}
    out = tmp_path / "planted"
    results = mp.build(write_good(tmp_path, reference=bare), "T1", out)
    assert results["forbidden_tool"].startswith("skipped: the task reference has no forbidden")
    assert results["wrong_order"].startswith("skipped: no ordering rule")
    assert (
        not (out / "T1" / "forbidden_tool").exists() and not (out / "T1" / "wrong_order").exists()
    )
    assert results["loop"] == "written"


def test_a_run_too_short_to_cut_skips_the_budget_stop(tmp_path):
    results = mp.build(write_good(tmp_path, steps=2), "T1", tmp_path / "p")
    assert results["budget_stop"].startswith("skipped: the good run has fewer than three steps")


def test_regenerating_replaces_the_set_instead_of_leaving_stale_flaws(tmp_path):
    good = write_good(tmp_path)
    out = tmp_path / "p"
    mp.build(good, "T1", out)
    stale = out / "T1" / "loop" / "leftover.txt"
    stale.write_text("old")
    mp.build(good, "T1", out, only=["wrong_order"])
    assert not stale.exists() and not (out / "T1" / "loop").exists()
    assert (out / "T1" / "wrong_order").exists()


def test_a_dirty_or_unfinished_good_run_is_refused(tmp_path):
    with_error = write_good(
        tmp_path,
        name="dirty",
        extra_events=[mp_error_event()],
    )
    with pytest.raises(SystemExit, match="has errors"):
        mp.build(with_error, "T1", tmp_path / "p")

    unfinished = write_good(tmp_path, name="unfinished")
    lines = (unfinished / "trace.jsonl").read_text().splitlines()
    (unfinished / "trace.jsonl").write_text("\n".join(lines[:-1]) + "\n")
    with pytest.raises(SystemExit, match="not a clean completed run"):
        mp.build(unfinished, "T1", tmp_path / "p")

    no_reference = write_good(tmp_path, name="noref")
    (no_reference / "reference.json").unlink()
    with pytest.raises(SystemExit, match="reference.json"):
        mp.build(no_reference, "T1", tmp_path / "p")


def mp_error_event():
    from claysandbox.contracts.trace import ErrorEvent, ErrorInfo

    return ErrorEvent(error=ErrorInfo(source="tool", kind="tool_error", message="x"))


def test_cli_writes_the_requested_flaws_and_rejects_unknown_ones(tmp_path, capsys):
    good = write_good(tmp_path)
    out = tmp_path / "planted"
    assert (
        mp.main(["--good", str(good), "--template", "T1", "--out", str(out), "--flaws", "loop"])
        == 0
    )
    assert "T1/loop: written" in capsys.readouterr().out
    assert sorted(p.name for p in (out / "T1").iterdir()) == ["good", "loop"]
    with pytest.raises(SystemExit) as err:
        mp.main(["--good", str(good), "--template", "T1", "--out", str(out), "--flaws", "nonsense"])
    assert err.value.code == 2
