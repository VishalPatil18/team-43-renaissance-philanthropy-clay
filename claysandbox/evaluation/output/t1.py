"""T1 output evaluator: NAIP item IDs against the reference item IDs.

Reference keys (built by WS2): ``output_reference["items"]`` is a list of item ID strings.
Output: ``{"items": [str]}`` (or a bare list). Metrics: precision, recall, f1 on the ID sets
(case-sensitive, trimmed, de-duplicated). Composite is F1.

Empty-set edge cases: an empty side is vacuously perfect for its own metric, so
reference=[] and output=[] gives P=R=F1=1; reference=[] with output gives P=0, R=1, F1=0;
output=[] with a non-empty reference gives P=1, R=0, F1=0.
"""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.registry import register

from ._common import OutputEvaluator, f1, id_list, precision_recall


class SetIdEvaluator(OutputEvaluator):
    metric_names = ("precision", "recall", "f1")
    composite_metric = "f1"
    keys: tuple[str, ...] = ("items",)

    def score(self, output, trace, manifest, reference, event_id):  # type: ignore[no-untyped-def]
        predicted = set(id_list(output, self.keys))
        expected = set(id_list(reference.output_reference, self.keys))
        p, r = precision_recall(len(predicted & expected), len(predicted), len(expected))
        metrics: dict[str, float] = {"precision": p, "recall": r, "f1": f1(p, r)}
        notes: list[str] = []
        if predicted - expected:
            notes.append(f"{len(predicted - expected)} output ID(s) not in the reference")
        if expected - predicted:
            notes.append(f"{len(expected - predicted)} reference ID(s) missing from the output")
        return metrics, notes, []


@register("evaluator", "output.t1@1")
@register("evaluator", "output.t1")
class T1Evaluator(SetIdEvaluator):
    name = "output.t1"
    keys = ("items",)


__all__: list[Any] = ["T1Evaluator", "SetIdEvaluator"]
