"""DuckDB queries over the run store (SHI-R2-03, DD-022, arch §13.3, NFR-PERF-3). Owner: WS3.

``open_connection(store)`` loads the store's JSON files into in-memory tables, then turns
file access off and locks the configuration. Whatever SQL a caller then runs can read only
those tables: it cannot open files, write files or re-enable access. Callers pass values as
named parameters (``$name``), never by building SQL strings.

Tables (explicit column types, so manifests of different shapes or versions still load; a
missing key is NULL, and ``union_by_name`` style inference is never relied on):

* ``manifests``   one row per run: ids, task instance, ``template``, ``model_id``,
                  ``harness_name``, ``toolset_name`` and the raw component JSON.
* ``status``      ``status.json`` per run: ``state``, ``attempt``, ``incomplete``.
* ``assessments`` one row per assessment file: ``kind``, ``composite``, ``success``, ...
* ``run_ends``    the ``run_end`` event of each ``trace.jsonl``: ``state`` and token totals.

``template`` is the part of ``task_instance_id`` before the first ``:`` (for example
``T1:us-ca-kern`` gives ``T1``). That ID convention belongs to WS2; adjust ``TEMPLATE_SEP``
if it changes.

Runs in read-only roots (``samples/``) and in the writable root are merged; the writable
root wins when a file exists in both.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Any

from claysandbox.contracts.errors import ConfigError

if TYPE_CHECKING:
    import duckdb

    from .local import LocalRunStore

TEMPLATE_SEP = ":"

# column name -> DuckDB type. Only these keys are read; anything else in the file is ignored.
_MANIFEST_COLS = {
    "run_id": "VARCHAR",
    "eval_id": "VARCHAR",
    "trial_index": "BIGINT",
    "attempt": "BIGINT",
    "task_instance_id": "VARCHAR",
    "task_reference_version": "VARCHAR",
    "started_at": "VARCHAR",
    "model": "JSON",
    "harness": "JSON",
    "toolset": "JSON",
    "tracer": "JSON",
    "executor": "JSON",
}
_STATUS_COLS = {
    "state": "VARCHAR",
    "updated_at": "VARCHAR",
    "attempt": "BIGINT",
    "incomplete": "BOOLEAN",
}
_ASSESSMENT_COLS = {
    "assessment_id": "VARCHAR",
    "run_id": "VARCHAR",
    "kind": "VARCHAR",
    "task_reference_version": "VARCHAR",
    "composite": "DOUBLE",
    "success": "BOOLEAN",
    "evaluator": "JSON",
    "metrics": "JSON",
    "cost_usd": "DOUBLE",
    "created_at": "VARCHAR",
}
_TRACE_COLS = {"type": "VARCHAR", "run_id": "VARCHAR", "state": "VARCHAR", "totals": "JSON"}

# Filters that list_runs accepts. The *column* comes from this whitelist, the *value* is bound.
LIST_FILTERS = ("eval_id", "state", "template", "model_id", "harness_name", "toolset_name")


def _cols(cols: dict[str, str]) -> str:
    return "{" + ", ".join(f"'{k}': '{v}'" for k, v in cols.items()) + "}"


def _roots(store: LocalRunStore) -> list[Path]:
    return [*store.read_roots, store.root]  # later roots override earlier ones


def _one_per_run(store: LocalRunStore, filename: str) -> list[str]:
    """``<root>/<run_id>/<filename>`` across all roots, the writable root winning."""
    chosen: dict[str, str] = {}
    for root in _roots(store):
        for p in sorted(root.glob(f"*/{filename}")):
            chosen[p.parent.name] = str(p)
    return list(chosen.values())


def _assessment_files(store: LocalRunStore) -> list[str]:
    chosen: dict[tuple[str, str], str] = {}
    for root in _roots(store):
        for p in sorted(root.glob("*/assessments/*.json")):
            chosen[(p.parent.parent.name, p.name)] = str(p)
    return list(chosen.values())


def _load(
    con: duckdb.DuckDBPyConnection,
    table: str,
    files: list[str],
    cols: dict[str, str],
    select: str,
    *,
    filename: bool = False,
    where: str = "",
) -> None:
    """Create ``table`` from the JSON ``files``, or an empty table of the same shape.

    The file list is bound as a parameter (an empty glob would raise instead of returning no
    rows). ``ignore_errors`` skips a truncated last line, so one crashed run cannot break a
    query. ``filename`` adds the source path as a column.
    """
    source_cols = {**cols, "filename": "VARCHAR"} if filename else cols
    if not files:
        dummy = ", ".join(f"NULL::{t} AS {k}" for k, t in source_cols.items())
        con.execute(f"CREATE TABLE {table} AS SELECT {select} FROM (SELECT {dummy}) WHERE false")
        return
    options = f"columns={_cols(cols)}, ignore_errors=true" + (", filename=true" if filename else "")
    con.execute(
        f"CREATE TABLE {table} AS SELECT {select} FROM read_json($files, {options}) {where}",
        {"files": files},
    )


def open_connection(store: LocalRunStore) -> duckdb.DuckDBPyConnection:
    # Imported here, not at module level: the Docker image installs without the dev group, and
    # workers only write runs. Only code that actually runs SQL needs DuckDB.
    try:
        import duckdb
    except ImportError:
        raise ConfigError(
            "querying the run store needs the 'duckdb' package; add it to the project "
            "dependencies (it is currently only in the dev group)",
            kind="missing_dependency",
        ) from None
    con = duckdb.connect(":memory:")

    _load(
        con,
        "manifests",
        _one_per_run(store, "manifest.json"),
        _MANIFEST_COLS,
        "run_id, eval_id, trial_index, attempt, task_instance_id, task_reference_version, "
        "started_at, "
        f"split_part(task_instance_id, '{TEMPLATE_SEP}', 1) AS template, "
        "json_extract_string(model, '$.params.model_id') AS model_id, "
        "json_extract_string(harness, '$.name') AS harness_name, "
        "json_extract_string(toolset, '$.name') AS toolset_name, "
        "model, harness, toolset, tracer, executor",
    )

    # status.json has no run_id of its own: it is the folder name.
    status_files = _one_per_run(store, "status.json")
    _load(
        con,
        "status",
        status_files,
        _STATUS_COLS,
        "regexp_extract(filename, '([^/]+)/status\\.json$', 1) AS run_id, "
        "state, updated_at, attempt, incomplete",
        filename=True,
    )

    _load(
        con,
        "assessments",
        _assessment_files(store),
        _ASSESSMENT_COLS,
        "assessment_id, run_id, kind, task_reference_version, composite, success, "
        "json_extract_string(evaluator, '$.name') AS evaluator_name, "
        "json_extract_string(evaluator, '$.version') AS evaluator_version, "
        "metrics, cost_usd, created_at",
    )

    _load(
        con,
        "run_ends",
        _one_per_run(store, "trace.jsonl"),
        _TRACE_COLS,
        "run_id, state, "
        "TRY_CAST(json_extract_string(totals, '$.input_tokens') AS BIGINT) AS input_tokens, "
        "TRY_CAST(json_extract_string(totals, '$.output_tokens') AS BIGINT) AS output_tokens, "
        "TRY_CAST(json_extract_string(totals, '$.cost_usd') AS DOUBLE) AS cost_usd, "
        "TRY_CAST(json_extract_string(totals, '$.steps') AS BIGINT) AS steps, "
        "TRY_CAST(json_extract_string(totals, '$.wall_ms') AS DOUBLE) AS wall_ms",
        where="WHERE type = 'run_end'",
    )

    # Everything the caller may read is now in memory. From here on no SQL can touch files.
    con.execute("SET enable_external_access = false")
    con.execute("SET lock_configuration = true")
    return con


def run_query(store: LocalRunStore, sql: str, params: dict[str, Any] | None = None) -> list[dict]:
    con = open_connection(store)
    try:
        cur = con.execute(sql, params or {})
        names = [d[0] for d in cur.description] if cur.description else []
        return [dict(zip(names, row, strict=True)) for row in cur.fetchall()]
    finally:
        con.close()


# ---------------------------------------------------------------- helpers for other workstreams
def runs_for_eval(store: LocalRunStore, eval_id: str) -> list[dict]:
    """Manifest essentials plus lifecycle state of every run in an eval."""
    return store.query(
        "SELECT m.run_id, m.eval_id, m.trial_index, m.attempt, m.task_instance_id, m.template, "
        "m.model_id, m.harness_name, m.toolset_name, s.state, s.incomplete "
        "FROM manifests m LEFT JOIN status s USING (run_id) "
        "WHERE m.eval_id = $eval_id ORDER BY m.trial_index, m.run_id",
        {"eval_id": eval_id},
    )


def assessments_for_eval(store: LocalRunStore, eval_id: str, kind: str | None = None) -> list[dict]:
    """Assessments of every run in an eval, optionally one kind (workflow, output, process)."""
    return store.query(
        "SELECT a.*, m.template, m.model_id, m.harness_name, m.toolset_name, m.task_instance_id "
        "FROM assessments a JOIN manifests m USING (run_id) "
        "WHERE m.eval_id = $eval_id AND ($kind IS NULL OR a.kind = $kind) "
        "ORDER BY a.run_id, a.created_at",
        {"eval_id": eval_id, "kind": kind},
    )


def token_history(
    store: LocalRunStore, template: str, model_id: str, harness: str | None = None
) -> dict[str, Any]:
    """Median input and output tokens of completed runs, for the pre-flight cost estimate.

    ``n`` is the number of runs behind the medians (0 means no history: the medians are None
    and the estimator should fall back to its default and say so).
    """
    rows = store.query(
        "SELECT count(*) AS n, median(r.input_tokens) AS input_tokens, "
        "median(r.output_tokens) AS output_tokens "
        "FROM manifests m JOIN run_ends r USING (run_id) "
        "WHERE m.template = $template AND m.model_id = $model_id "
        "AND ($harness IS NULL OR m.harness_name = $harness) "
        "AND r.state = 'completed' AND r.input_tokens IS NOT NULL",
        {"template": template, "model_id": model_id, "harness": harness},
    )
    return rows[0]


def list_runs(
    store: LocalRunStore,
    filters: dict[str, Any] | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """Runs for the API and the Runs screen, newest first. Unknown filters are an error."""
    filters = filters or {}
    unknown = set(filters) - set(LIST_FILTERS)
    if unknown:
        raise ValueError(f"unknown filter(s) {sorted(unknown)}; allowed: {list(LIST_FILTERS)}")
    # Column names come from the whitelist above, never from the caller; values are bound.
    where = "".join(f" AND {col} = ${col}" for col in LIST_FILTERS if col in filters)
    return store.query(
        "SELECT m.run_id, m.eval_id, m.trial_index, m.task_instance_id, m.template, "
        "m.model_id, m.harness_name, m.toolset_name, m.started_at, s.state, s.incomplete "
        "FROM manifests m LEFT JOIN status s USING (run_id) "
        f"WHERE true{where} "
        "ORDER BY m.started_at DESC NULLS LAST, m.run_id LIMIT $limit OFFSET $offset",
        {**filters, "limit": max(0, int(limit)), "offset": max(0, int(offset))},
    )
