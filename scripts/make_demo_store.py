#!/usr/bin/env python3
"""Build a small offline run store for the UI prototype (no network, no AWS, no model calls).

It holds the three hand-written fixture runs (``tests/fixtures/traces/{good_t1,errors_t1,
loop_t1}``). Every run is scored by the deterministic ``workflow`` and ``output``
evaluators, summarised, and marked terminal (which locks it like a real run). All runs belong
to one eval with a stored ``eval_report.json`` built by ``build_eval_report_content``.

Usage::

    uv run python scripts/make_demo_store.py --out /tmp/demo-store
    uv run python -m claysandbox.api --store /tmp/demo-store
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace, parse_event
from claysandbox.evaluation.compare import build_eval_report_content
from claysandbox.platform import registry_bootstrap  # noqa: F401  (registers the evaluators)
from claysandbox.store.local import LocalRunStore
from claysandbox.summary.deterministic import DeterministicSummarizer

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures" / "traces"
FIXTURE_RUNS = ("good_t1", "errors_t1", "loop_t1")
EVAL_ID = "demo-eval"
CONFIG = "fixture-baseline"
EVALUATORS = ("workflow", "output")


def build(out: Path) -> LocalRunStore:
    """Write the demo store under ``out`` (``runs/`` and ``evals/``). Refuses an existing folder."""
    out = Path(out)
    out.mkdir(parents=True, exist_ok=False)
    store = LocalRunStore(out / "runs", out / "evals")

    runs: list[tuple[RunManifest, list[dict], TaskReference]] = []
    for name in FIXTURE_RUNS:
        d = FIXTURES / name
        lines = [json.loads(x) for x in (d / "trace.jsonl").read_text().splitlines() if x]
        manifest = RunManifest.model_validate_json((d / "manifest.json").read_text())
        manifest = manifest.model_copy(update={"eval_id": EVAL_ID})
        reference = TaskReference.model_validate_json((d / "reference.json").read_text())
        runs.append((manifest, lines, reference))

    summarizer = DeterministicSummarizer()
    evaluators = [resolve("evaluator", n)() for n in EVALUATORS]
    manifests, assessments, states, totals = [], [], {}, {}
    for manifest, lines, reference in runs:
        directory = store.create_run(manifest.model_dump(mode="json"))
        (directory / "reference.json").write_text(reference.model_dump_json(indent=2))
        store.write_status(manifest.run_id, "running")
        events = [parse_event(json.dumps(line)) for line in lines]
        (store.run_dir(manifest.run_id) / "trace.jsonl").write_text(
            "".join(json.dumps(line, separators=(",", ":")) + "\n" for line in lines)
        )
        trace = Trace(run_id=manifest.run_id, events=events)
        for evaluator in evaluators:
            a = evaluator.assess(trace, manifest, reference)
            store.append_assessment(manifest.run_id, a)
            assessments.append(a)
        store.write_summary(manifest.run_id, summarizer.summarize(trace, manifest))
        end = events[-1]
        state = end.state if end.type == "run_end" else "agent_failed"
        store.write_status(manifest.run_id, state)  # terminal: locks manifest and trace
        manifests.append(manifest)
        states[manifest.run_id] = state
        totals[manifest.run_id] = end.totals if end.type == "run_end" else {}

    store.create_eval(
        EVAL_ID,
        {"eval_id": EVAL_ID, "baseline": CONFIG, "variants": {}, "evaluators": list(EVALUATORS)},
    )
    store.write_eval_artifact(
        EVAL_ID, "plan.json", json.dumps({"runs": [m.run_id for m in manifests]}, indent=2)
    )
    report = build_eval_report_content(
        EVAL_ID,
        None,
        CONFIG,
        {},
        manifests=manifests,
        assessments=assessments,
        run_states=states,
        totals=totals,
    )
    store.write_eval_artifact(EVAL_ID, "eval_report.json", report.model_dump_json(indent=2))
    return store


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--out", required=True, type=Path, help="new folder for the store")
    args = ap.parse_args(argv)
    try:
        store = build(args.out)
    except FileExistsError:
        print(f"{args.out} already exists; pick a new folder", file=sys.stderr)
        return 1
    print(f"demo store with {len(store.list_runs())} runs at {args.out}")
    print(f"start the UI: uv run python -m claysandbox.api --store {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
