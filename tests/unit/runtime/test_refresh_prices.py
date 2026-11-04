from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
import yaml

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "refresh_prices.py"
spec = importlib.util.spec_from_file_location("refresh_prices", SCRIPT)
assert spec and spec.loader
refresh_prices = importlib.util.module_from_spec(spec)
spec.loader.exec_module(refresh_prices)


def product(usage: str, usd: str, unit: str = "1K tokens") -> str:
    return json.dumps(
        {
            "product": {"attributes": {"usagetype": usage}},
            "terms": {
                "OnDemand": {
                    "t": {"priceDimensions": {"d": {"unit": unit, "pricePerUnit": {"USD": usd}}}}
                }
            },
        }
    )


class FakePricing:
    """Returns Price List style pages, including the batch/flex/cache lines to be ignored."""

    def __init__(self, models: dict[str, list[str]], paged: bool = False) -> None:
        self.models = models
        self.paged = paged
        self.requests: list[dict[str, Any]] = []

    def get_products(self, **kwargs: Any) -> dict[str, Any]:
        self.requests.append(kwargs)
        model = next(f["Value"] for f in kwargs["Filters"] if f["Field"] == "model")
        items = self.models.get(model, [])
        if self.paged and "NextToken" not in kwargs:
            return {"PriceList": items[:1], "NextToken": "page2"}
        return {"PriceList": items[1:] if self.paged else items}


def lite(inp: str = "0.00006", out: str = "0.00024") -> list[str]:
    return [
        product("USW2-NovaLite-input-tokens", inp),
        product("USW2-NovaLite-input-tokens-batch", "0.00003"),
        product("USW2-NovaLite-output-tokens", out),
        product("USW2-NovaLite-output-tokens-batch", "0.00012"),
        product("USW2-NovaLite-cache-read-input-token-count", "0.000015"),
        product("USW2-NovaLite-Customization-Storage", "1.95", unit="Model/month"),
    ]


TABLE: dict[str, Any] = {
    "version": "2026-11-04.1",
    "retrieved_at": "2026-11-04",
    "models": {
        "lite": {
            "input_per_1k": 0.00006,
            "output_per_1k": 0.00024,
            "source": "pricelist",
            "price_list_model": "Nova Lite",
        },
        "alias": {"alias_of": "lite", "source": "manual"},
        "claude": {"input_per_1k": 0.003, "output_per_1k": 0.015, "source": "manual"},
    },
}


def test_standard_input_and_output_prices_are_picked_and_other_tiers_ignored() -> None:
    assert refresh_prices.fetch_model_price(FakePricing({"Nova Lite": lite()}), "Nova Lite") == (
        0.00006,
        0.00024,
    )


def test_pagination_is_followed() -> None:
    client = FakePricing({"Nova Lite": lite()}, paged=True)
    assert refresh_prices.fetch_model_price(client, "Nova Lite") == (0.00006, 0.00024)
    assert len(client.requests) == 2
    assert {"Type": "TERM_MATCH", "Field": "regionCode", "Value": "us-west-2"} in client.requests[
        0
    ]["Filters"]


def test_unchanged_prices_give_an_empty_diff() -> None:
    new, diff = refresh_prices.refresh(TABLE, FakePricing({"Nova Lite": lite()}))
    assert diff == [] and new == TABLE


def test_changed_prices_are_reported_and_manual_entries_are_kept() -> None:
    new, diff = refresh_prices.refresh(TABLE, FakePricing({"Nova Lite": lite("0.0001", "0.00024")}))
    assert diff == ["  lite.input_per_1k: 6e-05 -> 0.0001"]
    assert new["models"]["lite"]["input_per_1k"] == 0.0001
    assert new["models"]["claude"] == TABLE["models"]["claude"]
    assert new["models"]["alias"] == TABLE["models"]["alias"]
    assert TABLE["models"]["lite"]["input_per_1k"] == 0.00006  # the input table is not mutated


def test_a_model_the_api_does_not_return_is_kept_and_flagged() -> None:
    new, diff = refresh_prices.refresh(TABLE, FakePricing({}))
    assert len(diff) == 1 and diff[0].lstrip().startswith("!") and "Nova Lite" in diff[0]
    assert new["models"]["lite"] == TABLE["models"]["lite"]


def test_version_numbers() -> None:
    assert refresh_prices.next_version("2026-11-04.1", "2026-11-04") == "2026-11-04.2"
    assert refresh_prices.next_version("2026-11-04.9", "2026-11-05") == "2026-11-05.1"
    assert refresh_prices.next_version("weird", "2026-11-05") == "2026-11-05.1"


def run_main(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, client: Any, *args: str
) -> tuple[int, str]:
    path = tmp_path / "prices.yaml"
    path.write_text(yaml.safe_dump(TABLE, sort_keys=False))
    import boto3

    monkeypatch.setattr(boto3, "client", lambda *a, **k: client)
    return refresh_prices.main(["--path", str(path), *args]), path.read_text()


def test_dry_run_prints_a_diff_and_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    before = yaml.safe_dump(TABLE, sort_keys=False)
    code, after = run_main(
        tmp_path, monkeypatch, FakePricing({"Nova Lite": lite("0.0001")}), "--dry-run"
    )
    out = capsys.readouterr().out
    assert code == 0 and after == before
    assert (
        "lite.input_per_1k" in out and "Dry run: nothing written" in out and "New version:" in out
    )


def test_a_real_run_writes_a_new_version_the_price_table_can_load(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from claysandbox.runtime.pricing import YamlPriceTable

    code, after = run_main(tmp_path, monkeypatch, FakePricing({"Nova Lite": lite("0.0001")}))
    assert code == 0 and after.startswith("# Versioned price table")
    prices = YamlPriceTable({"path": str(tmp_path / "prices.yaml")})
    assert prices.version != "2026-11-04.1"
    assert prices.model_cost("lite", 1000, 0) == pytest.approx(0.0001)
    assert prices.has("alias") and prices.model_cost("claude", 1000, 0) == pytest.approx(0.003)


def test_no_change_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _ = run_main(tmp_path, monkeypatch, FakePricing({"Nova Lite": lite()}))
    assert code == 0 and "No price changes" in capsys.readouterr().out
