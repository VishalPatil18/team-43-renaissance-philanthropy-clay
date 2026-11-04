"""Planted-trace validation of evaluators (architecture §11, FR-10.6, FR-10.7, DD-038).

Planted folder layout
---------------------
::

    <planted_root>/<template>/<flaw>/manifest.json
                                    /trace.jsonl
                                    /reference.json   (optional with ``reference_loader``)
                                    /expected.json

A sub-folder is a flaw when it holds ``expected.json``. The good run it is compared with
is named by ``expected.json``; it is usually ``<planted_root>/<template>/good/``.

``expected.json``
-----------------
::

    {
      "good": "../good",
      "drops": ["workflow.recovery", "workflow.required_coverage"],
      "less_than": {"flaw": "unrecovered_tool_failure", "metric": "workflow.recovery"},
      "description": "free text, ignored"
    }

* ``good`` (default ``"../good"``): the good run folder, relative to the flaw folder.
* ``drops`` (required, non-empty): every metric that must score strictly lower on the
  flawed run than on the good run. Metric names:

  - ``workflow.<subscore>`` and ``workflow.composite`` (workflow evaluator),
  - ``output.<metric>`` and ``output.composite`` (output evaluator),
  - ``process.<subscore>`` and ``process.composite`` (LLM process evaluator),
  - ``success`` (the workflow evaluator's ``success``, true = 1, false or none = 0).

* ``less_than`` (optional): a control flaw. The drop on ``metric`` (good minus flawed)
  must be strictly smaller than the drop of the named flaw of the same template.

A flaw is *detected* when every drop (and the ``less_than`` relation) holds. Drops whose
evaluator was not run (for example ``process.*`` without an LLM evaluator) are listed in
``FlawResult.unchecked`` and do not count either way.

Report
------
* ``detection_rate[flaw]``: detected / (template, flaw) pairs with something checkable.
* ``margin``: mean ``workflow.composite`` over the good runs minus mean over every flawed
  run (output-only flaws included, so they pull the margin down), compared with
  ``ci_halfwidth`` when given. ``None`` without a workflow evaluator.
* ``margins``: the same good-minus-flawed composite margin, separately per evaluator kind.
* ``llm_agreement``: only when a non-deterministic evaluator is passed; see :func:`validate`.

The task reference comes from ``reference.json`` in each run folder, or from
``reference_loader(run_dir, manifest)``. Apart from reading the planted folder this is pure.
At most one evaluator per kind is accepted, so metric names stay unambiguous; compare
evaluator versions with one ``validate`` call each.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from claysandbox.contracts.assessment import Assessment, Evaluator
from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.stats import FlawResult, ValidationReport
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace, parse_event
from claysandbox.evaluation._keys import assessment_values, metric_key

ReferenceLoader = Callable[[Path, RunManifest], TaskReference]
Run = tuple[Trace, RunManifest, TaskReference]


def _load_run(d: Path, reference_loader: ReferenceLoader | None) -> Run:
    lines = (d / "trace.jsonl").read_text().splitlines()
    events = [parse_event(line) for line in lines if line.strip()]
    manifest = RunManifest.model_validate_json((d / "manifest.json").read_text())
    if reference_loader is not None:
        reference = reference_loader(d, manifest)
    else:
        reference = TaskReference.model_validate_json((d / "reference.json").read_text())
    incomplete = not events or events[-1].type != "run_end"
    trace = Trace(run_id=manifest.run_id, events=events, incomplete=incomplete)
    return trace, manifest, reference


def _label(ev: Evaluator) -> str:
    return f"{ev.name}@{ev.version}" if ev.version else ev.name


def _values(a: Assessment) -> dict[str, float | None]:
    out = assessment_values(a)
    if a.kind == "workflow":
        out["success"] = 1.0 if a.success else 0.0
    return out


def _kind_of(metric: str) -> str:
    return "workflow" if metric == "success" else metric.split(".", 1)[0]


def _lower(bad: dict[str, float | None], good: dict[str, float | None], metric: str) -> bool:
    b, g = bad.get(metric), good.get(metric)
    return b is not None and g is not None and b < g


def _score(
    evaluators: Sequence[Evaluator], run: Run, spreads: list[float]
) -> dict[str, float | None]:
    """All metric values of one run; LLM repeat spreads (max - min over k) go to ``spreads``."""
    values: dict[str, float | None] = {}
    for ev in evaluators:
        a = ev.assess(*run)
        values.update(_values(a))
        if not ev.deterministic and a.repeats:
            spreads.append(max(a.repeats) - min(a.repeats))
    return values


@dataclass
class _Scored:
    template: str
    flaw: str
    expected: dict[str, Any]
    good_dir: Path
    good: dict[str, float | None]
    bad: dict[str, float | None]


def _score_planted(
    root: Path,
    evaluators: Sequence[Evaluator],
    reference_loader: ReferenceLoader | None,
    spreads: list[float],
) -> tuple[list[_Scored], dict[Path, dict[str, float | None]]]:
    goods: dict[Path, dict[str, float | None]] = {}
    scored: list[_Scored] = []
    for template_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        flaw_dirs = sorted(p for p in template_dir.iterdir() if (p / "expected.json").exists())
        for flaw_dir in flaw_dirs:
            expected: dict[str, Any] = json.loads((flaw_dir / "expected.json").read_text())
            good_dir = (flaw_dir / expected.get("good", "../good")).resolve()
            if good_dir not in goods:
                goods[good_dir] = _score(evaluators, _load_run(good_dir, reference_loader), spreads)
            bad = _score(evaluators, _load_run(flaw_dir, reference_loader), spreads)
            scored.append(
                _Scored(template_dir.name, flaw_dir.name, expected, good_dir, goods[good_dir], bad)
            )
    return scored, goods


def _drop(s: _Scored, metric: str) -> float | None:
    g, b = s.good.get(metric), s.bad.get(metric)
    return None if g is None or b is None else g - b


def _flaw_result(s: _Scored, siblings: dict[str, _Scored], kinds: list[str]) -> FlawResult:
    drops = list(s.expected["drops"])
    unchecked = [m for m in drops if _kind_of(m) not in kinds]
    missing = [m for m in drops if m not in unchecked and not _lower(s.bad, s.good, m)]
    notes: list[str] = []
    rel = s.expected.get("less_than")
    if rel is not None:
        key = f"less_than:{rel['flaw']}:{rel['metric']}"
        other = siblings.get(rel["flaw"])
        if _kind_of(rel["metric"]) not in kinds:
            unchecked.append(key)
        elif other is None:
            missing.append(key)
            notes.append(f"less_than names flaw {rel['flaw']!r}, not in this template")
        else:
            mine, theirs = _drop(s, rel["metric"]), _drop(other, rel["metric"])
            if mine is None or theirs is None or not mine < theirs:
                missing.append(key)
            notes.append(f"{rel['metric']} drop {mine} vs {rel['flaw']} drop {theirs}")
    checked = len(drops) + (rel is not None) - len(unchecked)
    if not checked:
        notes.append("no expected drop could be checked")
    shown = [m for m in drops if m not in unchecked]
    return FlawResult(
        template=s.template,
        flaw=s.flaw,
        expected_drops=drops,
        detected=checked > 0 and not missing,
        good_value={m: s.good.get(m) for m in shown},
        bad_value={m: s.bad.get(m) for m in shown},
        missing=missing,
        unchecked=unchecked,
        notes=notes,
    )


def default_evaluators() -> list[Evaluator]:
    """The deterministic evaluators CI validates: latest workflow and the output dispatcher."""
    import claysandbox.evaluation.output  # noqa: F401  (registers the evaluators)
    import claysandbox.evaluation.workflow  # noqa: F401

    return [resolve("evaluator", "workflow")(), resolve("evaluator", "output")()]


def validate(
    evaluators: Sequence[Evaluator] | None = None,
    planted_root: str | Path = "samples/planted",
    ci_halfwidth: float | None = None,
    reference_loader: ReferenceLoader | None = None,
) -> ValidationReport:
    """Score every planted flaw against its good run and report detection (FR-10.6).

    ``evaluators`` defaults to :func:`default_evaluators`. A non-deterministic (LLM)
    evaluator is only run when passed here; ``llm_agreement`` is then the mean spread
    (max - min) of its k repeat composites over every scored run (0 = perfect agreement).
    """
    if evaluators is None:
        evaluators = default_evaluators()
    kinds: list[str] = [e.kind for e in evaluators]
    if len(set(kinds)) != len(kinds):
        raise ValueError(
            "validate() takes at most one evaluator per kind; call it once per version"
        )
    spreads: list[float] = []
    scored, goods = _score_planted(Path(planted_root), evaluators, reference_loader, spreads)
    report = ValidationReport(evaluators=[_label(e) for e in evaluators])
    for s in scored:
        siblings = {o.flaw: o for o in scored if o.template == s.template}
        report.flaws.append(_flaw_result(s, siblings, kinds))
    by_flaw: dict[str, list[bool]] = {}
    for f in report.flaws:
        if f.detected or f.missing:
            by_flaw.setdefault(f.flaw, []).append(f.detected)
    report.detection_rate = {k: sum(v) / len(v) for k, v in sorted(by_flaw.items())}
    report.ci_halfwidth = ci_halfwidth
    if spreads:
        report.llm_agreement = sum(spreads) / len(spreads)
        report.notes.append(
            f"llm_agreement = mean spread of LLM repeat composites over {len(spreads)} "
            "assessments (lower is better)"
        )
    report.margins = {
        kind: _margin(list(goods.values()), [s.bad for s in scored], metric_key(kind, "composite"))
        for kind in kinds
    }
    report.margin = report.margins.get("workflow")
    if report.margin is None:
        report.notes.append("no margin: no workflow composite on both good and flawed runs")
    elif ci_halfwidth is not None:
        report.margin_exceeds_ci = report.margin > ci_halfwidth
    return report


def _margin(
    goods: list[dict[str, float | None]], bads: list[dict[str, float | None]], metric: str
) -> float | None:
    """mean(good composite) - mean(flawed composite) for one evaluator kind."""
    g = [v for v in (x.get(metric) for x in goods) if v is not None]
    b = [v for v in (x.get(metric) for x in bads) if v is not None]
    if not g or not b:
        return None
    return sum(g) / len(g) - sum(b) / len(b)


def _num(v: float | None) -> str:
    return "n/a" if v is None else f"{v:.4g}"


def format_report(report: ValidationReport) -> str:
    """Plain-text report for ``clay-sandbox validate-evaluator``."""
    lines = [f"Planted-trace validation of {', '.join(report.evaluators)}", ""]
    for f in report.flaws:
        head = f"  {f.template}/{f.flaw}"
        if f.detected:
            lines.append(f"{head}  detected")
        elif f.missing:
            why = [
                f"{m} (good {_num(f.good_value.get(m))}, flawed {_num(f.bad_value.get(m))})"
                if m in f.good_value
                else m
                for m in f.missing
            ]
            lines.append(f"{head}  MISSED: {', '.join(why)}")
        else:
            lines.append(f"{head}  not checked")
        if f.unchecked:
            lines.append(f"      unchecked: {', '.join(f.unchecked)}")
    lines += ["", "Detection rate per flaw type:"]
    lines += [f"  {k}: {v:.0%}" for k, v in report.detection_rate.items()]
    lines.append("")
    if report.margin is None:
        lines.append("margin: n/a")
    elif report.ci_halfwidth is None:
        lines.append(f"margin {_num(report.margin)} (no CI half-width given)")
    else:
        verdict = "exceeds" if report.margin_exceeds_ci else "does NOT exceed"
        lines.append(
            f"margin {_num(report.margin)} vs CI half-width {_num(report.ci_halfwidth)}: {verdict}"
        )
    for kind, margin in report.margins.items():
        lines.append(f"{kind} margin: {_num(margin)}")
    if report.llm_agreement is not None:
        lines.append(f"LLM agreement over k (mean spread): {_num(report.llm_agreement)}")
    lines += [f"note: {n}" for n in report.notes]
    return "\n".join(lines) + "\n"
