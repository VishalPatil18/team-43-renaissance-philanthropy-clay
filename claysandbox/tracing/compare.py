"""Tracer comparison from tee-tracer data (SHI-R2-02, FR-9.6, UC-06). Owner: WS3.

Compares tracers on *identical* runs recorded with the tee tracer: capture overhead per
event (median and p95 emit time), events lost (written but not readable back), and
fidelity (share of read-back events that equal the reference event field by field).

Reference for fidelity: the ``trace.jsonl`` copy, which is the canonical serialisation of the
events the sink stamped. When a run has no ``trace.jsonl`` the longest readable copy is used.

The result type is local to this module. The plan names Barath's
``MeasurementComparison(kind="tracer")``; his contract is not on ``main`` yet, so this
returns ``TracerComparison`` with the same intent. Map it onto his type when it lands.
"""

from __future__ import annotations

import json
import statistics
from collections.abc import Callable, Iterable, Mapping
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field

from claysandbox.contracts.trace import AnyEvent

from .tee import METRICS_FILE, percentile

#: Reads one trace file into (events, ended_abnormally).
FormatReader = Callable[[Path], tuple[list[AnyEvent], bool]]
#: tracer name (as in tracer_metrics.json) -> (trace file name, reader). The store owns the
#: readers (``store.reader.TRACE_FORMAT_READERS``) and the composition root passes them in,
#: because components do not import each other (architecture §4.1).
FormatReaders = Mapping[str, tuple[str, FormatReader]]


class TracerStats(BaseModel):
    tracer: str
    runs: int
    events_written: int
    events_read_back: int
    events_lost: int
    events_equal: int
    fidelity_pct: float
    emit_ms_median: float | None = None
    emit_ms_p95: float | None = None
    emit_errors: int = 0
    export_ms_total: float | None = None


class TracerComparison(BaseModel):
    kind: Literal["tracer"] = "tracer"
    run_ids: list[str]
    tracers: list[TracerStats]
    notes: list[str] = Field(default_factory=list)

    def to_measurement_comparison(self) -> dict[str, Any]:
        """The same result in the shape of WS4's ``MeasurementComparison(kind="tracer")``.

        Returned as a plain dict so this package need not import WS4's contract:
        ``MeasurementComparison.model_validate(result.to_measurement_comparison())``.
        Headline numbers are flat in ``values`` (``"<tracer>.<metric>"``); the full per-tracer
        stats are in ``details``.
        """
        values: dict[str, float | None] = {}
        for t in self.tracers:
            for metric in (
                "emit_ms_median",
                "emit_ms_p95",
                "events_written",
                "events_lost",
                "fidelity_pct",
            ):
                value = getattr(t, metric)
                values[f"{t.tracer}.{metric}"] = None if value is None else float(value)
        return {
            "kind": "tracer",
            "subjects": [t.tracer for t in self.tracers],
            "n_runs": len(self.run_ids),
            "values": values,
            "details": {"run_ids": self.run_ids, "tracers": [t.model_dump() for t in self.tracers]},
            "notes": list(self.notes),
        }


def compare_tracers(run_dirs: Iterable[str | Path], readers: FormatReaders) -> TracerComparison:
    """Compare the tracers found in tee-recorded run folders.

    ``readers`` is ``claysandbox.store.reader.TRACE_FORMAT_READERS``.
    """
    dirs = [Path(d) for d in run_dirs]
    if not dirs:
        raise ValueError("compare_tracers needs at least one run folder")

    notes: list[str] = []
    samples: dict[str, list[float]] = {}
    errors: dict[str, int] = {}
    export_ms: dict[str, float] = {}
    written: dict[str, int] = {}
    read_back: dict[str, int] = {}
    equal: dict[str, int] = {}
    runs: dict[str, int] = {}
    names_seen: list[str] = []

    for d in dirs:
        metrics = _load_metrics(d)
        if metrics is None:
            notes.append(f"{d.name}: no {METRICS_FILE}; overhead unavailable (not a tee run)")
        loaded: dict[str, list[AnyEvent]] = {}
        for tracer, (fname, reader) in readers.items():
            path = d / fname
            if path.exists():
                loaded[tracer] = reader(path)[0]
        if len(loaded) < 2:
            notes.append(f"{d.name}: found {sorted(loaded)}; need two formats to compare")
        reference = _reference(loaded)
        for tracer, events in loaded.items():
            if tracer not in names_seen:
                names_seen.append(tracer)
            runs[tracer] = runs.get(tracer, 0) + 1
            entry = (metrics or {}).get("tracers", {}).get(tracer)
            # "written" is what the tracer was handed; without metrics fall back to the reference
            w = entry["count"] if entry else len(reference)
            written[tracer] = written.get(tracer, 0) + w
            read_back[tracer] = read_back.get(tracer, 0) + len(events)
            by_seq = {e.seq: e for e in reference}
            equal[tracer] = equal.get(tracer, 0) + sum(1 for e in events if by_seq.get(e.seq) == e)
            if entry:
                samples.setdefault(tracer, []).extend(entry.get("emit_ms", []))
                errors[tracer] = errors.get(tracer, 0) + int(entry.get("errors", 0))
                if "export_ms_total" in entry:
                    export_ms[tracer] = export_ms.get(tracer, 0.0) + entry["export_ms_total"]

    stats: list[TracerStats] = []
    for tracer in names_seen:
        w, r, eq = written[tracer], read_back[tracer], equal[tracer]
        s = sorted(samples.get(tracer, []))
        stats.append(
            TracerStats(
                tracer=tracer,
                runs=runs[tracer],
                events_written=w,
                events_read_back=r,
                events_lost=max(0, w - r),
                events_equal=eq,
                fidelity_pct=round(100.0 * eq / w, 2) if w else 100.0,
                emit_ms_median=statistics.median(s) if s else None,
                emit_ms_p95=percentile(s, 95) if s else None,
                emit_errors=errors.get(tracer, 0),
                export_ms_total=export_ms.get(tracer),
            )
        )
    return TracerComparison(run_ids=[d.name for d in dirs], tracers=stats, notes=notes)


def _load_metrics(run_dir: Path) -> dict | None:
    path = run_dir / METRICS_FILE
    return json.loads(path.read_text()) if path.exists() else None


def _reference(loaded: dict[str, list[AnyEvent]]) -> list[AnyEvent]:
    if "jsonl" in loaded:
        return loaded["jsonl"]
    return max(loaded.values(), key=len, default=[])


def render_text(c: TracerComparison) -> str:
    """Plain-text table for the CLI (`compare-tracers`) and the eval report."""
    lines = [
        f"Tracer comparison over {len(c.run_ids)} run(s): " + ", ".join(c.run_ids),
        f"{'tracer':<8} {'median ms':>10} {'p95 ms':>9} {'written':>8} "
        f"{'read back':>9} {'lost':>5} {'fidelity':>9}",
    ]
    for t in c.tracers:
        med = f"{t.emit_ms_median:.3f}" if t.emit_ms_median is not None else "n/a"
        p95 = f"{t.emit_ms_p95:.3f}" if t.emit_ms_p95 is not None else "n/a"
        lines.append(
            f"{t.tracer:<8} {med:>10} {p95:>9} {t.events_written:>8} "
            f"{t.events_read_back:>9} {t.events_lost:>5} {t.fidelity_pct:>8.2f}%"
        )
    lines += [f"note: {n}" for n in c.notes]
    return "\n".join(lines)
