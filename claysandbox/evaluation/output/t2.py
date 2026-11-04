"""T2 output evaluator: RODA dataset slugs against the reference slugs.

Reference keys (built by WS2): ``output_reference["datasets"]`` is a list of slug strings;
``output_reference["k"]`` (optional) is how many slugs the prompt asks for.
Output: ``{"datasets": [str]}`` (or a bare list). Metrics and edge cases as in ``t1``, except:

* With ``k`` set (the T2 keys hold ~120 script-built candidates and the agent is asked for at
  most ``k`` = 10), recall is recall@k: matched slugs among the first ``k`` distinct output slugs
  ÷ min(k, reference size). Precision stays matched ÷ all output slugs, so padding past ``k``
  with wrong slugs still costs precision. F1 combines the two.
* Without ``k``, recall is over the whole reference, as in ``t1``.
"""

from __future__ import annotations

from typing import Any

from claysandbox.contracts.registry import register

from ._common import f1, id_list
from .t1 import SetIdEvaluator


@register("evaluator", "output.t2@1")
@register("evaluator", "output.t2")
class T2Evaluator(SetIdEvaluator):
    name = "output.t2"
    keys = ("datasets",)

    def score(self, output, trace, manifest, reference, event_id):  # type: ignore[no-untyped-def]
        metrics, notes, evidence = super().score(output, trace, manifest, reference, event_id)
        k: Any = reference.output_reference.get("k")
        if not isinstance(k, int) or isinstance(k, bool) or k <= 0:
            return metrics, notes, evidence
        expected = set(id_list(reference.output_reference, self.keys))
        first_k = id_list(output, self.keys)[:k]
        hits = len(set(first_k) & expected)
        denominator = min(k, len(expected))
        recall = 1.0 if denominator == 0 else hits / denominator
        metrics["recall"] = recall
        metrics["f1"] = f1(metrics["precision"], recall)
        notes.append(f"recall@{k}: {hits} of min({k}, {len(expected)}) reference slugs found")
        return metrics, notes, evidence
