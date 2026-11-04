"""T4 output evaluator: recall@k of predicted ``chips_id``s against the reference top-k.

Reference keys (built by WS2): ``output_reference["top_k"]`` is the ranked list of expected
chips, each a ``chips_id`` string or a dict with a ``chips_id`` field; k = its length.
Output: a bare list, or a dict holding the list under ``chips``, ``chips_id``, ``results``,
``top_k`` or ``items``; entries are ID strings or dicts with ``chips_id``.

Metric: ``recall_at_k`` = |first k distinct predicted IDs ∩ reference| / k. Order inside the
top k does not matter. An empty reference gives 1.0 (nothing to find).
"""

from __future__ import annotations

from claysandbox.contracts.registry import register

from ._common import OutputEvaluator, id_list

_KEYS = ("chips", "chips_id", "results", "top_k", "items")


@register("evaluator", "output.t4@1")
@register("evaluator", "output.t4")
class T4Evaluator(OutputEvaluator):
    name = "output.t4"
    metric_names = ("recall_at_k",)
    composite_metric = "recall_at_k"

    def score(self, output, trace, manifest, reference, event_id):  # type: ignore[no-untyped-def]
        expected = id_list(reference.output_reference.get("top_k", []), ("top_k",), "chips_id")
        k = len(expected)
        predicted = id_list(output, _KEYS, "chips_id")[:k]
        recall = 1.0 if k == 0 else len(set(predicted) & set(expected)) / k
        notes = [f"k={k}, {len(set(predicted) & set(expected))} of the top-k found"]
        return {"recall_at_k": recall}, notes, []
