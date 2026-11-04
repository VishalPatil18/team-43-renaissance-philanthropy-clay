"""CDK stack for the Clay sandbox (FR-15.5, FR-15.6, architecture §17.3, DD-024).

One stack holds everything the Fargate executor needs:

* S3 bucket (block public access, SSE-S3, versioned, destroyed with the stack)
* ECR repository (scan on push)
* VPC with public subnets and no NAT gateway (cost)
* ECS cluster and a Fargate task definition for the run worker
* task role: Bedrock InvokeModel on the listed models only, the sandbox bucket, the NAIP
  Requester-Pays buckets (read), X-Ray write
* execution role: ECR pull and CloudWatch Logs write (created by the task definition)
* CloudWatch log group with 7-day retention

Context values (``cdk.json`` or ``-c key=value``):

* ``bedrockModelIds``: model or inference-profile IDs the task role may call
* ``naipBuckets``: Requester-Pays NAIP buckets the task role may read
* ``imageTag``: tag of the worker image in ECR (default ``latest``)
* ``taskCpu`` / ``taskMemoryMiB``: Fargate size (default 1 vCPU / 2 GB)
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from constructs import Construct

CONTAINER_NAME = "worker"
_PROFILE_PREFIXES = ("us.", "eu.", "apac.", "global.", "jp.", "au.", "ca.")


def bedrock_arns(model_ids: list[str], region: str, account: str) -> list[str]:
    """IAM resource ARNs for the Bedrock models the task may call.

    A plain model ID needs the foundation-model ARN in the stack's region. A cross-region
    inference profile ID (``us.``, ``global.``...) needs the profile ARN *and* the underlying
    foundation-model ARN in every region the profile may route to, so that one uses ``*`` for the
    region. Both stay limited to the named models.
    """
    arns: list[str] = []
    for model_id in model_ids:
        prefix = next((p for p in _PROFILE_PREFIXES if model_id.startswith(p)), None)
        if prefix is None:
            arns.append(f"arn:aws:bedrock:{region}::foundation-model/{model_id}")
            continue
        base = model_id[len(prefix) :]
        arns.append(f"arn:aws:bedrock:{region}:{account}:inference-profile/{model_id}")
        arns.append(f"arn:aws:bedrock:*::foundation-model/{base}")
    return list(dict.fromkeys(arns))


class ClaySandboxStack(Stack):
    def __init__(self, scope: Construct, construct_id: str, **kwargs: Any) -> None:
        super().__init__(scope, construct_id, **kwargs)

        model_ids: list[str] = self.node.try_get_context("bedrockModelIds") or []
        naip_buckets: list[str] = self.node.try_get_context("naipBuckets") or []
        image_tag: str = self.node.try_get_context("imageTag") or "latest"
        cpu = int(self.node.try_get_context("taskCpu") or 1024)
        memory = int(self.node.try_get_context("taskMemoryMiB") or 2048)

        # -- storage ------------------------------------------------------------------------
        bucket = s3.Bucket(
            self,
            "Bucket",
            block_public_access=s3.BlockPublicAccess.BLOCK_ALL,
            encryption=s3.BucketEncryption.S3_MANAGED,
            enforce_ssl=True,
            versioned=True,
            removal_policy=RemovalPolicy.DESTROY,  # the sandbox is disposable
            auto_delete_objects=True,
        )
        repository = ecr.Repository(
            self,
            "Repository",
            image_scan_on_push=True,
            removal_policy=RemovalPolicy.DESTROY,
            empty_on_delete=True,
        )

        # -- network: public subnets, no NAT gateway ----------------------------------------
        vpc = ec2.Vpc(
            self,
            "Vpc",
            max_azs=2,
            nat_gateways=0,
            subnet_configuration=[
                ec2.SubnetConfiguration(
                    name="public", subnet_type=ec2.SubnetType.PUBLIC, cidr_mask=24
                )
            ],
        )
        security_group = ec2.SecurityGroup(
            self,
            "WorkerSecurityGroup",
            vpc=vpc,
            description="Clay sandbox workers: outbound only",
            allow_all_outbound=True,
        )
        cluster = ecs.Cluster(self, "Cluster", vpc=vpc)

        # -- task ---------------------------------------------------------------------------
        log_group = logs.LogGroup(
            self,
            "WorkerLogs",
            retention=logs.RetentionDays.ONE_WEEK,
            removal_policy=RemovalPolicy.DESTROY,
        )
        task_definition = ecs.FargateTaskDefinition(
            self, "WorkerTask", cpu=cpu, memory_limit_mib=memory
        )
        task_definition.add_container(
            CONTAINER_NAME,
            image=ecs.ContainerImage.from_ecr_repository(repository, tag=image_tag),
            logging=ecs.LogDrivers.aws_logs(stream_prefix="worker", log_group=log_group),
            environment={
                "AWS_REGION": self.region,
                "CLAYSANDBOX_BUCKET": bucket.bucket_name,
            },
            stop_timeout=Duration.seconds(30),
        )

        # -- task role (least privilege) ----------------------------------------------------
        role = task_definition.task_role
        if model_ids:
            role.add_to_principal_policy(
                iam.PolicyStatement(
                    sid="InvokeConfiguredModels",
                    actions=["bedrock:InvokeModel"],  # Converse is authorised by InvokeModel
                    resources=bedrock_arns(model_ids, self.region, self.account),
                )
            )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="SandboxBucketObjects",
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[bucket.arn_for_objects("*")],
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="SandboxBucketList",
                actions=["s3:ListBucket"],
                resources=[bucket.bucket_arn],
            )
        )
        if naip_buckets:
            role.add_to_principal_policy(
                iam.PolicyStatement(
                    sid="ReadNaipRequesterPays",
                    actions=["s3:GetObject"],
                    resources=[f"arn:aws:s3:::{name}/*" for name in naip_buckets],
                )
            )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="XRayWrite",  # X-Ray write actions do not support resource-level scoping
                actions=[
                    "xray:PutTraceSegments",
                    "xray:PutTelemetryRecords",
                    "xray:GetSamplingRules",
                    "xray:GetSamplingTargets",
                ],
                resources=["*"],
            )
        )

        # -- outputs for the Fargate executor (see infra/write_outputs.py) -------------------
        CfnOutput(self, "BucketName", value=bucket.bucket_name)
        CfnOutput(self, "RepositoryUri", value=repository.repository_uri)
        CfnOutput(self, "ClusterArn", value=cluster.cluster_arn)
        CfnOutput(self, "TaskDefinitionArn", value=task_definition.task_definition_arn)
        CfnOutput(
            self,
            "SubnetIds",
            value=",".join(s.subnet_id for s in vpc.public_subnets),
        )
        CfnOutput(self, "SecurityGroupId", value=security_group.security_group_id)
        CfnOutput(self, "ContainerName", value=CONTAINER_NAME)
        CfnOutput(self, "LogGroupName", value=log_group.log_group_name)
