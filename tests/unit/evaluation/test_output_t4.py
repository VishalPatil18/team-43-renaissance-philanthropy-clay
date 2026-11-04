from claysandbox.contracts.registry import resolve
from tests.unit.evaluation._output_traces import make_case

REF = {"top_k": [{"chips_id": "c1"}, {"chips_id": "c2"}, {"chips_id": "c3"}, {"chips_id": "c4"}]}


def run(output, ref=REF, name="output.t4"):
    return resolve("evaluator", name)().assess(*make_case("T4", output, ref))


def test_correct_scores_one_in_any_order_via_generic():
    a = run({"chips": [{"chips_id": c} for c in ("c4", "c1", "c3", "c2")]}, name="output")
    assert a.composite == 1.0 and a.metrics == {"recall_at_k": 1.0}


def test_plain_ids_and_partial():
    a = run({"chips": ["c1", "c2", "zz", "yy"]})
    assert a.composite == 0.5


def test_only_first_k_predictions_count():
    a = run({"chips": ["x1", "x2", "x3", "x4", "c1", "c2", "c3", "c4"]})
    assert a.composite == 0.0


def test_plain_reference_ids_and_bare_list():
    a = run({"chips": ["c1", "c2"]}, ref={"top_k": ["c1", "c2"]})
    assert a.composite == 1.0


def test_empty_reference():
    assert run({"chips": []}, ref={"top_k": []}).composite == 1.0
    assert run({"chips": ["a"]}, ref={"top_k": []}).composite == 1.0


def test_unparseable_zero():
    a = run("garbage")
    assert a.composite == 0.0 and a.evidence == ["r:final"]
