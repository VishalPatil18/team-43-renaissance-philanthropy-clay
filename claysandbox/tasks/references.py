"""Task-reference versioning and storage (FR-13.5, FR-13.6, DD-029, DD-043, architecture §14.4).

Version: ``<template>.v<n>+sha256:<first 12 hex of sha256(canonical JSON)>``, where the canonical
JSON covers ``workflow``, ``output_reference`` and ``weights`` (keys sorted, no spaces, UTF-8).
``n`` goes up by one only when that hash changes. Rebuilding identical content returns the
existing version and writes nothing.

Files: ``<root>/<template>/<aoi>/<version>.json`` (``:`` written as ``-``). An existing file is
never overwritten, except to record the human spot-check (``record_spot_check``).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.task import REFERENCE_VERSION, ReferenceMethod, TaskReference


@dataclass
class BuildResult:
    """What a reference builder returns (``tasks/builders/<name>.py``, function ``build``)."""

    output_reference: dict[str, Any]
    inputs: dict[str, Any]
    method: ReferenceMethod = "script"
    notes: list[str] = field(default_factory=list)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def content_hash(workflow: dict[str, Any], output_reference: Any, weights: dict[str, float]) -> str:
    """First 12 hex digits of the sha256 of the hashed content."""
    payload = canonical_json(
        {"workflow": workflow, "output_reference": output_reference, "weights": weights}
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:12]


def reference_hash(ref: TaskReference) -> str:
    return content_hash(ref.workflow.model_dump(mode="json"), ref.output_reference, ref.weights)


def parse_version(version: str) -> tuple[str, int, str]:
    match = REFERENCE_VERSION.match(version)
    if not match:
        raise ConfigError(f"not a task-reference version: {version!r}")
    return match.group(1), int(match.group(2)), match.group(3)


def file_name(version: str) -> str:
    """``T1.v1+sha256:abc`` → ``T1.v1+sha256-abc.json`` (no ``:`` in file names, for Windows)."""
    return version.replace(":", "-") + ".json"


class ReferenceStore:
    """Reads and writes references under one root directory (default ``tasks/references``)."""

    def __init__(self, root: Path | str) -> None:
        self.root = Path(root)

    def _dir(self, template: str, aoi: str) -> Path:
        return self.root / template / aoi

    def versions(self, template: str, aoi: str) -> list[TaskReference]:
        """All stored versions of one instance, oldest first."""
        directory = self._dir(template, aoi)
        if not directory.is_dir():
            return []
        refs = [
            TaskReference.model_validate_json(p.read_text(encoding="utf-8"))
            for p in directory.glob("*.json")
        ]
        return sorted(refs, key=lambda r: parse_version(r.version)[1])

    def latest(self, template: str, aoi: str) -> TaskReference:
        refs = self.versions(template, aoi)
        if not refs:
            raise ConfigError(
                f"no task reference for {template}@{aoi}; build it with "
                f"`python -m claysandbox.tasks build --template {template} --aoi {aoi}`",
                kind="missing_reference",
            )
        return refs[-1]

    def get(self, template: str, aoi: str, version: str) -> TaskReference:
        for ref in self.versions(template, aoi):
            if ref.version == version:
                return ref
        raise ConfigError(f"no task reference {version} for {template}@{aoi}",
                          kind="missing_reference")

    def next_version(
        self, template: str, aoi: str, digest: str
    ) -> tuple[str, TaskReference | None]:
        """The version for content with ``digest``, and the stored reference if it exists."""
        refs = self.versions(template, aoi)
        for ref in refs:
            if parse_version(ref.version)[2] == digest:
                return ref.version, ref
        n = max((parse_version(r.version)[1] for r in refs), default=0) + 1
        return f"{template}.v{n}+sha256:{digest}", None

    def record_spot_check(
        self,
        template: str,
        aoi: str,
        version: str,
        checked_by: str,
        checked_at: datetime | None = None,
        note: str | None = None,
    ) -> TaskReference:
        """Record the human spot-check (FR-13.5) on an existing version.

        This is the one change allowed to a stored reference: ``checked_by``, ``checked_at`` and a
        note. None of them is part of the version hash, so the version stays valid.
        """
        ref = self.get(template, aoi, version)
        notes = list(ref.notes) + ([f"spot-check: {note}"] if note else [])
        updated = ref.model_copy(
            update={
                "checked_by": checked_by,
                "checked_at": checked_at or datetime.now(UTC),
                "notes": notes,
            }
        )
        if reference_hash(updated) != reference_hash(ref):
            raise ConfigError("spot-check must not change hashed content")
        path = self._dir(template, aoi) / file_name(version)
        path.write_text(_dump(updated), encoding="utf-8")
        return updated

    def save(self, ref: TaskReference) -> Path:
        """Write a new version. Refuses to overwrite and checks the hash matches the content."""
        template, _, digest = parse_version(ref.version)
        if template != ref.template:
            raise ConfigError(f"version {ref.version} does not belong to template {ref.template}")
        if reference_hash(ref) != digest:
            raise ConfigError(f"version {ref.version} does not match the reference content")
        path = self._dir(ref.template, ref.aoi_id) / file_name(ref.version)
        if path.exists():
            raise ConfigError(f"refusing to overwrite existing reference {path}")
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("x", encoding="utf-8") as handle:
            handle.write(_dump(ref))
        return path


def _dump(ref: TaskReference) -> str:
    return json.dumps(ref.model_dump(mode="json"), indent=2, ensure_ascii=False) + "\n"
