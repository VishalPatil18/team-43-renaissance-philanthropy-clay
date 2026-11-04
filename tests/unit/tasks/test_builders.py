"""Reference builders that can be tested without network: the T2 coverage filter and T5 rules."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

from claysandbox.contracts.fakes.task import fixture_aoi, fixture_t1_instance
from claysandbox.tasks.library import FileTaskLibrary

BUILDERS = Path(__file__).resolve().parents[3] / "tasks" / "builders"


def load(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(f"test_{name}", BUILDERS / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


t2 = load("t2_open_datasets")


def doc(name: str, description: str, tags: list[str], **extra: Any) -> dict[str, Any]:
    return {"Name": name, "Description": description, "Tags": tags, **extra}


@pytest.mark.parametrize(
    ("slug", "document", "state", "expected"),
    [
        ("naip", doc("NAIP on AWS", "Aerial imagery of the continental U.S.", ["aerial imagery"]),
         "Texas", True),
        ("usgs-lidar", doc("3DEP", "Lidar over the conterminous United States.", ["lidar"]),
         "Nevada", True),
        ("copernicus-dem", doc("Copernicus DEM", "A worldwide elevation model.", ["elevation"]),
         "Texas", True),
        ("sentinel-2", doc("Sentinel-2", "Optical imagery from the European Space Agency.",
                           ["satellite imagery"]), "Texas", True),
        ("deafrica-landsat", doc("Digital Earth Africa Landsat", "Global Landsat data.",
                                 ["satellite imagery"]), "Texas", False),
        ("ca-trees", doc("California tree height", "Canopy height for California.",
                         ["land cover"]), "California", True),
        ("ca-trees", doc("California tree height", "Canopy height for California.",
                         ["land cover"]), "Texas", False),
        ("nasa-boreas", doc("BOREAS", "A field campaign in Canada; part of global change work.",
                            ["satellite imagery"]), "Texas", False),
        ("sst", doc("Sea surface temperature", "Global SST.", ["satellite imagery", "oceans"]),
         "Texas", False),
        ("nasa-usgs-mars-hirise", doc("HiRISE", "A global mosaic.", ["satellite imagery"]),
         "Texas", False),
        ("genomes", doc("1000 Genomes", "Global human genomes.", ["genomic"]), "Texas", False),
        ("old", doc("Old", "Global imagery.", ["satellite imagery"], Deprecated=True), "Texas",
         False),
        ("vague", doc("Some imagery", "Imagery of a site.", ["satellite imagery"]), "Texas", False),
    ],
)
def test_t2_coverage_rules(slug: str, document: dict[str, Any], state: str, expected: bool) -> None:
    assert t2.covers(slug, document, state) is expected


def test_t5_rules_carry_the_aoi_values() -> None:
    t5 = load("t5_rules")
    lib = FileTaskLibrary()
    result = t5.build(lib.template("T5"), fixture_aoi(), fixture_t1_instance())
    rules = {r["id"]: r for r in result.output_reference["rules"]}
    assert set(rules) == {"states_assumptions_or_asks", "no_fabricated_ids", "items_intersect_aoi"}
    assert rules["items_intersect_aoi"]["aoi_geometry"] == fixture_aoi().geometry
    assert result.method == "script"
