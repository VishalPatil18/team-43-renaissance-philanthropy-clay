"""Local store with an S3 mirror (SHI-R2-03, DD-022, arch §13.4). Owner: WS3.

``local+s3`` is the local store plus three operations, so it honours the whole ``RunStore``
contract and its conformance suite unchanged:

* ``mirror_run(run_id)``  upload a *finished* run folder to ``s3://<bucket>/runs/<run_id>/``.
* ``mirror_eval(eval_id)`` upload an eval folder to ``s3://<bucket>/evals/<eval_id>/``.
* ``sync_down(prefix)``   pull Fargate-written runs (or evals) into the local roots, before
                          scoring and statistics.

The same immutability rules hold remotely: ``manifest.json``, the trace files and
``spec.yaml`` are never overwritten once they exist in S3, and sync-down never replaces a
local protected file. Keys that come back from S3 are untrusted: every one is checked so
it cannot write outside the local root.

The bucket is the explicit ``bucket`` parameter, else ``BucketName`` in ``infra/outputs.json``
(written by WS1's ``write_outputs.py``), else ``$CLAYSANDBOX_BUCKET``. The S3 client is
injected for tests; otherwise a boto3 client is created on first use.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from pathlib import Path, PurePosixPath
from typing import Any

from botocore.exceptions import ClientError
from pydantic import BaseModel

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.registry import register
from claysandbox.contracts.store import TERMINAL_STATES, StoreWriteRefused

from .local import PROTECTED, LocalRunStore, _safe_name

log = logging.getLogger("claysandbox.store")

DEFAULT_OUTPUTS_PATH = Path(__file__).resolve().parents[2] / "infra" / "outputs.json"
RUNS_PREFIX = "runs/"
EVALS_PREFIX = "evals/"
#: Never replaced once they exist, locally or in S3 (arch §13.2).
IMMUTABLE_NAMES = (*PROTECTED, "spec.yaml")
_MISSING_CODES = {"404", "NoSuchKey", "NotFound"}


def _is_leftover(path: Path) -> bool:
    """Atomic-write temp files (``.name.xxxx``) and blob temp files (``<sha>.tmp<thread>``)."""
    return path.name.startswith(".") or ".tmp" in path.suffix


@register("store", "local+s3")
class S3MirrorRunStore(LocalRunStore):
    name = "local+s3"
    version = "1"

    class Params(BaseModel):
        root: str = "./runs"
        evals_root: str = "./evals"
        read_roots: list[str] = []
        bucket: str | None = None
        outputs_path: str | None = None
        region: str = "us-west-2"

    def __init__(
        self,
        root: str | Path = "./runs",
        evals_root: str | Path = "./evals",
        read_roots: list[str | Path] | None = None,
        manifest_model: type[BaseModel] | None = None,
        *,
        bucket: str | None = None,
        outputs_path: str | Path | None = None,
        region: str = "us-west-2",
        client: Any = None,
    ):
        super().__init__(root, evals_root, read_roots, manifest_model)
        self.evals_root.mkdir(parents=True, exist_ok=True)
        self.region = region
        self._client = client
        self._explicit_bucket = bucket
        self._outputs_path = Path(outputs_path) if outputs_path else DEFAULT_OUTPUTS_PATH

    # ------------------------------------------------------------ configuration
    @property
    def bucket(self) -> str:
        name = self._explicit_bucket
        if not name and self._outputs_path.exists():
            name = json.loads(self._outputs_path.read_text()).get("BucketName")
        name = name or os.environ.get("CLAYSANDBOX_BUCKET")
        if not name:
            raise ConfigError(
                "no S3 bucket: set the store's 'bucket', or write infra/outputs.json, "
                "or set CLAYSANDBOX_BUCKET",
                kind="missing_bucket",
            )
        return name

    @property
    def client(self) -> Any:
        if self._client is None:
            import boto3

            self._client = boto3.client("s3", region_name=self.region)
        return self._client

    # ------------------------------------------------------------ upload
    def mirror_run(self, run_id: str) -> dict[str, Any]:
        """Upload a finished run folder. Refuses a run that is still being written."""
        folder = self.root / _safe_name(run_id)
        if not folder.is_dir():
            raise FileNotFoundError(f"run {run_id} is not in the writable root {self.root}")
        status = self.read_status(run_id)
        if status is None or status.state not in TERMINAL_STATES:
            raise StoreWriteRefused(
                f"run {run_id} is not finished ({status.state if status else 'no status'}); "
                "mirror it after run_end"
            )
        return self._upload_folder(folder, f"{RUNS_PREFIX}{run_id}/")

    def mirror_eval(self, eval_id: str) -> dict[str, Any]:
        """Upload an eval folder (spec, plan, estimate, eval report)."""
        folder = self.evals_root / _safe_name(eval_id)
        if not folder.is_dir():
            raise FileNotFoundError(f"eval {eval_id} is not in {self.evals_root}")
        return self._upload_folder(folder, f"{EVALS_PREFIX}{eval_id}/")

    def _upload_folder(self, folder: Path, prefix: str) -> dict[str, Any]:
        bucket, uploaded, skipped = self.bucket, [], []
        for path in sorted(p for p in folder.rglob("*") if p.is_file() and not _is_leftover(p)):
            key = prefix + path.relative_to(folder).as_posix()
            immutable = path.name in IMMUTABLE_NAMES or path.parent.name == "blobs"
            if immutable and self._exists(bucket, key):
                skipped.append(key)  # already there: immutable, never overwritten
                continue
            self.client.upload_file(str(path), bucket, key)
            uploaded.append(key)
        return {"bucket": bucket, "prefix": prefix, "uploaded": uploaded, "skipped": skipped}

    def _exists(self, bucket: str, key: str) -> bool:
        try:
            self.client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            if str(e.response.get("Error", {}).get("Code")) in _MISSING_CODES:
                return False
            raise

    # ------------------------------------------------------------ download
    def sync_down(self, prefix: str = RUNS_PREFIX, *, overwrite: bool = False) -> list[Path]:
        """Pull objects under ``prefix`` (``runs/``, ``runs/<id>/``, ``evals/``, ...) to disk.

        Protected files that already exist locally are never replaced. Other files (status,
        summary, reports) are refreshed only when ``overwrite`` is true, and a terminal
        ``status.json`` is never replaced. Returns the paths written.
        """
        if prefix.startswith(RUNS_PREFIX):
            base, root_prefix = self.root, RUNS_PREFIX
        elif prefix.startswith(EVALS_PREFIX):
            base, root_prefix = self.evals_root, EVALS_PREFIX
        else:
            raise ValueError(f"prefix must start with {RUNS_PREFIX!r} or {EVALS_PREFIX!r}")
        bucket, written, touched_runs = self.bucket, [], set()
        for key in self._list_keys(bucket, prefix):
            dest = self._local_path(base, root_prefix, key)
            if dest is None:
                continue
            if dest.exists() and not self._may_replace(dest, overwrite):
                continue
            dest.parent.mkdir(parents=True, exist_ok=True)
            fd, tmp = tempfile.mkstemp(dir=dest.parent, prefix=f".{dest.name}.")
            os.close(fd)
            try:
                self.client.download_file(bucket, key, tmp)
                os.replace(tmp, dest)
            except BaseException:
                Path(tmp).unlink(missing_ok=True)
                raise
            written.append(dest)
            if base is self.root:
                touched_runs.add(dest.relative_to(base).parts[0])
        for run_id in touched_runs:  # a finished run synced down is locked like a local one
            status = self.read_status(run_id)
            if status is not None and status.state in TERMINAL_STATES:
                self._lock_files(self.root / run_id)
        return written

    def _may_replace(self, dest: Path, overwrite: bool) -> bool:
        if dest.name in IMMUTABLE_NAMES or dest.parent.name == "blobs":
            return False
        if dest.name == "status.json":
            run_id = dest.parent.name
            status = self.read_status(run_id)
            if status is not None and status.state in TERMINAL_STATES:
                return False
        return overwrite

    def _list_keys(self, bucket: str, prefix: str) -> list[str]:
        keys: list[str] = []
        token: str | None = None
        while True:
            kwargs: dict[str, Any] = {"Bucket": bucket, "Prefix": prefix}
            if token:
                kwargs["ContinuationToken"] = token
            page = self.client.list_objects_v2(**kwargs)
            keys += [obj["Key"] for obj in page.get("Contents", [])]
            if not page.get("IsTruncated"):
                return keys
            token = page["NextContinuationToken"]

    @staticmethod
    def _local_path(base: Path, root_prefix: str, key: str) -> Path | None:
        """Map ``runs/<id>/<rel>`` to ``base/<id>/<rel>``; None for keys that are not files or
        that try to leave the root (S3 keys are untrusted input)."""
        rel = key[len(root_prefix) :]
        if not rel or rel.endswith("/"):
            return None
        parts = PurePosixPath(rel).parts
        if len(parts) < 2 or any(p in ("", ".", "..") or "\\" in p for p in parts):
            log.warning("ignoring unsafe or malformed S3 key", extra={"key": key})
            return None
        try:
            _safe_name(parts[0])
        except ValueError:
            log.warning("ignoring S3 key with an unsafe id", extra={"key": key})
            return None
        dest = base.joinpath(*parts)
        if base.resolve() not in dest.resolve().parents:
            log.warning("ignoring S3 key outside the local root", extra={"key": key})
            return None
        return dest
