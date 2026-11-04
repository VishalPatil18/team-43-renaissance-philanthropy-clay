"""Trace reader with schema upgrades (SHI-R0-03, FR-2.9, FR-7.5). Owner: WS3.

``read_trace(run_dir)`` parses ``trace.jsonl`` into a ``Trace``; when only the OTel
tracer ran it rebuilds the same events from ``trace.otlp.jsonl`` (FR-2.7, SHI-R2-01).
A missing ``run_end`` or a truncated last line (a crash) gives ``incomplete=True`` and
keeps every valid event before it. Older schema versions are upgraded through
``UPGRADES``; a newer, unknown version raises a clear error.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Literal

from claysandbox.contracts.trace import (
    OTEL_EVENT_ATTR,
    SCHEMA_VERSION,
    AnyEvent,
    Trace,
    parse_event,
)

JSONL_FILE = "trace.jsonl"
OTLP_FILE = "trace.otlp.jsonl"
TRACE_FILES = (JSONL_FILE, OTLP_FILE)  # JSONL first: it is the canonical copy when both exist
TraceSource = Literal["jsonl", "otlp"]

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


def _json_lines(path: Path) -> Iterator[dict | None]:
    """Yield each line as a dict. Yield ``None`` once for a line that is not a JSON object
    (truncated by a crash, or garbage) and then stop, so callers keep what came before."""
    with path.open("r", encoding="utf-8") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                raw = json.loads(line)
            except json.JSONDecodeError:
                raw = None
            if not isinstance(raw, dict):
                yield None
                return
            yield raw


def read_jsonl_events(path: str | Path) -> tuple[list[AnyEvent], bool]:
    """Events from a ``trace.jsonl`` file and whether the file ended abnormally."""
    events: list[AnyEvent] = []
    incomplete = False
    for raw in _json_lines(Path(path)):
        if raw is None:
            incomplete = True
            break
        events.append(parse_event(upgrade_event(raw)))
    return events, incomplete or not events or events[-1].type != "run_end"


def _event_json(span: dict[str, Any]) -> str | None:
    """The ``clay.event`` attribute of one OTLP/JSON span, or None (e.g. the root span)."""
    for attr in span.get("attributes", []):
        if attr.get("key") == OTEL_EVENT_ATTR:
            value = attr["value"]["stringValue"]
            return value if isinstance(value, str) else None
    return None


def read_otlp_events(path: str | Path) -> tuple[list[AnyEvent], bool]:
    """Rebuild events from a ``trace.otlp.jsonl`` file written by the OTel tracer."""
    events: list[AnyEvent] = []
    incomplete = False
    for envelope in _json_lines(Path(path)):
        if envelope is None:
            incomplete = True
            break
        try:
            spans = [
                span
                for rs in envelope["resourceSpans"]
                for ss in rs["scopeSpans"]
                for span in ss["spans"]
            ]
            for span in spans:
                payload = _event_json(span)
                if payload is not None:
                    events.append(parse_event(upgrade_event(json.loads(payload))))
        except (KeyError, TypeError, json.JSONDecodeError):
            incomplete = True  # valid JSON, but not a span envelope we wrote
            break
    events.sort(key=lambda e: e.seq)
    return events, incomplete or not events or events[-1].type != "run_end"


def read_trace(
    run_dir: str | Path, run_id: str | None = None, source: TraceSource | None = None
) -> Trace:
    """Read a run's trace. ``source`` forces one format (used to compare tracers);
    by default ``trace.jsonl`` wins and ``trace.otlp.jsonl`` is the fallback."""
    run_dir = Path(run_dir)
    names = {"jsonl": (JSONL_FILE,), "otlp": (OTLP_FILE,), None: TRACE_FILES}[source]
    path = next((run_dir / f for f in names if (run_dir / f).exists()), None)
    rid = run_id or run_dir.name
    if path is None:
        return Trace(run_id=rid, events=[], incomplete=True).with_blobs(blob_loader(run_dir))
    reader = read_otlp_events if path.name == OTLP_FILE else read_jsonl_events
    events, incomplete = reader(path)
    if events:
        rid = events[0].run_id or rid
    return Trace(run_id=rid, events=events, incomplete=incomplete).with_blobs(blob_loader(run_dir))
