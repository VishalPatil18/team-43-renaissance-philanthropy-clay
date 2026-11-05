"""Command-line interface for the sandbox composition root."""

import argparse
import importlib
import sys
from collections import Counter
from pathlib import Path

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.execution import TERMINAL_STATES


def _parser():
    parser = argparse.ArgumentParser(prog="clay-sandbox")
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("run", "eval", "estimate", "status", "worker", "serve"):
        command = commands.add_parser(name)
        command.add_argument("--store", default=".")
        if name in ("run", "eval", "estimate"):
            command.add_argument("spec")
        if name == "run":
            command.add_argument("--yes", action="store_true")
        if name == "eval":
            command.add_argument("--confirm", action="store_true")
        if name == "status":
            command.add_argument("eval_id")
        if name == "worker":
            command.add_argument("--request", required=True)
        if name == "serve":
            command.add_argument("--port", type=int, default=8765)
            command.add_argument("--hosted", action="store_true", help="AWS mode (web service)")
    query = commands.add_parser(
        "query", help="run your own question on one or more models and compare them"
    )
    query.add_argument("prompt", help="the question, in plain words")
    query.add_argument(
        "--model",
        action="append",
        required=True,
        dest="models",
        metavar="MODEL_ID",
        help="Bedrock model ID; repeat to compare models (the first is the baseline)",
    )
    query.add_argument(
        "--expect",
        action="append",
        default=[],
        metavar="TEXT",
        help="a string the answer must contain (an item ID, a place name); repeatable",
    )
    query.add_argument("--harness", default="converse_loop")
    query.add_argument("--toolset", default="T1")
    query.add_argument("--adapter", default="bedrock", help="model adapter (registry name)")
    query.add_argument("--system-prompt")
    query.add_argument("--trials", type=int, default=1)
    query.add_argument("--max-steps", type=int, default=25)
    query.add_argument("--max-usd", type=float, default=0.10, help="per run")
    query.add_argument("--max-seconds", type=float, default=240, help="per run")
    query.add_argument("--eval-cap", type=float, default=2.0, help="$ for all runs together")
    query.add_argument("--name", help="evaluation name (default: from the question)")
    query.add_argument("--save-spec", metavar="PATH", help="also write the spec, to rerun it")
    query.add_argument("--estimate-only", action="store_true")
    query.add_argument(
        "--executor",
        choices=("local", "fargate"),
        default="local",
        help="fargate runs each model in its own ECS task (needs infra/outputs.json)",
    )
    query.add_argument("--confirm", action="store_true", help="needed for more than one run")
    query.add_argument("--store", default=".")
    commands.add_parser("validate-evaluator").add_argument("--planted")
    commands.add_parser("registry").add_argument("--kind")
    commands.add_parser("tasks")
    return parser


def _execute(args):
    if args.command == "serve":
        from claysandbox.api.__main__ import main as serve

        serve(
            ["--store", args.store, "--port", str(args.port)]
            + (["--hosted"] if args.hosted else [])
        )
        return 0
    if args.command == "registry":
        import claysandbox.platform.registry_bootstrap  # noqa: F401
        from claysandbox.contracts.registry import list_components

        print("Kind\tName\tVersion")
        for entry in list_components(args.kind):
            print(f"{entry['kind']}\t{entry['name']}\t{entry['version']}")
        return 0
    if args.command == "tasks":
        from claysandbox.tasks.library import FileTaskLibrary

        for task in FileTaskLibrary().instances():
            print(f"{task.id}\t{task.title}")
        return 0
    if args.command == "validate-evaluator":
        from claysandbox.evaluation.validate import default_evaluators, format_report, validate

        root = args.planted or (
            "samples/planted" if Path("samples/planted").exists() else "tests/fixtures/planted"
        )
        print(format_report(validate(default_evaluators(), planted_root=root)), end="")
        return 0
    service = importlib.import_module("claysandbox.platform.service")
    if args.command == "query":
        from claysandbox.platform import query

        return query.run_cli(args, service)
    if args.command == "worker":
        status = service.run_worker_request(args.request, store_dir=args.store)
        print(f"{status.run_id}\t{status.state}")
        return 0 if status.state in TERMINAL_STATES else 1
    if args.command == "status":
        status = service.eval_status(args.eval_id, store_dir=args.store)
        print("Run ID\tConfig\tTask instance\tTrial\tState")
        for run in status["runs"]:
            print(
                "\t".join(
                    str(run.get(k, "–"))
                    for k in ("run_id", "config_name", "task_instance_id", "trial_index", "state")
                )
            )
        for state, count in sorted(Counter(r["state"] for r in status["runs"]).items()):
            print(f"{state}: {count}")
        return 0
    spec = service.load_spec(args.spec)
    for warning in service.validate_spec(spec):
        print(f"warning: {warning}", file=sys.stderr)
    if args.command in ("estimate", "eval"):
        estimate = service.estimate(spec, store_dir=args.store)
        for config, cost in estimate.per_config.items():
            print(f"{config}: ${cost:.4f}")
        print(f"Total: ${estimate.total_usd:.4f}")
        for note in estimate.notes:
            print(f"note: {note}")
        if args.command == "estimate":
            return 0
    single = len(service.plan(spec, "cli-preflight")) == 1
    confirmed = getattr(args, "yes", False) or getattr(args, "confirm", False)
    if args.command == "eval" and not single and not confirmed:
        raise ConfigError("multi-run eval requires --confirm", kind="needs_confirm")
    result = service.run_eval(
        spec,
        store_dir=args.store,
        confirm=confirmed or single,
        on_status=lambda run_id, state: print(f"{run_id}\t{state}", flush=True),
    )
    print(f"Eval: {result.eval_id}")
    print(f"Report: {result.report_path or '–'}")
    print(f"View: clay-sandbox serve --store {args.store}")
    return (
        0
        if all(
            result.states.get(run_id) in TERMINAL_STATES
            and result.states.get(run_id) != "infra_excluded"
            for run_id in result.run_ids
        )
        else 1
    )


def main(argv=None) -> int:
    """Parse arguments and return an exit code; configuration errors are user errors."""
    args = _parser().parse_args(argv)
    try:
        return _execute(args)
    except ConfigError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
