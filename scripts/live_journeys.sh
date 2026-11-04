#!/usr/bin/env bash
# Live journeys against real AWS. THESE SPEND MONEY (Bedrock). See tests/live/README.md.
# Usage: scripts/live_journeys.sh <r1|r2>
set -euo pipefail

usage() { echo "usage: $0 <r1|r2>" >&2; exit 2; }
[[ $# -eq 1 ]] || usage
release="$1"
case "$release" in r1|r2) ;; *) usage ;; esac

: "${AWS_PROFILE:?set AWS_PROFILE to your SSO profile (never put credentials in this script)}"
if [[ "${AWS_REGION:-}" != "us-west-2" ]]; then
  echo "AWS_REGION must be us-west-2 (DD-010); got '${AWS_REGION:-}'" >&2
  exit 2
fi

root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if command -v clay-sandbox >/dev/null 2>&1; then
  cli=(clay-sandbox)
elif uv run clay-sandbox --help >/dev/null 2>&1; then
  cli=(uv run clay-sandbox)
else
  echo "clay-sandbox CLI not found (neither on PATH nor via 'uv run'). It is built by WS5; install the package first." >&2
  exit 1
fi

# Placeholders live in non-comment lines as "<name>"; refuse to spend money on them.
if placeholders="$(grep -nE '^[^#]*"<[a-z0-9-]+>"' specs/live/*.yaml)"; then
  echo "specs/live/*.yaml still contain placeholders; fill in model IDs and AOIs first:" >&2
  echo "$placeholders" >&2
  exit 1
fi

report_dir="${REPORT_DIR:-./runs}"
echo "release=$release profile=$AWS_PROFILE region=$AWS_REGION report_dir=$report_dir"

run_spec() { # <command> <spec>
  local cmd="$1" spec="$2"
  echo
  echo "== ${cmd} ${spec}"
  "${cli[@]}" estimate "$spec"
  "${cli[@]}" "$cmd" "$spec" | tee -a "$log"
}

log="$(mktemp -t clay-live-XXXXXX.log)"
echo "output log: $log"

case "$release" in
  r1)
    run_spec run specs/live/j1.yaml   # J1: T1, T2, T5 x two AOIs
    run_spec run specs/live/j4.yaml   # J4.1: faulty tools, errors in the trace
    run_spec run specs/live/j4-wrong-tool.yaml # J4.2: attempt an unavailable tool call
    ;;
  r2)
    run_spec run  specs/live/j3.yaml        # J3: swap model, harness, tracer
    echo "J3 step 4: re-score stored runs with: ${cli[*]} rescore --evaluator llm_process@1 <run ids>"
    run_spec eval specs/live/j5-j6.yaml     # J5 + J6: comparison and statistics
    run_spec run  specs/live/j7-steps2.yaml # J7 step 1: guard stops the run
    run_spec run  specs/live/j7-nolimit.yaml # J7 step 2: no limits
    ;;
esac

echo
echo "== run IDs and report paths seen in the CLI output"
grep -Ei 'run[_ -]?id|report' "$log" || echo "(none printed; look under $report_dir)"
