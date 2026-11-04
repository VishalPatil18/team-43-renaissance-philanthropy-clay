from __future__ import annotations

from typing import Any

from claysandbox.contracts.registry import register
from claysandbox.contracts.summary import Claim, Summary
from claysandbox.contracts.trace import Trace, digest_line


@register("summarizer", "echo")
class EchoSummarizer:
    """One claim per event, citing it. For tests of anything that consumes summaries."""

    name = "echo"
    version = "1"

    def __init__(self, params: dict | None = None):
        pass

    def summarize(self, trace: Trace, manifest: Any = None) -> Summary:
        return Summary(
            run_id=trace.run_id,
            claims=[
                Claim(claim=digest_line(e), event_ids=[e.event_id])
                for e in trace.events
            ],
            summarizer={"name": self.name, "version": self.version, "params": {}},
        )
