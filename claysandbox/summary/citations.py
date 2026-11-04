"""Citation checker (FR-3.2, FR-3.3, arch §10.4). Owner: WS3.

Keeps claims that cite at least one event ID and only IDs that exist, counts
the rest as dropped, then adds a deterministic line for every error event no
kept claim mentions, so no error is ever missing from a summary.
"""

from __future__ import annotations

from claysandbox.contracts.summary import Claim
from claysandbox.contracts.trace import AnyEvent, GuardStop, ToolCall, Trace


def error_line(e: AnyEvent) -> str:
    err = e.error
    where = f"{e.server}.{e.tool}" if isinstance(e, ToolCall) else e.type
    if isinstance(e, GuardStop):
        return f"Run stopped by the {e.limit} guard (limit {e.limit_value:g}, observed {e.observed_value:g})."
    if err is None:
        return f"Error at {where}."
    retry = " (retryable)" if err.retryable else ""
    return f"Error at {where}: {err.source}/{err.kind}{retry}: {err.message}"


def is_error_event(e: AnyEvent) -> bool:
    return (
        e.error is not None
        or isinstance(e, GuardStop)
        or (isinstance(e, ToolCall) and e.status != "ok")
    )


def check(claims: list[Claim], trace: Trace) -> tuple[list[Claim], int]:
    ids = {e.event_id for e in trace.events}
    kept = [c for c in claims if c.event_ids and all(i in ids for i in c.event_ids)]
    dropped = len(claims) - len(kept)
    cited = {i for c in kept for i in c.event_ids}
    for e in trace.events:
        if is_error_event(e) and e.event_id not in cited:
            kept.append(
                Claim(claim=error_line(e), event_ids=[e.event_id], deterministic=True)
            )
    return kept, dropped
