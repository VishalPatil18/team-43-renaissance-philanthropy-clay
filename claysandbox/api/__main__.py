"""Serve the API and UI.

``python -m claysandbox.api --store <path> [--port 8765]`` serves on loopback only (DD-034).

``python -m claysandbox.api --hosted --store <path> --port 8080`` is the AWS mode (the web
service in the CDK stack): it listens on all interfaces behind the load balancer, requires the
shared login from ``CLAYSANDBOX_UI_PASSWORD``, launches every evaluation on Fargate, and keeps
the store in step with ``s3://$CLAYSANDBOX_BUCKET`` (runs and evals from any machine appear).
"""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

from .app import Hosted, create_app

log = logging.getLogger("claysandbox.api")
SYNC_SECONDS = 60


def fargate_params() -> dict[str, Any]:
    """Executor parameters from the web task's environment (set by the CDK stack)."""
    env = {
        "bucket": "CLAYSANDBOX_BUCKET",
        "cluster": "CLAYSANDBOX_CLUSTER",
        "task_definition": "CLAYSANDBOX_TASK_DEFINITION",
        "subnets": "CLAYSANDBOX_SUBNETS",
        "security_groups": "CLAYSANDBOX_SECURITY_GROUPS",
    }
    missing = [name for name in env.values() if not os.environ.get(name)]
    if missing:
        raise SystemExit(f"hosted mode needs {', '.join(missing)}")
    params: dict[str, Any] = {key: os.environ[name] for key, name in env.items()}
    params["subnets"] = params["subnets"].split(",")
    params["security_groups"] = params["security_groups"].split(",")
    params["region"] = os.environ.get("AWS_REGION", "us-west-2")
    return params


def _sync_forever(store_root: Path, bucket: str) -> None:
    """Pull new runs and eval folders from S3 now and every ``SYNC_SECONDS``."""
    from claysandbox.store.s3 import S3MirrorRunStore

    store = S3MirrorRunStore(store_root / "runs", store_root / "evals", bucket=bucket)
    while True:
        try:
            store.sync_down("runs/")  # finished run folders: new ones only
            store.sync_down("evals/", overwrite=True)  # small; reports can change
        except Exception as exc:  # noqa: BLE001  keep serving what is already here
            log.warning("S3 sync failed: %s", exc)
        time.sleep(SYNC_SECONDS)


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="API and UI over a run store.")
    ap.add_argument("--store", required=True, help="store folder holding runs/ and evals/")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--hosted", action="store_true", help="AWS mode (see module docstring)")
    args = ap.parse_args(argv)
    if not args.hosted:
        # Loopback only (DD-034); there is deliberately no --host option.
        uvicorn.run(create_app(args.store), host="127.0.0.1", port=args.port)
        return

    logging.basicConfig(level=logging.INFO)
    password = os.environ.get("CLAYSANDBOX_UI_PASSWORD", "")
    params = fargate_params()
    root = Path(args.store)
    for sub in ("runs", "evals"):
        (root / sub).mkdir(parents=True, exist_ok=True)
    threading.Thread(
        target=_sync_forever, args=(root, params["bucket"]), name="s3-sync", daemon=True
    ).start()
    app = create_app(root, hosted=Hosted(password, executor_params=params))
    # Behind the load balancer, inside the task's own network namespace.
    uvicorn.run(app, host="0.0.0.0", port=args.port, proxy_headers=True)  # noqa: S104


if __name__ == "__main__":
    main()
