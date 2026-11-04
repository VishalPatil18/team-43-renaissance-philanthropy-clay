"""Imports every plugin module once so all registrations happen (owner: WS5).

Each workstream adds its own import lines. WS1's lines are below.
"""

from __future__ import annotations

# WS1 (runtime and cloud execution)
from claysandbox.platform.executors import fargate  # noqa: F401
from claysandbox.runtime import pricing  # noqa: F401
from claysandbox.runtime.harness import converse_loop, strands_harness  # noqa: F401
from claysandbox.runtime.models import bedrock  # noqa: F401

# WS3 (trace and store)
from claysandbox.store import local  # noqa: F401
from claysandbox.summary import deterministic, llm  # noqa: F401
from claysandbox.tracing import jsonl, otel  # noqa: F401
