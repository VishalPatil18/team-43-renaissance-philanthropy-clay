from claysandbox.contracts.registry import resolve
from tests.unit.evaluation._output_traces import make_case


def square(lon, lat, d=0.001):
    return {
        "type": "Polygon",
        "coordinates": [
            [[lon, lat], [lon + d, lat], [lon + d, lat + d], [lon, lat + d], [lon, lat]]
        ],
    }


# ~0.001 deg = ~90 m x 111 m at lat 35.5
REF = {"sites": [square(-119.5, 35.5), square(-119.2, 35.2)]}


def run(output, ref=REF, name="output.t3"):
    return resolve("evaluator", name)().assess(*make_case("T3", output, ref))


def test_points_inside_score_one_via_generic():
    a = run({"sites": [[-119.4995, 35.5005], {"lon": -119.1995, "lat": 35.2005}]}, name="output")
    assert a.metrics == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert a.composite == 1.0


def test_geojson_geometry_site_matches():
    a = run({"sites": [square(-119.5, 35.5), {"type": "Point", "coordinates": [-119.2, 35.2]}]})
    assert a.composite == 1.0


def test_tolerance_default_500m():
    # ~0.003 deg of longitude east of the polygon edge is roughly 270 m: within tolerance
    near = run({"sites": [[-119.5 + 0.001 + 0.003, 35.5005]]})
    assert near.metrics["precision"] == 1.0 and near.metrics["recall"] == 0.5
    # ~0.02 deg is roughly 1.8 km: outside
    far = run({"sites": [[-119.5 + 0.02, 35.5005]]})
    assert far.metrics["precision"] == 0.0 and far.metrics["recall"] == 0.0


def test_custom_tolerance_from_reference():
    ref = {**REF, "tolerance_m": 50}
    assert run({"sites": [[-119.5 + 0.001 + 0.003, 35.5005]]}, ref).metrics["precision"] == 0.0


def test_one_to_one_matching():
    a = run({"sites": [[-119.4995, 35.5005], [-119.4996, 35.5004]]})
    assert a.metrics["precision"] == 0.5 and a.metrics["recall"] == 0.5
    assert a.metrics["f1"] == 0.5


def test_negative_control_empty_scores_one():
    a = run({"sites": []}, {"sites": []})
    assert a.metrics == {"precision": 1.0, "recall": 1.0, "f1": 1.0}
    assert a.composite == 1.0


def test_negative_control_false_positive():
    a = run({"sites": [[-119.5, 35.5]]}, {"sites": []})
    assert a.metrics["precision"] == 0.0 and a.composite == 0.0


def test_missing_everything():
    a = run({"sites": []})
    assert a.metrics["recall"] == 0.0 and a.composite == 0.0


def test_bad_site_is_parse_failure():
    a = run({"sites": ["somewhere nice"]})
    assert a.composite == 0.0 and a.evidence == ["r:final"] and a.notes
