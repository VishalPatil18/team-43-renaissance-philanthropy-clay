"""Plugin registry (architecture §7.6). Everything that varies is registered by (kind, name)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, TypeVar

from .errors import ConfigError

T = TypeVar("T", bound=type)

_REGISTRY: dict[tuple[str, str], type] = {}


def register(kind: str, name: str) -> Callable[[T], T]:
    """Class decorator that registers ``cls`` under ``(kind, name)``."""

    def deco(cls: T) -> T:
        _REGISTRY[(kind, name)] = cls
        return cls

    return deco


def resolve(kind: str, name: str) -> type:
    """Return the class registered under ``(kind, name)``."""
    try:
        return _REGISTRY[(kind, name)]
    except KeyError:
        known = sorted(n for (k, n) in _REGISTRY if k == kind)
        raise ConfigError(
            f"No {kind} named {name!r} is registered. Known: {known}", kind="unknown_component"
        ) from None


def list_components(kind: str | None = None) -> list[dict[str, Any]]:
    """Describe registered components: kind, name, version and parameter JSON Schema."""
    out: list[dict[str, Any]] = []
    for (k, n), cls in sorted(_REGISTRY.items()):
        if kind is not None and k != kind:
            continue
        params_model = getattr(cls, "Params", None)
        schema = params_model.model_json_schema() if params_model is not None else {}
        out.append({"kind": k, "name": n, "version": getattr(cls, "version", ""), "params": schema})
    return out
