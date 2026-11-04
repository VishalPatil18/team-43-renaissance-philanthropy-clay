"""Runs the fallback token-history SQL against real run folders with DuckDB (DD-022)."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import duckdb
import pytest

from claysandbox.runtime.estimate import query_token_history


class DuckStore:
    def __init__(self, root: Path) -> None:
        self.root = str(root)

    def query(self, sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        cur = duckdb.connect().execute(sql, params or {})
        names = [d[0] for d in cur.description]
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]


def write_run(
    root: Path,
    run_id: str,
    instance: str,
    model_id: str,
    harness: str,
    state: str,
    tokens: tuple[int, int],
) -> None:
    folder = root / run_id
    folder.mkdir(parents=True)
    (folder / "manifest.json").write_text(
        json.dumps(
            {
                "run_id": run_id,
                "task_instance_id": instance,
                "model": {"name": "bedrock", "params": {"model_id": model_id, "temperature": 0.2}},
                "harness": {"name": harness},
                "prompt": "x",
            }
        )
    )
    events = [
        {"type": "run_start", "run_id": run_id, "seq": 0, "task_instance_id": instance},
        {"type": "tool_call", "run_id": run_id, "seq": 1, "args": {"bbox": [1, 2, 3, 4]}},
        {"type": "model_call", "run_id": run_id, "seq": 2, "tool_use_requests": [{"a": {}}]},
        {
            "type": "run_end",
            "run_id": run_id,
            "seq": 3,
            "state": state,
            "totals": {"steps": 2, "input_tokens": tokens[0], "output_tokens": tokens[1]},
        },
    ]
    (folder / "trace.jsonl").write_text("\n".join(json.dumps(e) for e in events) + "\n")


@pytest.fixture
def runs(tmp_path: Path) -> Path:
    root = tmp_path / "runs"
    write_run(root, "a", "T1@us-ca-kern", "m1", "strands", "completed", (1000, 100))
    write_run(root, "b", "T1@us-tx-harris", "m1", "strands", "completed", (3000, 300))
    write_run(root, "c", "T1@us-ca-kern", "m1", "converse_loop", "completed", (7000, 700))
    write_run(root, "d", "T2@us-ca-kern", "m1", "strands", "completed", (9000, 900))
    write_run(root, "e", "T1@us-ca-kern", "m2", "strands", "completed", (9000, 900))
    write_run(root, "f", "T1@us-ca-kern", "m1", "strands", "budget_stopped", (9000, 900))
    return root


def test_sql_selects_completed_runs_for_template_model_and_harness(runs: Path) -> None:
    rows = query_token_history(DuckStore(runs), "T1", "m1", "strands")  # type: ignore[arg-type]
    assert sorted(rows) == [(1000, 100), (3000, 300)]


def test_sql_without_a_harness_includes_every_harness(runs: Path) -> None:
    rows = query_token_history(DuckStore(runs), "T1", "m1", None)  # type: ignore[arg-type]
    assert sorted(rows) == [(1000, 100), (3000, 300), (7000, 700)]


def test_sql_for_an_unknown_template_returns_nothing(runs: Path) -> None:
    assert query_token_history(DuckStore(runs), "T9", "m1", None) == []  # type: ignore[arg-type]
