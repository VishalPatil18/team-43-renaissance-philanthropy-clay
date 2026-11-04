"""LLM summarizer (SHI-R1-02, FR-3.1, FR-3.2, FR-3.5, DD-007, DD-027). Owner: WS3.

Asks a model for a JSON list of claims, each citing trace event IDs, then runs the
citation checker: claims without a valid citation are dropped and counted, and a
deterministic line is added for every error the model did not cite (FR-3.3).

The model adapter is passed in by the run worker and is the *uninstrumented* one, so
this is evaluation cost, never agent cost (FR-3.5). If the model's answer cannot be
parsed after one retry, or the model call itself fails, the deterministic summarizer
is used and ``fallback`` is set, so a summary is always produced.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from claysandbox.contracts.registry import register
from claysandbox.contracts.summary import Claim, Summary
from claysandbox.contracts.trace import Trace, trace_digest

from .citations import check
from .deterministic import DeterministicSummarizer

log = logging.getLogger("claysandbox.summary")

PROMPT_VERSION = "summary-prompt@1"
DIGEST_CHARS = 12000

SYSTEM_PROMPT = """\
You summarise the trace of an AI agent that ran a geospatial data task by calling tools.
You are given one line per trace event, each starting with its event ID in square brackets.

Write a short, factual account of what the agent did, in order. Cover every failure, retry
and dead end. Do not invent anything that is not in the trace.

Rules:
- Reply with JSON only, no prose and no code fences, in exactly this shape:
  {"claims": [{"claim": "<one sentence>", "event_ids": ["<event id>", ...]}]}
- Every claim must cite at least one event ID, copied exactly from the trace.
- Cite only events that support the claim.
- Write at most __MAX_CLAIMS__ claims. Merge routine steps; never merge away an error.
"""

RETRY_NOTE = (
    "Your last reply was not valid. Reply with JSON only, exactly in the shape "
    '{"claims": [{"claim": "...", "event_ids": ["..."]}]}.'
)


class _ClaimsReply(BaseModel):
    """Strict shape of the model's reply."""

    model_config = ConfigDict(extra="forbid")

    class _Item(BaseModel):
        model_config = ConfigDict(extra="forbid")
        claim: str
        event_ids: list[str] = Field(default_factory=list)

    claims: list[_Item]


_FENCE = re.compile(r"^\s*```(?:json)?\s*(.*?)\s*```\s*$", re.DOTALL)


def parse_reply(text: str) -> list[Claim]:
    """Parse the model's reply strictly. A single code fence around the JSON is tolerated."""
    body = text.strip()
    m = _FENCE.match(body)
    if m:
        body = m.group(1)
    reply = _ClaimsReply.model_validate(json.loads(body))
    return [Claim(claim=i.claim, event_ids=i.event_ids) for i in reply.claims]


@register("summarizer", "llm")
class LlmSummarizer:
    name = "llm"
    version = "1"

    class Params(BaseModel):
        model_id: str = ""  # informational: the adapter owns the real model ID (FR-1.5)
        max_claims: int = 12
        temperature: float = 0.0

    def __init__(self, params: dict | None = None, *, model: Any = None, prices: Any = None):
        self.params = self.Params(**(params or {}))
        self.model = model  # ModelAdapter, uninstrumented; set by the run worker
        self.prices = prices  # PriceTable, to price the summary calls

    # ------------------------------------------------------------------ public API
    def summarize(self, trace: Trace, manifest: Any = None) -> Summary:
        fallback = DeterministicSummarizer()
        if self.model is None:
            log.error("llm summarizer has no model adapter; using the deterministic summary")
            return self._fallback(fallback, trace, manifest, cost=0.0, model_id=None)

        system = SYSTEM_PROMPT.replace("__MAX_CLAIMS__", str(self.params.max_claims))
        messages: list[dict[str, Any]] = [
            {"role": "user", "content": [{"text": trace_digest(trace, DIGEST_CHARS)}]}
        ]
        cost = 0.0
        model_id: str | None = getattr(self.model, "model_id", None)

        for attempt in (1, 2):  # one retry on an unparseable reply (plan: retry once)
            try:
                resp = self.model.converse(
                    messages,
                    system,
                    [],
                    {"temperature": self.params.temperature, "max_tokens": 2048},
                )
            except Exception as e:  # noqa: BLE001  a summary must never kill the run
                log.error(
                    "summary model call failed",
                    extra={"run_id": trace.run_id, "error": repr(e)},
                )
                return self._fallback(fallback, trace, manifest, cost, model_id)

            model_id = resp.model_id or model_id
            cost += self._price(model_id, resp.input_tokens, resp.output_tokens)
            try:
                claims = parse_reply(resp.text)
            except (json.JSONDecodeError, ValidationError, ValueError) as e:
                log.warning(
                    "summary reply not valid",
                    extra={"run_id": trace.run_id, "attempt": attempt, "error": repr(e)},
                )
                messages = [
                    *messages,
                    resp.message,
                    {"role": "user", "content": [{"text": RETRY_NOTE}]},
                ]
                continue

            kept, dropped = check(claims, trace)
            return Summary(
                run_id=trace.run_id,
                claims=kept,
                dropped_claims=dropped,
                summarizer=self._ref(),
                model_id=model_id,
                prompt_version=PROMPT_VERSION,
                cost_usd=cost,
            )

        return self._fallback(fallback, trace, manifest, cost, model_id)

    # ------------------------------------------------------------------ helpers
    def _ref(self) -> dict:
        return {"name": self.name, "version": self.version, "params": self.params.model_dump()}

    def _price(self, model_id: str | None, tokens_in: int, tokens_out: int) -> float:
        if self.prices is None or not model_id or not self.prices.has(model_id):
            return 0.0
        return float(self.prices.model_cost(model_id, tokens_in, tokens_out))

    def _fallback(
        self,
        deterministic: DeterministicSummarizer,
        trace: Trace,
        manifest: Any,
        cost: float,
        model_id: str | None,
    ) -> Summary:
        s = deterministic.summarize(trace, manifest)
        return s.model_copy(
            update={
                "summarizer": self._ref(),
                "model_id": model_id,
                "prompt_version": PROMPT_VERSION,
                "cost_usd": cost,  # tokens spent on failed attempts are still evaluation cost
                "fallback": True,
            }
        )
