"""Summary contract (arch §10.4, FR-3.*). Owner: WS3 (Shivaani)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, Field

from .trace import Trace


class Claim(BaseModel):
    claim: str
    event_ids: list[str] = Field(
        default_factory=list
    )  # FR-3.2: at least one existing event
    deterministic: bool = False  # True for lines added by the citation checker (FR-3.3)


class Summary(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    claims: list[Claim] = Field(default_factory=list)
    dropped_claims: int = 0
    summarizer: dict = Field(default_factory=dict)  # {"name", "version", "params"}
    model_id: str | None = None
    prompt_version: str | None = None
    cost_usd: float = 0.0  # evaluation cost, never agent cost (FR-3.5)
    fallback: bool = False  # LLM summary failed and the deterministic one was used

    def text(self) -> str:
        return "\n".join(f"- {c.claim} [{', '.join(c.event_ids)}]" for c in self.claims)


@runtime_checkable
class Summarizer(Protocol):
    name: str
    version: str

    def summarize(self, trace: Trace, manifest: Any) -> Summary: ...
