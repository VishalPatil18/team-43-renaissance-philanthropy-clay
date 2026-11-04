#!/usr/bin/env python3
"""CDK app entry point. Run from ``infra/``: ``cdk synth`` / ``cdk deploy`` (see cdk.json)."""

from __future__ import annotations

import os

import aws_cdk as cdk
from stack import ClaySandboxStack

app = cdk.App()
ClaySandboxStack(
    app,
    "ClaySandbox",
    env=cdk.Environment(
        account=os.environ.get("CDK_DEFAULT_ACCOUNT"),
        region=os.environ.get("CDK_DEFAULT_REGION") or "us-west-2",
    ),
    description="Clay agent-eval sandbox: worker image, Fargate task, run storage",
)
app.synth()
