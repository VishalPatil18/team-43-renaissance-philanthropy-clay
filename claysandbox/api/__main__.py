"""``python -m claysandbox.api --store <path> [--port 8765]`` serves the API and UI locally."""

from __future__ import annotations

import argparse

import uvicorn

from .app import create_app


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Read-only API and UI over a run store.")
    ap.add_argument("--store", required=True, help="store folder holding runs/ and evals/")
    ap.add_argument("--port", type=int, default=8765)
    args = ap.parse_args(argv)
    # Loopback only (DD-034); there is deliberately no --host option.
    uvicorn.run(create_app(args.store), host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
