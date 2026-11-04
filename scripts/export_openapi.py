#!/usr/bin/env python3
"""Write the API's OpenAPI document to ``api/openapi.json`` (FR-12.5); ``--check`` fails if stale.

Usage::

    uv run python scripts/export_openapi.py [--check]
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

from claysandbox.api.app import create_app

OUT = Path(__file__).resolve().parents[1] / "api" / "openapi.json"


def render() -> str:
    with tempfile.TemporaryDirectory() as tmp:  # the schema does not depend on store contents
        (Path(tmp) / "runs").mkdir()
        return json.dumps(create_app(tmp).openapi(), indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--check", action="store_true", help="exit 1 if api/openapi.json is stale")
    args = ap.parse_args(argv)
    text = render()
    if args.check:
        if not OUT.is_file() or OUT.read_text() != text:
            print(f"{OUT} is stale; run scripts/export_openapi.py", file=sys.stderr)
            return 1
        return 0
    OUT.parent.mkdir(exist_ok=True)
    OUT.write_text(text)
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
