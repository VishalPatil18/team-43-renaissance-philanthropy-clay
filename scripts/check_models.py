#!/usr/bin/env python3
"""Check which Bedrock models the sandbox account can call with tool use (PRI-R0-00).

For every candidate model ID this calls Bedrock Converse through the sandbox's own
``BedrockModelAdapter`` with a one-line prompt and one dummy tool, then prints: model ID,
ok/FAIL, whether a ``toolUse`` came back, latency, tokens (or the error).

Claude-family models often need a cross-region inference profile ID (a ``us.`` prefix), so each
base ID is tried with and without the prefix.

    uv run python scripts/check_models.py                 # the default candidate list
    uv run python scripts/check_models.py --discover      # also list what the account offers
    uv run python scripts/check_models.py --models amazon.nova-lite-v1:0 us.amazon.nova-pro-v1:0
    uv run python scripts/check_models.py --json          # machine-readable result

Every candidate is tried (use --first to stop at the first working ID per role). Each call
uses at most a few hundred tokens. Exit code 0 when every role has a working ID,
1 when a role is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass

import boto3

from claysandbox.contracts.errors import ConfigError, InfraError
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.runtime.models.bedrock import BedrockModelAdapter

REGION = os.environ.get("AWS_REGION", "us-west-2")

DUMMY_TOOL = ToolSpec(
    server="check",
    name="get_weather",
    description="Get the current weather for a city.",
    input_schema={
        "type": "object",
        "properties": {"city": {"type": "string"}},
        "required": ["city"],
    },
)
PROMPT = "Use the get_weather tool to look up the weather in Seattle."

# role -> base model IDs (tried bare and with the "us." inference-profile prefix, in order)
ROLE_CANDIDATES: dict[str, list[str]] = {
    "dev": ["amazon.nova-lite-v1:0"],
    "baseline": ["amazon.nova-pro-v1:0"],
    "variant": [
        "anthropic.claude-sonnet-4-6",
        "anthropic.claude-sonnet-4-5-20250929-v1:0",
        "anthropic.claude-sonnet-4-20250514-v1:0",
        "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "anthropic.claude-3-5-sonnet-20241022-v2:0",
    ],
    "summary": ["amazon.nova-lite-v1:0"],
    "judge": [
        "meta.llama3-3-70b-instruct-v1:0",
        "mistral.mistral-large-2407-v1:0",
        "meta.llama3-1-70b-instruct-v1:0",
    ],
}


# Roles whose model must return a toolUse. The summary and judge models only produce text/JSON.
NEEDS_TOOL_USE = {"dev", "baseline", "variant"}


@dataclass
class Result:
    model_id: str
    ok: bool
    tool_use: bool
    latency_ms: float | None
    input_tokens: int | None
    output_tokens: int | None
    error: str | None


def with_variants(base_id: str) -> list[str]:
    return [base_id] if base_id.startswith("us.") else [f"us.{base_id}", base_id]


def check(model_id: str) -> Result:
    t0 = time.monotonic()
    try:
        adapter = BedrockModelAdapter(
            {
                "model_id": model_id,
                "region": REGION,
                "max_tokens": 200,
                "temperature": 0.0,
                "max_attempts": 2,
            }
        )
        response = adapter.converse(
            [{"role": "user", "content": [{"text": PROMPT}]}], "", [DUMMY_TOOL], {}
        )
    except (ConfigError, InfraError) as exc:
        return Result(
            model_id,
            False,
            False,
            (time.monotonic() - t0) * 1000,
            None,
            None,
            f"{exc.kind}: {exc.message}"[:160],
        )
    return Result(
        model_id,
        True,
        bool(response.tool_uses),
        response.latency_ms,
        response.input_tokens,
        response.output_tokens,
        None,
    )


def discover() -> None:
    client = boto3.client("bedrock", region_name=REGION)
    print(f"\nModels offered in {REGION} that stream/converse with tool use is likely on:")
    for m in client.list_foundation_models(byOutputModality="TEXT")["modelSummaries"]:
        print(f"  {m['modelId']:<70} {m['providerName']}")
    print("\nInference profiles:")
    token = None
    while True:
        kwargs = {"nextToken": token} if token else {}
        page = client.list_inference_profiles(**kwargs)
        for p in page["inferenceProfileSummaries"]:
            print(f"  {p['inferenceProfileId']}")
        token = page.get("nextToken")
        if not token:
            break


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--models", nargs="+", help="check only these exact model IDs")
    parser.add_argument("--discover", action="store_true", help="also list models and profiles")
    parser.add_argument("--json", action="store_true", help="print JSON instead of a table")
    parser.add_argument(
        "--first", action="store_true", help="stop at the first working ID of each role"
    )
    args = parser.parse_args()

    if args.discover:
        discover()

    results: dict[str, Result] = {}

    def run(model_id: str) -> Result:
        if model_id not in results:
            results[model_id] = check(model_id)
        return results[model_id]

    if args.models:
        for model_id in args.models:
            run(model_id)
        roles: dict[str, str | None] = {}
    else:
        roles = {}
        for role, bases in ROLE_CANDIDATES.items():
            roles[role] = None
            for base in bases:
                for candidate in with_variants(base):
                    result = run(candidate)  # every candidate is checked and printed
                    usable = result.ok and (result.tool_use or role not in NEEDS_TOOL_USE)
                    if usable and roles[role] is None:
                        roles[role] = candidate
                    if usable and args.first:
                        break
                if roles[role] and args.first:
                    break

    if args.json:
        print(
            json.dumps({"results": [asdict(r) for r in results.values()], "roles": roles}, indent=2)
        )
    else:
        print(
            f"{'model id':<62} {'result':<6} {'toolUse':<8} {'ms':>7} {'in/out tokens':>14}  error"
        )
        for r in results.values():
            tokens = f"{r.input_tokens}/{r.output_tokens}" if r.ok else "-"
            ms = f"{r.latency_ms:.0f}" if r.latency_ms is not None else "-"
            tool = ("yes" if r.tool_use else "no") if r.ok else "-"
            print(
                f"{r.model_id:<62} {'ok' if r.ok else 'FAIL':<6} {tool:<8} {ms:>7} "
                f"{tokens:>14}  {r.error or ''}"
            )
        if roles:
            print("\nRole -> confirmed model ID")
            for role, model_id in roles.items():
                print(f"  {role:<9} {model_id or 'MISSING: tell the team lead'}")
    return 1 if roles and any(v is None for v in roles.values()) else 0


if __name__ == "__main__":
    sys.exit(main())
