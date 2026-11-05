"""Pre-flight cost estimate (FR-11.7 to FR-11.9, architecture §12, UC-03).

Tokens per planned run come from this fallback chain:

1. median input/output tokens of stored *completed* runs with the same (template, model, harness);
2. else the same (template, model);
3. else the template default in ``pricing/prices.yaml`` (``defaults.tokens_per_run``), labelled
   ``default_guess``.

Evaluation cost adds one summary call per run and ``k`` LLM-evaluator calls per run if the spec
configures them. Requester-Pays reads are added from ``defaults.requester_pays_gb_per_run``.
With the Fargate executor, vCPU and memory time (``defaults.run_seconds`` per run, a guess) is
added as compute cost (architecture §12).

History comes from ``store.token_history(template=, model_id=, harness=)`` when the store has it
(WS3's helper), else from ``store.query`` over the run folders. If neither works (for example no
runs exist yet) the estimate falls back to the defaults and says so.
"""

from __future__ import annotations

import logging
import re
import statistics
from typing import Any

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import RunRequest
from claysandbox.contracts.runtime import CostEstimate, CostLine, PriceTable
from claysandbox.contracts.store import RunStore

log = logging.getLogger(__name__)

# Used when neither history nor prices.yaml has a number. These are guesses, labelled as such.
FALLBACK_TOKENS_PER_RUN = 20_000
INPUT_SHARE = 0.85  # agent loops resend history, so most tokens are input
SUMMARY_TOKENS = (6_000, 800)
LLM_EVALUATOR_TOKENS = (8_000, 600)
FARGATE_RUN_SECONDS = 120  # guess when prices.yaml has no `run_seconds` default
DEFAULT_LLM_EVALUATOR_K = 3

_SAFE_ROOT = re.compile(r"^[\w./:\-]+$")

TOKEN_HISTORY_SQL = """
WITH ends AS (
  SELECT run_id,
         CAST(json_extract(totals, '$.input_tokens') AS BIGINT) AS input_tokens,
         CAST(json_extract(totals, '$.output_tokens') AS BIGINT) AS output_tokens
  FROM read_json('{root}/*/trace.jsonl', format = 'newline_delimited',
                 columns = {{run_id: 'VARCHAR', type: 'VARCHAR', state: 'VARCHAR', totals: 'JSON'}})
  WHERE type = 'run_end' AND state = 'completed'
), runs AS (
  SELECT run_id, task_instance_id, model.params.model_id AS model_id, harness.name AS harness
  FROM read_json_auto('{root}/*/manifest.json')
)
SELECT e.input_tokens AS input_tokens, e.output_tokens AS output_tokens
FROM ends e JOIN runs r USING (run_id)
WHERE r.model_id = $model_id
  AND starts_with(r.task_instance_id, $template_prefix)
  AND ($harness = '' OR r.harness = $harness)
  AND e.input_tokens IS NOT NULL AND e.output_tokens IS NOT NULL
"""


# LocalRunStore.query loads manifests and run_end totals into memory, then turns file access off,
# so its SQL must use those tables (store/query.py), not read_json on the run folders.
STORE_TOKEN_HISTORY_SQL = """
SELECT r.input_tokens AS input_tokens, r.output_tokens AS output_tokens
FROM manifests m JOIN run_ends r USING (run_id)
WHERE m.model_id = $model_id AND m.template = $template
  AND ($harness = '' OR m.harness_name = $harness)
  AND r.state = 'completed' AND r.input_tokens IS NOT NULL AND r.output_tokens IS NOT NULL
"""


def query_token_history(
    store: RunStore, template: str, model_id: str, harness: str | None
) -> list[tuple[int, int]]:
    """Input/output token totals of completed runs, newest information available."""
    helper = getattr(store, "token_history", None)
    if callable(helper):
        rows = helper(template=template, model_id=model_id, harness=harness)
        return [(int(i), int(o)) for i, o in rows]
    if hasattr(store, "run_dir"):  # LocalRunStore: query its in-memory tables
        rows = store.query(
            STORE_TOKEN_HISTORY_SQL,
            {"model_id": model_id, "template": template, "harness": harness or ""},
        )
        return [(int(r["input_tokens"]), int(r["output_tokens"])) for r in rows]
    root = str(getattr(store, "root", "runs"))
    if not _SAFE_ROOT.match(root):
        raise ConfigError(f"Unsafe store root for token history: {root!r}")
    rows = store.query(
        TOKEN_HISTORY_SQL.format(root=root),
        {"model_id": model_id, "template_prefix": f"{template}@", "harness": harness or ""},
    )
    return [(int(r["input_tokens"]), int(r["output_tokens"])) for r in rows]


class CostEstimator:
    def __init__(self, store: RunStore | None, prices: PriceTable) -> None:
        self.store = store
        self.prices = prices
        self._defaults: dict[str, Any] = dict(getattr(prices, "defaults", {}) or {})

    # -- public ---------------------------------------------------------------------------

    def estimate(self, requests: list[RunRequest], spec: Any) -> CostEstimate:
        notes: list[str] = []
        lines: list[CostLine] = []
        eval_cost_cache: dict[str, float] = {}
        for request in requests:
            lines.append(self._estimate_run(request, spec, notes, eval_cost_cache))

        per_config: dict[str, float] = {}
        for line in lines:
            per_config[line.config_name] = per_config.get(line.config_name, 0.0) + line.total_usd
        agent = sum(line.agent_usd for line in lines)
        evaluation = sum(line.evaluation_usd for line in lines)
        data = sum(line.data_usd for line in lines)
        compute = sum(line.compute_usd for line in lines)
        total = agent + evaluation + data + compute

        cap = _get(spec, "budget", "eval", "max_usd")
        if compute:
            notes.append("Fargate compute uses a default run duration (a guess).")
        if any(line.basis == "default_guess" for line in lines):
            notes.append("Some lines use default token guesses (no stored runs to learn from).")
        return CostEstimate(
            lines=lines,
            per_config=per_config,
            agent_usd=agent,
            evaluation_usd=evaluation,
            data_usd=data,
            compute_usd=compute,
            total_usd=total,
            price_table_version=self.prices.version,
            eval_cap_usd=cap,
            exceeds_eval_cap=cap is not None and total > cap,
            notes=list(dict.fromkeys(notes)),
        )

    # -- per run --------------------------------------------------------------------------

    def _estimate_run(
        self,
        request: RunRequest,
        spec: Any,
        notes: list[str],
        eval_cost_cache: dict[str, float],
    ) -> CostLine:
        model_id = request.model.params.get("model_id")
        if not model_id:
            raise ConfigError(f"Configuration {request.config_name!r} has no model_id")
        tokens_in, tokens_out, basis, samples = self._tokens(request, model_id, notes)
        agent = self.prices.model_cost(model_id, tokens_in, tokens_out)

        if request.template not in eval_cost_cache:
            eval_cost_cache[request.template] = self._evaluation_cost(spec, notes)
        data = self._data_cost(request.template)
        compute = self._compute_cost(spec)
        return CostLine(
            run_id=request.run_id,
            config_name=request.config_name,
            template=request.template,
            input_tokens=tokens_in,
            output_tokens=tokens_out,
            agent_usd=agent,
            evaluation_usd=eval_cost_cache[request.template],
            data_usd=data,
            compute_usd=compute,
            basis=basis,
            sample_size=samples,
        )

    def _tokens(
        self, request: RunRequest, model_id: str, notes: list[str]
    ) -> tuple[int, int, Any, int]:
        history_usable = self.store is not None
        for harness, basis in (
            (request.harness.name, "history_template_model_harness"),
            (None, "history_template_model"),
        ):
            if not history_usable:
                break
            try:
                rows = query_token_history(self.store, request.template, model_id, harness)  # type: ignore[arg-type]
            except Exception as exc:  # no runs yet, store without history, bad SQL...
                log.warning("Token history unavailable (%s); using defaults", exc)
                notes.append("Token history was unavailable; defaults were used.")
                history_usable = False
                break
            if rows:
                return (
                    round(statistics.median(r[0] for r in rows)),
                    round(statistics.median(r[1] for r in rows)),
                    basis,
                    len(rows),
                )
        total = int(
            (self._defaults.get("tokens_per_run") or {}).get(
                request.template, FALLBACK_TOKENS_PER_RUN
            )
        )
        share = float(self._defaults.get("input_share", INPUT_SHARE))
        tokens_in = round(total * share)
        return tokens_in, total - tokens_in, "default_guess", 0

    def _evaluation_cost(self, spec: Any, notes: list[str]) -> float:
        cost = 0.0
        summary = _get(spec, "summary")
        if summary is not None:
            tin, tout = self._pair("summary_tokens", SUMMARY_TOKENS)
            cost += self._call_cost(
                _get(summary, "params", "model_id"), tin, tout, "summary", notes
            )
        for evaluator in _get(spec, "evaluators") or []:
            if _get(evaluator, "name") != "llm_process":
                continue
            params = _get(evaluator, "params") or {}
            k = int(params.get("k", DEFAULT_LLM_EVALUATOR_K))
            tin, tout = self._pair("llm_evaluator_tokens", LLM_EVALUATOR_TOKENS)
            cost += k * self._call_cost(params.get("model_id"), tin, tout, "llm_process", notes)
        return cost

    def _call_cost(
        self, model_id: str | None, tin: int, tout: int, what: str, notes: list[str]
    ) -> float:
        if not model_id:
            notes.append(f"The {what} model has no model_id; its cost is not included.")
            return 0.0
        if not self.prices.has(model_id):
            notes.append(f"No price for the {what} model {model_id!r}; its cost is not included.")
            return 0.0
        return self.prices.model_cost(model_id, tin, tout)

    def _pair(self, key: str, fallback: tuple[int, int]) -> tuple[int, int]:
        value = self._defaults.get(key)
        if isinstance(value, dict) and "input" in value and "output" in value:
            return int(value["input"]), int(value["output"])
        return fallback

    def _data_cost(self, template: str) -> float:
        gb = (self._defaults.get("requester_pays_gb_per_run") or {}).get(template, 0.0)
        return self.prices.data_cost("s3_requester_pays_gb", float(gb)) if gb else 0.0

    def _compute_cost(self, spec: Any) -> float:
        """Fargate vCPU and memory time for one run, when the spec uses the Fargate executor."""
        if _get(spec, "executor", "name") != "fargate":
            return 0.0
        params = _get(spec, "executor", "params") or {}
        vcpus = float(params.get("vcpus", 1))
        gb = float(params.get("memory_gb", 2))
        hours = float(self._defaults.get("run_seconds", FARGATE_RUN_SECONDS)) / 3600
        return self.prices.data_cost("fargate_vcpu_hour", vcpus * hours) + self.prices.data_cost(
            "fargate_gb_hour", gb * hours
        )


def _get(obj: Any, *path: str) -> Any:
    """Read ``obj.a.b`` or ``obj['a']['b']``; ``None`` if any step is missing."""
    for key in path:
        if obj is None:
            return None
        obj = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return obj
