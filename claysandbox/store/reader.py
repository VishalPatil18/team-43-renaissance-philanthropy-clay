"""Trace reader with schema upgrades (SHI-R0-03, FR-2.9, FR-7.5). Owner: WS3.

``read_trace(run_dir)`` parses ``trace.jsonl`` into a ``Trace``. A missing
``run_end`` or a truncated last line (a crash) gives ``incomplete=True`` and
keeps every valid event before it. Older schema versions are upgraded through
``UPGRADES``; a newer, unknown version raises a clear error.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path

from claysandbox.contracts.trace import SCHEMA_VERSION, Trace, parse_event

TRACE_FILES = ("trace.jsonl",)  # R2 (SHI-R2-01) adds trace.otlp.jsonl as a fallback

# schema_version -> function that upgrades one raw event dict to the next version.
# Add an entry per new version, e.g. "1.0": upgrade_1_0_to_1_1, then "1.1": identity.
UPGRADES: dict[str, Callable[[dict], dict]] = {"1.0": lambda d: d}


class UnsupportedTraceVersion(ValueError):
    pass


def _version_key(v: str) -> tuple[int, ...]:
    try:
        return tuple(int(p) for p in v.split("."))
    except ValueError:
        raise UnsupportedTraceVersion(f"unreadable trace schema version {v!r}") from None


def upgrade_event(raw: dict) -> dict:
    version = str(raw.get("schema_version", "1.0"))
    if version not in UPGRADES:
        if _version_key(version) > _version_key(SCHEMA_VERSION):
            raise UnsupportedTraceVersion(
                f"trace schema {version} is newer than this reader ({SCHEMA_VERSION}); "
                "update claysandbox"
            )
        raise UnsupportedTraceVersion(f"unknown trace schema version {version}")
    while version != SCHEMA_VERSION:
        raw = UPGRADES[version](raw)
        version = str(raw.get("schema_version"))
    return UPGRADES[SCHEMA_VERSION](raw)


def blob_loader(run_dir: Path) -> Callable[[str], bytes]:
    root = (Path(run_dir) / "blobs").resolve()

    def load(ref: str) -> bytes:
        path = (Path(run_dir) / ref).resolve()
        if root not in path.parents:  # refs come from trace data: never leave blobs/
            raise ValueError(f"blob ref outside the run's blobs folder: {ref!r}")
        return path.read_bytes()

    return load


def read_trace(run_dir: str | Path, run_id: str | None = None) -> Trace:
    run_dir = Path(run_dir)
    path = next((run_dir / f for f in TRACE_FILES if (run_dir / f).exists()), None)
    rid = run_id or run_dir.name
    if path is None:
        return Trace(run_id=rid, events=[], incomplete=True).with_blobs(blob_loader(run_dir))
    events, incomplete = [], False
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                raw = None  # truncated line: a crash mid-write
            if not isinstance(raw, dict):
                # Not an event at all (truncated, or garbage that happens to be valid
                # JSON). Keep what came before and flag the trace.
                incomplete = True
                break
            events.append(parse_event(upgrade_event(raw)))
    if not events or events[-1].type != "run_end":
        incomplete = True
    if events:
        rid = events[0].run_id or rid
    return Trace(run_id=rid, events=events, incomplete=incomplete).with_blobs(blob_loader(run_dir))
