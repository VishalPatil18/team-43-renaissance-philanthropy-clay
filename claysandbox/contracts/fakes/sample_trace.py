"""A scripted run's events (no AWS) for tests across workstreams.

Covers each event type, a tool error that is later recovered, and a run_end.
Pass the events through a ``RunEventSink`` to get seq/event_id/run_id filled.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta

from claysandbox.contracts.trace import (
    AnyEvent,
    ErrorInfo,
    FinalOutput,
    ModelCall,
    RunEnd,
    RunStart,
    ToolCall,
)

T0 = datetime(2026, 11, 4, 10, 0, 0, tzinfo=UTC)


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def scripted_events() -> list[AnyEvent]:
    """Without parent_id: the sink assigns event IDs, so parents are linked by position in tests."""
    return [
        RunStart(
            ts_start=at(0), task_instance_id="T1:kern", config_name="fake-baseline"
        ),
        ModelCall(
            ts_start=at(0.1),
            ts_end=at(1.0),
            latency_ms=900,
            model_id="fake-model",
            input_tokens=420,
            output_tokens=60,
            stop_reason="tool_use",
            tool_use_requests=[
                {"name": "stac__search_items", "input": {"collection": "naip"}}
            ],
            cost_usd=0.0004,
            price_table_version="fixed-1",
        ),
        ToolCall(
            ts_start=at(1.0),
            ts_end=at(2.0),
            latency_ms=1000,
            server="stac",
            tool="search_items",
            capability="imagery_search",
            args={"collection": "naip", "bbox": [-119.2, 35.0, -118.0, 35.8]},
            status="timeout",
            result_preview=None,
            error=ErrorInfo(
                source="tool",
                kind="tool_timeout",
                message="no result within 30s",
                retryable=True,
            ),
        ),
        ModelCall(
            ts_start=at(2.0),
            ts_end=at(2.8),
            latency_ms=800,
            model_id="fake-model",
            input_tokens=510,
            output_tokens=55,
            stop_reason="tool_use",
            tool_use_requests=[
                {"name": "stac__search_items", "input": {"collection": "naip"}}
            ],
            cost_usd=0.0005,
            price_table_version="fixed-1",
        ),
        ToolCall(
            ts_start=at(2.8),
            ts_end=at(3.6),
            latency_ms=800,
            server="stac",
            tool="search_items",
            capability="imagery_search",
            args={"collection": "naip", "bbox": [-119.2, 35.0, -118.0, 35.8]},
            status="ok",
            result_preview=json.dumps({"numberMatched": 41, "features": []}),
        ),
        ModelCall(
            ts_start=at(3.6),
            ts_end=at(4.4),
            latency_ms=800,
            model_id="fake-model",
            input_tokens=900,
            output_tokens=120,
            stop_reason="end_turn",
            text_preview="Found 41 NAIP items.",
            cost_usd=0.0008,
            price_table_version="fixed-1",
        ),
        FinalOutput(
            ts_start=at(4.4), output={"items": ["ca_m_3511801_ne"], "count": 41}
        ),
        RunEnd(
            ts_start=at(4.5),
            state="completed",
            totals={
                "steps": 3,
                "input_tokens": 1830,
                "output_tokens": 235,
                "cost_usd": 0.0017,
                "wall_ms": 4500,
            },
        ),
    ]
