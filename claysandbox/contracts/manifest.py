"""Manifest building blocks (architecture §7.2).

Owner: WS5 (5th member). Only the parts WS1 needs are defined here: ``ToolSpec`` and
``ComponentRef``. ``RunManifest`` itself belongs to WS5.
"""

from __future__ import annotations

import hashlib
import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field, model_validator

_TOOL_NAME_MAX = 64
_BAD_CHARS = re.compile(r"[^A-Za-z0-9_-]")


def make_model_name(server: str, tool: str) -> str:
    """Return the tool name the model sees (contracts open point 2).

    ``<server>__<tool>`` limited to ``[A-Za-z0-9_-]`` and 64 characters (Bedrock's rule).
    When the name must be shortened, an 8-character hash of the full name is appended so
    two long names do not collide.
    """
    full = _BAD_CHARS.sub("_", f"{server}__{tool}")
    if len(full) <= _TOOL_NAME_MAX:
        return full
    digest = hashlib.sha256(f"{server}__{tool}".encode()).hexdigest()[:8]
    return f"{full[: _TOOL_NAME_MAX - 9]}_{digest}"


class ToolSpec(BaseModel):
    server: str
    name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=lambda: {"type": "object"})
    capability: str | None = None
    model_name: str = ""

    @model_validator(mode="after")
    def _fill_model_name(self) -> ToolSpec:
        if not self.model_name:
            self.model_name = make_model_name(self.server, self.name)
        return self


class ComponentRef(BaseModel):
    kind: str
    name: str
    version: str = ""
    params: dict[str, Any] = Field(default_factory=dict)


# --- PLACEHOLDER (WS4 branch): RunManifest is owned by WS5 (5th member). This copy follows
# architecture §7.2 so the evaluators can be built and tested before the scaffold merges.
# Fields the evaluators do not read have defaults. Replace with WS5's module on merge.
class RunManifest(BaseModel):
    schema_version: str = "1.0"
    run_id: str
    eval_id: str = ""
    trial_index: int = 0
    attempt: int = 1
    attempts: list[dict[str, Any]] = Field(default_factory=list)
    task_instance_id: str
    task_reference_version: str = ""
    prompt: str = ""
    system_prompt: str = ""
    config_name: str = ""
    toolset: ComponentRef | None = None
    mcp_servers: list[dict[str, Any]] = Field(default_factory=list)
    tools: list[ToolSpec] = Field(default_factory=list)
    model: ComponentRef | None = None
    harness: ComponentRef | None = None
    tracer: ComponentRef | None = None
    evaluators: list[ComponentRef] = Field(default_factory=list)
    budget: dict[str, Any] = Field(default_factory=dict)
    loop_guard: dict[str, Any] = Field(default_factory=dict)
    seed: int = 0
    price_table_version: str = ""
    executor: ComponentRef | None = None
    environment: dict[str, Any] = Field(default_factory=dict)
    package_version: str = ""
    git_sha: str = ""
    lockfile_sha256: str = ""
    spec_sha256: str = ""
    started_at: datetime | None = None
