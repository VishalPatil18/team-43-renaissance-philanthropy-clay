"""Versioned price table (architecture §12, FR-2.3, FR-11.10).

``pricing/prices.yaml`` lists per-1 000-token model prices, data prices, Fargate rates, a
``version`` and a ``retrieved_at`` date. A model entry may say ``alias_of: <model id>`` so a
cross-region inference profile ID uses the prices of the underlying model.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, ValidationError

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.registry import register

DEFAULT_PRICES_PATH = Path(__file__).resolve().parents[2] / "pricing" / "prices.yaml"


class ModelPrice(BaseModel):
    input_per_1k: float | None = Field(default=None, ge=0)
    output_per_1k: float | None = Field(default=None, ge=0)
    alias_of: str | None = None
    source: str = "manual"
    price_list_model: str | None = None
    note: str | None = None


class PriceFile(BaseModel):
    version: str
    retrieved_at: str
    currency: str = "USD"
    models: dict[str, ModelPrice] = Field(default_factory=dict)
    data: dict[str, float] = Field(default_factory=dict)
    fargate: dict[str, float] = Field(default_factory=dict)
    defaults: dict[str, Any] = Field(default_factory=dict)


# kind -> (section, key). ``amount`` is in the unit named by the key.
_DATA_KINDS: dict[str, tuple[str, str]] = {
    "s3_requester_pays_gb": ("data", "s3_requester_pays_per_gb"),
    "fargate_vcpu_hour": ("fargate", "vcpu_hour"),
    "fargate_gb_hour": ("fargate", "gb_hour"),
}


@register("pricing", "yaml")
class YamlPriceTable:
    name = "yaml"
    version: str

    class Params(BaseModel):
        path: str | None = None

    def __init__(self, params: dict[str, Any] | str | Path | None = None) -> None:
        if isinstance(params, (str, Path)):
            path = Path(params)
        else:
            path = Path(p) if params and (p := params.get("path")) else DEFAULT_PRICES_PATH
        try:
            raw = yaml.safe_load(path.read_text(encoding="utf-8"))
            self._file = PriceFile.model_validate(raw)
        except FileNotFoundError:
            raise ConfigError(f"Price table not found: {path}", kind="price_table") from None
        except (yaml.YAMLError, ValidationError, TypeError) as exc:
            raise ConfigError(f"Price table {path} is invalid: {exc}", kind="price_table") from exc
        self.path = path
        self.version = self._file.version
        self.retrieved_at = self._file.retrieved_at

    @property
    def defaults(self) -> dict[str, Any]:
        return self._file.defaults

    def _entry(self, model_id: str) -> ModelPrice:
        seen: set[str] = set()
        current = model_id
        while True:
            entry = self._file.models.get(current)
            if entry is None:
                raise ConfigError(
                    f"No price for model {model_id!r} in price table {self.version}",
                    kind="price_missing",
                )
            if entry.alias_of is None:
                return entry
            if current in seen:
                raise ConfigError(f"Price alias loop at {current!r}", kind="price_table")
            seen.add(current)
            current = entry.alias_of

    def has(self, model_id: str) -> bool:
        try:
            self._entry(model_id)
        except ConfigError:
            return False
        return True

    def model_cost(self, model_id: str, input_tokens: int, output_tokens: int) -> float:
        entry = self._entry(model_id)
        if entry.input_per_1k is None or entry.output_per_1k is None:
            raise ConfigError(f"Price for {model_id!r} is incomplete", kind="price_missing")
        return input_tokens / 1000 * entry.input_per_1k + output_tokens / 1000 * entry.output_per_1k

    def data_cost(self, kind: str, amount: float) -> float:
        try:
            section, key = _DATA_KINDS[kind]
        except KeyError:
            raise ConfigError(f"Unknown data cost kind {kind!r}", kind="price_missing") from None
        rates = self._file.data if section == "data" else self._file.fargate
        return amount * rates.get(key, 0.0)
