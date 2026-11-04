"""J6.2 / FR-10.7: the deterministic evaluators detect every planted flaw, in CI.

Runs on Shivaani's ``samples/planted`` when it exists, else on the stand-in set under
``tests/fixtures/planted`` (regenerate with ``tests/fixtures/planted/make_fixture_planted.py``).
"""

from pathlib import Path

from claysandbox.evaluation.validate import default_evaluators, format_report, validate

REPO = Path(__file__).resolve().parents[2]
SAMPLES = REPO / "samples" / "planted"
FIXTURES = REPO / "tests" / "fixtures" / "planted"
PLANTED = SAMPLES if SAMPLES.is_dir() else FIXTURES

FLAWS = {
    "unrecovered_tool_failure",
    "recovered_tool_failure",
    "loop",
    "wrong_order",
    "forbidden_tool",
    "unknown_tool",
    "budget_stop",
    "fabricated_output",
}


def test_deterministic_evaluators_detect_every_planted_flaw():
    report = validate(default_evaluators(), planted_root=PLANTED)
    text = format_report(report)

    assert report.evaluators == ["workflow@1", "output@1"]
    assert report.flaws, f"no planted flaws under {PLANTED}"
    missing = {f"{f.template}/{f.flaw}": f.missing for f in report.flaws if f.missing}
    assert not missing, f"expected drops missing:\n{text}"
    assert all(f.detected for f in report.flaws), text
    assert set(report.detection_rate) >= FLAWS, text
    assert all(rate == 1.0 for rate in report.detection_rate.values()), text
    assert report.margin is not None and report.margin > 0, text


def test_stand_in_planted_set_matches_its_generator():
    from tests.fixtures.planted.make_fixture_planted import build

    files = build()
    assert files == build()  # deterministic
    for rel, text in files.items():
        assert (FIXTURES / rel).read_text() == text, f"{rel} is stale: rerun the generator"
