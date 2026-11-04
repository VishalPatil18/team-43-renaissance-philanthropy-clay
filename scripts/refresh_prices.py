#!/usr/bin/env python3
"""Rebuild ``pricing/prices.yaml`` from the AWS Price List API (FR-11.10, PRI-R2-02).

* Queries service ``AmazonBedrock`` (Price List endpoint in us-east-1), filtered to us-west-2,
  for every model entry that has a ``price_list_model`` name. Only the Standard-tier input and
  output token prices are used (not batch, flex, priority or cache prices).
* Entries the API does not return (``source: manual``, such as Claude models) are kept as they are.
* Prints a diff. With ``--dry-run`` nothing is written. The file is never committed for you: a
  person reviews the diff and commits the new version.

    uv run python scripts/refresh_prices.py --dry-run
    uv run python scripts/refresh_prices.py
"""

from __future__ import annotations

import argparse
import copy
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml

DEFAULT_PATH = Path(__file__).resolve().parents[1] / "pricing" / "prices.yaml"
REGION_CODE = "us-west-2"
HEADER = """\
# Versioned price table (FR-11.10). Prices are USD per 1 000 tokens, Standard tier, us-west-2.
# Rebuild with: uv run python scripts/refresh_prices.py   (review the diff, then commit)
# Entries with `source: pricelist` come from the AWS Price List API. `source: manual` entries
# were typed from public pricing pages and are kept as they are by the refresh script.
"""


def fetch_model_price(client: Any, price_list_model: str) -> tuple[float, float] | None:
    """Return (input_per_1k, output_per_1k) for a Price List model name, or ``None``."""
    prices: dict[str, float] = {}
    token: str | None = None
    while True:
        kwargs: dict[str, Any] = {
            "ServiceCode": "AmazonBedrock",
            "Filters": [
                {"Type": "TERM_MATCH", "Field": "model", "Value": price_list_model},
                {"Type": "TERM_MATCH", "Field": "regionCode", "Value": REGION_CODE},
            ],
        }
        if token:
            kwargs["NextToken"] = token
        page = client.get_products(**kwargs)
        for raw in page.get("PriceList", []):
            product = json.loads(raw) if isinstance(raw, str) else raw
            usage = product["product"]["attributes"].get("usagetype", "")
            kind = (
                "input"
                if usage.endswith("-input-tokens")
                else "output"
                if usage.endswith("-output-tokens")
                else None
            )
            if kind is None:
                continue  # batch, flex, priority and cache usage types have longer suffixes
            for term in product["terms"]["OnDemand"].values():
                for dim in term["priceDimensions"].values():
                    if dim["unit"] == "1K tokens":
                        prices[kind] = float(dim["pricePerUnit"]["USD"])
        token = page.get("NextToken")
        if not token:
            break
    if "input" in prices and "output" in prices:
        return prices["input"], prices["output"]
    return None


def refresh(table: dict[str, Any], client: Any) -> tuple[dict[str, Any], list[str]]:
    """Return (new table, human-readable diff lines)."""
    new = copy.deepcopy(table)
    diff: list[str] = []
    for model_id, entry in new["models"].items():
        name = entry.get("price_list_model")
        if not name or entry.get("source") == "manual":
            continue
        found = fetch_model_price(client, name)
        if found is None:
            diff.append(f"  ! {model_id}: no Standard-tier price returned for {name!r}; kept")
            continue
        for field, value in zip(("input_per_1k", "output_per_1k"), found, strict=True):
            old = entry.get(field)
            if old != value:
                diff.append(f"  {model_id}.{field}: {old} -> {value}")
                entry[field] = value
    return new, diff


def next_version(current: str, today: str) -> str:
    date, _, serial = current.partition(".")
    if date == today and serial.isdigit():
        return f"{today}.{int(serial) + 1}"
    return f"{today}.1"


def write_table(table: dict[str, Any], path: Path) -> None:
    body = yaml.safe_dump(table, sort_keys=False, default_flow_style=False, allow_unicode=True)
    path.write_text(HEADER + body, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("--path", type=Path, default=DEFAULT_PATH)
    parser.add_argument("--dry-run", action="store_true", help="print the diff, write nothing")
    args = parser.parse_args(argv)

    import boto3

    client = boto3.client("pricing", region_name="us-east-1")
    table = yaml.safe_load(args.path.read_text(encoding="utf-8"))
    new, diff = refresh(table, client)

    today = datetime.now(UTC).strftime("%Y-%m-%d")
    print(f"Price table {table['version']} (retrieved {table['retrieved_at']})")
    if not diff:
        print("No price changes.")
        return 0
    print("Changes:")
    print("\n".join(diff))
    if any(not line.lstrip().startswith("!") for line in diff):
        new["version"] = next_version(str(table["version"]), today)
        new["retrieved_at"] = today
        print(f"New version: {new['version']}")
        if args.dry_run:
            print("Dry run: nothing written.")
        else:
            write_table(new, args.path)
            print(f"Wrote {args.path}. Review the diff with git and commit it.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
