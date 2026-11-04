"""Run-store conformance (arch §7.7, §13.2), shared by every registered store."""

from __future__ import annotations

import json

import pytest

import claysandbox.contracts.fakes
import claysandbox.store.local  # noqa: F401  registers LocalRunStore
from claysandbox.contracts.registry import _REGISTRY, resolve
from claysandbox.contracts.store import StoreWriteRefused

STORES = sorted(name for kind, name in _REGISTRY if kind == "store")


def make(name, tmp_path):
    cls = resolve("store", name)
    if name == "memory":
        return cls()
    return cls(root=tmp_path / "runs", evals_root=tmp_path / "evals")


MANIFEST = {"run_id": "r1", "eval_id": "e1", "prompt": "find NAIP for Kern County"}


@pytest.mark.parametrize("name", STORES)
def test_manifest_written_once(name, tmp_path):
    s = make(name, tmp_path)
    s.create_run(MANIFEST)
    assert s.read_manifest("r1")["prompt"] == MANIFEST["prompt"]
    with pytest.raises(StoreWriteRefused):
        s.create_run(MANIFEST)


@pytest.mark.parametrize("name", STORES)
def test_assessments_never_overwritten(name, tmp_path):
    s = make(name, tmp_path)
    s.create_run(MANIFEST)
    s.append_assessment("r1", {"assessment_id": "a1", "composite": 0.8})
    s.append_assessment("r1", {"assessment_id": "a2", "composite": 0.9})
    with pytest.raises(StoreWriteRefused):
        s.append_assessment("r1", {"assessment_id": "a1", "composite": 0.1})
    assert sorted(a["composite"] for a in s.list_assessments("r1")) == [0.8, 0.9]


@pytest.mark.parametrize("name", STORES)
def test_terminal_status_is_final(name, tmp_path):
    s = make(name, tmp_path)
    s.create_run(MANIFEST)
    s.write_status("r1", "running")
    s.write_status("r1", "completed")
    assert s.read_status("r1").state == "completed"
    with pytest.raises(StoreWriteRefused):
        s.write_status("r1", "running")


@pytest.mark.parametrize("name", STORES)
def test_views_may_be_overwritten(name, tmp_path):
    s = make(name, tmp_path)
    s.create_run(MANIFEST)
    s.write_summary("r1", {"claims": [1]})
    s.write_summary("r1", {"claims": [2]})
    s.write_report("r1", {"v": 1}, {"report.md": "# one"})
    s.write_report("r1", {"v": 2}, {"report.md": "# two"})


@pytest.mark.parametrize("name", STORES)
def test_eval_artifacts(name, tmp_path):
    s = make(name, tmp_path)
    s.create_eval("e1", {"name": "compare-default", "trials": 3})
    s.write_eval_artifact(
        "e1", "plan.json", json.dumps({"runs": [{"run_id": "r1"}, {"run_id": "r2"}]})
    )
    assert s.list_eval_runs("e1") == ["r1", "r2"]
    assert (
        json.loads(s.read_eval_artifact("e1", "plan.json"))["runs"][0]["run_id"] == "r1"
    )
    with pytest.raises(StoreWriteRefused):
        s.create_eval("e1", {})
    with pytest.raises(StoreWriteRefused):
        s.write_eval_artifact("e1", "spec.yaml", "changed")
