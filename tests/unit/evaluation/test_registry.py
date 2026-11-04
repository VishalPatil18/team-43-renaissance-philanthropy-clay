"""Versioned names used by rescore resolve to the recorded evaluator implementation."""

import pytest

import claysandbox.evaluation.llm_process  # noqa: F401
import claysandbox.evaluation.output  # noqa: F401
from claysandbox.contracts.registry import resolve


@pytest.mark.parametrize("name", ["llm_process", "output", *[f"output.t{i}" for i in range(1, 6)]])
def test_versioned_evaluator_name_resolves(name):
    versioned = resolve("evaluator", f"{name}@1")
    assert versioned is resolve("evaluator", name)
    assert versioned.version == "1"
