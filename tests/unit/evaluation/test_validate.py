"""Planted-trace validation (BAR-R2-05): ``validate()`` over a small planted folder."""

import json
import shutil
from pathlib import Path

import pytest

import claysandbox.evaluation.output  # noqa: F401  (registers the evaluators)
import claysandbox.evaluation.workflow  # noqa: F401
from claysandbox.contracts.registry import resolve
from claysandbox.evaluation.validate import format_report, validate
from tests.fixtures.traces import ROOT as TRACES

GOOD = TRACES / "good_t1"


def _events(d: Path) -> list[dict]:
    return [json.loads(line) for line in (d / "trace.jsonl").read_text().splitlines() if line]


def _write_events(d: Path, events: list[dict]) -> None:
    (d / "trace.jsonl").write_text("".join(json.dumps(e) + "\n" for e in events))


def planted(root: Path, flaw: str, edit, expected: dict, template: str = "T1") -> Path:
    """Copy good_t1 to ``<root>/<template>/good`` (once) and a flawed copy to ``<flaw>``."""
    good = root / template / "good"
    if not good.exists():
        shutil.copytree(GOOD, good)
    d = root / template / flaw
    shutil.copytree(GOOD, d)
    _write_events(d, edit(_events(d)))
    (d / "expected.json").write_text(json.dumps({"good": "../good", **expected}))
    return d


def forbid(events: list[dict]) -> list[dict]:
    """Turn the geocode call into a call of the forbidden ``dataset_discovery``."""
    for e in events:
        if e["type"] == "tool_call" and e["capability"] == "geocode":
            e["capability"] = "dataset_discovery"
    return events


def keep(events: list[dict]) -> list[dict]:
    return events


def fabricate(events: list[dict]) -> list[dict]:
    for e in events:
        if e["type"] == "final_output":
            e["output"] = {"items": ["made_up_1", "made_up_2"]}
    return events


def fail_search(events: list[dict]) -> list[dict]:
    for e in events:
        if e["type"] == "tool_call" and e["capability"] == "imagery_search":
            e["status"] = "error"
            e["error"] = {"source": "tool", "kind": "tool_error", "message": "boom"}
    return events


def workflow():
    return resolve("evaluator", "workflow@1")()


def output():
    return resolve("evaluator", "output")()


def test_flaw_detected_when_expected_subscore_drops(tmp_path):
    planted(tmp_path, "forbidden_tool", forbid, {"drops": ["workflow.forbidden_tools"]})

    report = validate([workflow()], planted_root=tmp_path)

    [flaw] = report.flaws
    assert (flaw.template, flaw.flaw) == ("T1", "forbidden_tool")
    assert flaw.detected is True
    assert flaw.missing == []
    assert flaw.good_value["workflow.forbidden_tools"] == 1.0
    assert flaw.bad_value["workflow.forbidden_tools"] == 0.0
    assert report.detection_rate == {"forbidden_tool": 1.0}
    assert report.evaluators == ["workflow@1"]


def test_drop_that_does_not_happen_is_missing(tmp_path):
    planted(tmp_path, "no_change", keep, {"drops": ["workflow.recovery", "success"]})

    [flaw] = validate([workflow()], planted_root=tmp_path).flaws

    assert flaw.detected is False
    assert flaw.missing == ["workflow.recovery", "success"]


def test_output_drop_checked_with_output_evaluator(tmp_path):
    planted(tmp_path, "fabricated_output", fabricate, {"drops": ["output.f1", "output.precision"]})

    [flaw] = validate([workflow(), output()], planted_root=tmp_path).flaws

    assert flaw.detected is True
    assert flaw.bad_value["output.f1"] == 0.0


def test_drop_of_an_evaluator_not_run_is_unchecked(tmp_path):
    planted(tmp_path, "fabricated_output", fabricate, {"drops": ["output.f1"]})
    planted(
        tmp_path, "forbidden_tool", forbid, {"drops": ["workflow.forbidden_tools", "output.f1"]}
    )

    report = validate([workflow()], planted_root=tmp_path)
    fab, forb = report.flaws

    assert fab.unchecked == ["output.f1"] and fab.missing == []
    assert forb.unchecked == ["output.f1"] and forb.detected is True
    # A flaw with nothing checkable does not count towards detection.
    assert report.detection_rate == {"forbidden_tool": 1.0}


def recover_search(events: list[dict]) -> list[dict]:
    """Insert a failed imagery_search right before the successful one (recovered)."""
    i = next(n for n, e in enumerate(events) if e.get("capability") == "imagery_search")
    failed = json.loads(json.dumps(events[i]))
    failed["event_id"] += "x"
    failed["status"] = "error"
    failed["error"] = {"source": "tool", "kind": "tool_error", "message": "boom"}
    return events[:i] + [failed] + events[i:]


CONTROL = {"flaw": "unrecovered_tool_failure", "metric": "workflow.recovery"}


def test_control_flaw_must_drop_less_than_the_named_flaw(tmp_path):
    planted(tmp_path, "unrecovered_tool_failure", fail_search, {"drops": ["workflow.recovery"]})
    planted(
        tmp_path,
        "recovered_tool_failure",
        recover_search,
        {"drops": ["workflow.recovery"], "less_than": CONTROL},
    )

    flaws = {f.flaw: f for f in validate([workflow()], planted_root=tmp_path).flaws}

    assert flaws["recovered_tool_failure"].bad_value["workflow.recovery"] == 0.75
    assert flaws["recovered_tool_failure"].detected is True


def test_control_flaw_that_drops_as_much_is_not_detected(tmp_path):
    planted(tmp_path, "unrecovered_tool_failure", fail_search, {"drops": ["workflow.recovery"]})
    planted(
        tmp_path,
        "recovered_tool_failure",
        fail_search,
        {"drops": ["workflow.recovery"], "less_than": CONTROL},
    )

    flaws = {f.flaw: f for f in validate([workflow()], planted_root=tmp_path).flaws}

    control = flaws["recovered_tool_failure"]
    assert control.detected is False
    assert control.missing == ["less_than:unrecovered_tool_failure:workflow.recovery"]


@pytest.mark.parametrize(("ci", "exceeds"), [(None, None), (0.1, True), (0.2, False)])
def test_margin_is_good_minus_bad_workflow_composite(tmp_path, ci, exceeds):
    # forbidden_tools 0 of eight equal-weight sub-scores: composite 7/8.
    planted(tmp_path, "forbidden_tool", forbid, {"drops": ["workflow.forbidden_tools"]})
    # unrecovered search: recovery 0 and required_coverage 0: composite 6/8.
    planted(tmp_path, "unrecovered", fail_search, {"drops": ["workflow.recovery"]})

    report = validate([workflow()], planted_root=tmp_path, ci_halfwidth=ci)

    assert report.margin == pytest.approx(1.0 - (7 / 8 + 6 / 8) / 2)
    assert report.ci_halfwidth == ci
    assert report.margin_exceeds_ci is exceeds


def test_no_margin_without_a_workflow_evaluator(tmp_path):
    planted(tmp_path, "fabricated_output", fabricate, {"drops": ["output.f1"]})

    report = validate([output()], planted_root=tmp_path, ci_halfwidth=0.1)

    assert report.margin is None and report.margin_exceeds_ci is None
    assert any("margin" in n for n in report.notes)


class FakeJudge:
    """A non-deterministic process evaluator: k=3 repeats, lower scores on flawed runs."""

    name = "fake_judge"
    version = "1"
    kind = "process"
    deterministic = False

    def assess(self, trace, manifest, reference):
        from claysandbox.contracts.assessment import Assessment
        from claysandbox.contracts.manifest import ComponentRef

        flawed = any(
            e.type == "tool_call" and e.capability == "dataset_discovery" for e in trace.events
        )
        repeats = [0.2, 0.3, 0.4] if flawed else [0.9, 0.9, 1.0]
        return Assessment(
            run_id=manifest.run_id,
            evaluator=ComponentRef(kind="evaluator", name=self.name, version=self.version),
            kind="process",
            task_reference_version=reference.version,
            composite=sum(repeats) / 3,
            repeats=repeats,
        )


def test_default_evaluators_are_deterministic_workflow_and_output(tmp_path):
    planted(tmp_path, "fabricated_output", fabricate, {"drops": ["output.f1", "process.composite"]})

    report = validate(planted_root=tmp_path)

    assert report.evaluators == ["workflow@1", "output@1"]
    assert report.llm_agreement is None
    assert report.flaws[0].unchecked == ["process.composite"]


def test_llm_evaluator_given_explicitly_reports_mean_spread_over_k(tmp_path):
    planted(tmp_path, "forbidden_tool", forbid, {"drops": ["process.composite"]})

    report = validate([workflow(), FakeJudge()], planted_root=tmp_path)

    assert report.flaws[0].detected is True
    # Spreads: good run 0.1, flawed run 0.2.
    assert report.llm_agreement == pytest.approx(0.15)


def test_format_report_lists_each_flaw_rate_and_margin(tmp_path):
    planted(tmp_path, "forbidden_tool", forbid, {"drops": ["workflow.forbidden_tools"]})
    planted(tmp_path, "no_change", keep, {"drops": ["workflow.recovery"]})

    text = format_report(validate([workflow()], planted_root=tmp_path, ci_halfwidth=0.01))

    assert "workflow@1" in text
    assert "T1/forbidden_tool  detected" in text
    assert "T1/no_change  MISSED: workflow.recovery (good 1, flawed 1)" in text
    assert "forbidden_tool: 100%" in text and "no_change: 0%" in text
    assert "margin 0.0625 vs CI half-width 0.01: exceeds" in text


def test_reference_loader_replaces_reference_json(tmp_path):
    d = planted(tmp_path, "forbidden_tool", forbid, {"drops": ["workflow.forbidden_tools"]})
    reference = (GOOD / "reference.json").read_text()
    (d / "reference.json").unlink()
    (tmp_path / "T1" / "good" / "reference.json").unlink()
    seen = []

    def loader(run_dir, manifest):
        from claysandbox.contracts.task import TaskReference

        seen.append(manifest.task_instance_id)
        return TaskReference.model_validate_json(reference)

    report = validate([workflow()], planted_root=tmp_path, reference_loader=loader)

    assert report.flaws[0].detected is True
    assert seen == ["T1@us-ca-kern", "T1@us-ca-kern"]


def test_margins_are_reported_separately_for_every_evaluator_kind(tmp_path):
    planted(tmp_path, "forbidden_tool", forbid, {"drops": ["workflow.forbidden_tools"]})
    planted(tmp_path, "fabricated_output", fabricate, {"drops": ["output.f1"]})

    report = validate([workflow(), output(), FakeJudge()], planted_root=tmp_path, ci_halfwidth=0.1)

    assert report.margins == pytest.approx(
        {
            "workflow": 1 / 16,
            "output": 0.5,
            "process": (0.9 + 0.9 + 1.0) / 3 - ((0.2 + 0.3 + 0.4) / 3 + (0.9 + 0.9 + 1.0) / 3) / 2,
        }
    )
    assert report.margin == report.margins["workflow"]
    assert report.margin_exceeds_ci is False
    text = format_report(report)
    assert "output margin: 0.5" in text
    assert "process margin:" in text


def test_output_only_validation_has_output_margin_without_workflow_margin(tmp_path):
    planted(tmp_path, "fabricated_output", fabricate, {"drops": ["output.f1"]})
    report = validate([output()], planted_root=tmp_path, ci_halfwidth=0.1)
    assert report.margins == {"output": 1.0}
    assert report.margin is None
    assert report.margin_exceeds_ci is None
