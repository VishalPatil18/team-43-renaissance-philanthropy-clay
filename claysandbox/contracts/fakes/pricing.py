"""Fixed price table fake (owner: WS1)."""

from __future__ import annotations


class FixedPriceTable:
    """Every model costs the same per 1 000 tokens. ``FixedPriceTable(0)`` is free."""

    version = "fixed-test"

    def __init__(self, input_per_1k: float = 0.0, output_per_1k: float = 0.0):
        self.input_per_1k = input_per_1k
        self.output_per_1k = output_per_1k

    def model_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        return input_tokens / 1000 * self.input_per_1k + output_tokens / 1000 * self.output_per_1k

    def data_cost(self, kind: str, amount: float) -> float:
        return 0.0

    def has(self, model_id: str) -> bool:
        return True
