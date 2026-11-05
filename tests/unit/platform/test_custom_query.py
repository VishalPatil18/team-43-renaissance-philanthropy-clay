"""Custom queries end to end on fake components: spec, plan, worker, expect evaluator, CLI."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import BaseModel

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.cli import main
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.model import FakeModelAdapter, text_reply
from claysandbox.contracts.fakes.tools import FakeToolSession
from claysandbox.contracts.registry import register
from claysandbox.contracts.spec import EvalSpec
from claysandbox.platform import custom, query, service
from claysandbox.runtime.testing import SEARCH_TOOL
from claysandbox.store.local import LocalRunStore

LITE, PRO = "us.amazon.nova-lite-v1:0", "us.amazon.nova-pro-v1:0"
ANSWER = "I found item ABC123 in Kern County."


@register("model", "fake-answer")
class AnswerModel(FakeModelAdapter):
    """Answers every question at once with ``ANSWER``."""

    name = "fake-answer"
    version = "test"

    class Params(BaseModel):
        model_id: str = LITE

    def __init__(self, params: dict | None = None):
        super().__init__([], model_id=self.Params(**(params or {})).model_id)

    def converse(self, messages, system, tools, params):  # type: ignore[no-untyped-def]
        self.calls.append({"system": system})
        return text_reply(ANSWER).model_copy(update={"model_id": self.model_id})


@register("toolset", "fake-none")
class NoTools:
    name = "fake-none"
    version = "test"

    def open_blocking(self, *_a, **_k):
        return FakeToolSession([SEARCH_TOOL], {})


def _spec(models=(LITE,), expect=("ABC123", "Fresno")) -> EvalSpec:
    return query.build_spec(
        "Find NAIP items over Kern County",
        list(models),
        expect=list(expect),
        adapter="fake-answer",
        toolset="fake-none",
    )


def test_build_spec_makes_one_custom_task_and_a_config_per_model():
    spec = _spec(models=(LITE, PRO))
    assert [t.id for t in spec.tasks.custom] == ["find-naip-items-over-kern-county"]
    assert spec.baseline.name == "nova-lite-v1" and spec.variants[0].name == "nova-pro-v1"
    assert spec.variants[0].override == {"model": {"params": {"model_id": PRO}}}
    assert query.config_name("us.anthropic.claude-sonnet-4-6:0") == "claude-sonnet-4-6"
    with pytest.raises(ConfigError):
        query.build_spec("q", [LITE, LITE])


def test_custom_only_spec_plans_only_its_queries():
    reqs = service.plan(_spec(models=(LITE, PRO)), "e1")
    assert [r.task_instance_id for r in reqs] == ["Q@find-naip-items-over-kern-county"] * 2
    assert reqs[0].extra["custom_task"]["expect"] == ["ABC123", "Fresno"]
    assert reqs[0].extra["evaluators"] == custom.EVALUATORS


def test_library_and_custom_tasks_mix():
    spec = _spec().model_copy(deep=True)
    spec.tasks.templates, spec.tasks.aois = ["T1"], ["us-ca-kern"]
    ids = [r.task_instance_id for r in service.plan(spec, "e1")]
    assert ids == ["T1@us-ca-kern", "Q@find-naip-items-over-kern-county"]
    library_req = service.plan(spec, "e1")[0]
    assert "custom_task" not in library_req.extra


def test_custom_task_ids_must_be_unique():
    data = _spec().model_dump()
    data["tasks"]["custom"].append(data["tasks"]["custom"][0])
    with pytest.raises(ConfigError):
        service.plan(EvalSpec.model_validate(data), "e1")


def test_query_runs_and_scores_expected_strings(tmp_path: Path):
    result = service.run_eval(_spec(), store_dir=tmp_path, poll_seconds=0.05)
    assert set(result.states.values()) == {"completed"}
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    run_id = result.run_ids[0]
    manifest = json.loads((store.run_dir(run_id) / "manifest.json").read_text())
    assert manifest["task_instance_id"] == "Q@find-naip-items-over-kern-county"
    assert manifest["system_prompt"] == custom.SYSTEM_PROMPT
    ref = json.loads((store.run_dir(run_id) / "reference.json").read_text())
    assert ref["output_reference"] == {"expect": ["ABC123", "Fresno"]}
    (a,) = store.list_assessments(run_id)
    assert a["evaluator"]["name"] == "expect" and a["composite"] == 0.5
    assert "Fresno" in a["notes"][0]
    (row,) = query.results(store, result.run_ids)
    assert row["answer"] == ANSWER and row["found"] == 0.5 and row["state"] == "completed"
    assert (tmp_path / "evals" / result.eval_id / "eval_report.json").exists()


def test_query_without_expectations_is_unscored(tmp_path: Path):
    result = service.run_eval(_spec(expect=()), store_dir=tmp_path, poll_seconds=0.05)
    store = LocalRunStore(tmp_path / "runs", tmp_path / "evals")
    (a,) = store.list_assessments(result.run_ids[0])
    assert a["composite"] is None and "nothing to score" in a["notes"][0]


def test_cli_query_compares_models(tmp_path: Path, capsys):
    argv = ["query", "Find NAIP items over Kern County", "--model", LITE, "--model", PRO]
    argv += ["--expect", "abc123", "--adapter", "fake-answer", "--toolset", "fake-none"]
    argv += ["--store", str(tmp_path)]
    assert main(argv) == 2  # two runs need --confirm
    assert "add --confirm" in capsys.readouterr().err
    assert main([*argv, "--confirm", "--save-spec", str(tmp_path / "q.json")]) == 0
    out = capsys.readouterr().out
    assert "== nova-lite-v1 (trial 1) · completed" in out and "== nova-pro-v1" in out
    assert "expected found 100%" in out and ANSWER in out
    assert EvalSpec.model_validate_json((tmp_path / "q.json").read_text()).tasks.custom


def test_estimate_learns_token_history_from_a_local_store(tmp_path: Path):
    service.run_eval(_spec(), store_dir=tmp_path, poll_seconds=0.05)
    est = service.estimate(_spec(), store_dir=tmp_path)
    assert not any("unavailable" in n for n in est.notes), est.notes


def test_missing_aws_credentials_fail_once_before_any_run(tmp_path: Path, monkeypatch):
    import boto3

    class NoCreds:
        def get_credentials(self):
            return None

    monkeypatch.setattr(boto3, "Session", NoCreds)
    spec = query.build_spec("q", [LITE], adapter="bedrock", toolset="fake-none")
    with pytest.raises(ConfigError) as exc:
        service.run_eval(spec, store_dir=tmp_path)
    assert exc.value.kind == "aws_credentials" and "aws login" in str(exc.value)
    assert not list((tmp_path / "runs").glob("*"))  # nothing was started
    service.check_aws_credentials(_spec())  # fake models need no AWS
