"""Hand-written fixture traces (BAR-R0-00): good_t1, errors_t1, loop_t1."""

from __future__ import annotations

from pathlib import Path

from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace, parse_event

ROOT = Path(__file__).parent
NAMES = ("good_t1", "errors_t1", "loop_t1")


def load_run(d: Path) -> tuple[Trace, RunManifest, TaskReference]:
    """Load ``trace.jsonl``, ``manifest.json`` and ``reference.json`` from a run folder."""
    events = [parse_event(line) for line in (d / "trace.jsonl").read_text().splitlines() if line]
    manifest = RunManifest.model_validate_json((d / "manifest.json").read_text())
    reference = TaskReference.model_validate_json((d / "reference.json").read_text())
    incomplete = not events or events[-1].type != "run_end"
    return Trace(run_id=manifest.run_id, events=events, incomplete=incomplete), manifest, reference


def load(name: str) -> tuple[Trace, RunManifest, TaskReference]:
    return load_run(ROOT / name)
