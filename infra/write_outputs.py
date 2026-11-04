#!/usr/bin/env python3
"""Write ``infra/outputs.json`` from a deployed stack, for the Fargate executor (FR-15.4).

    uv run python infra/write_outputs.py                       # reads the ClaySandbox stack
    uv run python infra/write_outputs.py --stack MyStack --region us-west-2
    uv run python infra/write_outputs.py --from-cdk-outputs infra/cdk-outputs.json

The second form takes the file written by ``cdk deploy --outputs-file``, which nests the outputs
under the stack name. The result is a flat ``{OutputKey: value}`` map (``outputs.json`` is
gitignored: it names your account's resources).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

DEFAULT_OUT = Path(__file__).resolve().parent / "outputs.json"
REQUIRED = ("BucketName", "ClusterArn", "TaskDefinitionArn", "SubnetIds", "SecurityGroupId")


def from_stack(client: Any, stack_name: str) -> dict[str, str]:
    response = client.describe_stacks(StackName=stack_name)
    outputs = response["Stacks"][0].get("Outputs", [])
    return {o["OutputKey"]: o["OutputValue"] for o in outputs}


def from_cdk_outputs(path: Path, stack_name: str | None) -> dict[str, str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if stack_name is not None:
        return dict(data[stack_name])
    if len(data) != 1:
        raise SystemExit(f"{path} has several stacks {sorted(data)}; pass --stack")
    return dict(next(iter(data.values())))


def check(outputs: dict[str, str]) -> None:
    missing = [k for k in REQUIRED if not outputs.get(k)]
    if missing:
        raise SystemExit(f"The stack outputs are missing {missing}. Is the stack fully deployed?")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--stack", default=None, help="stack name (default: ClaySandbox)")
    parser.add_argument("--region", default="us-west-2")
    parser.add_argument("--from-cdk-outputs", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    if args.from_cdk_outputs:
        outputs = from_cdk_outputs(args.from_cdk_outputs, args.stack)
    else:
        import boto3

        client = boto3.client("cloudformation", region_name=args.region)
        outputs = from_stack(client, args.stack or "ClaySandbox")
    check(outputs)
    args.out.write_text(json.dumps(outputs, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {args.out} ({len(outputs)} outputs)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
