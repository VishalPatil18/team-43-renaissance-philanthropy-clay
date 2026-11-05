import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml

from claysandbox.cli import main
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.runtime import CostEstimate
from claysandbox.contracts.spec import EvalSpec


@pytest.mark.parametrize("name", ["r0", "demo-compare"])
def test_specs(name):
    spec = EvalSpec.model_validate(yaml.safe_load(Path(f"specs/{name}.yaml").read_text()))
    assert spec.summary.name == "deterministic"


def test_help(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--help"])
    assert exc.value.code == 0
    output = capsys.readouterr().out
    for command in (
        "run",
        "eval",
        "estimate",
        "status",
        "worker",
        "serve",
        "validate-evaluator",
        "registry",
        "tasks",
    ):
        assert command in output


@pytest.mark.parametrize(
    "command, expected",
    [
        ("registry", "workflow"),
        ("tasks", "T1@us-ca-kern"),
        ("validate-evaluator", "Detection rate"),
    ],
)
def test_real_commands(command, expected, capsys):
    assert main([command]) == 0
    assert expected in capsys.readouterr().out


@pytest.fixture
def service(monkeypatch):
    fake = SimpleNamespace(
        count=1,
        state="completed",
        called=False,
        load_spec=lambda path: object(),
        validate_spec=lambda spec: ["fixture warning"],
        estimate=lambda spec, **kw: CostEstimate(
            per_config={"base": 0.1}, total_usd=0.1, notes=["fixture estimate"]
        ),
        eval_status=lambda *a, **kw: {"runs": [{"run_id": "r1", "state": "completed"}]},
    )
    fake.plan = lambda spec, eval_id: [object()] * fake.count
    fake.run_worker_request = lambda *a, **kw: SimpleNamespace(run_id="r1", state=fake.state)

    def run_eval(spec, **kwargs):
        fake.called = True
        fake.confirm = kwargs["confirm"]
        kwargs["on_status"]("r1", fake.state)
        return SimpleNamespace(
            eval_id="e1",
            run_ids=["r1"],
            states={"r1": fake.state},
            report_path=Path("evals/e1/report.md"),
        )

    fake.run_eval = run_eval
    monkeypatch.setitem(sys.modules, "claysandbox.platform.service", fake)
    return fake


@pytest.mark.parametrize("command", ["run", "eval"])
def test_run(command, service, capsys):
    assert main([command, "fake.yaml", "--store", "/tmp/example"]) == 0
    assert service.confirm
    output = capsys.readouterr()
    assert "r1\tcompleted" in output.out
    assert "Eval: e1" in output.out
    assert "evals/e1/report.md" in output.out
    assert "serve --store /tmp/example" in output.out
    assert "fixture warning" in output.err


def test_multi_confirmation(service, capsys):
    service.count = 2
    assert main(["eval", "fake.yaml"]) == 2
    output = capsys.readouterr()
    assert "Total: $0.1000" in output.out
    assert "--confirm" in output.err
    assert not service.called
    assert main(["eval", "fake.yaml", "--confirm"]) == 0
    assert service.confirm


@pytest.mark.parametrize(
    "state, code",
    [("infra_excluded", 1), ("running", 1), ("budget_stopped", 0), ("agent_failed", 0)],
)
def test_run_states(service, state, code):
    service.state = state
    assert main(["run", "fake.yaml", "--yes"]) == code


def test_estimate_status_worker(service, capsys):
    assert main(["estimate", "fake.yaml"]) == 0
    assert "base: $0.1000" in capsys.readouterr().out
    assert main(["status", "e1"]) == 0
    assert "completed: 1" in capsys.readouterr().out
    service.state = "infra_excluded"
    assert main(["worker", "--request", "s3://bucket/request.json"]) == 0
    assert "infra_excluded" in capsys.readouterr().out
    service.state = "running"
    assert main(["worker", "--request", "local.json"]) == 1


def test_config_error(service, capsys):
    def fail(path):
        raise ConfigError("bad spec")

    service.load_spec = fail
    assert main(["run", "bad.yaml"]) == 2
    assert "error: bad spec" in capsys.readouterr().err


def test_serve(monkeypatch):
    from claysandbox.api import __main__ as api

    calls = []
    monkeypatch.setattr(api, "main", calls.append)
    assert main(["serve", "--store", "/tmp/store", "--port", "9000"]) == 0
    assert calls == [["--store", "/tmp/store", "--port", "9000"]]
