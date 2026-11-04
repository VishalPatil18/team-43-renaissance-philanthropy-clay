"""Component registry (arch §7.6).

PLACEHOLDER copied verbatim from the architecture sketch so WS3 code can
register its components before the scaffold lands. The owner is WS5 (5th
member): if their registry merges first, delete this file in favour of theirs.
"""

from __future__ import annotations

from typing import Any

_REGISTRY: dict[tuple[str, str], type] = {}


def register(kind: str, name: str):
    def deco(cls):
        _REGISTRY[(kind, name)] = cls
        return cls

    return deco


def resolve(kind: str, name: str) -> type:
    try:
        return _REGISTRY[(kind, name)]
    except KeyError:
        known = sorted(n for k, n in _REGISTRY if k == kind)
        raise KeyError(f"no {kind} named {name!r}; registered: {known}") from None


def list_components(kind: str | None = None) -> list[dict[str, Any]]:
    out = []
    for (k, n), cls in sorted(_REGISTRY.items()):
        if kind and k != kind:
            continue
        params = getattr(cls, "Params", None)
        out.append(
            {
                "kind": k,
                "name": n,
                "version": getattr(cls, "version", ""),
                "params_schema": params.model_json_schema() if params else {},
            }
        )
    return out
