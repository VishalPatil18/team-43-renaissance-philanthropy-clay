"""Imports every plugin module once so all registrations happen (owner: WS5).

Each workstream adds its own import lines. WS1's lines are below.
"""

from __future__ import annotations

# WS4 (evaluation): workflow@0/@1, output and output.t1..t5, llm_process
from claysandbox.evaluation import llm_process, output, workflow  # noqa: F401

# WS3 (trace and store)
from claysandbox.platform import custom as custom_query  # noqa: F401  (expect evaluator)

# WS1 (runtime and cloud execution)
from claysandbox.platform.executors import fargate  # noqa: F401
from claysandbox.platform.executors import local as local_executor  # noqa: F401
from claysandbox.runtime import pricing  # noqa: F401
from claysandbox.runtime.harness import converse_loop, strands_harness  # noqa: F401
from claysandbox.runtime.models import bedrock  # noqa: F401
from claysandbox.store import local, s3  # noqa: F401
from claysandbox.summary import deterministic, llm  # noqa: F401

# WS2 (tools and tasks)
from claysandbox.tools.toolsets import register_toolsets

# WS3 (trace and store)
from claysandbox.tracing import jsonl, otel, tee  # noqa: F401

# WS2: one registry entry per toolsets/*.yaml file
register_toolsets()
