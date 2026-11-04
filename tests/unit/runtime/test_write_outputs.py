from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest

SCRIPT = Path(__file__).resolve().parents[3] / "infra" / "write_outputs.py"
spec = importlib.util.spec_from_file_location("write_outputs", SCRIPT)
assert spec and spec.loader
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

OUTPUTS = {
    "BucketName": "b",
    "ClusterArn": "arn:cluster",
    "TaskDefinitionArn": "arn:td",
    "SubnetIds": "subnet-1,subnet-2",
    "SecurityGroupId": "sg-1",
    "ContainerName": "worker",
}


class FakeCloudFormation:
    def __init__(self, outputs: dict[str, str]) -> None:
        self.outputs = outputs

    def describe_stacks(self, StackName: str) -> dict[str, Any]:  # noqa: N803
        return {
            "Stacks": [
                {"Outputs": [{"OutputKey": k, "OutputValue": v} for k, v in self.outputs.items()]}
            ]
        }


def test_outputs_are_read_from_the_stack() -> None:
    assert mod.from_stack(FakeCloudFormation(OUTPUTS), "ClaySandbox") == OUTPUTS


def test_cdk_outputs_file_is_flattened(tmp_path: Path) -> None:
    path = tmp_path / "cdk-outputs.json"
    path.write_text(json.dumps({"ClaySandbox": OUTPUTS}))
    assert mod.from_cdk_outputs(path, None) == OUTPUTS
    assert mod.from_cdk_outputs(path, "ClaySandbox") == OUTPUTS
    path.write_text(json.dumps({"A": OUTPUTS, "B": OUTPUTS}))
    with pytest.raises(SystemExit, match="several stacks"):
        mod.from_cdk_outputs(path, None)


def test_main_writes_a_file_the_fargate_executor_can_use(tmp_path: Path) -> None:
    from claysandbox.platform.executors.fargate import FargateExecutor

    source = tmp_path / "cdk-outputs.json"
    source.write_text(json.dumps({"ClaySandbox": OUTPUTS}))
    out = tmp_path / "outputs.json"
    assert mod.main(["--from-cdk-outputs", str(source), "--out", str(out)]) == 0
    executor = FargateExecutor({"outputs_path": str(out)}, ecs_client=object(), s3_client=object())
    assert executor.bucket == "b" and executor.subnets == ["subnet-1", "subnet-2"]


def test_incomplete_outputs_are_refused(tmp_path: Path) -> None:
    source = tmp_path / "cdk-outputs.json"
    source.write_text(json.dumps({"ClaySandbox": {"BucketName": "b"}}))
    with pytest.raises(SystemExit, match="missing"):
        mod.main(["--from-cdk-outputs", str(source), "--out", str(tmp_path / "o.json")])
    assert not (tmp_path / "o.json").exists()
