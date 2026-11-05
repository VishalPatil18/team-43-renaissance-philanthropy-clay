"""Pure Markdown views of persisted run and evaluation records."""

import json
from typing import Any
from urllib.parse import quote


def _text(value):
    if value is None or value == "" or value == [] or value == {}:
        return "–"
    if isinstance(value, (dict, list)):
        value = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return str(value).replace("|", "\\|").replace("\n", "<br>")


def _table(headers, rows):
    return [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
        *("| " + " | ".join(_text(v) for v in row) + " |" for row in rows),
        "",
    ]


def _bullets(values):
    return [*(f"- {_text(v)}" for v in values), ""] if values else ["–", ""]


def _component(value):
    return value.get("name") if isinstance(value, dict) else value


def render_run_report(
    manifest: dict, trace_events: list[dict], summary: dict | None, assessments: list[dict]
) -> str:
    """Render a run, retaining every assessment and event in input order."""
    end: dict[str, Any] = next(
        (e for e in reversed(trace_events) if e.get("type") == "run_end"), {}
    )
    lines = [f"# Run {_text(manifest.get('run_id'))} — {_text(end.get('state'))}", ""]
    lines += _table(
        ["Field", "Value"],
        [
            ("Task instance", manifest.get("task_instance_id")),
            ("Config", manifest.get("config_name")),
            ("Model", (manifest.get("model") or {}).get("params", {}).get("model_id")),
            ("Harness", _component(manifest.get("harness"))),
            ("Toolset", _component(manifest.get("toolset"))),
            ("Task reference version", manifest.get("task_reference_version")),
            ("Seed", manifest.get("seed")),
        ],
    )
    latest: dict[str, dict[str, Any]] = {}
    for assessment in assessments:
        kind = str(assessment.get("kind", ""))
        previous = latest.get(kind)
        if previous is None or str(assessment.get("created_at", "")) >= str(
            previous.get("created_at", "")
        ):
            latest[kind] = assessment
    lines += ["## Headline scores", ""]
    lines += _table(
        ["Kind", "Composite", "Success / metrics / repeats"],
        [
            (kind, latest.get(kind, {}).get("composite"), latest.get(kind, {}).get(field))
            for kind, field in [
                ("workflow", "success"),
                ("output", "metrics"),
                ("process", "repeats"),
            ]
        ],
    )
    for assessment in assessments:
        evaluator = assessment.get("evaluator") or {}
        lines += [
            f"## Assessment: {_text(assessment.get('kind'))} — "
            f"{_text(evaluator.get('name'))}@{_text(evaluator.get('version'))}",
            "",
            f"Composite: {_text(assessment.get('composite'))}",
            "",
        ]
        for score in assessment.get("subscores", []):
            value = score.get("value")
            filled = round(max(0, min(1, value)) * 10) if value is not None else 0
            bar = "█" * filled + "░" * (10 - filled)
            number = f"{value:.2f}" if value is not None else "–"
            lines += [f"- {_text(score.get('name'))}: {bar} {number}"]
            lines += [f"  - Note: {_text(n)}" for n in score.get("notes", [])]
            lines += [f"  - Evidence event IDs: {_text(score.get('evidence'))}"]
        for field in ("metrics", "success", "repeats", "evidence", "notes"):
            lines += [f"{field.title()}: {_text(assessment.get(field))}", ""]
    lines += ["## Summary claims", ""]
    lines += _bullets(
        [
            f"{claim.get('claim', '–')} [{', '.join(claim.get('event_ids', [])) or '–'}]"
            for claim in (summary or {}).get("claims", [])
        ]
    )
    lines += ["## Timeline", ""]
    rows = []
    for event in trace_events:
        error = event.get("error") or {}
        tool = (
            f"{_text(event.get('server'))}.{_text(event.get('tool'))}"
            if event.get("type") == "tool_call"
            else None
        )
        rows.append(
            (
                event.get("seq"),
                event.get("event_id"),
                event.get("type"),
                tool,
                event.get("status", event.get("state")),
                f"{error.get('source', '–')}/{error.get('kind', '–')}" if error else None,
                event.get("latency_ms"),
                event.get("cost_usd"),
            )
        )
    lines += _table(
        ["Seq", "Event ID", "Type", "Tool", "Status", "Error", "Latency (ms)", "Cost ($)"], rows
    )
    totals = end.get("totals") or {}
    lines += ["## Totals", ""]
    lines += _table(
        ["Measure", "Value"],
        [
            ("Steps", totals.get("steps")),
            ("Tokens", totals.get("tokens")),
            ("Agent cost ($)", totals.get("cost_usd")),
            ("Evaluation cost ($)", sum(a.get("cost_usd") or 0 for a in assessments)),
        ],
    )
    lines += ["## Provenance", ""]
    lines += _table(
        ["Field", "Value"],
        [
            (key, manifest.get(key))
            for key in ("budget", "loop_guard", "price_table_version", "git_sha", "environment")
        ],
    )
    return "\n".join(lines)


def render_eval_report(report: dict) -> str:
    """Render EvalReportContent serialized as a dictionary."""
    lines = [
        f"# Evaluation {_text(report.get('eval_id'))}",
        "",
        f"Baseline: {_text(report.get('baseline'))}",
        "",
        "## Variants",
        "",
    ]
    lines += _table(
        ["Variant", "Axis", "Changed", "Warning"],
        [
            tuple(v.get(k) for k in ("variant", "axis", "changed", "warning"))
            for v in report.get("variants", [])
        ],
    )
    stats = report.get("stats") or {}
    lines += ["## Per-config stats", ""]
    for config in stats.get("configs", []):
        lines += [f"### {_text(config.get('config_name'))}", ""]
        intervals = [("success_rate", config.get("success_rate") or {})]
        intervals += list(config.get("metrics", {}).items())
        lines += _table(
            ["Metric", "Estimate", "CI low–high", "n", "Method"],
            [
                (
                    name,
                    interval.get("estimate"),
                    f"{_text(interval.get('low'))}–{_text(interval.get('high'))}",
                    interval.get("n"),
                    interval.get("method"),
                )
                for name, interval in intervals
            ],
        )
        lines += _bullets(config.get("warnings", []))
    lines += ["## Paired comparisons", ""]
    lines += _table(
        ["Baseline", "Variant", "Metric", "Effect", "CI", "p", "Adjusted p", "Pairs", "Verdict"],
        [
            (
                c.get("baseline"),
                c.get("variant"),
                c.get("metric"),
                c.get("effect"),
                f"{_text(c.get('ci_low'))}–{_text(c.get('ci_high'))}",
                c.get("p_value"),
                c.get("p_adjusted"),
                c.get("n_instances"),
                c.get("verdict"),
            )
            for c in stats.get("comparisons", [])
        ],
    )
    lines += _bullets([w for c in stats.get("comparisons", []) for w in c.get("warnings", [])])
    for heading, key in [("Verdicts", "verdicts"), ("Exclusions", "exclusions")]:
        lines += [f"## {heading}", ""]
        lines += _bullets([f"{k}: {_text(v)}" for k, v in report.get(key, {}).items()])
    for kind in ("evaluator", "tracer"):
        comparison = report.get(f"{kind}_comparison") or {}
        lines += [f"## {kind.title()} comparison", ""]
        lines += _table(["Field", "Value"], list(comparison.items()))
    lines += ["## Warnings", ""] + _bullets(report.get("warnings", []))
    lines += ["## Run links", ""]
    for config, runs in report.get("run_links", {}).items():
        lines += [f"### {_text(config)}", ""]
        lines += _bullets(
            [f"[{_text(run)}](../../runs/{quote(run, safe='')}/report.md)" for run in runs]
        )
    return "\n".join(lines)
