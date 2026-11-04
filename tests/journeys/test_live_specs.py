"""Exercise the live runner with a local CLI stub; no models or tools are called."""

import os
import shutil
import subprocess
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[2]


def _stub_aws(bin_dir: Path, exit_code: int) -> None:
    """A fake ``aws`` whose ``sts get-caller-identity`` succeeds or fails."""
    aws = bin_dir / "aws"
    aws.write_text(f"#!/bin/sh\nexit {exit_code}\n")
    aws.chmod(0o755)


def test_runner_refuses_without_working_credentials(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    _stub_aws(bin_dir, exit_code=255)
    result = subprocess.run(
        ["bash", str(REPO / "scripts" / "live_journeys.sh"), "r1"],
        env={**os.environ, "PATH": f"{bin_dir}:{os.environ['PATH']}", "AWS_REGION": "us-west-2"},
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 2
    assert "No working AWS credentials" in result.stderr


def test_r1_runner_estimates_and_runs_both_j4_cases(tmp_path):
    shutil.copytree(REPO / "specs" / "live", tmp_path / "specs" / "live")
    for path in (tmp_path / "specs" / "live").glob("*.yaml"):
        path.write_text(path.read_text().replace("<", "stub-").replace(">", ""))
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    shutil.copy(REPO / "scripts" / "live_journeys.sh", scripts)
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    cli = bin_dir / "clay-sandbox"
    cli.write_text('#!/bin/sh\nprintf "%s\\n" "$*" >> "$LIVE_TEST_LOG"\n')
    cli.chmod(0o755)
    _stub_aws(bin_dir, exit_code=0)
    log = tmp_path / "calls.log"
    result = subprocess.run(
        ["bash", str(scripts / "live_journeys.sh"), "r1"],
        env={
            **os.environ,
            "PATH": f"{bin_dir}:{os.environ['PATH']}",
            "AWS_PROFILE": "stub",
            "AWS_REGION": "us-west-2",
            "LIVE_TEST_LOG": str(log),
        },
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, result.stderr
    assert log.read_text().splitlines() == [
        "estimate specs/live/j1.yaml",
        "run specs/live/j1.yaml",
        "estimate specs/live/j4.yaml",
        "run specs/live/j4.yaml",
        "estimate specs/live/j4-wrong-tool.yaml",
        "run specs/live/j4-wrong-tool.yaml",
    ]
    faulty = yaml.safe_load((REPO / "specs/live/j4.yaml").read_text())
    wrong_tool = yaml.safe_load((REPO / "specs/live/j4-wrong-tool.yaml").read_text())
    assert faulty["baseline"]["toolset"] == "T1-faulty"
    assert wrong_tool["baseline"]["toolset"] == "T0"
    assert wrong_tool["tasks"]["templates"] == ["T1"]
