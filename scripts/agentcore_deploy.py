#!/usr/bin/env python3
"""Deploy the Clay sandbox agent to Amazon Bedrock AgentCore Runtime (direct code deployment).

    uv run python scripts/agentcore_deploy.py package    # build build/agentcore/agent.zip (arm64)
    uv run python scripts/agentcore_deploy.py deploy     # package, upload, IAM role, runtime
    uv run python scripts/agentcore_deploy.py invoke     # one request through the deployed runtime
    uv run python scripts/agentcore_deploy.py status
    uv run python scripts/agentcore_deploy.py delete     # remove the runtime, role and bucket

What ``deploy`` creates in the account (us-west-2):

* S3 bucket ``clay-sandbox-agentcore-<account>-<region>`` (private, SSE-S3) holding the zip
* IAM role ``ClaySandboxAgentCoreRuntime`` (trusted by bedrock-agentcore.amazonaws.com) with the
  execution-role permissions from the AgentCore docs, Bedrock limited to the Nova models
* AgentCore Runtime ``clay_sandbox_strands`` (HTTP protocol, public network, Python 3.12), started
  with ``opentelemetry-instrument`` so AgentCore Observability traces every request

The zip holds ``agentcore/main.py``, the ``claysandbox`` package, ``pricing/`` and Linux arm64
wheels of the runtime dependencies, pinned to the versions in ``uv.lock``.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any

import boto3
from botocore.exceptions import ClientError

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build" / "agentcore"
ZIP_PATH = BUILD / "agent.zip"
REGION = os.environ.get("AWS_REGION", "us-west-2")
AGENT_NAME = "clay_sandbox_strands"
ROLE_NAME = "ClaySandboxAgentCoreRuntime"
ZIP_KEY = f"{AGENT_NAME}/agent.zip"
DEFAULT_PROMPT = (
    "Search the Registry of Open Data on AWS for datasets about NAIP aerial imagery. "
    'Return {"datasets": [<dataset slug>, ...]} with at most 3 entries.'
)
# Only what the agent imports at run time (numpy/scipy for evaluation are left out).
RUNTIME_REQUIREMENTS = [
    "pydantic",
    "boto3",
    "jsonschema",
    "pyyaml",
    "python-ulid",
    "strands-agents",
    "mcp",
    "bedrock-agentcore",
    "aws-opentelemetry-distro",
    "awslabs.roda-mcp-server",
]
MODEL_IDS = ["us.amazon.nova-lite-v1:0", "us.amazon.nova-pro-v1:0"]


def account_id() -> str:
    return boto3.client("sts").get_caller_identity()["Account"]


def bucket_name() -> str:
    return f"clay-sandbox-agentcore-{account_id()}-{REGION}"


# -- package ----------------------------------------------------------------------------------


def package() -> Path:
    """Build the deployment zip with Linux arm64 wheels pinned to uv.lock."""
    if BUILD.exists():
        shutil.rmtree(BUILD)
    pkg = BUILD / "package"
    pkg.mkdir(parents=True)
    with tempfile.TemporaryDirectory() as tmp:
        constraints = Path(tmp) / "constraints.txt"
        exported = subprocess.run(
            [
                "uv",
                "export",
                "--frozen",
                "--no-hashes",
                "--no-emit-project",
                "--group",
                "agentcore",
                "--group",
                "observability",
            ],
            cwd=ROOT,
            check=True,
            capture_output=True,
            text=True,
        ).stdout
        constraints.write_text(exported)
        subprocess.run(
            [
                "uv",
                "pip",
                "install",
                "--quiet",
                "--target",
                str(pkg),
                "--python-platform",
                "aarch64-manylinux2014",
                "--python-version",
                "3.12",
                "--only-binary",
                ":all:",
                "-c",
                str(constraints),
                *RUNTIME_REQUIREMENTS,
            ],
            cwd=ROOT,
            check=True,
        )
    shutil.copytree(
        ROOT / "claysandbox",
        pkg / "claysandbox",
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"),
    )
    shutil.copytree(ROOT / "pricing", pkg / "pricing")
    shutil.copy(ROOT / "agentcore" / "main.py", pkg / "main.py")
    for cache in pkg.rglob("__pycache__"):
        shutil.rmtree(cache, ignore_errors=True)

    with zipfile.ZipFile(ZIP_PATH, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(pkg.rglob("*")):
            if path.is_file():
                info = zipfile.ZipInfo.from_file(path, path.relative_to(pkg).as_posix())
                info.compress_type = zipfile.ZIP_DEFLATED
                with path.open("rb") as f:
                    zf.writestr(info, f.read())
    size_mb = ZIP_PATH.stat().st_size / 1e6
    unzipped_mb = sum(p.stat().st_size for p in pkg.rglob("*") if p.is_file()) / 1e6
    print(f"built {ZIP_PATH} ({size_mb:.1f} MB zipped, {unzipped_mb:.1f} MB unzipped)")
    return ZIP_PATH


# -- AWS resources ------------------------------------------------------------------------------


def ensure_bucket(s3: Any, name: str) -> None:
    try:
        s3.head_bucket(Bucket=name)
        return
    except ClientError as exc:
        if exc.response["Error"]["Code"] not in ("404", "NoSuchBucket", "NotFound"):
            raise
    s3.create_bucket(Bucket=name, CreateBucketConfiguration={"LocationConstraint": REGION})
    s3.put_public_access_block(
        Bucket=name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )
    s3.put_bucket_encryption(
        Bucket=name,
        ServerSideEncryptionConfiguration={
            "Rules": [{"ApplyServerSideEncryptionByDefault": {"SSEAlgorithm": "AES256"}}]
        },
    )
    print(f"created bucket {name}")


def role_policies(account: str, bucket: str) -> tuple[dict[str, Any], dict[str, Any]]:
    trust = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "AssumeRolePolicy",
                "Effect": "Allow",
                "Principal": {"Service": "bedrock-agentcore.amazonaws.com"},
                "Action": "sts:AssumeRole",
                "Condition": {
                    "StringEquals": {"aws:SourceAccount": account},
                    "ArnLike": {"aws:SourceArn": f"arn:aws:bedrock-agentcore:{REGION}:{account}:*"},
                },
            }
        ],
    }
    logs_prefix = f"arn:aws:logs:{REGION}:{account}:log-group:/aws/bedrock-agentcore/runtimes"
    models = []
    for model_id in MODEL_IDS:
        models.append(f"arn:aws:bedrock:{REGION}:{account}:inference-profile/{model_id}")
        models.append(f"arn:aws:bedrock:*::foundation-model/{model_id.split('.', 1)[1]}")
    permissions = {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReadAgentCode",
                "Effect": "Allow",
                "Action": ["s3:GetObject"],
                "Resource": [f"arn:aws:s3:::{bucket}/{AGENT_NAME}/*"],
            },
            {
                "Sid": "RuntimeLogGroups",
                "Effect": "Allow",
                "Action": ["logs:DescribeLogStreams", "logs:CreateLogGroup"],
                "Resource": [f"{logs_prefix}/*"],
            },
            {
                "Sid": "DescribeLogGroups",
                "Effect": "Allow",
                "Action": ["logs:DescribeLogGroups"],
                "Resource": [f"arn:aws:logs:{REGION}:{account}:log-group:*"],
            },
            {
                "Sid": "RuntimeLogStreams",
                "Effect": "Allow",
                "Action": ["logs:CreateLogStream", "logs:PutLogEvents"],
                "Resource": [f"{logs_prefix}/*:log-stream:*"],
            },
            {
                "Sid": "XRay",
                "Effect": "Allow",
                "Action": [
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                "Resource": ["*"],
            },
            {
                "Sid": "Metrics",
                "Effect": "Allow",
                "Action": "cloudwatch:PutMetricData",
                "Resource": "*",
                "Condition": {"StringEquals": {"cloudwatch:namespace": "bedrock-agentcore"}},
            },
            {
                "Sid": "GetAgentAccessToken",
                "Effect": "Allow",
                "Action": [
                    "bedrock-agentcore:GetWorkloadAccessToken",
                    "bedrock-agentcore:GetWorkloadAccessTokenForJWT",
                ],
                "Resource": [
                    f"arn:aws:bedrock-agentcore:{REGION}:{account}:workload-identity-directory/default",
                    f"arn:aws:bedrock-agentcore:{REGION}:{account}:workload-identity-directory/"
                    f"default/workload-identity/{AGENT_NAME}-*",
                ],
            },
            {
                "Sid": "BedrockModelInvocation",
                "Effect": "Allow",
                "Action": ["bedrock:InvokeModel", "bedrock:InvokeModelWithResponseStream"],
                "Resource": models,
            },
        ],
    }
    return trust, permissions


def ensure_role(iam: Any, account: str, bucket: str) -> str:
    trust, permissions = role_policies(account, bucket)
    try:
        arn = iam.get_role(RoleName=ROLE_NAME)["Role"]["Arn"]
        iam.update_assume_role_policy(RoleName=ROLE_NAME, PolicyDocument=json.dumps(trust))
    except iam.exceptions.NoSuchEntityException:
        arn = iam.create_role(
            RoleName=ROLE_NAME,
            AssumeRolePolicyDocument=json.dumps(trust),
            Description="Execution role for the Clay sandbox agent on AgentCore Runtime",
        )["Role"]["Arn"]
        print(f"created role {arn}")
        time.sleep(10)  # IAM propagation before the runtime tries to assume it
    iam.put_role_policy(
        RoleName=ROLE_NAME,
        PolicyName="AgentCoreRuntimeExecution",
        PolicyDocument=json.dumps(permissions),
    )
    return arn


def find_runtime(control: Any) -> dict[str, Any] | None:
    token = None
    while True:
        page = control.list_agent_runtimes(**({"nextToken": token} if token else {}))
        for runtime in page.get("agentRuntimes", []):
            if runtime["agentRuntimeName"] == AGENT_NAME:
                return runtime
        token = page.get("nextToken")
        if not token:
            return None


def deploy() -> None:
    zip_path = package()
    account, bucket = account_id(), bucket_name()
    s3 = boto3.client("s3", region_name=REGION)
    ensure_bucket(s3, bucket)
    s3.upload_file(str(zip_path), bucket, ZIP_KEY)
    print(f"uploaded s3://{bucket}/{ZIP_KEY}")
    role_arn = ensure_role(boto3.client("iam"), account, bucket)

    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    config: dict[str, Any] = {
        "agentRuntimeArtifact": {
            "codeConfiguration": {
                "code": {"s3": {"bucket": bucket, "prefix": ZIP_KEY}},
                "runtime": "PYTHON_3_12",
                "entryPoint": ["opentelemetry-instrument", "main.py"],
            }
        },
        "roleArn": role_arn,
        "networkConfiguration": {"networkMode": "PUBLIC"},
        "protocolConfiguration": {"serverProtocol": "HTTP"},
        "description": "Clay sandbox: Strands harness + RODA MCP tools, instrumented",
        "environmentVariables": {"CLAY_MODEL_ID": MODEL_IDS[0]},
    }
    existing = find_runtime(control)
    for attempt in range(6):  # a new role can take a little longer to be assumable
        try:
            if existing is None:
                response = control.create_agent_runtime(agentRuntimeName=AGENT_NAME, **config)
                print(f"created runtime {response['agentRuntimeArn']}")
            else:
                response = control.update_agent_runtime(
                    agentRuntimeId=existing["agentRuntimeId"], **config
                )
                print(
                    f"updated runtime {response['agentRuntimeArn']} "
                    f"(version {response.get('agentRuntimeVersion')})"
                )
            break
        except ClientError as exc:
            message = exc.response["Error"].get("Message", "")
            if attempt < 5 and "role" in message.lower():
                print(f"  waiting for the IAM role ({message[:100]})")
                time.sleep(10)
                continue
            raise
    runtime = wait_ready(control, response["agentRuntimeId"])
    configure_otel_logs(control, runtime, config)


def configure_otel_logs(control: Any, runtime: dict[str, Any], config: dict[str, Any]) -> None:
    """Send the agent's OTel logs to a stream that exists in the runtime's log group.

    The OTLP logs endpoint does not create log streams, so the stream is created here and the
    exporter is pointed at it explicitly (otherwise every export fails with "log stream does not
    exist" and the structured agent logs are lost; spans are unaffected).
    """
    runtime_id = runtime["agentRuntimeId"]
    group = f"/aws/bedrock-agentcore/runtimes/{runtime_id}-DEFAULT"
    stream = "otel-rt-logs"
    logs = boto3.client("logs", region_name=REGION)
    for create in (
        lambda: logs.create_log_group(logGroupName=group),
        lambda: logs.create_log_stream(logGroupName=group, logStreamName=stream),
    ):
        try:
            create()
        except logs.exceptions.ResourceAlreadyExistsException:
            pass
    headers = (
        f"x-aws-log-group={group},x-aws-log-stream={stream},"
        "x-aws-metric-namespace=bedrock-agentcore"
    )
    env = dict(runtime.get("environmentVariables") or config["environmentVariables"])
    if env.get("OTEL_EXPORTER_OTLP_LOGS_HEADERS") == headers:
        return
    env["OTEL_EXPORTER_OTLP_LOGS_HEADERS"] = headers
    control.update_agent_runtime(
        agentRuntimeId=runtime_id, **{**config, "environmentVariables": env}
    )
    print(f"OTel logs -> {group}:{stream}")
    wait_ready(control, runtime_id)


def wait_ready(control: Any, runtime_id: str, timeout_s: int = 600) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_s
    while True:
        runtime = control.get_agent_runtime(agentRuntimeId=runtime_id)
        status = runtime["status"]
        print(f"  status: {status}")
        if status == "READY":
            print(f"runtime ARN: {runtime['agentRuntimeArn']}")
            return runtime
        if status.endswith("FAILED") or time.monotonic() > deadline:
            raise SystemExit(f"runtime not ready: {status} {runtime.get('failureReason', '')}")
        time.sleep(10)


# -- use ------------------------------------------------------------------------------------------


def invoke(prompt: str) -> None:
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    runtime = find_runtime(control)
    if runtime is None:
        raise SystemExit("not deployed: run `deploy` first")
    client = boto3.client("bedrock-agentcore", region_name=REGION)
    session_id = f"clay-{uuid.uuid4()}"  # must be at least 33 characters
    t0 = time.monotonic()
    response = client.invoke_agent_runtime(
        agentRuntimeArn=runtime["agentRuntimeArn"],
        runtimeSessionId=session_id,
        payload=json.dumps({"prompt": prompt}).encode(),
        qualifier="DEFAULT",
    )
    body = json.loads(response["response"].read())
    print(f"session: {session_id}  ({(time.monotonic() - t0):.1f} s)")
    print(json.dumps(body, indent=2)[:3000])


def status() -> None:
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    runtime = find_runtime(control)
    if runtime is None:
        print("not deployed")
        return
    details = control.get_agent_runtime(agentRuntimeId=runtime["agentRuntimeId"])
    for key in (
        "agentRuntimeName",
        "agentRuntimeArn",
        "agentRuntimeVersion",
        "status",
        "lastUpdatedAt",
    ):
        print(f"{key}: {details.get(key)}")


def delete() -> None:
    control = boto3.client("bedrock-agentcore-control", region_name=REGION)
    runtime = find_runtime(control)
    if runtime is not None:
        control.delete_agent_runtime(agentRuntimeId=runtime["agentRuntimeId"])
        print(f"deleting runtime {runtime['agentRuntimeArn']}")
    iam = boto3.client("iam")
    try:
        iam.delete_role_policy(RoleName=ROLE_NAME, PolicyName="AgentCoreRuntimeExecution")
        iam.delete_role(RoleName=ROLE_NAME)
        print(f"deleted role {ROLE_NAME}")
    except iam.exceptions.NoSuchEntityException:
        pass
    s3 = boto3.resource("s3", region_name=REGION)
    bucket = s3.Bucket(bucket_name())
    try:
        bucket.objects.all().delete()
        bucket.delete()
        print(f"deleted bucket {bucket.name}")
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "NoSuchBucket":
            raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["package", "deploy", "invoke", "status", "delete"])
    parser.add_argument("--prompt", default=DEFAULT_PROMPT)
    args = parser.parse_args()
    {
        "package": package,
        "deploy": deploy,
        "status": status,
        "delete": delete,
        "invoke": lambda: invoke(args.prompt),
    }[args.command]()
    return 0


if __name__ == "__main__":
    sys.exit(main())
