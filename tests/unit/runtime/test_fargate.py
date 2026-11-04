from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any

import pytest
from botocore.exceptions import ClientError

import claysandbox.platform.registry_bootstrap  # noqa: F401
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import Executor, RunRequest
from claysandbox.contracts.manifest import ComponentRef
from claysandbox.contracts.registry import resolve
from claysandbox.platform.executors.fargate import FargateExecutor, fargate_environment

PARAMS = {
    "bucket": "sandbox-bucket",
    "cluster": "arn:aws:ecs:us-west-2:1:cluster/clay",
    "task_definition": "arn:aws:ecs:us-west-2:1:task-definition/worker:3",
    "subnets": ["subnet-a", "subnet-b"],
    "security_groups": ["sg-1"],
    "container_name": "worker",
    "max_parallel": 2,
}


class FakeS3:
    def __init__(self) -> None:
        self.objects: dict[str, bytes] = {}

    def put_object(self, Bucket: str, Key: str, Body: bytes, **_: Any) -> None:  # noqa: N803
        self.objects[f"{Bucket}/{Key}"] = Body

    def get_object(self, Bucket: str, Key: str) -> dict[str, Any]:  # noqa: N803
        try:
            return {"Body": io.BytesIO(self.objects[f"{Bucket}/{Key}"])}
        except KeyError:
            raise ClientError(
                {"Error": {"Code": "NoSuchKey", "Message": "x"}}, "GetObject"
            ) from None


class FakeECS:
    def __init__(self) -> None:
        self.run_calls: list[dict[str, Any]] = []
        self.stopped_calls: list[dict[str, Any]] = []
        self.tasks: dict[str, dict[str, Any]] = {}
        self.fail_next: list[dict[str, Any]] | None = None
        self.raise_next: ClientError | None = None
        self.describe_missing: set[str] = set()
        self._n = 0

    def run_task(self, **kwargs: Any) -> dict[str, Any]:
        self.run_calls.append(kwargs)
        if self.raise_next is not None:
            exc, self.raise_next = self.raise_next, None
            raise exc
        if self.fail_next is not None:
            failures, self.fail_next = self.fail_next, None
            return {"tasks": [], "failures": failures}
        self._n += 1
        arn = f"arn:aws:ecs:us-west-2:1:task/clay/t{self._n}"
        self.tasks[arn] = {"taskArn": arn, "lastStatus": "RUNNING"}
        return {"tasks": [{"taskArn": arn}], "failures": []}

    def describe_tasks(self, cluster: str, tasks: list[str]) -> dict[str, Any]:
        found = [self.tasks[t] for t in tasks if t in self.tasks and t not in self.describe_missing]
        failures = [
            {"arn": t, "reason": "MISSING"}
            for t in tasks
            if t not in self.tasks or t in self.describe_missing
        ]
        return {"tasks": found, "failures": failures}

    def stop_task(self, **kwargs: Any) -> None:
        self.stopped_calls.append(kwargs)

    def stop(self, arn: str, **extra: Any) -> None:
        self.tasks[arn] = {"taskArn": arn, "lastStatus": "STOPPED", **extra}


def request(n: int, eval_id: str = "e1") -> RunRequest:
    return RunRequest(
        run_id=f"run{n}",
        eval_id=eval_id,
        config_name="base",
        template="T1",
        task_instance_id=f"T1@a{n}",
        model=ComponentRef(kind="model", name="bedrock", params={"model_id": "m"}),
        harness=ComponentRef(kind="harness", name="strands"),
        toolset=ComponentRef(kind="toolset", name="T1"),
    )


@pytest.fixture
def parts() -> tuple[FargateExecutor, FakeECS, FakeS3]:
    ecs, s3 = FakeECS(), FakeS3()
    return FargateExecutor(PARAMS, ecs_client=ecs, s3_client=s3), ecs, s3


def test_it_is_a_registered_executor() -> None:
    assert resolve("executor", "fargate") is FargateExecutor
    executor = FargateExecutor(PARAMS, ecs_client=FakeECS(), s3_client=FakeS3())
    assert isinstance(executor, Executor) and executor.name == "fargate"


def test_submit_writes_requests_to_s3_without_starting_tasks(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, s3 = parts
    executor.submit([request(1), request(2)])
    assert sorted(s3.objects) == [
        "sandbox-bucket/requests/run1.json",
        "sandbox-bucket/requests/run2.json",
    ]
    assert (
        RunRequest.model_validate_json(s3.objects["sandbox-bucket/requests/run1.json"]).run_id
        == "run1"
    )
    assert ecs.run_calls == []


def test_poll_starts_tasks_with_the_worker_command_and_network_settings(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, _ = parts
    executor.submit([request(1)])
    (status,) = executor.poll()
    assert (status.run_id, status.state) == ("run1", "running")
    assert status.environment["executor"] == "fargate"  # FR-15.7
    assert status.environment["task_arn"].endswith("/t1")
    call = ecs.run_calls[0]
    assert call["launchType"] == "FARGATE" and call["count"] == 1
    assert (
        call["cluster"] == PARAMS["cluster"] and call["taskDefinition"] == PARAMS["task_definition"]
    )
    assert call["networkConfiguration"]["awsvpcConfiguration"] == {
        "subnets": ["subnet-a", "subnet-b"],
        "securityGroups": ["sg-1"],
        "assignPublicIp": "ENABLED",
    }
    (override,) = call["overrides"]["containerOverrides"]
    assert override == {
        "name": "worker",
        "command": ["worker", "--request", "s3://sandbox-bucket/requests/run1.json"],
    }
    assert len(call["startedBy"]) <= 36


def test_at_most_max_parallel_tasks_run_and_the_queue_drains_as_they_finish(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, s3 = parts
    executor.submit([request(i) for i in range(1, 5)])
    started = executor.poll()
    assert [s.run_id for s in started] == ["run1", "run2"]  # max_parallel = 2
    assert executor.poll() == []  # nothing changed, nothing new to launch

    arns = list(ecs.tasks)
    s3.objects["sandbox-bucket/runs/run1/status.json"] = json.dumps({"state": "completed"}).encode()
    ecs.stop(arns[0])
    statuses = executor.poll()
    by_run = {s.run_id: s.state for s in statuses}
    assert by_run == {"run1": "completed", "run3": "running"}  # a slot freed, run3 started
    assert len(ecs.run_calls) == 3


def test_terminal_state_comes_from_status_json(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, s3 = parts
    executor.submit([request(1), request(2), request(3)])
    executor.poll()
    a1, a2 = list(ecs.tasks)
    s3.objects["sandbox-bucket/runs/run1/status.json"] = json.dumps(
        {"state": "budget_stopped", "message": "max_usd"}
    ).encode()
    s3.objects["sandbox-bucket/runs/run2/status.json"] = json.dumps(
        {"state": "agent_failed"}
    ).encode()
    ecs.stop(a1)
    ecs.stop(a2)
    statuses = executor.poll()
    done = {s.run_id: s for s in statuses if s.state != "running"}
    assert done["run1"].state == "budget_stopped" and done["run1"].message == "max_usd"
    assert done["run2"].state == "agent_failed"
    assert done["run1"].environment["task_arn"] == a1
    assert [s.run_id for s in statuses if s.state == "running"] == ["run3"]  # freed slot reused
    assert executor.poll() == []  # each terminal state is reported only once


def test_a_stopped_task_with_no_terminal_status_is_an_executor_failure(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, s3 = parts
    executor.submit([request(1), request(2)])
    executor.poll()
    a1, a2 = list(ecs.tasks)
    ecs.stop(
        a1,
        stoppedReason="Essential container exited",
        containers=[{"exitCode": 137}, {"exitCode": 0}],
    )
    s3.objects["sandbox-bucket/runs/run2/status.json"] = json.dumps({"state": "running"}).encode()
    ecs.stop(a2)  # status.json says "running": the worker died mid-run
    statuses = {s.run_id: s for s in executor.poll()}
    for run_id in ("run1", "run2"):
        status = statuses[run_id]
        assert (status.state, status.error_kind) == ("infra_retry", "executor_failure")
    assert "Essential container exited" in (statuses["run1"].message or "")
    assert "exit 137" in (statuses["run1"].message or "")


def test_a_task_ecs_no_longer_knows_is_an_executor_failure_unless_it_finished(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, s3 = parts
    executor.submit([request(1), request(2)])
    executor.poll()
    a1, a2 = list(ecs.tasks)
    ecs.describe_missing = {a1, a2}
    s3.objects["sandbox-bucket/runs/run2/status.json"] = json.dumps({"state": "completed"}).encode()
    statuses = {s.run_id: s for s in executor.poll()}
    assert statuses["run1"].error_kind == "executor_failure"
    assert statuses["run2"].state == "completed"


def test_run_task_failures_are_reported_and_do_not_block_the_queue(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, _ = parts
    ecs.fail_next = [{"arn": "x", "reason": "RESOURCE:FARGATE"}]
    executor.submit([request(1), request(2)])
    statuses = {s.run_id: s for s in executor.poll()}
    assert statuses["run1"].state == "infra_retry" and "RESOURCE:FARGATE" in (
        statuses["run1"].message or ""
    )
    assert statuses["run2"].state == "running"


def test_throttling_is_an_executor_failure_but_permission_problems_are_config_errors(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, _ = parts
    ecs.raise_next = ClientError(
        {"Error": {"Code": "ThrottlingException", "Message": "slow"}}, "RunTask"
    )
    executor.submit([request(1)])
    (status,) = executor.poll()
    assert status.error_kind == "executor_failure"

    ecs.raise_next = ClientError(
        {"Error": {"Code": "AccessDeniedException", "Message": "no"}}, "RunTask"
    )
    executor.submit([request(2)])
    with pytest.raises(ConfigError):
        executor.poll()


def test_cancel_drops_queued_runs_of_that_eval_and_stops_its_tasks(
    parts: tuple[FargateExecutor, FakeECS, FakeS3],
) -> None:
    executor, ecs, _ = parts
    executor.submit([request(1), request(2), request(3, eval_id="e2"), request(4, eval_id="e2")])
    executor.poll()  # run1, run2 running (both e1); run3, run4 queued
    executor.cancel("e2")
    assert ecs.stopped_calls == []
    executor.cancel("e1")
    assert len(ecs.stopped_calls) == 2 and "cancelled" in ecs.stopped_calls[0]["reason"]
    assert [s for s in executor.poll() if s.state == "running"] == []  # e2 runs never start


def test_infrastructure_comes_from_outputs_json(tmp_path: Path) -> None:
    outputs = tmp_path / "outputs.json"
    outputs.write_text(
        json.dumps(
            {
                "BucketName": "b",
                "ClusterArn": "arn:cluster",
                "TaskDefinitionArn": "arn:td",
                "SubnetIds": "subnet-1,subnet-2",
                "SecurityGroupId": "sg-9",
                "ContainerName": "main",
            }
        )
    )
    executor = FargateExecutor(
        {"outputs_path": str(outputs)}, ecs_client=FakeECS(), s3_client=FakeS3()
    )
    assert (executor.bucket, executor.cluster, executor.task_definition) == (
        "b",
        "arn:cluster",
        "arn:td",
    )
    assert executor.subnets == ["subnet-1", "subnet-2"]
    assert executor.security_groups == ["sg-9"] and executor.container_name == "main"


def test_missing_or_incomplete_infrastructure_is_a_clear_config_error(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="write_outputs"):
        FargateExecutor({"outputs_path": str(tmp_path / "nope.json")}, FakeECS(), FakeS3())
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    with pytest.raises(ConfigError, match="not valid JSON"):
        FargateExecutor({"outputs_path": str(bad)}, FakeECS(), FakeS3())
    partial = tmp_path / "partial.json"
    partial.write_text(json.dumps({"BucketName": "b"}))
    with pytest.raises(ConfigError, match="missing"):
        FargateExecutor({"outputs_path": str(partial)}, FakeECS(), FakeS3())


def test_fargate_environment_reads_ecs_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ECS_CONTAINER_METADATA_URI_V4", raising=False)
    assert fargate_environment() == {"executor": "fargate"}

    class Response(io.BytesIO):
        def __enter__(self) -> Response:
            return self

        def __exit__(self, *_: object) -> None:
            return None

    seen: list[str] = []

    def fake_urlopen(url: str, timeout: float) -> Response:
        seen.append(url)
        return Response(json.dumps({"TaskARN": "arn:task/1", "Cluster": "clay"}).encode())

    monkeypatch.setenv("ECS_CONTAINER_METADATA_URI_V4", "http://169.254.170.2/v4/abc")
    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    env = fargate_environment()
    assert seen == ["http://169.254.170.2/v4/abc/task"]
    assert env["task_arn"] == "arn:task/1" and env["executor"] == "fargate"

    def broken(url: str, timeout: float) -> Response:
        raise OSError("no route")

    monkeypatch.setattr("urllib.request.urlopen", broken)
    assert fargate_environment() == {"executor": "fargate"}
