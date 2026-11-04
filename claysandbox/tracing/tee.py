"""Tee tracer (SHI-R2-02, FR-2.8, UC-06, DD-026). Owner: WS3.

Records one run through two tracers at once (default ``jsonl`` and ``otel``) and measures
how long each tracer's ``emit`` takes, so the two can be compared on identical events
(P7: measurement is compared apart from the measured thing, never through new agent runs).

Writes ``tracer_metrics.json`` into the run folder: per tracer the event count, median and
p95 emit time in milliseconds, the number of failed emits, and the raw per-event samples
so metrics from several runs can be pooled exactly. For tracers that export remotely it
also records the export time measured in the exporter callback (``OtelTracer``).

One tracer failing never stops the other, and ``emit`` never raises (FR-2.6).
"""

from __future__ import annotations

import json
import logging
import math
import os
import statistics
import tempfile
import time
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from claysandbox.contracts.registry import register, resolve
from claysandbox.contracts.trace import AnyEvent

log = logging.getLogger("claysandbox.tracing")

METRICS_FILE = "tracer_metrics.json"


def percentile(sorted_values: list[float], q: float) -> float:
    """Nearest-rank percentile of an already sorted list (q in 0..100)."""
    if not sorted_values:
        return 0.0
    rank = max(1, math.ceil(q / 100 * len(sorted_values)))
    return sorted_values[rank - 1]


@register("tracer", "tee")
class TeeTracer:
    name = "tee"
    version = "1"

    class Params(BaseModel):
        tracers: list[str] = ["jsonl", "otel"]
        tracer_params: dict[str, dict[str, Any]] = {}

    def __init__(self, params: TeeTracer.Params | dict | None = None, *, tracers: Any = None):
        self.params = params if isinstance(params, self.Params) else self.Params(**(params or {}))
        if tracers is not None:  # ready-made instances (tests, custom wiring)
            self._children: list[Any] = list(tracers)
        else:
            names = self.params.tracers
            if len(names) < 2 or len(set(names)) != len(names):
                raise ValueError("tee needs two or more different tracers, e.g. ['jsonl', 'otel']")
            if "tee" in names:
                raise ValueError("tee cannot contain itself")
            self._children = [resolve("tracer", n)(self.params.tracer_params.get(n)) for n in names]
        self._samples_ms: dict[str, list[float]] = {c.name: [] for c in self._children}
        self._errors: dict[str, int] = {c.name: 0 for c in self._children}
        self.run_id: str | None = None
        self.run_dir: Path | None = None
        self.incomplete = False

    # ------------------------------------------------------------ lifecycle
    def open(self, run_id: str, run_dir: Path) -> None:
        self.run_id, self.run_dir = run_id, Path(run_dir)
        opened: list[Any] = []
        try:
            for child in self._children:
                child.open(run_id, run_dir)
                opened.append(child)
        except Exception:
            for child in opened:  # do not leave half a tee running
                try:
                    child.close()
                except Exception:  # noqa: BLE001
                    log.exception("closing a tracer after a failed tee open")
            raise

    def emit(self, event: AnyEvent) -> None:
        for child in self._children:
            t0 = time.perf_counter_ns()
            try:
                child.emit(event)
            except Exception as e:  # noqa: BLE001  one tracer must not stop the other
                self._errors[child.name] += 1
                self.incomplete = True
                log.error(
                    "sandbox error",
                    extra={
                        "run_id": self.run_id,
                        "kind": f"tee_{child.name}_emit",
                        "error": repr(e),
                    },
                )
            finally:
                self._samples_ms[child.name].append((time.perf_counter_ns() - t0) / 1e6)
            if getattr(child, "incomplete", False):
                self.incomplete = True

    def close(self) -> None:
        for child in self._children:
            try:
                child.close()
            except Exception as e:  # noqa: BLE001
                self._errors[child.name] += 1
                self.incomplete = True
                log.error(
                    "sandbox error",
                    extra={
                        "run_id": self.run_id,
                        "kind": f"tee_{child.name}_close",
                        "error": repr(e),
                    },
                )
            if getattr(child, "incomplete", False):
                self.incomplete = True
        self._write_metrics()

    # ------------------------------------------------------------ metrics
    def metrics(self) -> dict[str, Any]:
        out: dict[str, Any] = {"run_id": self.run_id, "tracers": {}}
        for child in self._children:
            samples = self._samples_ms[child.name]
            ordered = sorted(samples)
            entry: dict[str, Any] = {
                "version": getattr(child, "version", ""),
                "count": len(samples),
                "median_ms": statistics.median(samples) if samples else 0.0,
                "p95_ms": percentile(ordered, 95),
                "errors": self._errors[child.name],
                "emit_ms": [round(s, 5) for s in samples],
            }
            if hasattr(child, "export_ns_total"):
                entry["export_ms_total"] = child.export_ns_total / 1e6
                entry["export_batches"] = child.export_batches
            out["tracers"][child.name] = entry
        return out

    def _write_metrics(self) -> None:
        if self.run_dir is None:
            return
        try:
            self.run_dir.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=self.run_dir, prefix=f".{METRICS_FILE}.")
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(self.metrics(), fh, indent=2)
            os.replace(tmp, self.run_dir / METRICS_FILE)
        except OSError as e:
            self.incomplete = True
            log.error(
                "sandbox error",
                extra={"run_id": self.run_id, "kind": "tee_metrics_write", "error": repr(e)},
            )
