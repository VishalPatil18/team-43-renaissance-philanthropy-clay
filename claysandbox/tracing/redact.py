"""Secret redaction for trace events (FR-2.10, arch §18). Owner: WS3.

Applied by the event sink to every event before any tracer sees it, so no
tracer (JSONL, OTel, tee) can write a secret. Covers: AWS access key IDs,
secret keys that follow a secret-looking key, Authorization / Bearer headers,
session tokens, and the values of environment variables whose names contain
SECRET, TOKEN, PASSWORD or KEY.
"""

from __future__ import annotations

import os
import re
from typing import Any

REDACTED = "<redacted>"

_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"),  # AWS access key IDs
    re.compile(
        r"(?i)(aws_secret_access_key|secret_access_key|secretaccesskey)(\W{0,3})[A-Za-z0-9/+=]{40}"
    ),
    re.compile(
        r"(?i)(aws_session_token|x-amz-security-token|sessiontoken)(\W{0,3})[A-Za-z0-9/+=%]{16,}"
    ),
    re.compile(r"(?i)(authorization\s*:\s*)(?:[A-Za-z]+\s+)?[^\s,;\"']+"),
    re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=-]{8,}"),
]
_SECRET_KEY_NAME = re.compile(
    r"(?i)(secret|token|password|passwd|api[_-]?key|access[_-]?key|authorization|credential)"
)
_ENV_NAME = re.compile(r"(?i)(SECRET|TOKEN|PASSWORD|KEY)")
_MIN_ENV_SECRET_LEN = 8

# Fields of a serialised event that can carry free text from the agent, tools or errors.
REDACTED_FIELDS = (
    "args",
    "result_preview",
    "text_preview",
    "tool_use_requests",
    "output",
    "error",
    "totals",
)


def _env_secrets() -> list[str]:
    vals = [
        v
        for k, v in os.environ.items()
        if _ENV_NAME.search(k) and v and len(v) >= _MIN_ENV_SECRET_LEN
    ]
    return sorted(
        set(vals), key=len, reverse=True
    )  # longest first, so substrings don't win


def redact_text(text: str, env_secrets: list[str] | None = None) -> str:
    for secret in env_secrets if env_secrets is not None else _env_secrets():
        if secret in text:
            text = text.replace(secret, REDACTED)
    for pat in _PATTERNS:
        if pat.groups >= 2:
            text = pat.sub(lambda m: m.group(1) + m.group(2) + REDACTED, text)
        elif pat.groups == 1:
            text = pat.sub(lambda m: m.group(1) + REDACTED, text)
        else:
            text = pat.sub(REDACTED, text)
    return text


def redact_value(
    value: Any, env_secrets: list[str] | None = None, key: str | None = None
) -> Any:
    """Recursively redact strings. A value under a secret-looking key is replaced whole."""
    env = env_secrets if env_secrets is not None else _env_secrets()
    if (
        key is not None
        and _SECRET_KEY_NAME.search(key)
        and isinstance(value, (str, int, float))
        and value != ""
    ):
        return REDACTED
    if isinstance(value, str):
        return redact_text(value, env)
    if isinstance(value, dict):
        return {k: redact_value(v, env, str(k)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact_value(v, env) for v in value]
    return value


def redact_event_dict(data: dict) -> dict:
    """Redact the free-text fields of a serialised event (ids, types and numbers untouched)."""
    env = _env_secrets()
    out = dict(data)
    for f in REDACTED_FIELDS:
        if f in out and out[f] is not None:
            if f == "error" and isinstance(out[f], dict):
                err = dict(out[f])
                err["message"] = redact_text(str(err.get("message", "")), env)
                out[f] = err
            else:
                out[f] = redact_value(out[f], env)
    return out
