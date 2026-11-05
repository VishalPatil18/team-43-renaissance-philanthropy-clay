"""Template-level checks for the CDK stack (FR-15.5). No AWS account or deployment needed."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("aws_cdk")

import aws_cdk as cdk  # noqa: E402
from aws_cdk.assertions import Match, Template  # noqa: E402

INFRA = Path(__file__).resolve().parents[3] / "infra"
sys.path.insert(0, str(INFRA))
from stack import ClaySandboxStack, bedrock_arns  # noqa: E402

CONTEXT = {
    "bedrockModelIds": ["us.amazon.nova-lite-v1:0", "amazon.nova-pro-v1:0"],
    "naipBuckets": ["naip-source", "naip-analytic"],
}


@pytest.fixture(scope="module")
def template() -> Template:
    app = cdk.App(context=CONTEXT)
    stack = ClaySandboxStack(
        app, "Test", env=cdk.Environment(account="123456789012", region="us-west-2")
    )
    return Template.from_stack(stack)


def task_role_statements(template: Template) -> dict[str, Any]:
    policies = template.find_resources("AWS::IAM::Policy")
    statements: dict[str, Any] = {}
    for name, resource in policies.items():
        if "TaskRole" in name:
            for s in resource["Properties"]["PolicyDocument"]["Statement"]:
                statements[s["Sid"]] = s
    return statements


def test_bucket_blocks_public_access_encrypts_and_versions(template: Template) -> None:
    template.has_resource_properties(
        "AWS::S3::Bucket",
        {
            "PublicAccessBlockConfiguration": {
                "BlockPublicAcls": True,
                "BlockPublicPolicy": True,
                "IgnorePublicAcls": True,
                "RestrictPublicBuckets": True,
            },
            "BucketEncryption": Match.any_value(),
            "VersioningConfiguration": {"Status": "Enabled"},
        },
    )


def test_ecr_scans_on_push(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECR::Repository", {"ImageScanningConfiguration": {"ScanOnPush": True}}
    )


def test_no_nat_gateway_and_public_subnets_only(template: Template) -> None:
    template.resource_count_is("AWS::EC2::NatGateway", 0)
    template.has_resource_properties("AWS::EC2::Subnet", {"MapPublicIpOnLaunch": True})


def test_fargate_task_is_1_vcpu_2_gb_with_awslogs_and_7_day_retention(template: Template) -> None:
    template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "Cpu": "1024",
            "Memory": "2048",
            "RequiresCompatibilities": ["FARGATE"],
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Name": "worker",
                        "LogConfiguration": Match.object_like({"LogDriver": "awslogs"}),
                    }
                )
            ],
        },
    )
    template.has_resource_properties("AWS::Logs::LogGroup", {"RetentionInDays": 7})


def test_task_role_is_scoped_to_the_configured_models_and_buckets(template: Template) -> None:
    statements = task_role_statements(template)
    assert set(statements) == {
        "InvokeConfiguredModels",
        "SandboxBucketObjects",
        "SandboxBucketList",
        "ReadNaipRequesterPays",
        "XRayWrite",
    }
    invoke = statements["InvokeConfiguredModels"]
    assert invoke["Action"] == "bedrock:InvokeModel"
    assert invoke["Resource"] == [
        "arn:aws:bedrock:us-west-2:123456789012:inference-profile/us.amazon.nova-lite-v1:0",
        "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
        "arn:aws:bedrock:us-west-2::foundation-model/amazon.nova-pro-v1:0",
    ]
    assert set(statements["SandboxBucketObjects"]["Action"]) == {"s3:GetObject", "s3:PutObject"}
    assert statements["SandboxBucketList"]["Action"] == "s3:ListBucket"
    assert statements["ReadNaipRequesterPays"]["Action"] == "s3:GetObject"
    assert statements["ReadNaipRequesterPays"]["Resource"] == [
        "arn:aws:s3:::naip-source/*",
        "arn:aws:s3:::naip-analytic/*",
    ]
    assert not any(
        "*" == s["Action"] or "bedrock:*" in str(s["Action"]) for s in statements.values()
    )


def test_outputs_match_what_the_fargate_executor_reads(template: Template) -> None:
    outputs = template.to_json()["Outputs"]
    assert {
        "BucketName",
        "ClusterArn",
        "TaskDefinitionArn",
        "SubnetIds",
        "SecurityGroupId",
        "ContainerName",
    } <= set(outputs)


def test_the_stack_synthesizes_without_credentials_or_an_account() -> None:
    """CI has no AWS account; `cdk synth` must still work."""
    app = cdk.App(context=CONTEXT)
    stack = ClaySandboxStack(app, "NoAccount")
    assert Template.from_stack(stack).to_json()["Resources"]


def test_no_model_context_means_no_bedrock_permission() -> None:
    app = cdk.App()
    template = Template.from_stack(ClaySandboxStack(app, "NoModels"))
    assert "InvokeConfiguredModels" not in task_role_statements(template)


@pytest.mark.parametrize(
    ("model_ids", "expected"),
    [
        (["amazon.nova-lite-v1:0"], ["arn:aws:bedrock:r::foundation-model/amazon.nova-lite-v1:0"]),
        (
            ["global.anthropic.claude-sonnet-4-6"],
            [
                "arn:aws:bedrock:r:a:inference-profile/global.anthropic.claude-sonnet-4-6",
                "arn:aws:bedrock:*::foundation-model/anthropic.claude-sonnet-4-6",
            ],
        ),
        (
            ["us.amazon.nova-lite-v1:0", "us.amazon.nova-lite-v1:0"],
            [
                "arn:aws:bedrock:r:a:inference-profile/us.amazon.nova-lite-v1:0",
                "arn:aws:bedrock:*::foundation-model/amazon.nova-lite-v1:0",
            ],
        ),
    ],
)
def test_bedrock_arns(model_ids: list[str], expected: list[str]) -> None:
    assert bedrock_arns(model_ids, "r", "a") == expected


@pytest.fixture(scope="module")
def web_template() -> Template:
    app = cdk.App(context={**CONTEXT, "webUi": True, "cloudFrontPrefixListId": "pl-82a045eb"})
    stack = ClaySandboxStack(
        app, "WebTest", env=cdk.Environment(account="123456789012", region="us-west-2")
    )
    return Template.from_stack(stack)


def test_web_ui_is_off_unless_asked(template: Template) -> None:
    template.resource_count_is("AWS::CloudFront::Distribution", 0)
    template.resource_count_is("AWS::ECS::Service", 0)


def test_web_ui_serves_hosted_mode_with_a_generated_password(web_template: Template) -> None:
    web_template.resource_count_is("AWS::ECS::Service", 1)
    web_template.resource_count_is("AWS::SecretsManager::Secret", 1)
    web_template.has_resource_properties(
        "AWS::ECS::TaskDefinition",
        {
            "ContainerDefinitions": [
                Match.object_like(
                    {
                        "Name": "web",
                        "Command": ["serve", "--hosted", "--port", "8080", "--store", "/app/store"],
                        "Secrets": [Match.object_like({"Name": "CLAYSANDBOX_UI_PASSWORD"})],
                    }
                )
            ]
        },
    )


def test_web_load_balancer_accepts_only_cloudfront(web_template: Template) -> None:
    web_template.has_resource_properties(
        "AWS::EC2::SecurityGroupIngress",
        {"SourcePrefixListId": "pl-82a045eb", "FromPort": 80, "ToPort": 80},
    )
    rules = web_template.find_resources("AWS::EC2::SecurityGroupIngress").values()
    assert not any(r["Properties"].get("CidrIp") == "0.0.0.0/0" for r in rules)
    for group in web_template.find_resources("AWS::EC2::SecurityGroup").values():
        for rule in group["Properties"].get("SecurityGroupIngress") or []:
            assert rule.get("CidrIp") != "0.0.0.0/0"
    web_template.has_resource_properties(
        "AWS::CloudFront::Distribution",
        {
            "DistributionConfig": Match.object_like(
                {
                    "DefaultCacheBehavior": Match.object_like(
                        {"ViewerProtocolPolicy": "redirect-to-https"}
                    )
                }
            )
        },
    )
    web_template.has_resource_properties(
        "AWS::CloudFront::CachePolicy",
        {
            "CachePolicyConfig": Match.object_like(
                {
                    "DefaultTTL": 0,
                    "ParametersInCacheKeyAndForwardedToOrigin": Match.object_like(
                        {
                            "HeadersConfig": {
                                "HeaderBehavior": "whitelist",
                                "Headers": ["Authorization"],
                            }
                        }
                    ),
                }
            )
        },
    )


def test_web_task_may_start_only_the_worker_task(web_template: Template) -> None:
    policies = web_template.find_resources("AWS::IAM::Policy")
    statements = {
        s["Sid"]: s
        for name, r in policies.items()
        if "WebTaskTaskRole" in name
        for s in r["Properties"]["PolicyDocument"]["Statement"]
    }
    assert set(statements) >= {"RunWorkerTasks", "WatchWorkerTasks", "PassWorkerRoles"}
    assert statements["RunWorkerTasks"]["Action"] == "ecs:RunTask"
    assert "bedrock:InvokeModel" not in json.dumps(statements)


def test_web_redeploys_start_the_new_task_first(web_template: Template) -> None:
    web_template.has_resource_properties(
        "AWS::ECS::Service",
        {
            "DeploymentConfiguration": Match.object_like(
                {"MinimumHealthyPercent": 100, "MaximumPercent": 200}
            )
        },
    )
