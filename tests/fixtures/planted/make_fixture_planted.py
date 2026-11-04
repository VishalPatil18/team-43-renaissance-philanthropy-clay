"""Write the stand-in T1 planted set from ``tests/fixtures/traces/good_t1`` (BAR-R2-05).

Stand-in for Shivaani's ``samples/planted`` (SHI-R1-04) until it lands; same layout and the
``expected.json`` schema documented in ``claysandbox.evaluation.validate``. Deterministic:
the same input always gives byte-identical files.

    uv run python tests/fixtures/planted/make_fixture_planted.py
"""

from __future__ import annotations

import copy
import json
from collections.abc import Callable
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
GOOD = HERE.parent / "traces" / "good_t1"
TEMPLATE = "T1"
T0 = datetime(2026, 11, 4, 10, 0, 0)

Event = dict[str, Any]


def _read_events() -> list[Event]:
    lines = (GOOD / "trace.jsonl").read_text().splitlines()
    return [json.loads(line) for line in lines if line.strip()]


def _err(source: str, kind: str, message: str, retryable: bool = False) -> dict[str, Any]:
    return {
        "source": source,
        "kind": kind,
        "message": message,
        "retryable": retryable,
        "related_event_id": None,
    }


def _find(events: list[Event], type_: str, capability: str | None = None) -> int:
    for i, e in enumerate(events):
        if e["type"] == type_ and (capability is None or e.get("capability") == capability):
            return i
    raise LookupError(f"no {type_} {capability or ''}")


def _pair(events: list[Event], capability: str) -> tuple[int, int]:
    """Indices of a tool call of ``capability`` and the model call that requested it."""
    t = _find(events, "tool_call", capability)
    m = next(i for i, e in enumerate(events) if e["event_id"] == events[t]["parent_id"])
    return m, t


def _new_pair(tag: str, server: str, tool: str, capability: str | None, args: dict) -> list[Event]:
    model = {
        "schema_version": "1.0",
        "event_id": f"new-{tag}-m",
        "parent_id": None,
        "type": "model_call",
        "latency_ms": 1000.0,
        "error": None,
        "model_id": "fake-model",
        "input_tokens": 400,
        "output_tokens": 50,
        "stop_reason": "tool_use",
        "tool_use_requests": [{"name": f"{server}__{tool}" if server else tool, "input": args}],
        "text_preview": None,
        "cost_usd": 0.0004,
        "price_table_version": "fixed-1",
    }
    call = {
        "schema_version": "1.0",
        "event_id": f"new-{tag}-t",
        "parent_id": f"new-{tag}-m",
        "type": "tool_call",
        "latency_ms": 1000.0,
        "error": None,
        "server": server,
        "tool": tool,
        "capability": capability,
        "args": args,
        "status": "ok",
        "result_preview": "{}",
        "result_ref": None,
        "result_sha256": None,
        "cost_usd": 0.0,
    }
    return [model, call]


def _guard_stop(limit: str, limit_value: float, observed: float, error: dict) -> Event:
    return {
        "schema_version": "1.0",
        "event_id": "new-guard",
        "parent_id": None,
        "type": "guard_stop",
        "latency_ms": 1000.0,
        "error": error,
        "limit": limit,
        "limit_value": limit_value,
        "observed_value": observed,
    }


def _end(events: list[Event], state: str) -> list[Event]:
    """Drop everything after the last kept event and append a run_end with ``state``."""
    run_end = copy.deepcopy(next(e for e in _read_events() if e["type"] == "run_end"))
    run_end["state"] = state
    return [e for e in events if e["type"] != "run_end"] + [run_end]


# ------------------------------------------------------------------ flaw transforms
def unrecovered_tool_failure(events: list[Event]) -> list[Event]:
    """The required imagery_search fails and is never retried."""
    _, t = _pair(events, "imagery_search")
    call = events[t]
    call.update(status="error", result_preview=None)
    call["error"] = _err("tool", "tool_error", "STAC search returned an error", retryable=True)
    return [
        e for i, e in enumerate(events) if not (i > t and e.get("capability") == call["capability"])
    ]


def recovered_tool_failure(events: list[Event]) -> list[Event]:
    """A failed imagery_search right before the successful one (control flaw)."""
    m, t = _pair(events, "imagery_search")
    failed = copy.deepcopy(events[m : t + 1])
    for e in failed:
        e["event_id"] = f"new-retry-{e['event_id']}"
    failed[1]["parent_id"] = failed[0]["event_id"]
    failed[1].update(status="error", result_preview=None)
    failed[1]["error"] = _err("tool", "tool_error", "STAC search returned an error", True)
    return events[:m] + failed + events[m:]


def loop(events: list[Event]) -> list[Event]:
    """The imagery_search call repeated 4 times identically, stopped by the loop guard."""
    m, t = _pair(events, "imagery_search")
    repeats: list[Event] = []
    for k in range(4):
        pair = copy.deepcopy(events[m : t + 1])
        for e in pair:
            e["event_id"] = f"new-loop{k}-{e['event_id']}"
        pair[1]["parent_id"] = pair[0]["event_id"]
        repeats += pair
    stop = _guard_stop("loop", 3, 4, _err("agent", "loop_detected", "same call 4 times in a row"))
    return _end(events[:m] + repeats + [stop], "budget_stopped")


def wrong_order(events: list[Event]) -> list[Event]:
    """imagery_search before geocode, against the rule ``geocode before imagery_search``."""
    gm, gt = _pair(events, "geocode")
    im, it = _pair(events, "imagery_search")
    assert gt < im, "good trace must call geocode first"
    return events[:gm] + events[im : it + 1] + events[gm : gt + 1] + events[it + 1 :]


def forbidden_tool(events: list[Event]) -> list[Event]:
    """A call of the forbidden ``dataset_discovery`` capability before the answer."""
    i = _find(events, "final_output") - 1  # the end_turn model call
    pair = _new_pair("forbidden", "roda", "search_datasets", "dataset_discovery", {"q": "naip"})
    return events[:i] + pair + events[i:]


def unknown_tool(events: list[Event]) -> list[Event]:
    """A call of a tool that is not in the tool set."""
    i = _find(events, "final_output") - 1
    pair = _new_pair("unknown", "", "fly_drone", None, {"area": "kern"})
    pair[1].update(status="rejected", result_preview=None)
    pair[1]["error"] = _err("agent", "unknown_tool", "fly_drone is not in the tool set")
    return events[:i] + pair + events[i:]


def budget_stop(events: list[Event]) -> list[Event]:
    """Truncated after step 2 by ``max_steps=2``."""
    _, t = _pair(events, "imagery_search")
    steps = sum(e["type"] == "model_call" for e in events[: t + 1])
    assert steps == 2, steps
    stop = _guard_stop(
        "max_steps", 2, 2, _err("budget", "budget_exceeded", "max_steps 2 reached (observed 2)")
    )
    return _end(events[: t + 1] + [stop], "budget_stopped")


def fabricated_output(events: list[Event]) -> list[Event]:
    """The final output lists item IDs that no tool result returned."""
    final = events[_find(events, "final_output")]
    final["output"] = {
        "items": ["ca_m_3511899_sw_11_060_20220601", "ca_m_3511898_se_11_060_20220601"]
    }
    return events


FLAWS: dict[str, tuple[Callable[[list[Event]], list[Event]], dict[str, Any]]] = {
    "unrecovered_tool_failure": (
        unrecovered_tool_failure,
        {"drops": ["workflow.recovery", "workflow.required_coverage"]},
    ),
    "recovered_tool_failure": (
        recovered_tool_failure,
        {
            "drops": ["workflow.recovery"],
            "less_than": {"flaw": "unrecovered_tool_failure", "metric": "workflow.recovery"},
        },
    ),
    "loop": (loop, {"drops": ["success", "workflow.step_efficiency"]}),
    "wrong_order": (wrong_order, {"drops": ["workflow.ordering"]}),
    "forbidden_tool": (forbidden_tool, {"drops": ["workflow.forbidden_tools"]}),
    "unknown_tool": (unknown_tool, {"drops": ["workflow.tool_call_validity"]}),
    "budget_stop": (budget_stop, {"drops": ["success", "workflow.done_condition"]}),
    "fabricated_output": (
        fabricated_output,
        {"drops": ["output.precision", "output.recall", "output.f1"]},
    ),
}


# ------------------------------------------------------------------ renumbering and output
def _renumber(events: list[Event], run_id: str) -> list[Event]:
    """Fresh run ID, contiguous seq/event_id, remapped parent IDs, increasing timestamps."""
    ids = {e["event_id"]: f"{run_id}:{i}" for i, e in enumerate(events)}
    out: list[Event] = []
    for i, e in enumerate(events):
        e = copy.deepcopy(e)
        e["run_id"] = run_id
        e["seq"] = i
        e["event_id"] = ids[e["event_id"]]
        if e.get("parent_id") is not None:
            e["parent_id"] = ids[e["parent_id"]]
        start = T0 + timedelta(seconds=2 * i)
        e["ts_start"] = start.strftime("%Y-%m-%dT%H:%M:%SZ")
        e["ts_end"] = (start + timedelta(seconds=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
        if e["type"] == "run_end":
            steps = sum(x["type"] == "model_call" for x in events)
            cost = sum(x.get("cost_usd", 0.0) for x in events if x["type"] == "model_call")
            e["totals"] = {"steps": steps, "cost_usd": round(cost, 6)}
        # Keep a stable key order: the schema fields first as in the source trace.
        ordered = {k: e[k] for k in ("schema_version", "run_id", "seq", "event_id") if k in e}
        ordered.update({k: v for k, v in e.items() if k not in ordered})
        out.append(ordered)
    return out


def _manifest(run_id: str, flaw: str) -> str:
    m = json.loads((GOOD / "manifest.json").read_text())
    m["run_id"] = run_id
    m["eval_id"] = "planted-fixture"
    m["environment"] = {"planted": flaw != "good", "planted_flaw": flaw, "planted_from": "good_t1"}
    if flaw == "budget_stop":
        m["budget"] = {**m.get("budget", {}), "max_steps": 2}
    return json.dumps(m, indent=2) + "\n"


def _jsonl(events: list[Event]) -> str:
    return "".join(json.dumps(e, separators=(",", ":")) + "\n" for e in events)


def build() -> dict[str, str]:
    """Every file of the planted set, as ``{path relative to HERE: text}``."""
    reference = (GOOD / "reference.json").read_text()
    files: dict[str, str] = {}
    for flaw, (transform, expected) in [("good", (lambda e: e, {})), *FLAWS.items()]:
        run_id = f"planted-{TEMPLATE.lower()}-{flaw.replace('_', '-')}"
        d = f"{TEMPLATE}/{flaw}"
        files[f"{d}/trace.jsonl"] = _jsonl(_renumber(transform(_read_events()), run_id))
        files[f"{d}/manifest.json"] = _manifest(run_id, flaw)
        files[f"{d}/reference.json"] = reference
        if flaw != "good":
            body = {"good": "../good", **expected, "description": transform.__doc__}
            files[f"{d}/expected.json"] = json.dumps(body, indent=2) + "\n"
    return files


def main() -> None:
    for rel, text in build().items():
        p = HERE / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    print(f"wrote {len(build())} files under {HERE}")


if __name__ == "__main__":
    main()
