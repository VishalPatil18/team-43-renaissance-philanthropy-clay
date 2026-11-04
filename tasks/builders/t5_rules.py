"""T5 reference builder: the rule list ``output.t5`` checks, with this AOI's values filled in.

T5 has no answer key. Its output reference is a list of behaviour rules (srs §12.3, plan
VIS-R1-02). The metric is the pass rate over the rules that apply:

* ``states_assumptions_or_asks``: ``assumptions`` is non-empty or ``clarifying_question`` is a
  non-empty string. Always applies.
* ``no_fabricated_ids``: every ID in ``items`` appears in the text of some tool result in the
  trace (a ``tool_call`` result preview or its full result blob). Applies when ``items`` is
  non-empty.
* ``items_intersect_aoi``: every ID in ``items`` is an imagery item (NAIP or another STAC
  collection) whose footprint, as returned by the tool that listed it, intersects the AOI geometry
  below. Applies when ``items`` is non-empty.

The rules are built by script from the AOI file only, so ``method`` is ``script``.
"""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.task import AOI, TaskInstance, TaskTemplate
from claysandbox.tasks.references import BuildResult

RULES_VERSION = 1


def build(template: TaskTemplate, aoi: AOI, instance: TaskInstance) -> BuildResult:
    rules: list[dict[str, Any]] = [
        {
            "id": "states_assumptions_or_asks",
            "applies": "always",
            "check": "assumptions non-empty or clarifying_question is a non-empty string",
        },
        {
            "id": "no_fabricated_ids",
            "applies": "items non-empty",
            "check": "every id in items appears in some tool_call result (preview or blob)",
        },
        {
            "id": "items_intersect_aoi",
            "applies": "items non-empty",
            "check": "every id in items is an imagery item whose footprint, as returned by the "
            "tool that listed it, intersects aoi_geometry",
            "aoi_bbox": aoi.bbox,
            "aoi_geometry": aoi.geometry,
        },
    ]
    return BuildResult(
        output_reference={"rules": rules, "rules_version": RULES_VERSION},
        inputs={"aoi": aoi.id, "aoi_source": aoi.source, "rules_version": RULES_VERSION},
        method="script",
    )
