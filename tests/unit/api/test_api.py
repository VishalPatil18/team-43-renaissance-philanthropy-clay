"""Read-only API over a demo store (UI prototype)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

fastapi = pytest.importorskip("fastapi")  # the api dependency group is optional
from fastapi.testclient import TestClient  # noqa: E402

from claysandbox.api.app import create_app  # noqa: E402

_ROOT = Path(__file__).resolve().parents[3]
_spec = importlib.util.spec_from_file_location(
    "make_demo_store", _ROOT / "scripts" / "make_demo_store.py"
)
assert _spec and _spec.loader
demo = importlib.util.module_from_spec(_spec)
sys.modules["make_demo_store"] = demo
_spec.loader.exec_module(demo)

LOCAL = "http://127.0.0.1"


@pytest.fixture(scope="module")
def store_root(tmp_path_factory: pytest.TempPathFactory) -> Path:
    out = tmp_path_factory.mktemp("demo") / "store"
    demo.build(out)
    return out


@pytest.fixture(scope="module")
def client(store_root: Path) -> TestClient:
    return TestClient(create_app(store_root), base_url=LOCAL)


def _snapshot(root: Path) -> dict[str, tuple[int, int]]:
    return {
        str(p.relative_to(root)): (p.stat().st_mtime_ns, p.stat().st_size) for p in root.rglob("*")
    }


# ---------------------------------------------------------------- demo store
def test_demo_store_has_scored_terminal_runs(store_root: Path) -> None:
    from claysandbox.store.local import LocalRunStore

    store = LocalRunStore(store_root / "runs", store_root / "evals")
    runs = store.list_runs()
    assert {"fixture-good_t1", "fixture-errors_t1", "fixture-loop_t1"} == set(runs)
    for run_id in runs:
        assert store.read_status(run_id).state in {"completed", "budget_stopped", "agent_failed"}
        kinds = {a["kind"] for a in store.list_assessments(run_id)}
        assert {"workflow", "output"} <= kinds, run_id
    assert set(store.list_eval_runs(demo.EVAL_ID)) == set(runs)


def test_demo_store_refuses_existing_folder(store_root: Path) -> None:
    with pytest.raises(FileExistsError):
        demo.build(store_root)


# ---------------------------------------------------------------- runs
def test_runs_lists_every_run_with_totals_and_scores(client: TestClient) -> None:
    r = client.get("/api/runs")
    assert r.status_code == 200
    rows = {row["run_id"]: row for row in r.json()}
    good = rows["fixture-good_t1"]
    assert good["state"] == "completed"
    assert good["totals"]["steps"] == 3
    assert 0 <= good["scores"]["workflow"] <= 1
    assert "output" in good["scores"]


def test_runs_filter_by_state(client: TestClient) -> None:
    rows = client.get("/api/runs", params={"state": "budget_stopped"}).json()
    assert rows and all(row["state"] == "budget_stopped" for row in rows)


@pytest.mark.parametrize(
    "params", [{"state": "exploded"}, {"limit": 0}, {"limit": 10_000}, {"offset": -1}]
)
def test_runs_rejects_bad_filters(client: TestClient, params: dict) -> None:
    assert client.get("/api/runs", params=params).status_code == 422


def test_run_detail(client: TestClient) -> None:
    body = client.get("/api/runs/fixture-good_t1").json()
    assert body["manifest"]["run_id"] == "fixture-good_t1"
    assert body["status"]["state"] == "completed"


def test_run_trace_and_assessments(client: TestClient) -> None:
    trace = client.get("/api/runs/fixture-good_t1/trace").json()
    assert trace["events"][0]["type"] == "run_start"
    assert trace["events"][-1]["type"] == "run_end"
    kinds = {a["kind"] for a in client.get("/api/runs/fixture-good_t1/assessments").json()}
    assert {"workflow", "output"} <= kinds


def test_run_reference_has_aoi(client: TestClient) -> None:
    body = client.get("/api/runs/fixture-good_t1/reference").json()
    assert body["reference"]["instance_id"] == "T1@us-ca-kern"
    assert len(body["reference"]["aoi"]["bbox"]) == 4
    assert body["exact"] is True
    assert body["reference"]["version"] == "T1.v1+sha256:fixture00001"


@pytest.mark.parametrize("path", ["", "/trace", "/assessments", "/reference"])
def test_unknown_run_is_404(client: TestClient, path: str) -> None:
    assert client.get(f"/api/runs/no-such-run{path}").status_code == 404


@pytest.mark.parametrize("run_id", ["..", ".hidden", "a..b", "%2e%2e", "a%2Fb", "a%5Cb"])
def test_unsafe_run_ids_are_rejected(client: TestClient, run_id: str) -> None:
    assert client.get(f"/api/runs/{run_id}").status_code in (404, 422)


# ---------------------------------------------------------------- evals, registry, tasks
def test_evals(client: TestClient) -> None:
    ids = [e["eval_id"] for e in client.get("/api/evals").json()]
    assert demo.EVAL_ID in ids
    body = client.get(f"/api/evals/{demo.EVAL_ID}").json()
    assert len(body["runs"]) >= 3
    assert {a["kind"] for a in body["assessments"]} >= {"workflow", "output"}
    assert body["report"]["eval_id"] == demo.EVAL_ID
    assert client.get("/api/evals/nope").status_code == 404
    assert client.get("/api/evals/..").status_code in (404, 422)


def test_components_and_tasks(client: TestClient) -> None:
    kinds = {c["kind"] for c in client.get("/api/components").json()}
    assert {"evaluator", "store"} <= kinds
    tasks = client.get("/api/tasks").json()
    assert any(t["id"] == "T1@us-ca-kern" for t in tasks)


# ---------------------------------------------------------------- safety
def test_foreign_host_and_origin_are_refused(store_root: Path) -> None:
    evil = TestClient(create_app(store_root), base_url="http://evil.example")
    assert evil.get("/api/runs").status_code == 403
    c = TestClient(create_app(store_root), base_url=LOCAL)
    assert c.get("/api/runs", headers={"Origin": "http://evil.example"}).status_code == 403
    assert c.get("/api/runs", headers={"Origin": "http://localhost:5173"}).status_code == 200


@pytest.mark.parametrize(
    "host",
    [
        "[",
        "localhost/path",
        "user@localhost",
        "localhost:bad",
        "localhost:99999",
        "localhost?foreign",
        "localhost#foreign",
        "localhost:",
        "localhost:0",
        "localhost:" + "1" * 5000,
    ],
)
def test_malformed_hosts_are_forbidden(client: TestClient, host: str) -> None:
    assert client.get("/api/runs", headers={"Host": host}).status_code == 403


@pytest.mark.parametrize(
    "origin",
    [
        "http://[",
        "null",
        "localhost",
        "http://user@localhost",
        "http://localhost/path",
        "http://localhost:bad",
        "http://localhost:99999",
        "file://localhost",
        "http://localhost?foreign",
        "http://localhost#foreign",
    ],
)
def test_malformed_origins_are_forbidden(client: TestClient, origin: str) -> None:
    assert client.get("/api/runs", headers={"Origin": origin}).status_code == 403


def test_duplicate_host_and_origin_headers_are_forbidden(client: TestClient) -> None:
    for name in ("Host", "Origin"):
        headers = [
            (name, "http://localhost" if name == "Origin" else "localhost"),
            (name, "http://evil.example" if name == "Origin" else "evil.example"),
        ]
        assert client.get("/api/runs", headers=headers).status_code == 403


@pytest.mark.parametrize("authority", ["localhost", "127.0.0.1:8765", "[::1]:8765"])
def test_loopback_authorities_are_allowed(client: TestClient, authority: str) -> None:
    assert (
        client.get(
            "/api/runs", headers={"Host": authority, "Origin": f"http://{authority}"}
        ).status_code
        == 200
    )


@pytest.mark.parametrize("directory", ["runs", "evals"])
def test_store_symlinks_cannot_escape_root(tmp_path: Path, directory: str) -> None:
    root = tmp_path / "store"
    (root / "runs").mkdir(parents=True)
    (root / "evals").mkdir()
    outside = tmp_path / "private"
    outside.mkdir()
    (outside / "manifest.json").write_text('{"run_id":"secret"}')
    (outside / "spec.yaml").write_text("secret: private")
    c = TestClient(create_app(root), base_url=LOCAL)
    (root / directory / "secret").symlink_to(outside, target_is_directory=True)
    assert c.get(f"/api/{directory}/secret").status_code in (403, 404)
    assert c.get(f"/api/{directory}").status_code in (403, 404)


def test_runs_without_evals_remain_read_only(tmp_path: Path) -> None:
    (tmp_path / "runs").mkdir()
    before = _snapshot(tmp_path)
    c = TestClient(create_app(tmp_path), base_url=LOCAL)
    assert c.get("/api/runs").json() == []
    assert c.get("/api/evals").json() == []
    assert _snapshot(tmp_path) == before


def test_writes_are_not_routed(client: TestClient) -> None:
    assert client.post("/api/runs").status_code == 405
    assert client.delete("/api/runs/fixture-good_t1").status_code == 405


def test_no_route_mutates_the_store(store_root: Path, client: TestClient) -> None:
    before = _snapshot(store_root)
    for path in [
        "/api/runs",
        "/api/runs/fixture-good_t1",
        "/api/runs/fixture-good_t1/trace",
        "/api/runs/fixture-good_t1/assessments",
        "/api/runs/fixture-good_t1/reference",
        "/api/evals",
        f"/api/evals/{demo.EVAL_ID}",
        "/",
    ]:
        client.get(path)
    assert _snapshot(store_root) == before


def test_missing_store_is_an_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        create_app(tmp_path / "absent")
    assert not (tmp_path / "absent").exists()


def test_spa_fallback_never_leaves_dist(tmp_path: Path, store_root: Path) -> None:
    dist = tmp_path / "dist"
    dist.mkdir()
    (dist / "index.html").write_text("<p>ui</p>")
    (tmp_path / "secret.txt").write_text("nope")
    c = TestClient(create_app(store_root, ui_dist=dist), base_url=LOCAL)
    assert c.get("/runs/fixture-good_t1").text == "<p>ui</p>"
    assert "nope" not in c.get("/..%2Fsecret.txt").text


def test_committed_openapi_is_current() -> None:
    spec = importlib.util.spec_from_file_location(
        "export_openapi", _ROOT / "scripts" / "export_openapi.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod.OUT.read_text() == mod.render(), "run scripts/export_openapi.py"
