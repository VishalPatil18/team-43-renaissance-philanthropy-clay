"""Placeholder substitution for prompts and workflow values (architecture §14, §18).

Only ``{name}`` and ``{aoi.field}`` placeholders are recognised, matched by a regular expression.
Nothing is evaluated: there is no attribute access on Python objects, no indexing and no format
spec. Any other brace text, such as the JSON example ``{"items": [...]}`` in a prompt, is left as
it is. An unknown placeholder is an error, so typos fail when the template loads.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping
from types import MappingProxyType
from typing import Any

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.task import AOI

PLACEHOLDER = re.compile(r"\{([a-z_][a-z0-9_]*(?:\.[a-z_][a-z0-9_]*)?)\}")

AOI_FIELDS = ("id", "name", "state", "state_code", "fips", "bbox", "geometry")


def namespace(aoi: AOI, params: Mapping[str, Any]) -> Mapping[str, Any]:
    """The read-only values a template may refer to: ``aoi.<field>`` and its parameters."""
    values: dict[str, Any] = {f"aoi.{f}": getattr(aoi, f) for f in AOI_FIELDS}
    for key, value in params.items():
        if key == "aoi" or "." in key:
            raise ConfigError(f"parameter name {key!r} is reserved or invalid")
        values[key] = value
    return MappingProxyType(values)


def _as_text(value: Any) -> str:
    return value if isinstance(value, str) else json.dumps(value)


def render_text(text: str, ns: Mapping[str, Any]) -> str:
    """Substitute every placeholder in ``text``. Non-string values are written as JSON."""

    def repl(match: re.Match[str]) -> str:
        key = match.group(1)
        if key not in ns:
            raise ConfigError(f"unknown placeholder {{{key}}} (known: {sorted(ns)})")
        return _as_text(ns[key])

    return PLACEHOLDER.sub(repl, text)


def render_value(value: Any, ns: Mapping[str, Any]) -> Any:
    """Render placeholders inside any JSON-like value.

    A string that is exactly one placeholder becomes the typed value (``"{year}"`` → ``2022``);
    other strings are rendered as text; lists and dicts are walked. Dict keys are not rendered.
    """
    if isinstance(value, str):
        whole = PLACEHOLDER.fullmatch(value)
        if whole:
            key = whole.group(1)
            if key not in ns:
                raise ConfigError(f"unknown placeholder {value} (known: {sorted(ns)})")
            return ns[key]
        return render_text(value, ns)
    if isinstance(value, list):
        return [render_value(v, ns) for v in value]
    if isinstance(value, dict):
        return {k: render_value(v, ns) for k, v in value.items()}
    return value
