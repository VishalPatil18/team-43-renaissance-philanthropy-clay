#!/usr/bin/env python3
"""Planted-trace generator (SHI-R1-04, FR-10.6, FR-10.7, FR-13.7, DD-038). Owner: WS3.

Takes one *clean* run as the good trace and writes flawed variants of it, so the evaluators can
be shown to separate good from bad (J6 step 2). The output is the layout that
``claysandbox.evaluation.validate`` reads::

    <out>/<template>/good/        manifest.json trace.jsonl reference.json
    <out>/<template>/<flaw>/      manifest.json trace.jsonl reference.json expected.json

``expected.json`` names the metrics that must score strictly lower than on the good run, in the
validator's vocabulary (``workflow.recovery``, ``success``, ``output.composite``, ...).

What each flaw does comes from the run's own task reference (``reference.json``):
``workflow.required`` picks the call to break, ``workflow.ordering`` the pair to swap and
``workflow.forbidden`` the capability to call. A flaw that the reference gives no material for
is skipped with a message, never faked.

Every planted run gets a fresh, deterministic run ID (``<good run id>-<flaw>``), consistent
``seq``/``event_id``/``parent_id``, recomputed ``run_end`` totals, and ``planted: true`` in its
manifest ``environment`` so a planted trace can never be mistaken for a real run.

Usage::

    python scripts/make_planted.py --good samples/runs/<run_id> --template T1 --out samples/planted
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import itertools
import json
import shutil
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

Event = dict[str, Any]
STEP = timedelta(milliseconds=1)
_new_ids = itertools.count(1)  # unique placeholder IDs for inserted events


class Skip(Exception):
    """The good run or its reference has nothing this flaw can be built from."""


# ---------------------------------------------------------------- small helpers
def _t(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso(dt: datetime) -> str:
    return dt.isoformat().replace("+00:00", "Z")


def _model_calls(events: list[Event]) -> list[Event]:
    return [e for e in events if e["type"] == "model_call"]


def _tool_calls(events: list[Event]) -> list[Event]:
    return [e for e in events if e["type"] == "tool_call"]


def _index(events: list[Event], target: Event) -> int:
    return next(i for i, e in enumerate(events) if e is target)


def _first_ok(events: list[Event], capability: str | None = None) -> Event:
    for e in _tool_calls(events):
        if e["status"] == "ok" and (capability is None or e.get("capability") == capability):
            return e
    raise Skip(f"no successful tool call{f' for capability {capability!r}' if capability else ''}")


def _fresh(kind: str, after: Event, **fields: Any) -> Event:
    """A new event placed just after ``after`` in time. IDs are assigned by ``renumber``."""
    start = _t(after.get("ts_end") or after["ts_start"]) + STEP
    base: Event = {
        "schema_version": after.get("schema_version", "1.0"),
        "run_id": after["run_id"],
        "seq": -1,
        "event_id": f"new:{next(_new_ids)}",
        "parent_id": None,
        "type": kind,
        "ts_start": _iso(start),
        "ts_end": _iso(start + STEP),
        "latency_ms": 1.0,
        "error": None,
    }
    base.update(fields)
    return base


def _error(source: str, kind: str, message: str, retryable: bool = False) -> Event:
    return {"source": source, "kind": kind, "message": message, "retryable": retryable}


def _finish(events: list[Event], state: str) -> list[Event]:
    """Drop any final_output/run_end and close the run in ``state`` (no final output)."""
    kept = [e for e in events if e["type"] not in ("final_output", "run_end")]
    kept.append(_fresh("run_end", kept[-1], state=state, totals={}))
    return kept


def renumber(events: list[Event], run_id: str) -> list[Event]:
    """Consistent ``run_id``, ``seq``, ``event_id`` and ``parent_id`` after edits."""
    new_ids = {e["event_id"]: f"{run_id}:{i}" for i, e in enumerate(events)}
    out: list[Event] = []
    for i, e in enumerate(events):
        e = copy.deepcopy(e)
        e["run_id"], e["seq"], e["event_id"] = run_id, i, new_ids[e["event_id"]]
        if e.get("parent_id"):
            e["parent_id"] = new_ids.get(e["parent_id"])
        if e.get("error") and e["error"].get("related_event_id"):
            e["error"]["related_event_id"] = new_ids.get(e["error"]["related_event_id"])
        out.append(e)
    return out


def recompute_totals(events: list[Event]) -> None:
    """Make the run_end totals describe the edited trace (steps, tokens, cost, wall time)."""
    end = events[-1]
    if end["type"] != "run_end":
        return
    model = _model_calls(events)
    wall = _t(end["ts_start"]) - _t(events[0]["ts_start"])
    end["totals"] = {
        "steps": len(model),
        "input_tokens": sum(e.get("input_tokens", 0) for e in model),
        "output_tokens": sum(e.get("output_tokens", 0) for e in model),
        "cost_usd": round(sum(e.get("cost_usd", 0.0) for e in model), 6),
        "wall_ms": int(wall.total_seconds() * 1000),
    }


# ---------------------------------------------------------------- the flaws
@dataclass
class Flaw:
    name: str
    description: str
    drops: list[str]
    transform: Callable[[list[Event], dict[str, Any]], list[Event]]
    less_than: dict[str, str] | None = None
    #: Drops that only hold for some tasks, decided from the edited trace and the reference.
    conditional_drops: Callable[[list[Event], dict[str, Any]], list[str]] | None = None


def _unrecovered_tool_failure(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    """Break a required call and remove every later success of that capability."""
    required = wf.get("required") or [None]
    target = next((_first_ok(events, c) for c in required if _has_ok(events, c)), _first_ok(events))
    capability = target.get("capability")
    target["status"] = "error"
    target["result_preview"] = "upstream service returned an error"
    target["error"] = _error("tool", "tool_error", "upstream service returned an error")
    start = _index(events, target)
    return [
        e
        for i, e in enumerate(events)
        if not (
            i > start
            and e["type"] == "tool_call"
            and e["status"] == "ok"
            and e.get("capability") == capability
        )
    ]


def _has_ok(events: list[Event], capability: str | None) -> bool:
    try:
        _first_ok(events, capability)
        return True
    except Skip:
        return False


def _recovered_tool_failure(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    """Control: the same failure, but the agent retries and the call then succeeds."""
    required = wf.get("required") or [None]
    target = next((_first_ok(events, c) for c in required if _has_ok(events, c)), _first_ok(events))
    failed = copy.deepcopy(target)
    failed.update(
        event_id=f"new:recovered:{target['event_id']}",
        status="error",
        result_preview="upstream service returned an error",
        result_ref=None,
        result_sha256=None,
        error=_error("tool", "tool_error", "upstream service returned an error", retryable=True),
    )
    # Run the failure just before the original call, then the original call as the recovery.
    start = _t(target["ts_start"])
    failed["ts_start"], failed["ts_end"] = _iso(start - 2 * STEP), _iso(start - STEP)
    out = list(events)
    out.insert(_index(out, target), failed)
    return out


def _loop(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    """Three identical calls in a row, then the loop guard stops the run (loop guard N = 3)."""
    first = _first_ok(events)
    cut = _index(events, first)
    parent = next(e for e in reversed(events[:cut]) if e["type"] == "model_call")
    out = events[: cut + 1]
    for n in range(2):
        model = copy.deepcopy(parent)
        model["event_id"] = f"new:loop-model-{n}"
        model["ts_start"] = _iso(_t(out[-1].get("ts_end") or out[-1]["ts_start"]) + STEP)
        model["ts_end"] = _iso(_t(model["ts_start"]) + STEP)
        repeat = copy.deepcopy(first)
        repeat["event_id"] = f"new:loop-call-{n}"
        repeat["parent_id"] = model["event_id"]
        repeat["ts_start"] = _iso(_t(model["ts_end"]) + STEP)
        repeat["ts_end"] = _iso(_t(repeat["ts_start"]) + STEP)
        out += [model, repeat]
    blocked = copy.deepcopy(parent)  # the fourth attempt: the model asks again, the guard refuses
    blocked["event_id"] = "new:loop-model-blocked"
    blocked["ts_start"] = _iso(_t(out[-1].get("ts_end") or out[-1]["ts_start"]) + STEP)
    blocked["ts_end"] = _iso(_t(blocked["ts_start"]) + STEP)
    out.append(blocked)
    out.append(
        _fresh(
            "guard_stop",
            out[-1],
            limit="loop",
            limit_value=3,
            observed_value=4,
            error=_error("agent", "loop_detected", "same tool and arguments 4 times in a row"),
        )
    )
    return _finish(out, "budget_stopped")


def _loop_over_expected_steps(edited: list[Event], wf: dict[str, Any]) -> list[str]:
    """step_efficiency is 1.0 up to the task's ``expected_steps``, so a guard-stopped loop only
    scores lower on it when the loop makes more steps than that. Claim the drop only then."""
    expected = wf.get("expected_steps")
    steps = len(_model_calls(edited))
    return ["workflow.step_efficiency"] if expected is not None and steps > expected else []


def _wrong_order(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    """Swap the first calls of the two capabilities an ordering rule puts in sequence."""
    pairs = [(r["before"], r["after"]) for r in wf.get("ordering", [])]
    for before, after in pairs:
        if _has_ok(events, before) and _has_ok(events, after):
            a, b = _first_ok(events, before), _first_ok(events, after)
            break
    else:
        raise Skip("no ordering rule whose two capabilities are both used in the good run")
    swap = ("server", "tool", "capability", "args", "result_preview", "result_ref", "result_sha256")
    for key in swap:  # swap what was called; keep ids, parents and times in place
        a[key], b[key] = b.get(key), a.get(key)
    return events


def _forbidden_tool(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    forbidden = wf.get("forbidden") or []
    if not forbidden:
        raise Skip("the task reference has no forbidden capability (ask WS2 to add one)")
    calls = _tool_calls(events)
    if not calls:
        raise Skip("the good run makes no tool calls")
    last_ok = calls[-1]
    call = _fresh(
        "tool_call",
        last_ok,
        parent_id=last_ok.get("parent_id"),
        server="planted",
        tool=forbidden[0],
        capability=forbidden[0],
        args={},
        status="ok",
        result_preview="{}",
        result_ref=None,
        result_sha256=None,
        cost_usd=0.0,
    )
    out = list(events)
    out.insert(_index(out, last_ok) + 1, call)
    return out


def _unknown_tool(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    model = _model_calls(events)[0]
    err = _fresh(
        "error",
        model,
        parent_id=model["event_id"],
        error=_error("agent", "unknown_tool", "the model called 'geo_magic', which is not offered"),
    )
    out = list(events)
    out.insert(_index(out, model) + 1, err)
    return out


def _budget_stop(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    """Cut the run after its second step; the step guard stops it with no final output."""
    model = _model_calls(events)
    if len(model) < 3:
        raise Skip("the good run has fewer than three steps; nothing is left to cut")
    cut = _index(events, model[2])  # everything from the third model call on goes
    out = events[:cut]
    out.append(
        _fresh(
            "guard_stop",
            out[-1],
            limit="max_steps",
            limit_value=2,
            observed_value=3,
            error=_error("budget", "budget_exceeded", "max_steps limit of 2 reached"),
        )
    )
    return _finish(out, "budget_stopped")


def _fabricated_output(events: list[Event], wf: dict[str, Any]) -> list[Event]:
    """Replace the IDs in the final output with IDs that appear in no tool result."""
    final = next((e for e in events if e["type"] == "final_output"), None)
    if final is None:
        raise Skip("the good run has no final output")
    seen = " ".join(str(e.get("result_preview") or "") for e in _tool_calls(events))

    def fake(value: Any) -> Any:
        if isinstance(value, str) and len(value) >= 3 and value in seen:
            digest = hashlib.sha256(value.encode()).hexdigest()[:8]
            return f"fabricated-{digest}"  # same input, same fake: output is reproducible
        if isinstance(value, dict):
            return {k: fake(v) for k, v in value.items()}
        if isinstance(value, list):
            return [fake(v) for v in value]
        return value

    changed = fake(final["output"])
    if changed == final["output"]:
        raise Skip("no value in the final output comes from a tool result, so none can be faked")
    final["output"] = changed
    return events


FLAWS: list[Flaw] = [
    Flaw(
        "unrecovered_tool_failure",
        "A required call fails and the agent never gets that capability to succeed.",
        ["workflow.recovery", "workflow.required_coverage"],
        _unrecovered_tool_failure,
    ),
    Flaw(
        "recovered_tool_failure",
        "Control: the same failure, then a successful retry. Costs less than the unrecovered one.",
        ["workflow.recovery"],
        _recovered_tool_failure,
        less_than={"flaw": "unrecovered_tool_failure", "metric": "workflow.recovery"},
    ),
    Flaw(
        "loop",
        "The same call is repeated until the loop guard stops the run.",
        ["success"],
        _loop,
        conditional_drops=_loop_over_expected_steps,
    ),
    Flaw(
        "wrong_order",
        "Two capabilities an ordering rule puts in sequence are called the other way round.",
        ["workflow.ordering"],
        _wrong_order,
    ),
    Flaw(
        "forbidden_tool",
        "A capability the task forbids is called.",
        ["workflow.forbidden_tools"],
        _forbidden_tool,
    ),
    Flaw(
        "unknown_tool",
        "The agent calls a tool that is not in its tool set.",
        ["workflow.tool_call_validity"],
        _unknown_tool,
    ),
    Flaw(
        "budget_stop",
        "The step budget stops the run after two steps, with no final output.",
        ["success", "workflow.done_condition"],
        _budget_stop,
    ),
    Flaw(
        "fabricated_output",
        "The final output names items that no tool ever returned.",
        ["output.composite"],
        _fabricated_output,
    ),
]
FLAW_NAMES = [f.name for f in FLAWS]


# ---------------------------------------------------------------- reading and writing runs
def load_run(run_dir: Path) -> tuple[dict[str, Any], list[Event], str]:
    manifest = json.loads((run_dir / "manifest.json").read_text())
    events = [
        json.loads(line)
        for line in (run_dir / "trace.jsonl").read_text().splitlines()
        if line.strip()
    ]
    reference = run_dir / "reference.json"
    if not reference.exists():
        raise SystemExit(
            f"{reference} is missing: planted traces are built from the task reference"
        )
    if not events or events[-1]["type"] != "run_end" or events[-1]["state"] != "completed":
        raise SystemExit(f"{run_dir} is not a clean completed run; pick a different good run")
    if any(e.get("error") for e in events) or any(
        e["type"] == "tool_call" and e["status"] != "ok" for e in events
    ):
        raise SystemExit(f"{run_dir} has errors; the good run must be clean")
    return manifest, events, reference.read_text()


def write_run(
    dest: Path,
    manifest: dict[str, Any],
    events: list[Event],
    reference_text: str,
    *,
    expected: dict[str, Any] | None = None,
) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    (dest / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    (dest / "trace.jsonl").write_text(
        "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)
    )
    (dest / "reference.json").write_text(reference_text)
    if expected is not None:
        (dest / "expected.json").write_text(json.dumps(expected, indent=2) + "\n")


def build(
    good_dir: Path, template: str, out_root: Path, only: list[str] | None = None
) -> dict[str, str]:
    """Write ``good/`` and every buildable flaw. Returns ``{flaw: "written" | reason skipped}``."""
    manifest, events, reference_text = load_run(good_dir)
    workflow = json.loads(reference_text).get("workflow", {})
    good_id = manifest["run_id"]
    base = out_root / template
    shutil.rmtree(base, ignore_errors=True)  # a planted set is regenerated whole, never merged
    good_manifest = copy.deepcopy(manifest)
    write_run(base / "good", good_manifest, events, reference_text)

    results: dict[str, str] = {}
    for flaw in FLAWS:
        if only and flaw.name not in only:
            continue
        try:
            edited = flaw.transform(copy.deepcopy(events), workflow)
        except Skip as why:
            results[flaw.name] = f"skipped: {why}"
            continue
        run_id = f"{good_id}-{flaw.name}"
        flawed = renumber(edited, run_id)
        recompute_totals(flawed)
        flawed_manifest = copy.deepcopy(manifest)
        flawed_manifest["run_id"] = run_id
        flawed_manifest["environment"] = {
            **(flawed_manifest.get("environment") or {}),
            "planted": True,
            "planted_flaw": flaw.name,
            "source_run_id": good_id,
        }
        drops = list(flaw.drops)
        if flaw.conditional_drops:
            drops += [d for d in flaw.conditional_drops(edited, workflow) if d not in drops]
        expected: dict[str, Any] = {
            "good": "../good",
            "drops": drops,
            "description": flaw.description,
        }
        if flaw.less_than:
            expected["less_than"] = flaw.less_than
        write_run(base / flaw.name, flawed_manifest, flawed, reference_text, expected=expected)
        results[flaw.name] = "written"
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Generate planted (flawed) traces from a clean run.")
    ap.add_argument("--good", required=True, type=Path, help="clean run folder")
    ap.add_argument("--template", required=True, help="task template, e.g. T1")
    ap.add_argument("--out", type=Path, default=Path("samples/planted"))
    ap.add_argument("--flaws", help=f"comma-separated subset of: {', '.join(FLAW_NAMES)}")
    args = ap.parse_args(argv)
    only = [f for f in (args.flaws or "").split(",") if f]
    unknown = set(only) - set(FLAW_NAMES)
    if unknown:
        ap.error(f"unknown flaw(s): {sorted(unknown)}")
    for name, outcome in build(args.good, args.template, args.out, only or None).items():
        print(f"{args.template}/{name}: {outcome}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
