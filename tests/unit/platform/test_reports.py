import json
from pathlib import Path

from claysandbox.contracts.manifest import RunManifest
from claysandbox.contracts.registry import resolve
from claysandbox.contracts.stats import RunRow
from claysandbox.contracts.task import TaskReference
from claysandbox.contracts.trace import Trace, parse_event
from claysandbox.evaluation.compare import build_eval_report_content
from claysandbox.platform import registry_bootstrap  # noqa: F401
from claysandbox.platform.reports import render_eval_report, render_run_report
from claysandbox.summary.deterministic import DeterministicSummarizer


def test_fixture_report():
    root = Path("tests/fixtures/traces/good_t1")
    manifest = RunManifest.model_validate_json((root / "manifest.json").read_text())
    reference = TaskReference.model_validate_json((root / "reference.json").read_text())
    events = [json.loads(line) for line in (root / "trace.jsonl").read_text().splitlines()]
    trace = Trace(run_id=manifest.run_id, events=[parse_event(e) for e in events])
    assessments = [
        resolve("evaluator", name)().assess(trace, manifest, reference).model_dump()
        for name in ("workflow", "output")
    ]
    summary = DeterministicSummarizer().summarize(trace, manifest).model_dump()
    report = render_run_report(manifest.model_dump(), events, summary, assessments)
    for text in (
        manifest.run_id,
        "completed",
        "Task reference",
        "workflow",
        "output",
        "Timeline",
        "Provenance",
        "Evaluation cost",
        "█",
        events[0]["event_id"],
    ):
        assert text in report
    assert "rubric" not in report.lower()


def test_eval_report():
    rows = [
        RunRow(
            run_id=f"{config}-{i}",
            config_name=config,
            task_instance_id=f"T1@{i}",
            state="completed",
            success=True,
            metrics={"workflow.composite": 0.8},
        )
        for config in ("base", "variant")
        for i in range(3)
    ]
    content = build_eval_report_content(
        "eval-test", rows, "base", {"variant": {"harness": {"name": "other"}}}, iterations=20
    )
    report = render_eval_report(content.model_dump())
    for text in (
        "eval-test",
        "Baseline: base",
        "Variants",
        "harness",
        "Per-config stats",
        "success_rate",
        "Paired comparisons",
        "Verdicts",
        "Exclusions",
        "Warnings",
        "Evaluator comparison",
        "Tracer comparison",
        "Run links",
        "base-0",
    ):
        assert text in report


def test_missing_values_and_last_end():
    report = render_run_report(
        {},
        [
            {"type": "run_end", "state": "agent_failed"},
            {"type": "run_end", "state": "completed"},
        ],
        None,
        [],
    )
    assert report.startswith("# Run – — completed")
    assert "–" in render_eval_report({})
