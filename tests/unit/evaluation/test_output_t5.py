from claysandbox.contracts.registry import resolve
from tests.unit.evaluation._output_traces import make_case, tool_call

SCHEMA = {
    "type": "object",
    "required": ["assumptions", "clarifying_question", "items"],
    "properties": {
        "assumptions": {"type": "array", "items": {"type": "string"}},
        "clarifying_question": {"type": ["string", "null"]},
        "items": {"type": "array", "items": {"type": "string"}},
    },
}
REF = {"aoi_items": ["naip_1", "naip_2"]}
CALLS = [tool_call('{"features":[{"id":"naip_1"},{"id":"naip_2"},{"id":"far_away"}]}')]


def run(output, ref=REF, calls=CALLS, blobs=None, name="output.t5"):
    case = make_case("T5", output, ref, SCHEMA, calls, blobs)
    return resolve("evaluator", name)().assess(*case)


def out(assumptions=("most recent NAIP",), question=None, items=("naip_1",)):
    return {"assumptions": list(assumptions), "clarifying_question": question, "items": list(items)}


def test_good_output_scores_one_via_generic():
    a = run(out(), name="output")
    assert a.composite == 1.0
    assert a.metrics == {"pass_rate": 1.0, "rule_a": 1.0, "rule_b": 1.0, "rule_c": 1.0}


def test_question_only_passes_rule_a_without_items():
    assert run(out(assumptions=(), question="Which year?", items=())).composite == 1.0


def test_no_assumptions_or_question_fails_a():
    a = run(out(assumptions=()))
    assert a.metrics["rule_a"] == 0.0 and abs(a.composite - 2 / 3) < 1e-9


def test_fabricated_id_fails_b_and_c():
    a = run(out(items=("naip_1", "made_up")))
    assert a.metrics["rule_b"] == 0.0 and a.metrics["rule_c"] == 0.0


def test_id_found_only_in_blob_counts_for_b():
    calls = [tool_call("truncated…", ref="blobs/x")]
    a = run(out(items=("naip_1",)), calls=calls, blobs={"blobs/x": b'{"id": "naip_1"}'})
    assert a.metrics["rule_b"] == 1.0


def test_found_in_results_but_not_in_aoi_fails_c_only():
    a = run(out(items=("far_away",)))
    assert a.metrics["rule_b"] == 1.0 and a.metrics["rule_c"] == 0.0


def test_rule_c_without_reference_list_falls_back_to_imagery_search_results():
    calls = [
        tool_call('{"id":"img_1"}', cap="imagery_search"),
        tool_call('{"id":"ds_1"}', cap="dataset_discovery"),
    ]
    assert run(out(items=("img_1",)), ref={}, calls=calls).metrics["rule_c"] == 1.0
    assert run(out(items=("ds_1",)), ref={}, calls=calls).metrics["rule_c"] == 0.0


def test_parse_failure_zeroes_all():
    a = run({"assumptions": "nope"})
    assert a.composite == 0.0 and a.evidence == ["r:final"]
    assert set(a.metrics) == {"pass_rate", "rule_a", "rule_b", "rule_c"}
