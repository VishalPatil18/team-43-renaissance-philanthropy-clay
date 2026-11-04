"""The platform's registry bootstrap registers every WS4 evaluator (arch §7.6)."""

import subprocess
import sys

NAMES = [
    "workflow",
    "workflow@0",
    "workflow@1",
    "output",
    *[f"output.t{i}" for i in range(1, 6)],
    "llm_process",
]


def test_bootstrap_alone_registers_every_evaluator():
    # A fresh interpreter: other tests import the evaluator modules directly, which would hide
    # a missing bootstrap line.
    code = (
        "import claysandbox.platform.registry_bootstrap\n"
        "from claysandbox.contracts.registry import resolve\n"
        f"for n in {NAMES!r}: resolve('evaluator', n)\n"
    )
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr[-500:]
