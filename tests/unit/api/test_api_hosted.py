"""Hosted (AWS) mode: shared login, same-origin POSTs, health check, Fargate-only launches."""

from __future__ import annotations

import base64
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claysandbox.api import __main__ as entry
from claysandbox.api.app import Hosted, create_app
from claysandbox.platform import service
from tests.unit.platform.test_pipeline import _spec

PASSWORD = "correct-horse-battery"
BASE = "https://d123.cloudfront.net"
FARGATE = {"bucket": "b", "cluster": "c", "task_definition": "t", "subnets": ["s1"]}


def login(app, user: str = "clay", password: str = PASSWORD) -> TestClient:
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    return TestClient(app, base_url=BASE, headers={"Authorization": f"Basic {token}"})


@pytest.fixture
def app(tmp_path: Path):
    (tmp_path / "runs").mkdir()
    return create_app(tmp_path, hosted=Hosted(PASSWORD, executor_params=FARGATE))


def test_every_route_but_healthz_needs_the_login(app) -> None:
    anonymous = TestClient(app, base_url=BASE)
    assert anonymous.get("/healthz").json() == {"ok": True}
    for path in ("/api/runs", "/", "/new-run"):
        response = anonymous.get(path)
        assert response.status_code == 401 and "Basic" in response.headers["www-authenticate"]
    wrong = login(app, password="nope-nope-nope")
    assert wrong.get("/api/runs").status_code == 401
    right = login(app)
    assert right.get("/api/runs").status_code == 200  # any Host: no loopback rule here


def test_posts_must_come_from_this_site(app) -> None:
    client = login(app)
    body = {"spec": _spec().model_dump(mode="json")}
    assert client.post("/api/estimate", json=body).status_code == 403  # no Origin
    evil = client.post("/api/estimate", json=body, headers={"Origin": "https://evil.example"})
    assert evil.status_code == 403
    ok = client.post("/api/estimate", json=body, headers={"Origin": BASE})
    assert ok.status_code == 200, ok.text


def test_launches_are_forced_onto_fargate(app, tmp_path: Path, monkeypatch) -> None:
    seen = {}

    def fake_run_eval(spec, *, store_dir, confirm, eval_id):
        seen["spec"] = spec
        (Path(store_dir) / "evals" / eval_id).mkdir(parents=True)
        (Path(store_dir) / "evals" / eval_id / "plan.json").write_text(json.dumps({"runs": []}))

    monkeypatch.setattr(service, "run_eval", fake_run_eval)
    monkeypatch.setattr(service, "check_aws_credentials", lambda spec: None)
    client = login(app)
    body = {"spec": _spec().model_dump(mode="json"), "confirm": True}
    response = client.post("/api/evals", json=body, headers={"Origin": BASE})
    assert response.status_code == 202, response.text
    executor = seen["spec"].executor
    assert executor.name == "fargate"
    assert executor.params == {**FARGATE, "max_parallel": 2}


def test_short_passwords_are_refused() -> None:
    with pytest.raises(ValueError):
        Hosted("short")


def test_fargate_params_come_from_the_environment(monkeypatch) -> None:
    for name, value in {
        "CLAYSANDBOX_BUCKET": "b",
        "CLAYSANDBOX_CLUSTER": "c",
        "CLAYSANDBOX_TASK_DEFINITION": "t",
        "CLAYSANDBOX_SUBNETS": "s1,s2",
        "CLAYSANDBOX_SECURITY_GROUPS": "g1",
        "AWS_REGION": "us-west-2",
    }.items():
        monkeypatch.setenv(name, value)
    params = entry.fargate_params()
    assert params["subnets"] == ["s1", "s2"] and params["security_groups"] == ["g1"]
    monkeypatch.delenv("CLAYSANDBOX_CLUSTER")
    with pytest.raises(SystemExit):
        entry.fargate_params()
