from __future__ import annotations

import json

import pytest

from claysandbox.contracts.fakes import MemoryTracer
from claysandbox.contracts.fakes.model import FakeModelAdapter, text_reply
from claysandbox.contracts.fakes.pricing import FixedPriceTable
from claysandbox.contracts.fakes.sample_trace import scripted_events
from claysandbox.contracts.registry import resolve
from claysandbox.summary.llm import PROMPT_VERSION, LlmSummarizer, parse_reply
from claysandbox.tracing.sink import RunEventSink


def recorded():
    tracer = MemoryTracer()
    sink = RunEventSink("r", "/tmp/unused", tracer)
    for e in scripted_events():
        sink.emit(e)
    return tracer.trace()


# In the scripted trace: r:2 is a tool timeout (error), r:4 the successful retry.
GOOD = {
    "claims": [
        {"claim": "Searched NAIP; the first call timed out.", "event_ids": ["r:1", "r:2"]},
        {"claim": "Retried and found 41 items.", "event_ids": ["r:3", "r:4"]},
        {"claim": "Returned the item list.", "event_ids": ["r:6"]},
    ]
}


def reply(payload, **kw):
    return text_reply(payload if isinstance(payload, str) else json.dumps(payload), **kw)


def make(script, prices=None):
    model = FakeModelAdapter(script, model_id="nova-lite-test")
    return LlmSummarizer({"model_id": "nova-lite-test"}, model=model, prices=prices), model


def test_registered_as_llm_summarizer():
    assert resolve("summarizer", "llm") is LlmSummarizer


def test_valid_reply_becomes_cited_claims_and_records_cost():
    prices = FixedPriceTable(input_per_1k=1.0, output_per_1k=2.0)
    s, model = make([reply(GOOD, input_tokens=1000, output_tokens=500)], prices)
    out = s.summarize(recorded())
    assert [c.event_ids for c in out.claims[:3]] == [["r:1", "r:2"], ["r:3", "r:4"], ["r:6"]]
    assert out.dropped_claims == 0 and out.fallback is False
    assert out.prompt_version == PROMPT_VERSION and out.model_id == "fake-model"
    assert out.cost_usd == pytest.approx(1000 / 1000 * 1.0 + 500 / 1000 * 2.0)
    assert out.summarizer["name"] == "llm"
    # the model saw the digest and was told the reply format
    call = model.calls[0]
    assert "[r:2] tool_call stac.search_items" in call["messages"][0]["content"][0]["text"]
    assert "JSON only" in call["system"] and call["tools"] == []
    assert call["params"]["temperature"] == 0.0


def test_claims_with_missing_or_unknown_citations_are_dropped_and_counted():
    bad = {
        "claims": [
            *GOOD["claims"],
            {"claim": "uncited", "event_ids": []},
            {"claim": "invented", "event_ids": ["r:99"]},
        ]
    }
    out = make([reply(bad)])[0].summarize(recorded())
    texts = [c.claim for c in out.claims]
    assert "uncited" not in texts and "invented" not in texts
    assert out.dropped_claims == 2


def test_error_the_model_forgot_still_appears_via_a_deterministic_line():
    forgot = {"claims": [{"claim": "Found 41 items.", "event_ids": ["r:4", "r:6"]}]}
    out = make([reply(forgot)])[0].summarize(recorded())
    added = [c for c in out.claims if c.deterministic]
    assert added and "tool_timeout" in added[0].claim and added[0].event_ids == ["r:2"]


def test_unparseable_reply_is_retried_once_and_both_calls_are_paid_for():
    prices = FixedPriceTable(input_per_1k=1.0, output_per_1k=0.0)
    s, model = make(
        [reply("sorry, here is a summary...", input_tokens=1000), reply(GOOD, input_tokens=1000)],
        prices,
    )
    out = s.summarize(recorded())
    assert len(model.calls) == 2 and out.fallback is False
    assert out.cost_usd == pytest.approx(2.0)
    retry_msgs = model.calls[1]["messages"]
    assert retry_msgs[-1]["role"] == "user" and "JSON only" in retry_msgs[-1]["content"][0]["text"]


def test_two_bad_replies_fall_back_to_the_deterministic_summary():
    s, model = make([reply("nope"), reply('{"claims": "not a list"}')])
    out = s.summarize(recorded())
    assert len(model.calls) == 2
    assert out.fallback is True and out.summarizer["name"] == "llm"
    assert "Run ended completed" in out.text()  # the deterministic text is there
    assert out.claims and all(c.event_ids for c in out.claims)


def test_model_error_falls_back_instead_of_raising():
    s, _ = make([RuntimeError("throttled")])
    out = s.summarize(recorded())
    assert out.fallback is True and "Run ended completed" in out.text()


def test_without_a_model_adapter_it_falls_back():
    out = LlmSummarizer({}).summarize(recorded())
    assert out.fallback is True and out.cost_usd == 0.0


def test_extra_keys_and_wrong_types_are_rejected_but_a_code_fence_is_tolerated():
    fenced = "```json\n" + json.dumps(GOOD) + "\n```"
    assert len(parse_reply(fenced)) == 3
    for bad in (
        '{"claims": [{"claim": "x", "event_ids": ["r:1"], "extra": 1}]}',
        '{"claims": [{"claim": 5, "event_ids": []}]}',
        '{"claims": [], "other": 1}',
        "[]",
    ):
        with pytest.raises(ValueError):
            parse_reply(bad)


def test_unknown_model_price_costs_nothing_rather_than_failing():
    class NoPrices(FixedPriceTable):
        def has(self, model_id):  # noqa: ARG002
            return False

    out = make([reply(GOOD)], NoPrices(1.0, 1.0))[0].summarize(recorded())
    assert out.cost_usd == 0.0 and out.fallback is False
