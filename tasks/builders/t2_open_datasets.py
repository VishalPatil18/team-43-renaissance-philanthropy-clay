"""T2 reference builder: open imagery, elevation and land-cover datasets that cover the AOI.

Source: the dataset YAML files of the Registry of Open Data on AWS
(https://github.com/awslabs/open-data-registry), pinned to one commit and downloaded as a tarball
(no git needed). The registry has no structured coverage field, so coverage is decided by
keywords, which is why the key is noisy and T2 is scored mainly by precision (see below).

A dataset is in the key for an AOI when all of these hold:

1. it is not ``Deprecated``;
2. it has at least one theme tag: ``satellite imagery``, ``aerial imagery``, ``elevation``,
   ``lidar`` or ``land cover``, and is not an ocean-only product (ocean tags without land tags);
3. its name or description says it covers the AOI: a global marker ("global", "worldwide", ...)
   or a United States coverage marker ("United States", "CONUS", "across the US", ...), or the
   AOI's state by name. Agency names ("U.S. Geological Survey", "NASA", ...) are removed first,
   because they say who made the data, not where it applies;
4. it is not limited to somewhere else: a dataset whose slug, name or tags name another country
   or region (``deafrica-*``, ``*_australia``) is out; one whose description names another
   country, region or US state needs a strong marker to stay in (a US coverage phrase, a phrase
   such as "global coverage" or "worldwide", "global" or a global mission such as Landsat,
   Sentinel or MODIS in its own name), or the AOI's state. Names of agencies and of AWS
   ("European Space Agency", "Amazon S3") are removed before matching;
5. it is about the Earth's land: astronomy, off-Earth (Mars, Moon, ...) and ocean-only products
   are out;
6. field or airborne campaigns are in only if they name the AOI's state.

Scoring (``output.t2``, agreed for T2 by the Task Author on 2026-11-04): the agent returns up to
``k`` = 10 slugs. Precision = returned slugs in the key ÷ returned slugs. Recall@k = returned
slugs in the key ÷ min(k, size of the key). The method is ``script`` (not hand-curated).
"""

from __future__ import annotations

import io
import os
import re
import tarfile
import urllib.request
from pathlib import Path
from typing import Any

import yaml

from claysandbox.contracts.task import AOI, TaskInstance, TaskTemplate
from claysandbox.tasks.references import BuildResult

REGISTRY_REPO = "https://github.com/awslabs/open-data-registry"
REGISTRY_COMMIT = "40c4313ffd10948ee5193e14b7605996cccb3d1b"  # main on 2026-11-02
TARBALL = f"https://codeload.github.com/awslabs/open-data-registry/tar.gz/{REGISTRY_COMMIT}"
FILTER_VERSION = 1
K = 10

THEME_TAGS = frozenset({"satellite imagery", "aerial imagery", "elevation", "lidar", "land cover"})

GLOBAL = re.compile(
    r"\b(global|globally|worldwide|world-wide|whole world|entire (earth|globe|world)|"
    r"all land|planet-wide|planetary)\b"
)
UNITED_STATES = re.compile(
    r"\b(united states|conus|conterminous us|conterminous u\.s|contiguous us|contiguous u\.s|"
    r"continental us|continental u\.s|lower 48|nationwide|"
    r"(across|over|for|of|throughout|covering|covers) the (u\.s\.|us|usa)|(u\.s\.|us)-wide)\b"
)
# Agency and programme names say who made a dataset, not where it applies; removed before matching.
AGENCIES = re.compile(
    r"\b(united states|u\.s\.|us) (geological survey|department of [a-z]+|army|navy|air force|"
    r"forest service|census bureau|environmental protection agency|government)\b|"
    r"\b(usgs|noaa|nasa|usda|epa|fema|nga)\b|"
    r"\b(european space agency|esa|european commission|european union's copernicus|"
    r"amazon web services|amazon s3|amazon sustainability data initiative|aws)\b"
)
# Missions that image the whole Earth. A dataset named after one (and not after a region, see
# rule 4) is taken as global.
GLOBAL_MISSIONS = re.compile(
    r"\b(landsat|sentinel|modis|viirs|aster|srtm|copernicus dem|hls|harmonized landsat)\b"
)
# "global" alone is common in descriptions ("the global carbon cycle"). These phrases, or "global"
# in the dataset's own name, are taken as real statements of global coverage.
STRONG_GLOBAL = re.compile(
    r"\b(global(ly)? (coverage|extent|dataset|mosaic|map|maps|product|scale|archive)|"
    r"worldwide|world-wide|entire (earth|globe|world)|whole world|across the globe|"
    r"covers the (globe|earth|world|entire)|all (land|continents|landmasses))\b"
)
NON_EARTH_TAGS = frozenset({"astronomy", "astrophysics", "planetary science"})
OCEAN_TAGS = frozenset({"oceans", "sea surface temperature", "ocean", "marine"})
LAND_TAGS = frozenset(
    {"land", "land cover", "land use", "elevation", "lidar", "aerial imagery", "agriculture"}
)
ELSEWHERE = re.compile(
    r"\b(africa|african|deafrica|australia|australian|aodn|canada|canadian|europe|european|"
    r"india|indian|brazil|brazilian|japan|japanese|ireland|irish|new zealand|united kingdom|"
    r"england|scotland|wales|germany|german|france|french|spain|spanish|italy|italian|"
    r"netherlands|dutch|switzerland|swiss|norway|denmark|finland|sweden|chile|peru|argentina|"
    r"colombia|mexico|china|chinese|korea|indonesia|philippines|antarctic|antarctica|arctic|"
    r"greenland|pacific islands|digital earth pacific|caribbean|amazonia|amazon basin|"
    r"amazon rainforest|tropics|tropical)\b"
)
# Field and airborne campaigns cover their study sites, not a whole country.
CAMPAIGN = re.compile(r"\b(campaign|field experiment|field study)\b")
OFF_EARTH = re.compile(
    r"\b(mars|martian|lunar|moon|europa|kaguya|mercury|titan|ganymede|asteroid|comet)\b"
)

US_STATES = (
    "alabama", "alaska", "arizona", "arkansas", "california", "colorado", "connecticut",
    "delaware", "florida", "georgia", "hawaii", "idaho", "illinois", "indiana", "iowa", "kansas",
    "kentucky", "louisiana", "maine", "maryland", "massachusetts", "michigan", "minnesota",
    "mississippi", "missouri", "montana", "nebraska", "nevada", "new hampshire", "new jersey",
    "new mexico", "new york", "north carolina", "north dakota", "ohio", "oklahoma", "oregon",
    "pennsylvania", "rhode island", "south carolina", "south dakota", "tennessee", "texas", "utah",
    "vermont", "virginia", "washington", "west virginia", "wisconsin", "wyoming", "puerto rico",
)


def _cache_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claysandbox" / "open-data-registry" / REGISTRY_COMMIT


def load_registry() -> dict[str, dict[str, Any]]:
    """``slug -> dataset YAML`` at the pinned commit, downloaded once and cached."""
    cache = _cache_dir()
    if not (cache / ".complete").exists():
        cache.mkdir(parents=True, exist_ok=True)
        with urllib.request.urlopen(TARBALL, timeout=120) as response:  # noqa: S310
            data = response.read()
        with tarfile.open(fileobj=io.BytesIO(data), mode="r:gz") as tar:
            for member in tar.getmembers():
                parts = Path(member.name).parts
                if len(parts) == 3 and parts[1] == "datasets" and parts[2].endswith(".yaml"):
                    handle = tar.extractfile(member)
                    if handle is not None:
                        (cache / parts[2]).write_bytes(handle.read())
        (cache / ".complete").write_text(REGISTRY_COMMIT)
    out: dict[str, dict[str, Any]] = {}
    for path in sorted(cache.glob("*.yaml")):
        try:
            doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        except yaml.YAMLError:
            continue
        if isinstance(doc, dict):
            out[path.stem] = doc
    return out


def _mentions_state(text: str, state: str) -> bool:
    return re.search(rf"\b{re.escape(state)}\b", text) is not None


def covers(slug: str, doc: dict[str, Any], state: str) -> bool:
    """Whether a registry dataset is in the T2 key for an AOI in ``state`` (rules 1-6 above)."""
    if doc.get("Deprecated"):
        return False
    tags = {str(t).lower() for t in doc.get("Tags") or []}
    if not tags & THEME_TAGS:
        return False
    if tags & OCEAN_TAGS and not tags & LAND_TAGS:
        return False  # ocean products don't cover a county
    if tags & NON_EARTH_TAGS:
        return False
    name = AGENCIES.sub(" ", f"{slug.replace('-', ' ').replace('_', ' ')} "
                             f"{doc.get('Name', '')} {' '.join(tags)}".lower())
    text = AGENCIES.sub(" ", f"{name} {doc.get('Description', '')}".lower())
    if OFF_EARTH.search(name):
        return False  # Mars, Moon, Europa ... products
    if ELSEWHERE.search(name):
        return False  # a regional product by its own name or tags (deafrica-*, *_australia)
    strong = (
        UNITED_STATES.search(text) is not None
        or STRONG_GLOBAL.search(text) is not None
        or GLOBAL.search(name) is not None
        or GLOBAL_MISSIONS.search(name) is not None
    )
    weak = GLOBAL.search(text) is not None
    state = state.lower()
    own_state = _mentions_state(text, state)
    other_state = any(
        _mentions_state(text, s) for s in US_STATES if s != state and s not in state
    )
    if CAMPAIGN.search(text):
        return own_state  # a campaign counts only if it names the AOI's state
    if ELSEWHERE.search(text) or other_state:
        return strong or own_state
    return strong or weak or own_state


def build(template: TaskTemplate, aoi: AOI, instance: TaskInstance) -> BuildResult:
    registry = load_registry()
    datasets = sorted(slug for slug, doc in registry.items() if covers(slug, doc, aoi.state))
    if not datasets:
        raise RuntimeError(f"no T2 datasets for {aoi.id}: check the filter")
    inputs: dict[str, Any] = {
        "registry": REGISTRY_REPO,
        "commit": REGISTRY_COMMIT,
        "datasets_read": len(registry),
        "theme_tags": sorted(THEME_TAGS),
        "filter_version": FILTER_VERSION,
        "state": aoi.state,
    }
    notes = [
        "Coverage is decided by keywords in each dataset's name and description (the registry "
        "has no coverage field), so the key has false positives and misses. T2 is scored by "
        "precision and recall@k; recall over the whole key is not meaningful.",
        "method script: not hand-curated (Task Author decision, 2026-11-04).",
    ]
    return BuildResult(
        output_reference={"datasets": datasets, "k": K},
        inputs=inputs,
        method="script",
        notes=notes,
    )
