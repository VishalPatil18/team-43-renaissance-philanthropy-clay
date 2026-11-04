"""Task library: loading, rendering, instantiation, versioning and lookup (FR-13.1–13.6)."""

from __future__ import annotations

import json
import textwrap
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.task import fixture_aoi, fixture_t1_reference
from claysandbox.contracts.task import (
    ArgumentConstraint,
    TaskLibrary,
    TaskTemplate,
    WorkflowSpec,
)
from claysandbox.tasks.library import FileTaskLibrary
from claysandbox.tasks.references import ReferenceStore, content_hash, reference_hash
from claysandbox.tasks.render import namespace, render_text, render_value

TEMPLATE = {
    "id": "T1",
    "title": "NAIP for {aoi.name}",
    "difficulty": "easy",
    "parameters": ["aoi", "year"],
    "defaults": {"year": 2022},
    "system_prompt": "Return JSON only.",
    "prompt": 'Find NAIP items covering {aoi.name} ({aoi.state}) for {year}. '
              'Return {"items": [<item id>, ...]}.',
    "output_schema": {"type": "object", "required": ["items"],
                      "properties": {"items": {"type": "array", "items": {"type": "string"}}}},
    "workflow": {
        "required": ["imagery_search"],
        "ordering": [{"before": "geocode", "after": "imagery_search", "optional_first": True}],
        "argument_constraints": [
            {"capability": "imagery_search", "check": "bbox_intersects_aoi", "arg_names": ["bbox"]},
            {"capability": "imagery_search", "check": "collection_in", "values": ["naip"]},
            {"capability": "imagery_search", "check": "datetime_within_year", "value": "{year}"},
        ],
        "expected_steps": 4,
        "step_limit": 15,
        "done": "output_matches_schema_nonempty",
    },
    "output": {"builder": "builders/fake_builder.py", "metric": "output.t1"},
}

BUILDER = '''
import os
from claysandbox.tasks.references import BuildResult

def build(template, aoi, instance):
    items = os.environ.get("FAKE_ITEMS", "a,b").split(",")
    return BuildResult(output_reference={"items": sorted(items)},
                       inputs={"year": instance.params["year"], "aoi": aoi.id})
'''


def make_library(root: Path, template: dict | None = None) -> FileTaskLibrary:
    (root / "templates").mkdir(parents=True)
    (root / "builders").mkdir()
    (root / "process_rubrics").mkdir()
    (root / "templates" / "T1.yaml").write_text(yaml.safe_dump(template or TEMPLATE))
    (root / "builders" / "fake_builder.py").write_text(textwrap.dedent(BUILDER))
    (root / "process_rubrics" / "T1.md").write_text("# T1 rubric\n")
    aoi = fixture_aoi().model_dump(mode="json")
    other = dict(aoi, id="us-zz-other", name="Other County", fips="99002",
                 template_params={"T1": {"year": 2020}})
    (root / "aois.yaml").write_text(yaml.safe_dump({"aois": [aoi, other]}))
    return FileTaskLibrary(root)


@pytest.fixture
def lib(tmp_path: Path) -> FileTaskLibrary:
    return make_library(tmp_path / "tasks")


# -- rendering ---------------------------------------------------------------------------


def test_render_substitutes_placeholders_and_keeps_json_braces() -> None:
    ns = namespace(fixture_aoi(), {"year": 2022})
    text = render_text('{aoi.name} ({aoi.state}) {year}: {"items": [1]}', ns)
    assert text == 'Testland County (Nowhere) 2022: {"items": [1]}'


def test_render_whole_placeholder_keeps_the_type() -> None:
    ns = namespace(fixture_aoi(), {"year": 2022})
    assert render_value({"v": "{year}", "s": "y={year}", "l": ["{aoi.fips}"]}, ns) == {
        "v": 2022, "s": "y=2022", "l": ["99001"]
    }
    assert render_value("{aoi.bbox}", ns) == [-100.2, 40.0, -100.0, 40.2]


@pytest.mark.parametrize("bad", ["{nope}", "{aoi.secret}"])
def test_unknown_placeholder_is_an_error(bad: str) -> None:
    with pytest.raises(ConfigError, match="unknown placeholder"):
        render_text(bad, namespace(fixture_aoi(), {}))


def test_render_does_not_evaluate_attribute_chains() -> None:
    ns = namespace(fixture_aoi(), {})
    with pytest.raises(ConfigError):  # looked up as a plain key, never as an attribute
        render_text("{aoi.__class__}", ns)
    assert render_text("{aoi.name.upper}", ns) == "{aoi.name.upper}"  # not a placeholder


# -- templates and instances -------------------------------------------------------------


def test_library_satisfies_the_protocol(lib: FileTaskLibrary) -> None:
    assert isinstance(lib, TaskLibrary)


def test_instance_id_prompt_and_params(lib: FileTaskLibrary) -> None:
    inst = lib.get_instance("T1@us-zz-testland")
    assert inst.id == "T1@us-zz-testland" and inst.template == "T1"
    assert inst.prompt == ('Find NAIP items covering Testland County (Nowhere) for 2022. '
                           'Return {"items": [<item id>, ...]}.')
    assert inst.title == "NAIP for Testland County" and inst.params == {"year": 2022}


def test_aoi_template_params_override_defaults(lib: FileTaskLibrary) -> None:
    assert lib.get_instance("T1@us-zz-other").params == {"year": 2020}


def test_instances_cross_product_and_all(lib: FileTaskLibrary) -> None:
    ids = [i.id for i in lib.instances()]
    assert ids == ["T1@us-zz-testland", "T1@us-zz-other"]
    assert [i.id for i in lib.instances(["T1"], "all")] == ids
    assert [i.id for i in lib.instances(["T1"], ["us-zz-other"])] == ["T1@us-zz-other"]


@pytest.mark.parametrize("bad", ["T9@us-zz-testland", "T1@us-zz-missing", "T1-us-zz-testland"])
def test_unknown_instances_are_config_errors(lib: FileTaskLibrary, bad: str) -> None:
    with pytest.raises(ConfigError):
        lib.get_instance(bad)


def test_missing_parameter_value_is_an_error(tmp_path: Path) -> None:
    template = dict(TEMPLATE, defaults={})
    lib = make_library(tmp_path / "tasks", template)
    with pytest.raises(ConfigError, match="year"):
        lib.get_instance("T1@us-zz-testland")


def test_resolved_workflow_fills_aoi_geometry_and_year(lib: FileTaskLibrary) -> None:
    wf = lib.resolve_workflow(lib.template("T1"), lib.aoi("us-zz-testland"))
    by_check = {c.check: c for c in wf.argument_constraints}
    assert by_check["bbox_intersects_aoi"].value == fixture_aoi().geometry
    assert by_check["datetime_within_year"].value == 2022
    assert by_check["collection_in"].values == ["naip"]


def test_template_validation_errors() -> None:
    with pytest.raises(ValidationError):
        TaskTemplate.model_validate(dict(TEMPLATE, id="X1"))
    with pytest.raises(ValidationError, match="expected_steps"):
        WorkflowSpec(expected_steps=20, step_limit=10, done="output_present")
    with pytest.raises(ValidationError, match="values"):
        ArgumentConstraint(capability="c", check="collection_in")
    with pytest.raises(ValidationError):
        TaskTemplate.model_validate(dict(TEMPLATE, unknown_field=1))


# -- references and versioning -----------------------------------------------------------


def test_build_creates_v1_with_metadata(lib: FileTaskLibrary) -> None:
    (ref,) = lib.build_references("T1", "us-zz-testland")
    assert ref.version.startswith("T1.v1+sha256:") and len(ref.version.split(":")[1]) == 12
    assert ref.method == "script" and ref.inputs == {"year": 2022, "aoi": "us-zz-testland"}
    assert ref.output_reference == {"items": ["a", "b"]}
    assert ref.process_rubric == "# T1 rubric\n" and ref.aoi_snapshot.id == "us-zz-testland"
    assert len(ref.builder_sha256) == 64 and reference_hash(ref) == ref.version.split(":")[1]
    files = list((lib.root / "references" / "T1" / "us-zz-testland").glob("*.json"))
    assert len(files) == 1 and ":" not in files[0].name


def test_same_content_gives_the_same_version_and_writes_nothing(lib: FileTaskLibrary) -> None:
    (first,) = lib.build_references("T1", "us-zz-testland")
    (second,) = lib.build_references("T1", "us-zz-testland")
    assert second.version == first.version and second.built_at == first.built_at
    assert len(lib.references.versions("T1", "us-zz-testland")) == 1


def test_changed_content_gives_the_next_version_and_old_stays_readable(
    lib: FileTaskLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    (v1,) = lib.build_references("T1", "us-zz-testland")
    monkeypatch.setenv("FAKE_ITEMS", "a,b,c")
    (v2,) = lib.build_references("T1", "us-zz-testland")
    assert v2.version.startswith("T1.v2+sha256:") and v2.version != v1.version
    assert lib.get_reference("T1@us-zz-testland").version == v2.version
    assert lib.get_reference("T1@us-zz-testland", v1.version).output_reference == {
        "items": ["a", "b"]
    }


def test_reverting_content_returns_the_old_version(
    lib: FileTaskLibrary, monkeypatch: pytest.MonkeyPatch
) -> None:
    (v1,) = lib.build_references("T1", "us-zz-testland")
    monkeypatch.setenv("FAKE_ITEMS", "x")
    lib.build_references("T1", "us-zz-testland")
    monkeypatch.setenv("FAKE_ITEMS", "a,b")
    (again,) = lib.build_references("T1", "us-zz-testland")
    assert again.version == v1.version


def test_build_every_aoi(lib: FileTaskLibrary) -> None:
    refs = lib.build_references("T1")
    assert [r.instance_id for r in refs] == ["T1@us-zz-testland", "T1@us-zz-other"]
    assert refs[1].inputs["year"] == 2020


def test_missing_reference_and_unknown_version(lib: FileTaskLibrary) -> None:
    with pytest.raises(ConfigError, match="no task reference"):
        lib.get_reference("T1@us-zz-testland")
    lib.build_references("T1", "us-zz-testland")
    with pytest.raises(ConfigError):
        lib.get_reference("T1@us-zz-testland", "T1.v9+sha256:000000000000")


def test_store_refuses_to_overwrite_and_checks_the_hash(tmp_path: Path) -> None:
    store = ReferenceStore(tmp_path)
    ref = fixture_t1_reference()
    store.save(ref)
    with pytest.raises(ConfigError, match="overwrite"):
        store.save(ref)
    tampered = ref.model_copy(update={"aoi": "us-zz-other",
                                      "output_reference": {"items": ["forged"]}})
    with pytest.raises(ConfigError, match="does not match"):
        store.save(tampered)


def test_hash_ignores_key_order() -> None:
    a = content_hash({"x": 1, "y": [1, 2]}, {"items": ["a"]}, {})
    b = content_hash({"y": [1, 2], "x": 1}, {"items": ["a"]}, {})
    assert a == b and a != content_hash({"x": 1, "y": [2, 1]}, {"items": ["a"]}, {})


def test_fixture_reference_is_self_consistent() -> None:
    ref = fixture_t1_reference()
    assert reference_hash(ref) == ref.version.split(":")[1]
    json.loads(ref.model_dump_json())


def test_spot_check_records_who_and_when_without_changing_the_version(
    lib: FileTaskLibrary,
) -> None:
    (ref,) = lib.build_references("T1", "us-zz-testland")
    checked = lib.references.record_spot_check(
        "T1", "us-zz-testland", ref.version, "Tester", note="compared with the STAC browser"
    )
    again = lib.get_reference("T1@us-zz-testland")
    assert again.version == ref.version and again.checked_by == "Tester"
    assert again.checked_at == checked.checked_at is not None
    assert again.notes[-1] == "spot-check: compared with the STAC browser"
    assert reference_hash(again) == ref.version.split(":")[1]
    assert len(lib.references.versions("T1", "us-zz-testland")) == 1


# -- the repository's own task library ---------------------------------------------------


def test_repository_templates_instantiate_on_every_aoi() -> None:
    repo = FileTaskLibrary()
    assert len(repo.list_aois()) == 6
    tags = {a.id: a.tags for a in repo.list_aois()}
    assert sum("has_solar" in t for t in tags.values()) == 4
    assert sum("no_solar" in t for t in tags.values()) == 2
    for inst in repo.instances():
        assert "{" + "aoi." not in inst.prompt  # every placeholder was filled
        workflow = repo.resolve_workflow(repo.template(inst.template), repo.aoi(inst.aoi))
        for c in workflow.argument_constraints:
            assert c.value is not None or c.values


def test_repository_references_are_consistent() -> None:
    repo = FileTaskLibrary()
    for inst in repo.instances():
        try:
            ref = repo.get_reference(inst.id)
        except ConfigError:
            continue  # not built yet
        assert ref.instance_id == inst.id
        assert reference_hash(ref) == ref.version.split(":")[1]
        assert ref.output_reference
