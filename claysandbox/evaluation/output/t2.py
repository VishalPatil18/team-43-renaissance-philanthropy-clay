"""T2 output evaluator: RODA dataset slugs against the reference slugs.

Reference keys (built by WS2): ``output_reference["datasets"]`` is a list of slug strings.
Output: ``{"datasets": [str]}`` (or a bare list). Metrics and edge cases as in ``t1``.
"""

from __future__ import annotations

from claysandbox.contracts.registry import register

from .t1 import SetIdEvaluator


@register("evaluator", "output.t2@1")
@register("evaluator", "output.t2")
class T2Evaluator(SetIdEvaluator):
    name = "output.t2"
    keys = ("datasets",)
