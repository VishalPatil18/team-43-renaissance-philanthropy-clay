"""ID helpers (DD-043). IDs are ULIDs so they sort by creation time."""

from __future__ import annotations

from ulid import ULID


def new_id() -> str:
    """Return a new ULID string."""
    return str(ULID())
