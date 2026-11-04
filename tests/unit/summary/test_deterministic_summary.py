from __future__ import annotations

from claysandbox.contracts.fakes import MemoryTracer
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.summary import Claim
from claysandbox.contracts.trace import ErrorInfo, GuardStop, RunEnd
from claysandbox.summary.citations import check
from claysandbox.summary.deterministic import DeterministicSummarizer
from claysandbox.tracing.sink import RunEventSink


def recorded(events=None):
    tracer = MemoryTracer()
    sink = RunEventSink("r", "/tmp/unused", tracer)
    for e in events or scripted_events():
        sink.emit(e)
    return tracer.trace()


def test_every_error_mentioned_and_every_claim_cites_real_events():
    trace = recorded()
    s = DeterministicSummarizer().summarize(trace)
    ids = {e.event_id for e in trace.events}
    assert all(c.event_ids and set(c.event_ids) <= ids for c in s.claims)
    errors = [e.event_id for e in trace.errors]
    assert errors and all(any(err in c.event_ids for c in s.claims) for err in errors)
    text = s.text()
    assert "recovered by a later successful call" in text
    assert "Run ended completed" in text and s.dropped_claims == 0 and s.cost_usd == 0


def test_steps_in_order():
    s = DeterministicSummarizer().summarize(recorded())
    steps = [c.claim for c in s.claims if c.claim.startswith("Step")]
    assert [c.split(":")[0] for c in steps] == ["Step 1", "Step 2", "Step 3"]
    assert "stac.search_items" in steps[0] and "41 results" in steps[1]


def test_guard_stop_and_unrecovered_error():
    events = scripted_events()[:3] + [
        GuardStop(
            limit="max_steps",
            limit_value=1,
            observed_value=2,
            error=ErrorInfo(source="budget", kind="budget_exceeded", message="max_steps reached"),
        ),
        RunEnd(state="budget_stopped", totals={"steps": 1}),
    ]
    s = DeterministicSummarizer().summarize(recorded(events))
    text = s.text()
    assert (
        "never recovered" in text and "max_steps guard" in text and "with no final output" in text
    )


def test_citation_checker_drops_bad_claims_and_adds_missing_errors():
    trace = recorded()
    claims = [
        Claim(claim="fine", event_ids=["r:1"]),
        Claim(claim="no cite", event_ids=[]),
        Claim(claim="ghost", event_ids=["r:99"]),
    ]
    kept, dropped = check(claims, trace)
    assert dropped == 2
    assert any(c.deterministic and "tool_timeout" in c.claim for c in kept)


def test_recovery_needs_the_same_server_and_tool():
    """A later success of a same-named tool on a different server is not a recovery."""
    from claysandbox.contracts.trace import ToolCall

    events = scripted_events()
    other_server_ok = ToolCall(server="roda", tool="search_items", status="ok", result_preview="{}")
    # failed stac.search_items, then an ok roda.search_items only
    events = events[:3] + [other_server_ok, events[-2], events[-1]]
    text = DeterministicSummarizer().summarize(recorded(events)).text()
    assert "never recovered" in text
    assert "recovered by a later successful call" not in text


def test_recovery_on_the_same_server_and_tool_is_credited():
    text = DeterministicSummarizer().summarize(recorded()).text()
    assert "recovered by a later successful call" in text
