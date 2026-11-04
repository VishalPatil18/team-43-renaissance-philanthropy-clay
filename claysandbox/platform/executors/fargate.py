"""Fargate executor (FR-15.2, FR-15.4, FR-15.7, UC-11, architecture §8.6).

Flow for each ``RunRequest``:

1. Write the request to ``s3://<bucket>/requests/<run_id>.json``.
2. Start one Fargate task whose command is
   ``clay-sandbox worker --request s3://<bucket>/requests/<run_id>.json``.
   The worker reads the request, runs exactly as it does locally, and writes the run folder
   (including ``status.json``) to ``s3://<bucket>/runs/<run_id>/``.
3. ``poll`` watches the tasks. When a task stops it reads ``runs/<run_id>/status.json``:

   * a terminal ``state`` is reported as is;
   * no terminal status means the worker died, which is reported as
     ``RunStatus(state="infra_retry", error_kind="executor_failure")``. The service decides
     whether to start another attempt (infra retries, DD-012) or mark the run excluded.

At most ``max_parallel`` tasks run at once; the rest wait in a queue that ``poll`` drains.
Terminal statuses are reported once. ``cancel`` drops queued runs of an eval and stops its tasks.

Cluster, task definition, subnets and the bucket come from ``infra/outputs.json`` (written by
``infra/write_outputs.py`` after ``cdk deploy``) or from explicit parameters.
"""

from __future__ import annotations

import json
import logging
import os
import urllib.request
from collections import deque
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

import boto3
from botocore.exceptions import ClientError
from pydantic import BaseModel, Field

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import TERMINAL_STATES, RunRequest, RunStatus
from claysandbox.contracts.registry import register

log = logging.getLogger(__name__)

DEFAULT_OUTPUTS_PATH = Path(__file__).resolve().parents[3] / "infra" / "outputs.json"
_DESCRIBE_BATCH = 100
_CONFIG_CODES = {"AccessDeniedException", "ClusterNotFoundException", "InvalidParameterException"}


@dataclass
class _Tracked:
    request: RunRequest
    task_arn: str | None = None
    reported_running: bool = False
    done: bool = False
    environment: dict[str, Any] = field(default_factory=dict)


@register("executor", "fargate")
class FargateExecutor:
    name = "fargate"

    class Params(BaseModel):
        max_parallel: int = Field(default=4, gt=0)
        region: str = "us-west-2"
        outputs_path: str | None = None
        container_name: str | None = None
        bucket: str | None = None
        cluster: str | None = None
        task_definition: str | None = None
        subnets: list[str] | None = None
        security_groups: list[str] | None = None
        assign_public_ip: Literal["ENABLED", "DISABLED"] = "ENABLED"

    def __init__(
        self,
        params: dict[str, Any] | None = None,
        ecs_client: Any | None = None,
        s3_client: Any | None = None,
    ) -> None:
        self.params = self.Params(**(params or {}))
        self._resolve_infrastructure()
        self._ecs: Any = ecs_client or boto3.client("ecs", region_name=self.params.region)
        self._s3: Any = s3_client or boto3.client("s3", region_name=self.params.region)
        self._queue: deque[_Tracked] = deque()
        self._running: dict[str, _Tracked] = {}  # task ARN -> tracked run

    # -- configuration --------------------------------------------------------------------

    def _resolve_infrastructure(self) -> None:
        p = self.params
        outputs: dict[str, Any] = {}
        path = Path(p.outputs_path) if p.outputs_path else DEFAULT_OUTPUTS_PATH
        needs_file = not (p.bucket and p.cluster and p.task_definition and p.subnets)
        if needs_file:
            try:
                outputs = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                raise ConfigError(
                    f"Fargate infrastructure is not configured: {path} not found. "
                    "Deploy the CDK stack and run infra/write_outputs.py, or pass "
                    "bucket, cluster, task_definition and subnets in the executor params.",
                    kind="fargate_config",
                ) from None
            except ValueError as exc:
                raise ConfigError(
                    f"{path} is not valid JSON: {exc}", kind="fargate_config"
                ) from exc

        def pick(explicit: Any, key: str) -> Any:
            return explicit if explicit else outputs.get(key)

        self.bucket: str = pick(p.bucket, "BucketName")
        self.cluster: str = pick(p.cluster, "ClusterArn")
        self.task_definition: str = pick(p.task_definition, "TaskDefinitionArn")
        subnets = pick(p.subnets, "SubnetIds")
        self.subnets: list[str] = subnets.split(",") if isinstance(subnets, str) else subnets
        groups = pick(p.security_groups, "SecurityGroupId")
        self.security_groups: list[str] = (
            [groups] if isinstance(groups, str) else list(groups or [])
        )
        self.container_name: str = p.container_name or outputs.get("ContainerName") or "worker"
        missing = [
            n
            for n, v in {
                "bucket": self.bucket,
                "cluster": self.cluster,
                "task_definition": self.task_definition,
                "subnets": self.subnets,
            }.items()
            if not v
        ]
        if missing:
            raise ConfigError(f"Fargate infrastructure is missing {missing}", kind="fargate_config")

    # -- Executor -------------------------------------------------------------------------

    def submit(self, requests: Iterable[RunRequest]) -> None:
        for request in requests:
            self._s3.put_object(
                Bucket=self.bucket,
                Key=self._request_key(request.run_id),
                Body=request.model_dump_json().encode("utf-8"),
                ContentType="application/json",
            )
            self._queue.append(_Tracked(request))

    def poll(self) -> list[RunStatus]:
        statuses = self._refresh_running()
        statuses.extend(self._launch_queued())
        return statuses

    def cancel(self, eval_id: str) -> None:
        self._queue = deque(t for t in self._queue if t.request.eval_id != eval_id)
        for arn, tracked in list(self._running.items()):
            if tracked.request.eval_id == eval_id:
                try:
                    self._ecs.stop_task(
                        cluster=self.cluster, task=arn, reason=f"eval {eval_id} cancelled"
                    )
                except ClientError as exc:
                    log.warning("stop_task failed for %s: %s", arn, exc)

    # -- internals ------------------------------------------------------------------------

    def _request_key(self, run_id: str) -> str:
        return f"requests/{run_id}.json"

    def _request_uri(self, run_id: str) -> str:
        return f"s3://{self.bucket}/{self._request_key(run_id)}"

    def _launch_queued(self) -> list[RunStatus]:
        statuses: list[RunStatus] = []
        while self._queue and len(self._running) < self.params.max_parallel:
            tracked = self._queue.popleft()
            request = tracked.request
            try:
                response = self._ecs.run_task(
                    cluster=self.cluster,
                    taskDefinition=self.task_definition,
                    launchType="FARGATE",
                    count=1,
                    startedBy=f"claysandbox-{request.eval_id}"[:36],
                    networkConfiguration={
                        "awsvpcConfiguration": {
                            "subnets": self.subnets,
                            "securityGroups": self.security_groups,
                            "assignPublicIp": self.params.assign_public_ip,
                        }
                    },
                    overrides={
                        "containerOverrides": [
                            {
                                "name": self.container_name,
                                "command": [
                                    "worker",
                                    "--request",
                                    self._request_uri(request.run_id),
                                ],
                            }
                        ]
                    },
                )
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code in _CONFIG_CODES:
                    raise ConfigError(f"ECS run_task failed: {exc}", kind="fargate_config") from exc
                statuses.append(self._executor_failure(request, f"run_task failed: {exc}"))
                continue
            if response.get("failures") or not response.get("tasks"):
                reason = "; ".join(
                    f"{f.get('arn', '')} {f.get('reason', '')}".strip()
                    for f in response.get("failures", [])
                )
                statuses.append(self._executor_failure(request, reason or "no task started"))
                continue
            task = response["tasks"][0]
            tracked.task_arn = task["taskArn"]
            tracked.environment = {
                "executor": "fargate",
                "task_arn": task["taskArn"],
                "cluster": self.cluster,
                "region": self.params.region,
            }
            self._running[tracked.task_arn] = tracked
            statuses.append(
                RunStatus(
                    run_id=request.run_id,
                    eval_id=request.eval_id,
                    state="running",
                    environment=tracked.environment,
                )
            )
            tracked.reported_running = True
        return statuses

    def _refresh_running(self) -> list[RunStatus]:
        statuses: list[RunStatus] = []
        arns = list(self._running)
        for i in range(0, len(arns), _DESCRIBE_BATCH):
            batch = arns[i : i + _DESCRIBE_BATCH]
            response = self._ecs.describe_tasks(cluster=self.cluster, tasks=batch)
            described: dict[str, dict[str, Any]] = {
                t["taskArn"]: t for t in response.get("tasks", [])
            }
            missing = {f.get("arn"): f.get("reason", "") for f in response.get("failures", [])}
            for arn in batch:
                tracked = self._running[arn]
                task = described.get(arn)
                if task is None:
                    reason = missing.get(arn, "task not found")
                    statuses.append(self._finish(arn, self._lost(tracked, reason)))
                elif task.get("lastStatus") == "STOPPED":
                    statuses.append(self._finish(arn, self._stopped(tracked, task)))
        return statuses

    def _finish(self, arn: str, status: RunStatus) -> RunStatus:
        self._running.pop(arn, None)
        return status

    def _stopped(self, tracked: _Tracked, task: dict[str, Any]) -> RunStatus:
        request = tracked.request
        stored = self._read_status(request.run_id)
        if stored is not None and stored.get("state") in TERMINAL_STATES:
            return RunStatus(
                run_id=request.run_id,
                eval_id=request.eval_id,
                state=stored["state"],
                error_kind=stored.get("error_kind"),
                message=stored.get("message"),
                environment=tracked.environment,
            )
        reason = task.get("stoppedReason") or "task stopped without a terminal status"
        codes = [
            f"exit {c['exitCode']}"
            for c in task.get("containers", [])
            if c.get("exitCode") not in (None, 0)
        ]
        return self._executor_failure(request, "; ".join([reason, *codes]), tracked.environment)

    def _lost(self, tracked: _Tracked, reason: str) -> RunStatus:
        stored = self._read_status(tracked.request.run_id)
        if stored is not None and stored.get("state") in TERMINAL_STATES:
            return RunStatus(
                run_id=tracked.request.run_id,
                eval_id=tracked.request.eval_id,
                state=stored["state"],
                environment=tracked.environment,
            )
        return self._executor_failure(tracked.request, reason, tracked.environment)

    @staticmethod
    def _executor_failure(
        request: RunRequest, message: str, environment: dict[str, Any] | None = None
    ) -> RunStatus:
        return RunStatus(
            run_id=request.run_id,
            eval_id=request.eval_id,
            state="infra_retry",
            error_kind="executor_failure",
            message=message[:500],
            environment=environment or {},
        )

    def _read_status(self, run_id: str) -> dict[str, Any] | None:
        try:
            body = self._s3.get_object(Bucket=self.bucket, Key=f"runs/{run_id}/status.json")["Body"]
            data = json.loads(body.read())
        except ClientError as exc:
            code = exc.response.get("Error", {}).get("Code", "")
            if code in {"NoSuchKey", "404", "NotFound"}:
                return None
            raise
        except ValueError:
            return None
        return data if isinstance(data, dict) else None


def fargate_environment() -> dict[str, Any]:
    """The worker's own environment for the manifest (FR-15.7), read from the ECS metadata.

    Returns ``{"executor": "fargate", "task_arn": ...}`` inside a Fargate task and
    ``{"executor": "fargate"}`` if the metadata endpoint is not available.
    """
    env: dict[str, Any] = {"executor": "fargate"}
    base = os.environ.get("ECS_CONTAINER_METADATA_URI_V4")
    if not base:
        return env
    try:
        with urllib.request.urlopen(f"{base}/task", timeout=2) as response:  # noqa: S310
            meta = json.loads(response.read())
        env["task_arn"] = meta.get("TaskARN")
        env["cluster"] = meta.get("Cluster")
        env["availability_zone"] = meta.get("AvailabilityZone")
    except (OSError, ValueError) as exc:
        log.warning("Could not read ECS task metadata: %s", exc)
    return env
