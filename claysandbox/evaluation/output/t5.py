"""T5 output evaluator: ambiguous request, scored as a rule pass rate.

Output schema (WS2): ``{"assumptions": [str], "clarifying_question": str | null, "items": [str]}``.

Rules, each 0 or 1; the composite ``pass_rate`` is their mean:
  a. ``assumptions`` is non-empty or ``clarifying_question`` is a non-blank string.
  b. Every ID in ``items`` appears in the text of some ``tool_call`` ``result_preview`` or in
     its blob (``result_ref``). No items passes vacuously.
  c. If ``items`` are given, each is an imagery item intersecting the AOI. No items passes.

Reference keys assumed (built by WS2): ``output_reference["aoi_items"]``, a list of imagery item
IDs known to intersect the AOI (``imagery_items`` is accepted as an alias). When neither key is
present, rule c falls back to the IDs found in ``ok`` tool_call results whose capability is
``imagery_search``, since STAC search already filters by the AOI bbox.
"""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.registry import register
from claysandbox.contracts.trace import ToolCall, Trace

from ._common import OutputEvaluator, ParseError, id_list


def _result_texts(trace: Trace, only_capability: str | None = None) -> list[str]:
    texts: list[str] = []
    for e in trace.events:
        if not isinstance(e, ToolCall):
            continue
        if only_capability is not None and (e.capability != only_capability or e.status != "ok"):
            continue
        if e.result_preview:
            texts.append(e.result_preview)
        if e.result_ref:
            try:
                texts.append(trace.blob(e.result_ref).decode("utf-8", errors="replace"))
            except Exception:  # missing store or blob: the preview alone has to do
                pass
    return texts


@register("evaluator", "output.t5@1")
@register("evaluator", "output.t5")
class T5Evaluator(OutputEvaluator):
    name = "output.t5"
    metric_names = ("pass_rate", "rule_a", "rule_b", "rule_c")
    composite_metric = "pass_rate"

    def score(self, output, trace, manifest, reference, event_id):  # type: ignore[no-untyped-def]
        if not isinstance(output, dict):
            raise ParseError("expected an object")
        assumptions = output.get("assumptions") or []
        question = output.get("clarifying_question")
        items = id_list(output.get("items") or [], ("items",))

        rule_a = bool(assumptions) or (isinstance(question, str) and bool(question.strip()))
        texts = _result_texts(trace)
        found = [i for i in items if any(i in t for t in texts)]
        rule_b = len(found) == len(items)

        ref: dict[str, Any] = reference.output_reference
        valid = ref.get("aoi_items", ref.get("imagery_items"))
        if valid is not None:
            valid_set = set(id_list(valid, ("aoi_items",)))
            rule_c = all(i in valid_set for i in items)
        else:
            img = _result_texts(trace, "imagery_search")
            rule_c = all(any(i in t for t in img) for i in items)

        rules = {"rule_a": rule_a, "rule_b": rule_b, "rule_c": rule_c}
        metrics = {k: 1.0 if v else 0.0 for k, v in rules.items()}
        metrics["pass_rate"] = sum(metrics.values()) / 3
        notes = [f"{k} failed" for k, v in rules.items() if not v]
        return metrics, notes, []
