"""Evaluator conformance suite (BAR-R0-02, DD-035, FR-4.8, FR-7.4).

Runs for every registered evaluator against every fixture trace:

* the Assessment validates against its JSON Schema and records the evaluator's name and
  version and the task-reference version;
* every evidence ID exists in the trace;
* a deterministic evaluator gives byte-identical ``stable_json()`` on repeated calls;
* injecting infra-error events into a copy of a trace changes no score.

Every evaluator module is imported here, so the parametrisation never depends on which
other tests happened to import what. Evaluators whose constructor needs collaborators
(the LLM judge) are built by ``FACTORIES``; the rest with ``cls()``. A dispatcher such as
``output`` may record the concrete evaluator it delegated to (``output.t1``), as long as
that recorded name and version resolve in the registry.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from datetime import UTC, datetime

import jsonschema
import pytest

import claysandbox.contracts.fakes.evaluator  # noqa: F401  (registers "constant")
import claysandbox.evaluation.output  # noqa: F401  (registers "output", "output.t1".."t5")
import claysandbox.evaluation.workflow  # noqa: F401  (registers "workflow", "workflow@0/1")
from claysandbox.contracts.assessment import Assessment, Evaluator
from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.model import text_reply
from claysandbox.contracts.registry import list_components, resolve
from claysandbox.contracts.runtime import ModelResponse
from claysandbox.contracts.trace import ErrorEvent, ErrorInfo, ModelCall, ToolCall, Trace
from claysandbox.evaluation.llm_process import LLMProcessEvaluator
from tests.fixtures.traces import NAMES, load

EVALUATORS = sorted(c["name"] for c in list_components("evaluator"))
SCHEMA = Assessment.model_json_schema()


class _StubJudge:
    """Always-valid judge reply citing the first event ID in the digest."""

    name = "judge-stub"
    version = "1"
    model_id = "judge-stub"

    def converse(self, messages, system, tools, params) -> ModelResponse:
        text = messages[0]["content"][0]["text"]
        first_id = text.split("[", 1)[1].split("]", 1)[0]
        reply = {"items": [{"name": "planning", "score": 0.5, "event_ids": [first_id]}]}
        return text_reply(json.dumps(reply))


FACTORIES: dict[str, Callable[[], Evaluator]] = {
    "llm_process": lambda: LLMProcessEvaluator(
        {"model_id": "judge-stub", "k": 2}, model=_StubJudge()
    ),
}


def build(name: str) -> Evaluator:
    factory = FACTORIES.get(name.removesuffix("@1"))
    return factory() if factory is not None else resolve("evaluator", name)()


def test_suite_covers_the_required_evaluators():
    assert {"constant", "workflow", "workflow@0", "workflow@1"} <= set(EVALUATORS)


def resolve_recorded(name: str, version: str) -> type:
    """The class a recorded ``(name, version)`` points to: ``name@version`` if registered
    (older versions), else ``name``."""
    try:
        return resolve("evaluator", f"{name}@{version}")
    except ConfigError:
        return resolve("evaluator", name)


@pytest.fixture(params=EVALUATORS)
def evaluator_name(request) -> str:
    return request.param


@pytest.fixture
def evaluator(evaluator_name) -> Evaluator:
    ev = build(evaluator_name)
    assert isinstance(ev, Evaluator)
    return ev


@pytest.fixture(params=NAMES)
def run(request):
    return load(request.param)


def _all_evidence(a: Assessment) -> list[str]:
    return [*a.evidence, *(i for s in a.subscores for i in s.evidence)]


def _scores(a: Assessment) -> tuple:
    return (
        a.composite,
        a.success,
        tuple((s.name, s.value, s.weight) for s in a.subscores),
        tuple(sorted(a.metrics.items())),
        a.repeats,
    )


def _with_infra_errors(trace: Trace) -> Trace:
    """Copy ``trace`` with an infra-failed model call, tool call and error event inserted
    before ``run_end``. New events get fresh IDs so existing IDs are unchanged."""
    run_id = trace.run_id
    ts = datetime(2026, 11, 4, tzinfo=UTC)
    base = max(e.seq for e in trace.events) + 100

    def ids(k: int) -> dict:
        return {
            "run_id": run_id,
            "seq": base + k,
            "event_id": f"{run_id}:{base + k}",
            "ts_start": ts,
        }

    def infra(kind: str) -> ErrorInfo:
        return ErrorInfo(source="infra", kind=kind, message="injected", retryable=True)

    injected = [
        ModelCall(
            **ids(0), model_id="m", input_tokens=1, output_tokens=0, error=infra("throttled")
        ),
        ToolCall(
            **ids(1),
            server="stac",
            tool="search_items",
            capability="imagery_search",
            args={"bbox": [0, 0, 1, 1]},
            status="error",
            error=infra("network"),
        ),
        ErrorEvent(**ids(2), error=infra("executor_failure")),
    ]
    events = list(trace.events)
    return trace.model_copy(update={"events": [*events[:-1], *injected, events[-1]]})


def test_assessment_is_schema_valid_and_records_provenance(evaluator, run):
    trace, manifest, reference = run
    a = evaluator.assess(trace, manifest, reference)
    jsonschema.validate(a.model_dump(mode="json"), SCHEMA)
    assert Assessment.model_validate_json(a.model_dump_json()) == a
    recorded = a.evaluator
    assert recorded.version
    assert recorded.name == evaluator.name or recorded.name.startswith(evaluator.name + ".")
    assert resolve_recorded(recorded.name, recorded.version).version == recorded.version
    if recorded.name == evaluator.name:
        assert recorded.version == evaluator.version
    assert a.task_reference_version == reference.version
    assert a.run_id == manifest.run_id
    assert a.kind == evaluator.kind


def test_every_evidence_id_exists_in_the_trace(evaluator, run):
    trace, manifest, reference = run
    a = evaluator.assess(trace, manifest, reference)
    ids = {e.event_id for e in trace.events}
    assert set(_all_evidence(a)) <= ids


def test_deterministic_evaluators_give_identical_stable_json(evaluator_name, evaluator, run):
    if not evaluator.deterministic:
        pytest.skip("non-deterministic evaluator")
    trace, manifest, reference = run
    first = evaluator.assess(trace, manifest, reference).stable_json()
    again = evaluator.assess(trace, manifest, reference).stable_json()
    fresh_json = build(evaluator_name).assess(trace, manifest, reference).stable_json()
    assert first == again == fresh_json


def test_infra_errors_change_no_score(evaluator, run):
    trace, manifest, reference = run
    before = evaluator.assess(trace, manifest, reference)
    after = evaluator.assess(_with_infra_errors(trace), manifest, reference)
    assert _scores(after) == _scores(before)
