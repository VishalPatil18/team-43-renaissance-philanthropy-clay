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
* ``webUi``: also host the web UI (default false). It adds a Fargate service running
  ``clay-sandbox serve --hosted`` from the same image, an internet-facing load balancer that
  accepts only CloudFront, a CloudFront distribution (HTTPS on its default domain), and a
  generated shared password in Secrets Manager. Launches from the UI run on the worker task.
* ``cloudFrontPrefixListId``: the CloudFront origin-facing prefix list (looked up if absent)
"""

from __future__ import annotations

from typing import Any

from aws_cdk import CfnOutput, Duration, RemovalPolicy, Stack
from aws_cdk import aws_cloudfront as cloudfront
from aws_cdk import aws_cloudfront_origins as origins
from aws_cdk import aws_ec2 as ec2
from aws_cdk import aws_ecr as ecr
from aws_cdk import aws_ecs as ecs
from aws_cdk import aws_elasticloadbalancingv2 as elbv2
from aws_cdk import aws_iam as iam
from aws_cdk import aws_logs as logs
from aws_cdk import aws_s3 as s3
from aws_cdk import aws_secretsmanager as secretsmanager
from constructs import Construct

CONTAINER_NAME = "worker"
WEB_CONTAINER_NAME = "web"
WEB_PORT = 8080
UI_USERNAME = "clay"
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

        if self.node.try_get_context("webUi"):
            self._web_ui(
                vpc=vpc,
                cluster=cluster,
                repository=repository,
                image_tag=image_tag,
                bucket=bucket,
                log_group=log_group,
                worker_task=task_definition,
                worker_security_group=security_group,
            )

    def _web_ui(
        self,
        *,
        vpc: ec2.Vpc,
        cluster: ecs.Cluster,
        repository: ecr.Repository,
        image_tag: str,
        bucket: s3.Bucket,
        log_group: logs.LogGroup,
        worker_task: ecs.FargateTaskDefinition,
        worker_security_group: ec2.SecurityGroup,
    ) -> None:
        """The hosted UI: CloudFront (HTTPS) -> load balancer -> one Fargate web task."""
        password = secretsmanager.Secret(
            self,
            "UiPassword",
            description=f"Shared login for the Clay sandbox web UI (user {UI_USERNAME!r})",
            generate_secret_string=secretsmanager.SecretStringGenerator(
                password_length=24, exclude_punctuation=True
            ),
            removal_policy=RemovalPolicy.DESTROY,
        )

        web_task = ecs.FargateTaskDefinition(self, "WebTask", cpu=512, memory_limit_mib=1024)
        web_task.add_container(
            WEB_CONTAINER_NAME,
            image=ecs.ContainerImage.from_ecr_repository(repository, tag=image_tag),
            command=["serve", "--hosted", "--port", str(WEB_PORT), "--store", "/app/store"],
            port_mappings=[ecs.PortMapping(container_port=WEB_PORT)],
            logging=ecs.LogDrivers.aws_logs(stream_prefix="web", log_group=log_group),
            environment={
                "AWS_REGION": self.region,
                "CLAYSANDBOX_BUCKET": bucket.bucket_name,
                "CLAYSANDBOX_CLUSTER": cluster.cluster_arn,
                "CLAYSANDBOX_TASK_DEFINITION": worker_task.task_definition_arn,
                "CLAYSANDBOX_SUBNETS": ",".join(s.subnet_id for s in vpc.public_subnets),
                "CLAYSANDBOX_SECURITY_GROUPS": worker_security_group.security_group_id,
            },
            secrets={"CLAYSANDBOX_UI_PASSWORD": ecs.Secret.from_secrets_manager(password)},
            stop_timeout=Duration.seconds(30),
        )

        # The web task reads and writes the store, and starts and watches worker tasks.
        role = web_task.task_role
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="WebBucketObjects",
                actions=["s3:GetObject", "s3:PutObject"],
                resources=[bucket.arn_for_objects("*")],
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="WebBucketList", actions=["s3:ListBucket"], resources=[bucket.bucket_arn]
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="RunWorkerTasks",
                actions=["ecs:RunTask"],
                resources=[worker_task.task_definition_arn],
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="WatchWorkerTasks",
                actions=["ecs:DescribeTasks", "ecs:StopTask"],
                resources=["*"],  # task ARNs are not known in advance
                conditions={"ArnEquals": {"ecs:cluster": cluster.cluster_arn}},
            )
        )
        pass_roles = [worker_task.task_role.role_arn]
        if worker_task.execution_role is not None:
            pass_roles.append(worker_task.execution_role.role_arn)
        role.add_to_principal_policy(
            iam.PolicyStatement(
                sid="PassWorkerRoles", actions=["iam:PassRole"], resources=pass_roles
            )
        )

        # Network: CloudFront -> load balancer (CloudFront addresses only) -> web task.
        prefix_list_id = self.node.try_get_context("cloudFrontPrefixListId") or (
            ec2.PrefixList.from_lookup(
                self,
                "CloudFrontOriginFacing",
                prefix_list_name="com.amazonaws.global.cloudfront.origin-facing",
            ).prefix_list_id
        )
        alb_sg = ec2.SecurityGroup(
            self, "WebAlbSecurityGroup", vpc=vpc, description="Web UI load balancer"
        )
        alb_sg.add_ingress_rule(
            ec2.Peer.prefix_list(prefix_list_id), ec2.Port.tcp(80), "CloudFront only"
        )
        web_sg = ec2.SecurityGroup(
            self, "WebSecurityGroup", vpc=vpc, description="Web UI task", allow_all_outbound=True
        )
        web_sg.add_ingress_rule(alb_sg, ec2.Port.tcp(WEB_PORT), "from the load balancer")

        service = ecs.FargateService(
            self,
            "WebService",
            cluster=cluster,
            task_definition=web_task,
            desired_count=1,
            assign_public_ip=True,  # public subnets, no NAT: needed to reach ECR, S3 and ECS
            vpc_subnets=ec2.SubnetSelection(subnet_type=ec2.SubnetType.PUBLIC),
            security_groups=[web_sg],
            # Start the new task before stopping the old one, so a redeploy has no downtime.
            min_healthy_percent=100,
            max_healthy_percent=200,
            circuit_breaker=ecs.DeploymentCircuitBreaker(rollback=True),
        )
        alb = elbv2.ApplicationLoadBalancer(
            self, "WebAlb", vpc=vpc, internet_facing=True, security_group=alb_sg
        )
        alb.add_listener("Http", port=80, open=False).add_targets(
            "Web",
            port=WEB_PORT,
            protocol=elbv2.ApplicationProtocol.HTTP,
            targets=[service],
            health_check=elbv2.HealthCheck(path="/healthz", healthy_http_codes="200"),
            deregistration_delay=Duration.seconds(10),
        )

        # CloudFront forwards Authorization (the login) only when it is in the cache key. With
        # default and minimum TTL 0 nothing is kept, and each login has its own cache entry.
        no_cache_with_login = cloudfront.CachePolicy(
            self,
            "WebNoCache",
            comment="Clay sandbox UI: forward the login, cache nothing",
            default_ttl=Duration.seconds(0),
            min_ttl=Duration.seconds(0),
            max_ttl=Duration.seconds(1),
            header_behavior=cloudfront.CacheHeaderBehavior.allow_list("Authorization"),
            query_string_behavior=cloudfront.CacheQueryStringBehavior.all(),
            cookie_behavior=cloudfront.CacheCookieBehavior.none(),
        )
        distribution = cloudfront.Distribution(
            self,
            "WebDistribution",
            comment="Clay sandbox web UI",
            default_behavior=cloudfront.BehaviorOptions(
                origin=origins.LoadBalancerV2Origin(
                    alb,
                    protocol_policy=cloudfront.OriginProtocolPolicy.HTTP_ONLY,
                    read_timeout=Duration.seconds(60),
                ),
                viewer_protocol_policy=cloudfront.ViewerProtocolPolicy.REDIRECT_TO_HTTPS,
                allowed_methods=cloudfront.AllowedMethods.ALLOW_ALL,
                cache_policy=no_cache_with_login,
                # Forwards Host (for the same-origin check), query strings and cookies.
                origin_request_policy=cloudfront.OriginRequestPolicy.ALL_VIEWER,
            ),
            price_class=cloudfront.PriceClass.PRICE_CLASS_100,
        )

        CfnOutput(self, "WebUrl", value=f"https://{distribution.distribution_domain_name}")
        CfnOutput(self, "WebUsername", value=UI_USERNAME)
        CfnOutput(self, "WebPasswordSecretArn", value=password.secret_arn)
