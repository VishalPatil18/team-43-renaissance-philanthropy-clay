"""Tool-set loading and registration (architecture §14.3, FR-1.10, FR-4.10).

Tool sets are YAML files in ``toolsets/``. ``register_toolsets(dir)`` validates every file and
registers each tool set under registry kind ``toolset``, so ``resolve("toolset", "T1")`` gives a
class whose instances open that tool set::

    cls = resolve("toolset", "T1")
    session = cls().open_blocking()          # a live McpStdioToolSession

Each registered class carries ``definition`` (the ``ToolSetDef``) and ``version`` (the first 12
hex digits of the sha256 of the YAML file), which the run manifest records.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any, ClassVar

import yaml
from pydantic import BaseModel, ValidationError

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.registry import register
from claysandbox.contracts.tools import EnvPolicy, ServerDef, ToolSetDef

TOOLSET_KIND = "toolset"

# Pinned package specs: the same rules as the Docker pre-install step (docker/preinstall_mcp.py)
_PY_PINNED = re.compile(
    r"^(?P<pkg>[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?)(==|@)(?P<ver>\d[\w.+!-]*)$"
)
_NPM_PINNED = re.compile(r"^(?P<pkg>(@[\w.-]+/)?[\w.-]+)@(?P<ver>\d[\w.+-]*)$")
_LOCAL_RUNNER = re.compile(r"^python(3(\.[0-9]+)?)?$")


def package_of(server: ServerDef) -> tuple[str | None, str | None]:
    """``(package, version)`` from a server command, or ``(None, None)`` for our own servers.

    Raises ``ConfigError`` if a ``uvx`` or ``npx`` command does not pin its version.
    """
    runner = Path(server.command[0]).name
    args = server.command[1:]
    if runner == "uvx":
        spec = args[args.index("--from") + 1] if "--from" in args else _first_positional(args)
        match = _PY_PINNED.match(spec)
    elif runner == "npx":
        spec = _first_positional(args)
        match = _NPM_PINNED.match(spec)
    elif _LOCAL_RUNNER.match(runner):
        return None, None  # our own servers, e.g. python -m clay_embeddings
    elif runner == "false":
        return None, None  # a command that always fails, for the faulty test tool set
    else:
        raise ConfigError(
            f"server {server.name!r}: unsupported runner {runner!r} (use uvx, npx or python)"
        )
    if not match:
        raise ConfigError(
            f"server {server.name!r}: package {spec!r} is not pinned (use name@1.2.3)",
            kind="unpinned_server",
        )
    return match.group("pkg"), match.group("ver")


def _first_positional(args: list[str]) -> str:
    return next((a for a in args if not a.startswith("-")), "")


def default_toolsets_dir() -> Path:
    """``toolsets/`` at the repository root (two levels above this package)."""
    return Path(__file__).resolve().parents[2] / "toolsets"


def load_toolset(path: Path) -> ToolSetDef:
    """Read and validate one tool-set file. The file name must equal the tool-set name."""
    try:
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        definition = ToolSetDef.model_validate(data)
    except (yaml.YAMLError, ValidationError) as exc:
        raise ConfigError(f"invalid tool set {path}: {exc}", kind="invalid_toolset") from exc
    if definition.name != path.stem:
        raise ConfigError(f"{path}: name {definition.name!r} must match the file name")
    for server in definition.servers:
        package_of(server)  # raises if unpinned
    return definition


def load_toolsets(directory: Path | str) -> dict[str, ToolSetDef]:
    root = Path(directory)
    return {p.stem: load_toolset(p) for p in sorted(root.glob("*.yaml"))}


def file_version(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:12]


class RegisteredToolSet:
    """Base for the per-tool-set classes that ``register_toolsets`` creates."""

    kind: ClassVar[str] = TOOLSET_KIND
    name: ClassVar[str] = ""
    version: ClassVar[str] = ""
    definition: ClassVar[ToolSetDef]
    source_path: ClassVar[str] = ""

    class Params(BaseModel):
        """Tool sets take no parameters: everything is in the YAML file."""

    def __init__(self, params: dict[str, Any] | None = None) -> None:
        self.params = self.Params.model_validate(params or {})

    def open_blocking(self, env_policy: EnvPolicy | None = None, **kwargs: Any) -> Any:
        from claysandbox.tools.launcher import McpStdioToolSession

        session = McpStdioToolSession(self.definition, env_policy, **kwargs)
        session.start()
        return session


def register_toolsets(
    directory: Path | str | None = None,
) -> dict[str, type[RegisteredToolSet]]:
    """Validate every ``*.yaml`` in ``directory`` (default ``toolsets/``) and register it."""
    root = Path(directory) if directory is not None else default_toolsets_dir()
    if not root.is_dir():
        raise ConfigError(f"tool-set directory {root} does not exist")
    out: dict[str, type[RegisteredToolSet]] = {}
    for path in sorted(root.glob("*.yaml")):
        definition = load_toolset(path)
        cls = type(
            f"ToolSet_{re.sub(r'[^A-Za-z0-9_]', '_', definition.name)}",
            (RegisteredToolSet,),
            {
                "name": definition.name,
                "version": file_version(path),
                "definition": definition,
                "source_path": str(path),
                "__doc__": definition.description or f"Tool set {definition.name}",
            },
        )
        register(TOOLSET_KIND, definition.name)(cls)
        out[definition.name] = cls
    return out
