"""Environment scrubbing for MCP server processes (FR-1.9, DD-034, architecture §18).

A server sees only:

1. the base allowlist (``PATH``, ``HOME``, locale, ``TMPDIR`` and the uv / npm cache settings that
   ``uvx`` and ``npx`` need to find already-installed packages),
2. its own ``env:`` entries from the tool-set file,
3. the AWS variables, only when the server entry says ``needs_aws: true``.

The MCP Python SDK also passes ``HOME``, ``LOGNAME``, ``PATH``, ``SHELL``, ``TERM`` and ``USER`` to
every server it starts. None of these hold secrets.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from pathlib import Path

from claysandbox.contracts.tools import EnvPolicy, ServerDef

BASE_ALLOW: tuple[str, ...] = (
    "PATH",
    "HOME",
    "LANG",
    "LC_ALL",
    "TMPDIR",
    # uv: where uvx finds cached tools and Python builds (and offline mode in Docker)
    "UV_CACHE_DIR",
    "UV_TOOL_DIR",
    "UV_TOOL_BIN_DIR",
    "UV_PYTHON_INSTALL_DIR",
    "UV_OFFLINE",
    "XDG_CACHE_HOME",
    "XDG_DATA_HOME",
    # npm: where npx finds cached packages (Node servers such as the OSM server)
    "NPM_CONFIG_CACHE",
    "npm_config_cache",
    "NPM_CONFIG_PREFIX",
    "npm_config_prefix",
)

AWS_ALLOW: tuple[str, ...] = (
    "AWS_PROFILE",
    "AWS_REGION",
    "AWS_DEFAULT_REGION",
    "AWS_ACCESS_KEY_ID",
    "AWS_SECRET_ACCESS_KEY",
    "AWS_SESSION_TOKEN",
    "AWS_CONTAINER_CREDENTIALS_RELATIVE_URI",  # Fargate task role
    "AWS_CONTAINER_CREDENTIALS_FULL_URI",
    "AWS_CONTAINER_AUTHORIZATION_TOKEN",
    "AWS_CONFIG_FILE",  # the ~/.aws path, if moved
    "AWS_SHARED_CREDENTIALS_FILE",
)


def default_policy() -> EnvPolicy:
    return EnvPolicy(allow=list(BASE_ALLOW), aws_allow=list(AWS_ALLOW))


def build_env(
    server: ServerDef,
    policy: EnvPolicy | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """The exact environment for one server process."""
    policy = policy or default_policy()
    source = os.environ if environ is None else environ
    env = {k: source[k] for k in policy.allow if k in source}
    if server.needs_aws:
        env.update({k: source[k] for k in policy.aws_allow if k in source})
        home = source.get("HOME")
        if home and "AWS_CONFIG_FILE" not in env and (Path(home) / ".aws").is_dir():
            # Point the SDK at ~/.aws explicitly (profiles, SSO cache) even if HOME is changed.
            env["AWS_CONFIG_FILE"] = str(Path(home) / ".aws" / "config")
            env["AWS_SHARED_CREDENTIALS_FILE"] = str(Path(home) / ".aws" / "credentials")
    env.update(server.env)
    return env
