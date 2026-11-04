"""Conformance suite for ``ModelAdapter`` implementations (FR-1.4, FR-1.5, DD-035).

Each implementation provides a factory that returns an adapter wired to a canned backend, so the
suite needs no AWS. Add a factory here when a new adapter is registered.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import boto3
import pytest
from botocore.stub import Stubber

from claysandbox.contracts.errors import ConfigError
from claysandbox.contracts.fakes.model import FakeModelAdapter, text_reply
from claysandbox.contracts.runtime import ModelAdapter, ModelResponse
from claysandbox.runtime.models.bedrock import BedrockModelAdapter
from claysandbox.runtime.testing import SEARCH_TOOL

Factory = Callable[[], ModelAdapter]


def _bedrock() -> ModelAdapter:
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-west-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    stubber = Stubber(client)
    stubber.add_response(
        "converse",
        {
            "output": {"message": {"role": "assistant", "content": [{"text": "hello"}]}},
            "stopReason": "end_turn",
            "usage": {"inputTokens": 12, "outputTokens": 3, "totalTokens": 15},
            "metrics": {"latencyMs": 42},
        },
    )
    stubber.activate()
    return BedrockModelAdapter({"model_id": "test-model"}, client=client)


def _fake() -> ModelAdapter:
    return FakeModelAdapter([text_reply("hello", input_tokens=12, output_tokens=3)])


FACTORIES: dict[str, Factory] = {"bedrock": _bedrock, "fake": _fake}
MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]


@pytest.mark.parametrize("name", FACTORIES)
def test_implements_the_adapter_interface(name: str) -> None:
    adapter = FACTORIES[name]()
    assert isinstance(adapter, ModelAdapter)
    assert adapter.name and adapter.version and adapter.model_id


@pytest.mark.parametrize("name", FACTORIES)
def test_converse_returns_text_tokens_and_stop_reason(name: str) -> None:
    response = FACTORIES[name]().converse(MESSAGES, "be brief", [SEARCH_TOOL], {})
    assert isinstance(response, ModelResponse)
    assert response.text == "hello"
    assert (response.input_tokens, response.output_tokens) == (12, 3)
    assert response.stop_reason == "end_turn"
    assert response.latency_ms is not None
    assert response.message["role"] == "assistant"


def test_the_model_id_cannot_be_changed_per_call() -> None:
    """FR-1.5: the model ID comes only from the spec."""
    adapter = _bedrock()
    assert isinstance(adapter, BedrockModelAdapter)
    with pytest.raises(ConfigError):
        adapter.converse(MESSAGES, "", [], {"model_id": "some-other-model"})
