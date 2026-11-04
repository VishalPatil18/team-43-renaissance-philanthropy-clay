"""Exceptions shared across components (architecture §9.3).

Owner: WS1 (Prithwish).

* ``GuardStopped``: a budget or loop guard ended the run. Harnesses must never swallow it.
* ``InfraError``: Bedrock or the network failed after SDK retries. The executor may retry the run.
* ``ConfigError``: the spec or credentials are wrong. Retrying will not help.
"""

from __future__ import annotations

from typing import Literal

ErrorSource = Literal["agent", "tool", "budget", "infra"]


class SandboxError(Exception):
    """Base class for sandbox errors."""


class GuardStopped(SandboxError):
    """A guard stopped the run. ``source``/``kind`` follow the taxonomy in srs §12.4."""

    def __init__(
        self,
        limit: Literal["max_steps", "max_tokens", "max_usd", "max_seconds", "loop"],
        limit_value: float,
        observed_value: float,
        message: str | None = None,
    ) -> None:
        self.limit = limit
        self.limit_value = limit_value
        self.observed_value = observed_value
        self.source: ErrorSource = "agent" if limit == "loop" else "budget"
        self.kind = "loop_detected" if limit == "loop" else "budget_exceeded"
        self.message = message or (
            f"{limit} reached: limit {limit_value:g}, observed {observed_value:g}"
        )
        super().__init__(self.message)


class InfraError(SandboxError):
    """Infrastructure failure. ``kind`` is one of throttled, service_error, network."""

    def __init__(self, kind: str, message: str, retryable: bool = True) -> None:
        self.kind = kind
        self.message = message
        self.retryable = retryable
        self.source: ErrorSource = "infra"
        super().__init__(f"{kind}: {message}")


class ConfigError(SandboxError):
    """Configuration or permission problem. Not retried; the eval stops fast."""

    def __init__(self, message: str, kind: str = "config_error") -> None:
        self.kind = kind
        self.message = message
        self.retryable = False
        self.source: ErrorSource = "infra"
        super().__init__(message)
