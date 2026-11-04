from __future__ import annotations

from typing import Any

import boto3
import pytest
from botocore.exceptions import (
    ConnectTimeoutError,
    EndpointConnectionError,
    NoCredentialsError,
)
from botocore.stub import Stubber

from claysandbox.contracts.errors import ConfigError, InfraError
from claysandbox.runtime.models.bedrock import BedrockModelAdapter, classify_client_error
from claysandbox.runtime.testing import SEARCH_TOOL

MESSAGES: list[dict[str, Any]] = [{"role": "user", "content": [{"text": "hi"}]}]


def make(**params: Any) -> tuple[BedrockModelAdapter, Stubber]:
    client = boto3.client(
        "bedrock-runtime",
        region_name="us-west-2",
        aws_access_key_id="test",
        aws_secret_access_key="test",
    )
    stubber = Stubber(client)
    stubber.activate()
    return BedrockModelAdapter({"model_id": "m-1", **params}, client=client), stubber


def reply(content: list[dict[str, Any]], stop: str = "end_turn") -> dict[str, Any]:
    return {
        "output": {"message": {"role": "assistant", "content": content}},
        "stopReason": stop,
        "usage": {"inputTokens": 100, "outputTokens": 20, "totalTokens": 120},
        "metrics": {"latencyMs": 250},
    }


def test_text_reply_is_parsed() -> None:
    adapter, stub = make()
    stub.add_response("converse", reply([{"text": "one "}, {"text": "two"}]))
    response = adapter.converse(MESSAGES, "sys", [], {})
    assert response.text == "one two"
    assert response.tool_uses == []
    assert (response.input_tokens, response.output_tokens) == (100, 20)
    assert response.latency_ms == 250.0
    assert response.stop_reason == "end_turn"
    assert response.model_id == "m-1"


def test_tool_use_reply_is_parsed() -> None:
    adapter, stub = make()
    stub.add_response(
        "converse",
        reply(
            [
                {"text": "searching"},
                {
                    "toolUse": {
                        "toolUseId": "tu-1",
                        "name": "stac__search_items",
                        "input": {"collection": "naip"},
                    }
                },
            ],
            stop="tool_use",
        ),
    )
    response = adapter.converse(MESSAGES, "", [SEARCH_TOOL], {})
    assert response.stop_reason == "tool_use"
    assert len(response.tool_uses) == 1
    use = response.tool_uses[0]
    assert (use.tool_use_id, use.name, use.input) == (
        "tu-1",
        "stac__search_items",
        {"collection": "naip"},
    )
    assert response.message["content"][1]["toolUse"]["toolUseId"] == "tu-1"


def test_request_has_model_id_system_inference_config_and_tool_config() -> None:
    adapter, _ = make(temperature=0.5, max_tokens=321, top_p=0.9)
    request = adapter.build_request(MESSAGES, "be brief", [SEARCH_TOOL], {})
    assert request["modelId"] == "m-1"
    assert request["system"] == [{"text": "be brief"}]
    assert request["inferenceConfig"] == {"maxTokens": 321, "temperature": 0.5, "topP": 0.9}
    tool = request["toolConfig"]["tools"][0]["toolSpec"]
    assert tool["name"] == "stac__search_items"
    assert tool["description"] == "Search STAC items"
    assert tool["inputSchema"] == {"json": SEARCH_TOOL.input_schema}


def test_request_without_tools_omits_tool_config() -> None:
    adapter, stub = make()
    request = adapter.build_request(MESSAGES, "", [], {})
    assert "toolConfig" not in request
    assert "system" not in request
    stub.add_response("converse", reply([{"text": "ok"}]), expected_params=request)
    adapter.converse(MESSAGES, "", [], {})
    stub.assert_no_pending_responses()


def test_per_call_overrides_apply_to_inference_params_only() -> None:
    adapter, _ = make(temperature=0.2, max_tokens=100)
    request = adapter.build_request(MESSAGES, "", [], {"temperature": 0.0, "max_tokens": 50})
    assert request["inferenceConfig"] == {"maxTokens": 50, "temperature": 0.0}
    with pytest.raises(ConfigError):
        adapter.build_request(MESSAGES, "", [], {"model_id": "other"})


def test_model_id_is_required_and_never_read_from_the_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("BEDROCK_MODEL_ID", "from-env")
    with pytest.raises(ConfigError):
        BedrockModelAdapter({}, client=object())
    with pytest.raises(ConfigError):
        BedrockModelAdapter(None, client=object())


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("ThrottlingException", "throttled"),
        ("ServiceUnavailableException", "service_error"),
        ("InternalServerException", "service_error"),
        ("ModelTimeoutException", "service_error"),
        ("ModelNotReadyException", "service_error"),
    ],
)
def test_infra_errors_are_retryable_infra_errors(code: str, kind: str) -> None:
    adapter, stub = make()
    stub.add_client_error("converse", service_error_code=code, service_message="nope")
    with pytest.raises(InfraError) as info:
        adapter.converse(MESSAGES, "", [], {})
    assert info.value.kind == kind
    assert info.value.retryable is True
    assert info.value.source == "infra"


@pytest.mark.parametrize(
    ("code", "kind"),
    [
        ("AccessDeniedException", "access_denied"),
        ("ResourceNotFoundException", "model_not_found"),
        ("ValidationException", "invalid_request"),
    ],
)
def test_config_errors_are_not_retryable(code: str, kind: str) -> None:
    adapter, stub = make()
    stub.add_client_error("converse", service_error_code=code, service_message="nope")
    with pytest.raises(ConfigError) as info:
        adapter.converse(MESSAGES, "", [], {})
    assert info.value.kind == kind
    assert info.value.retryable is False


def test_unknown_5xx_is_a_service_error_and_unknown_4xx_is_config() -> None:
    adapter, stub = make()
    stub.add_client_error("converse", service_error_code="WeirdThing", http_status_code=502)
    with pytest.raises(InfraError):
        adapter.converse(MESSAGES, "", [], {})
    stub.add_client_error("converse", service_error_code="WeirdThing", http_status_code=400)
    with pytest.raises(ConfigError):
        adapter.converse(MESSAGES, "", [], {})


def test_network_and_credential_errors_are_classified() -> None:
    adapter, _ = make()

    class Boom:
        def __init__(self, exc: Exception) -> None:
            self.exc = exc

        def converse(self, **_: Any) -> None:
            raise self.exc

    cases: list[tuple[Exception, type[Exception], str]] = [
        (EndpointConnectionError(endpoint_url="https://x"), InfraError, "network"),
        (ConnectTimeoutError(endpoint_url="https://x"), InfraError, "network"),
        (NoCredentialsError(), ConfigError, "credentials"),
    ]
    for exc, expected, kind in cases:
        adapter._client = Boom(exc)
        with pytest.raises(expected) as info:
            adapter.converse(MESSAGES, "", [], {})
        assert info.value.kind == kind  # type: ignore[attr-defined]


def test_classify_client_error_directly() -> None:
    from botocore.exceptions import ClientError

    err = ClientError({"Error": {"Code": "ThrottlingException", "Message": "x"}}, "Converse")
    assert isinstance(classify_client_error(err), InfraError)


def test_bedrock_adapter_is_registered_and_describes_its_params() -> None:
    import claysandbox.platform.registry_bootstrap  # noqa: F401
    from claysandbox.contracts.registry import list_components, resolve

    assert resolve("model", "bedrock") is BedrockModelAdapter
    entry = next(c for c in list_components("model") if c["name"] == "bedrock")
    assert "model_id" in entry["params"]["properties"]
