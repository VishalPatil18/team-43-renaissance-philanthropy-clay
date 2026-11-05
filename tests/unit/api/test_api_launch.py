"""Browser launch API against the real pipeline with fake model and tools."""

from __future__ import annotations

import json
import threading
import time
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from claysandbox.api.app import create_app
from claysandbox.platform import service
from tests.unit.platform.test_pipeline import _spec


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    (tmp_path / "runs").mkdir()
    return TestClient(create_app(tmp_path), base_url="http://127.0.0.1")


def body() -> dict:
    return {"spec": _spec().model_dump(mode="json")}


def test_estimate_and_schema(client: TestClient) -> None:
    response = client.post("/api/estimate", json=body())
    assert response.status_code == 200
    assert response.json()["runs"] == 4
    assert response.json()["total_usd"] >= 0
    assert set(response.json()) == {
        "runs",
        "total_usd",
        "per_config",
        "exceeds_eval_cap",
        "eval_cap_usd",
        "notes",
        "warnings",
    }
    assert "properties" in client.get("/api/schema/eval-spec").json()


@pytest.mark.parametrize("confirm", [None, False, 1, "true"])
def test_confirmation_required(client: TestClient, confirm: object) -> None:
    response = client.post("/api/evals", json={**body(), "confirm": confirm})
    assert response.status_code == 400
    assert response.json()["kind"] == "needs_confirm"


def test_launch_status_and_events(client: TestClient, tmp_path: Path) -> None:
    response = client.post("/api/evals", json={**body(), "confirm": True})
    assert response.status_code == 202, response.text
    launched = response.json()
    assert launched["runs"] == 4
    with client.stream("GET", launched["events_url"]) as stream:
        assert stream.headers["content-type"].startswith("text/event-stream")
        assert stream.headers["cache-control"] == "no-cache"
        lines = list(stream.iter_lines())
    assert lines[0] == "event: status"
    assert lines[-3] == "event: done"
    assert json.loads(lines[-2].removeprefix("data: "))["done"]
    assert not json.loads(lines[1].removeprefix("data: "))["done"]
    deadline = time.monotonic() + 30
    while True:
        response = client.get(launched["status_url"])
        assert response.status_code == 200
        status = response.json()
        if status["done"]:
            break
        assert time.monotonic() < deadline, status
        time.sleep(0.1)
    assert status["counts"] == {"completed": 4}
    assert status["error"] is None
    assert status["report"] is True
    assert len(list((tmp_path / "runs").iterdir())) == 4


@pytest.mark.parametrize("route", ["/api/estimate", "/api/evals"])
def test_request_guards(client: TestClient, route: str) -> None:
    assert (
        client.post(route, content="{}", headers={"Content-Type": "text/plain"}).status_code == 415
    )
    assert (
        client.post(route, json=body(), headers={"Origin": "http://evil.example"}).status_code
        == 403
    )
    assert (
        client.post(route, json=body(), headers={"Sec-Fetch-Site": "cross-site"}).status_code == 403
    )
    assert client.post(route, json={"spec": {}, "confirm": True}).status_code == 422
    invalid = body()
    invalid["spec"]["baseline"]["model"]["name"] = "no-such-model"
    response = client.post(route, json={**invalid, "confirm": True})
    assert response.status_code == 400
    assert response.json()["kind"] == "unknown_component"


@pytest.mark.parametrize("suffix", ["status", "events"])
def test_unknown_eval(client: TestClient, suffix: str) -> None:
    assert client.get(f"/api/evals/missing/{suffix}").status_code == 404


def test_cap_refused(client: TestClient) -> None:
    payload = body()
    payload["spec"]["budget"]["eval"] = {"max_usd": 0.00000001}
    response = client.post("/api/evals", json={**payload, "confirm": True})
    assert response.status_code == 400
    assert response.json()["kind"] == "exceeds_eval_cap"


def test_launch_failure(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args, **kwargs):
        raise RuntimeError("executor failed")

    monkeypatch.setattr(service, "run_eval", fail)
    response = client.post("/api/evals", json={**body(), "confirm": True})
    assert response.status_code == 400
    assert response.json()["detail"] == "executor failed"


def test_busy(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    release = threading.Event()

    def wait(*args, **kwargs):
        release.wait(20)

    monkeypatch.setattr(service, "run_eval", wait)
    try:
        for _ in range(2):
            assert client.post("/api/evals", json={**body(), "confirm": True}).status_code == 202
        response = client.post("/api/evals", json={**body(), "confirm": True})
        assert response.status_code == 409
        assert response.json()["kind"] == "busy"
    finally:
        release.set()
        for entry in client.app.state.launches.values():
            entry["thread"].join(5)
