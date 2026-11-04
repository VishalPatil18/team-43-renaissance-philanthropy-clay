"""Environment scrubbing for MCP servers (FR-1.9, DD-034)."""

from __future__ import annotations

import sys
from pathlib import Path

from claysandbox.contracts.fakes.mcp_fixture_server import FIXTURE_SERVER_PATH
from claysandbox.contracts.tools import ServerDef, ToolSetDef
from claysandbox.tools.env import AWS_ALLOW, BASE_ALLOW, build_env, default_policy
from claysandbox.tools.launcher import McpStdioToolSession

FIXTURE = FIXTURE_SERVER_PATH

PARENT = {
    "PATH": "/usr/bin",
    "HOME": "/home/u",
    "LANG": "C.UTF-8",
    "SECRET_X": "do-not-leak",
    "GITHUB_TOKEN": "ghp_xxx",
    "AWS_ACCESS_KEY_ID": "AKIAEXAMPLE",
    "AWS_SECRET_ACCESS_KEY": "secret",
    "AWS_SESSION_TOKEN": "token",
    "AWS_REGION": "us-west-2",
    "AWS_PROFILE": "sandbox",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI": "/v2/credentials/abc",
}


def server(needs_aws: bool, env: dict[str, str] | None = None) -> ServerDef:
    return ServerDef(name="s", command=["python", "x.py"], needs_aws=needs_aws, env=env or {})


def test_unknown_variables_are_never_passed() -> None:
    for needs_aws in (False, True):
        env = build_env(server(needs_aws), environ=PARENT)
        assert "SECRET_X" not in env and "GITHUB_TOKEN" not in env


def test_aws_variables_only_reach_servers_that_need_aws() -> None:
    plain = build_env(server(False), environ=PARENT)
    assert not any(k.startswith("AWS_") for k in plain)
    aws = build_env(server(True), environ=PARENT)
    for key in ("AWS_ACCESS_KEY_ID", "AWS_SECRET_ACCESS_KEY", "AWS_SESSION_TOKEN", "AWS_REGION",
                "AWS_PROFILE", "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI"):
        assert aws[key] == PARENT[key]


def test_base_variables_and_server_env_entries_are_passed() -> None:
    env = build_env(server(False, {"FASTMCP_LOG_LEVEL": "ERROR"}), environ=PARENT)
    assert env == {"PATH": "/usr/bin", "HOME": "/home/u", "LANG": "C.UTF-8",
                   "FASTMCP_LOG_LEVEL": "ERROR"}


def test_aws_config_dir_is_pointed_to_explicitly(tmp_path: Path) -> None:
    (tmp_path / ".aws").mkdir()
    env = build_env(server(True), environ={"HOME": str(tmp_path)})
    assert env["AWS_CONFIG_FILE"] == str(tmp_path / ".aws" / "config")
    assert env["AWS_SHARED_CREDENTIALS_FILE"] == str(tmp_path / ".aws" / "credentials")
    assert "AWS_CONFIG_FILE" not in build_env(server(False), environ={"HOME": str(tmp_path)})


def test_default_policy_lists() -> None:
    policy = default_policy()
    assert policy.allow == list(BASE_ALLOW) and policy.aws_allow == list(AWS_ALLOW)


def test_real_server_process_sees_only_the_scrubbed_environment(
    tmp_path: Path, monkeypatch: object
) -> None:
    parent = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path), "SECRET_X": "do-not-leak",
              "AWS_SECRET_ACCESS_KEY": "secret"}
    ts = ToolSetDef(
        name="TX",
        servers=[
            ServerDef(name="plain", command=[sys.executable, FIXTURE], env={"MODE": "test"}),
            ServerDef(name="aws", command=[sys.executable, FIXTURE], needs_aws=True),
        ],
    )
    with McpStdioToolSession(ts, log_dir=tmp_path, environ=parent) as s:
        def get(srv: str, name: str) -> str:
            return s.call_blocking(srv, "getenv", {"name": name}, 10).text

        assert get("plain", "SECRET_X") == "<unset>"
        assert get("aws", "SECRET_X") == "<unset>"
        assert get("plain", "AWS_SECRET_ACCESS_KEY") == "<unset>"
        assert get("aws", "AWS_SECRET_ACCESS_KEY") == "secret"
        assert get("plain", "MODE") == "test"
