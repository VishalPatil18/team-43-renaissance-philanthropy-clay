#!/usr/bin/env python3
"""Warm the package caches for every MCP server in ``toolsets/*.yaml`` (FR-15.3, FR-1.10).

Run at image build time so no network install happens at run time. Servers must be pinned:

* ``["uvx", "pkg@1.2.3", ...]`` or ``["uvx", "pkg==1.2.3", ...]`` or ``["uvx", "--from",
  "pkg==1.2.3", "cmd"]``: the package is run once with ``uvx --from pkg==1.2.3 python -c pass``,
  which fills the uv cache. At run time ``UV_OFFLINE=1 uvx pkg@1.2.3`` is served from the cache.
* ``["npx", "-y", "pkg@1.2.3", ...]``: installed globally with ``npm install -g pkg@1.2.3``
  (build the image with ``--build-arg WITH_NODE=true``).
* Anything else (``python -m ...`` for our own servers) needs no pre-install.

If there is no ``toolsets/`` directory yet the script does nothing and exits 0.
An unpinned or placeholder version (for example ``@<pinned>``) is an error.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

PINNED = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*(\[[A-Za-z0-9,._-]+\])?(==|@)\d[\w.+!-]*$")
NPM_PINNED = re.compile(r"^(@[\w.-]+/)?[\w.-]+@\d[\w.+-]*$")


class Unpinned(ValueError):
    pass


def package_spec(command: list[str]) -> tuple[str, str] | None:
    """Return ``("uvx" | "npx", pinned spec)`` for a server command, or ``None`` if none needed."""
    if not command:
        return None
    runner = Path(command[0]).name
    args = command[1:]
    if runner in ("uvx", "uv") and (runner == "uvx" or args[:1] == ["tool"]):
        args = args if runner == "uvx" else args[1:]
        if args[:1] == ["run"]:
            args = args[1:]
        if "--from" in args:
            spec = args[args.index("--from") + 1]
        else:
            spec = next((a for a in args if not a.startswith("-")), "")
        if not PINNED.match(spec):
            raise Unpinned(f"MCP server package {spec!r} is not pinned (use name@1.2.3): {command}")
        return "uvx", spec.replace("@", "==", 1)
    if runner == "npx":
        spec = next((a for a in args if not a.startswith("-")), "")
        if not NPM_PINNED.match(spec):
            raise Unpinned(f"MCP server package {spec!r} is not pinned (use name@1.2.3): {command}")
        return "npx", spec
    return None


def collect(toolsets_dir: Path) -> list[tuple[str, str]]:
    specs: list[tuple[str, str]] = []
    for path in sorted(toolsets_dir.glob("*.y*ml")):
        data: Any = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        for server in data.get("servers", []):
            found = package_spec(list(server.get("command", [])))
            if found and found not in specs:
                specs.append(found)
    return specs


def main(argv: list[str]) -> int:
    root = Path(argv[1]) if len(argv) > 1 else Path("toolsets")
    if not root.is_dir():
        print(f"No {root}/ directory yet: nothing to pre-install.")
        return 0
    try:
        specs = collect(root)
    except Unpinned as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    for kind, spec in specs:
        print(f"Pre-installing {kind} package {spec}")
        if kind == "uvx":
            cmd = ["uvx", "--from", spec, "python", "-c", "pass"]
        else:
            if shutil.which("npm") is None:
                print(
                    "ERROR: npx server found but npm is missing; build with WITH_NODE=true",
                    file=sys.stderr,
                )
                return 1
            cmd = ["npm", "install", "--global", spec]
        result = subprocess.run(cmd, check=False)
        if result.returncode != 0:
            print(f"ERROR: could not pre-install {spec}", file=sys.stderr)
            return result.returncode
    print(f"Pre-installed {len(specs)} MCP server package(s).")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
