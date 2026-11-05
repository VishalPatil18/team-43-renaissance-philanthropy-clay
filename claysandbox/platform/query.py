"""``clay-sandbox query``: your own question, on one or more models, as a small evaluation.

The question becomes one custom task (``tasks.custom``); each ``--model`` becomes one
configuration (the first is the baseline, the others are model variants), so the eval report
compares them like any other evaluation and every run is browsable in the UI.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import TERMINAL_STATES
from claysandbox.contracts.spec import EvalSpec
from claysandbox.contracts.trace import FinalOutput, RunEnd
from claysandbox.platform import custom
from claysandbox.store.local import LocalRunStore


def config_name(model_id: str) -> str:
    """``us.amazon.nova-pro-v1:0`` -> ``nova-pro-v1``: short, readable configuration names."""
    name = model_id.split("/")[-1]
    name = re.sub(r"^(us|eu|apac|global)\.", "", name)
    name = re.sub(r"^[a-z]+\.", "", name)  # vendor prefix: amazon., anthropic., meta.
    name = re.sub(r":\d+$", "", name)
    return re.sub(r"[^a-z0-9.-]+", "-", name.lower()).strip("-") or "model"


def build_spec(
    prompt: str,
    models: list[str],
    *,
    expect: list[str] | None = None,
    adapter: str = "bedrock",
    harness: str = "converse_loop",
    toolset: str = "T1",
    system_prompt: str | None = None,
    trials: int = 1,
    max_steps: int = 25,
    max_usd: float = 0.10,
    max_seconds: float = 240,
    eval_cap: float = 2.0,
    name: str | None = None,
) -> EvalSpec:
    if not models:
        raise ConfigError("give at least one model", kind="invalid_spec")
    if len(set(models)) != len(models):
        raise ConfigError("each model may be given once", kind="invalid_spec")
    names = [config_name(m) for m in models]
    if len(set(names)) != len(names):  # two IDs with the same short name: number them
        names = [f"{n}-{i + 1}" for i, n in enumerate(names)]
    task_id = custom.slug(prompt)
    task: dict[str, Any] = {"id": task_id, "prompt": prompt, "expect": list(expect or [])}
    if system_prompt:
        task["system_prompt"] = system_prompt
    return EvalSpec.model_validate(
        {
            "name": name or f"query-{task_id}"[:60],
            "tasks": {"custom": [task]},
            "baseline": {
                "name": names[0],
                "model": {"name": adapter, "params": {"model_id": models[0]}},
                "harness": {"name": harness, "params": {}},
                "toolset": toolset,
            },
            "variants": [
                {"name": n, "override": {"model": {"params": {"model_id": m}}}}
                for n, m in zip(names[1:], models[1:], strict=True)
            ],
            "evaluators": custom.EVALUATORS,
            "summary": {"name": "deterministic"},
            "trials": trials,
            "budget": {
                "run": {"max_steps": max_steps, "max_usd": max_usd, "max_seconds": max_seconds},
                "eval": {"max_usd": eval_cap},
            },
            "executor": {"name": "local", "params": {"max_parallel": min(4, len(models))}},
        }
    )


def _answer(output: Any) -> str:
    text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return " ".join(text.split())


def results(store: LocalRunStore, run_ids: list[str]) -> list[dict[str, Any]]:
    """One row per run: model, state, steps, cost, time, expect score and the answer."""
    rows = []
    for run_id in run_ids:
        try:
            manifest = json.loads((store.run_dir(run_id) / "manifest.json").read_text())
            trace = store.read_trace(run_id)
        except Exception:  # noqa: BLE001  a run that never started has no folder
            continue
        end = next((e for e in reversed(trace.events) if isinstance(e, RunEnd)), None)
        final = next((e for e in reversed(trace.events) if isinstance(e, FinalOutput)), None)
        expect = next(
            (a for a in store.list_assessments(run_id) if a.get("kind") == "output"), None
        )
        totals = end.totals if end else {}
        rows.append(
            {
                "run_id": run_id,
                "config": manifest["config_name"],
                "model_id": manifest["model"].get("params", {}).get("model_id", ""),
                "trial": manifest["trial_index"] + 1,
                "state": end.state if end else "unknown",
                "steps": totals.get("steps"),
                "cost_usd": totals.get("cost_usd"),
                "seconds": (totals.get("wall_ms") or 0) / 1000,
                "found": expect.get("composite") if expect else None,
                "missing": (expect.get("notes") or [""])[0] if expect else "",
                "answer": _answer(final.output) if final else "",
                "error": end.error.message if end and end.error else "",
            }
        )
    return rows


def _print_results(rows: list[dict[str, Any]], width: int = 240) -> None:
    for r in rows:
        cost = "–" if r["cost_usd"] is None else f"${r['cost_usd']:.4f}"
        found = "" if r["found"] is None else f" · expected found {r['found']:.0%}"
        print(
            f"\n== {r['config']} (trial {r['trial']}) · {r['state']} · {r['steps']} steps · "
            f"{cost} · {r['seconds']:.1f}s{found}"
        )
        if r["missing"]:
            print(f"   {r['missing']}")
        if r["error"]:
            print(f"   error: {r['error']}")
        answer = r["answer"] or "(no final answer)"
        print(f"   {answer[:width]}{'…' if len(answer) > width else ''}")
        print(f"   run: {r['run_id']}")


def run_cli(args: Any, service: Any) -> int:
    spec = build_spec(
        args.prompt,
        args.models,
        expect=args.expect,
        adapter=args.adapter,
        harness=args.harness,
        toolset=args.toolset,
        system_prompt=args.system_prompt,
        trials=args.trials,
        max_steps=args.max_steps,
        max_usd=args.max_usd,
        max_seconds=args.max_seconds,
        eval_cap=args.eval_cap,
        name=args.name,
    )
    for warning in service.validate_spec(spec):
        print(f"warning: {warning}", file=sys.stderr)
    if args.save_spec:
        Path(args.save_spec).write_text(spec.model_dump_json(indent=2, exclude_defaults=True))
        print(f"Spec: {args.save_spec} (rerun with clay-sandbox eval {args.save_spec} --confirm)")
    estimate = service.estimate(spec, store_dir=args.store)
    for config, cost in estimate.per_config.items():
        print(f"{config}: ${cost:.4f}")
    print(f"Total: ${estimate.total_usd:.4f} for {len(service.plan(spec, 'cli-preflight'))} run(s)")
    if args.estimate_only:
        return 0
    single = len(service.plan(spec, "cli-preflight")) == 1
    if not single and not args.confirm:
        raise ConfigError("more than one run: add --confirm to start them", kind="needs_confirm")
    result = service.run_eval(
        spec,
        store_dir=args.store,
        confirm=True,
        on_status=lambda run_id, state: print(f"{run_id}\t{state}", flush=True),
    )
    store = LocalRunStore(Path(args.store) / "runs", Path(args.store) / "evals")
    _print_results(results(store, result.run_ids))
    print(f"\nEval: {result.eval_id}")
    print(f"Report: {result.report_path or '–'}")
    print(f"View: clay-sandbox serve --store {args.store}  (then /evals/{result.eval_id})")
    ok = all(
        result.states.get(r) in TERMINAL_STATES and result.states.get(r) != "infra_excluded"
        for r in result.run_ids
    )
    return 0 if ok else 1
