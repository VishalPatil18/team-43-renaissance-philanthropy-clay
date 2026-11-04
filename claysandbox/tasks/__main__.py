"""``python -m claysandbox.tasks`` until the ``clay-sandbox tasks`` CLI is wired (WS5).

    python -m claysandbox.tasks list
    python -m claysandbox.tasks build --template T1 [--aoi us-ca-kern]
"""

from __future__ import annotations

import argparse
import sys

from claysandbox.contracts.errors import ConfigError
from claysandbox.tasks.library import FileTaskLibrary


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m claysandbox.tasks")
    parser.add_argument("--root", help="task library directory (default: tasks/ in the repo)")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list task instances and their latest reference version")
    build = sub.add_parser("build", help="build task references")
    build.add_argument("--template", required=True)
    build.add_argument("--aoi", help="one AOI id (default: every AOI)")
    args = parser.parse_args(argv)

    try:
        library = FileTaskLibrary(args.root)
        if args.command == "list":
            for inst in library.instances():
                try:
                    version = library.get_reference(inst.id).version
                except ConfigError:
                    version = "(no reference yet)"
                print(f"{inst.id:<28} {version}")
            return 0
        for ref in library.build_references(args.template, args.aoi):
            print(f"{ref.instance_id:<28} {ref.version}  built {ref.built_at:%Y-%m-%dT%H:%M:%SZ}")
        return 0
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
