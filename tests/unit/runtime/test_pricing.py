from __future__ import annotations

from pathlib import Path

import pytest

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.runtime import PriceTable
from claysandbox.runtime.pricing import DEFAULT_PRICES_PATH, YamlPriceTable

SAMPLE = """
version: "2026-01-01.1"
retrieved_at: "2026-01-01"
models:
  base:  {input_per_1k: 0.001, output_per_1k: 0.002}
  profile: {alias_of: base}
  chain: {alias_of: profile}
  loop_a: {alias_of: loop_b}
  loop_b: {alias_of: loop_a}
  half:  {input_per_1k: 0.001}
data: {s3_requester_pays_per_gb: 0.09}
fargate: {vcpu_hour: 0.04, gb_hour: 0.005}
defaults: {tokens_per_run: {T1: 1}}
"""


def table(tmp_path: Path, text: str = SAMPLE) -> YamlPriceTable:
    path = tmp_path / "prices.yaml"
    path.write_text(text)
    return YamlPriceTable({"path": str(path)})


def test_model_cost_is_per_1k_tokens(tmp_path: Path) -> None:
    prices = table(tmp_path)
    assert isinstance(prices, PriceTable)
    assert prices.version == "2026-01-01.1"
    assert prices.model_cost("base", 2000, 500) == pytest.approx(2 * 0.001 + 0.5 * 0.002)
    assert prices.model_cost("base", 0, 0) == 0


def test_aliases_use_the_underlying_prices_even_through_a_chain(tmp_path: Path) -> None:
    prices = table(tmp_path)
    assert prices.model_cost("chain", 1000, 1000) == prices.model_cost("base", 1000, 1000)
    assert prices.has("profile") and prices.has("chain")


def test_unknown_alias_loops_and_incomplete_entries_fail_clearly(tmp_path: Path) -> None:
    prices = table(tmp_path)
    assert not prices.has("nope") and not prices.has("loop_a")
    with pytest.raises(ConfigError, match="No price for model 'nope'"):
        prices.model_cost("nope", 1, 1)
    with pytest.raises(ConfigError, match="alias loop"):
        prices.model_cost("loop_a", 1, 1)
    with pytest.raises(ConfigError, match="incomplete"):
        prices.model_cost("half", 1, 1)


def test_data_and_fargate_costs(tmp_path: Path) -> None:
    prices = table(tmp_path)
    assert prices.data_cost("s3_requester_pays_gb", 10) == pytest.approx(0.9)
    assert prices.data_cost("fargate_vcpu_hour", 2) == pytest.approx(0.08)
    assert prices.data_cost("fargate_gb_hour", 4) == pytest.approx(0.02)
    with pytest.raises(ConfigError):
        prices.data_cost("teleportation", 1)


def test_missing_and_invalid_files_are_config_errors(tmp_path: Path) -> None:
    with pytest.raises(ConfigError, match="not found"):
        YamlPriceTable({"path": str(tmp_path / "missing.yaml")})
    with pytest.raises(ConfigError, match="invalid"):
        table(tmp_path, "version: 1\nmodels: [not, a, mapping]")
    with pytest.raises(ConfigError, match="invalid"):
        table(tmp_path, ": : :")


def test_the_committed_price_table_covers_the_confirmed_models() -> None:
    prices = YamlPriceTable()
    assert prices.path == DEFAULT_PRICES_PATH
    for model_id in (
        "us.amazon.nova-lite-v1:0",
        "amazon.nova-lite-v1:0",
        "us.amazon.nova-pro-v1:0",
        "us.anthropic.claude-sonnet-4-6",
        "us.meta.llama3-3-70b-instruct-v1:0",
    ):
        assert prices.has(model_id), model_id
    assert prices.model_cost("us.amazon.nova-lite-v1:0", 1_000_000, 1_000_000) == pytest.approx(
        0.06 + 0.24
    )
    assert prices.model_cost("us.anthropic.claude-sonnet-4-6", 1_000_000, 1_000_000) > 10
    assert prices.defaults["tokens_per_run"]["T1"] > 0
