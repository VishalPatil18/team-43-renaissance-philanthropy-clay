import pytest

from claysandbox.contracts.registry import resolve
from claysandbox.evaluation.output import t1 as _t1  # noqa: F401  (registers)
from tests.fixtures.traces import load
from tests.unit.evaluation.test_output_helpers import as_json_fenced, make_case

SCHEMA = {
    "type": "object",
    "required": ["items"],
    "properties": {"items": {"type": "array", "items": {"type": "string"}}},
}
DSCHEMA = {
    "type": "object",
    "required": ["datasets"],
    "properties": {"datasets": {"type": "array", "items": {"type": "string"}}},
}


def run(template, output, ref, schema=SCHEMA, name=None):
    ev = resolve("evaluator", name or f"output.{template.lower()}")()
    return ev.assess(*make_case(template, output, ref, schema))


def test_good_fixture_scores_one_directly_and_via_generic():
    for name in ("output.t1", "output"):
        trace, manifest, ref = load("good_t1")
        a = resolve("evaluator", name)().assess(trace, manifest, ref)
        assert a.composite == 1.0
        assert a.kind == "output"
        assert a.success is None
        assert a.metrics == {"precision": 1.0, "recall": 1.0, "f1": 1.0}


def test_stable_json_identical():
    trace, manifest, ref = load("good_t1")
    ev = resolve("evaluator", "output")()
    first = ev.assess(trace, manifest, ref).stable_json()
    assert first == ev.assess(trace, manifest, ref).stable_json()


def test_wrong_output_scores_lower():
    a = run("T1", {"items": ["a", "x"]}, {"items": ["a", "b"]})
    assert a.metrics["precision"] == 0.5
    assert a.metrics["recall"] == 0.5
    assert a.composite == 0.5


def test_case_sensitive_and_trimmed():
    a = run("T1", {"items": [" a ", "B"]}, {"items": ["a", "b"]})
    assert a.metrics["precision"] == 0.5


def test_json_string_with_fence_and_duplicates():
    a = run("T1", as_json_fenced({"items": ["a", "a"]}), {"items": ["a"]})
    assert a.composite == 1.0


def test_parse_failure_zeroes_with_evidence():
    a = run("T1", {"nope": 1}, {"items": ["a"]})
    assert a.composite == 0.0
    assert a.metrics == {"precision": 0.0, "recall": 0.0, "f1": 0.0}
    assert a.evidence == ["r:final"]
    assert a.notes
    b = run("T1", "not json at all", {"items": ["a"]})
    assert b.composite == 0.0 and b.evidence == ["r:final"]


def test_no_final_output_scores_zero():
    trace, manifest, ref = make_case("T1", {"items": []}, {"items": ["a"]}, SCHEMA)
    trace.events.pop(0)
    a = resolve("evaluator", "output.t1")().assess(trace, manifest, ref)
    assert a.composite == 0.0 and a.notes


@pytest.mark.parametrize(
    "out,ref,p,r,f",
    [
        ([], [], 1.0, 1.0, 1.0),
        (["a"], [], 0.0, 1.0, 0.0),
        ([], ["a"], 1.0, 0.0, 0.0),
    ],
)
def test_empty_edge_cases(out, ref, p, r, f):
    a = run("T1", {"items": out}, {"items": ref})
    assert (a.metrics["precision"], a.metrics["recall"], a.metrics["f1"]) == (p, r, f)


def test_t2_uses_datasets_key_and_generic_dispatch():
    a = run("T2", {"datasets": ["s1", "s2"]}, {"datasets": ["s1", "s2"]}, DSCHEMA, name="output")
    assert a.composite == 1.0
    assert a.evaluator.name == "output.t2"
    b = run("T2", {"datasets": ["s1"]}, {"datasets": ["s1", "s2"]}, DSCHEMA)
    assert b.metrics["recall"] == 0.5


def test_all_five_registered_and_unknown_template_errors():
    from claysandbox.contracts.errors import ConfigError

    for k in range(1, 6):
        cls = resolve("evaluator", f"output.t{k}")
        assert (cls.kind, cls.deterministic, cls.version) == ("output", True, "1")
    case = make_case("T9", {"items": []}, {})
    with pytest.raises(ConfigError):
        resolve("evaluator", "output")().assess(*case)


def test_fenced_final_output_agrees_with_workflow_done_condition():
    from claysandbox.evaluation.workflow import WorkflowEvaluatorV1
    from tests.fixtures.traces import load

    trace, manifest, reference = load("good_t1")
    events = [
        e.model_copy(update={"output": as_json_fenced(e.output)}) if e.type == "final_output" else e
        for e in trace.events
    ]
    fenced = trace.model_copy(update={"events": events})

    workflow = WorkflowEvaluatorV1().assess(fenced, manifest, reference)
    output = resolve("evaluator", "output.t1")().assess(fenced, manifest, reference)

    assert next(s.value for s in workflow.subscores if s.name == "done_condition") == 1.0
    assert workflow.success is True
    assert output.composite == 1.0
    assert not any("parse error" in note for note in output.notes)


def test_dispatcher_validates_params_at_construction():
    from pydantic import Field, ValidationError

    from claysandbox.evaluation.output import OutputDispatcher
    from claysandbox.evaluation.output._common import Params

    class RequiredParams(Params):
        threshold: float = Field(ge=0, le=1)

    class ConfiguredDispatcher(OutputDispatcher):
        Params = RequiredParams

    with pytest.raises(ValidationError):
        ConfiguredDispatcher({"threshold": 2})
    configured = ConfiguredDispatcher({"threshold": 0.5})
    assessment = configured.assess(*load("good_t1"))
    assert assessment.composite == 1.0
