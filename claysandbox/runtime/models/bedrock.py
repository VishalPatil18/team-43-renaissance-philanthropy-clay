"""Amazon Bedrock model adapter over the Converse API (FR-1.4, FR-1.5, FR-1.11).

The model ID and inference parameters come only from ``Params`` (the spec), never from code or
the environment. A Claude-family model may need a cross-region inference profile ID (for example
a ``us.``-prefixed ID); this adapter accepts either.

Errors that survive the SDK's own retries are classified:

* throttling, 5xx, timeouts, connection problems -> ``InfraError`` (retryable)
* access denied, unknown model, invalid request, missing credentials -> ``ConfigError``
"""

from __future__ import annotations

import time
from typing import Any, cast

import boto3
from botocore.config import Config
from botocore.exceptions import (
    BotoCoreError,
    ClientError,
    NoCredentialsError,
    ParamValidationError,
    PartialCredentialsError,
    ProfileNotFound,
)
from pydantic import BaseModel, Field

from claysandbox.contracts.errors import ConfigError, InfraError
from claysandbox.contracts.manifest import ToolSpec
from claysandbox.contracts.registry import register
from claysandbox.contracts.runtime import ModelResponse, ToolUse

_THROTTLE_CODES = {"ThrottlingException", "TooManyRequestsException"}
_SERVICE_CODES = {
    "ServiceUnavailableException",
    "InternalServerException",
    "ModelTimeoutException",
    "ModelNotReadyException",
    "ModelErrorException",
}
_CONFIG_CODES = {
    "AccessDeniedException",
    "ResourceNotFoundException",
    "ValidationException",
    "UnrecognizedClientException",
    "ExpiredTokenException",
    "ServiceQuotaExceededException",
}
_OVERRIDABLE = {"temperature": "temperature", "max_tokens": "maxTokens", "top_p": "topP"}


def classify_client_error(exc: ClientError) -> InfraError | ConfigError:
    """Map a botocore ``ClientError`` to the sandbox error taxonomy (srs §12.4)."""
    error = exc.response.get("Error", {})
    code = error.get("Code", "")
    message = f"{code}: {error.get('Message', str(exc))}"
    status = exc.response.get("ResponseMetadata", {}).get("HTTPStatusCode", 0)
    if code in _THROTTLE_CODES:
        return InfraError("throttled", message)
    if code in _SERVICE_CODES:
        return InfraError("service_error", message)
    if code in _CONFIG_CODES:
        return ConfigError(message, kind=_config_kind(code))
    if isinstance(status, int) and status >= 500:
        return InfraError("service_error", message)
    return ConfigError(message)


def _config_kind(code: str) -> str:
    return {
        "AccessDeniedException": "access_denied",
        "ResourceNotFoundException": "model_not_found",
        "ValidationException": "invalid_request",
        "ServiceQuotaExceededException": "quota_exceeded",
    }.get(code, "config_error")


@register("model", "bedrock")
class BedrockModelAdapter:
    name = "bedrock"
    version = "1"

    class Params(BaseModel):
        model_id: str
        temperature: float = Field(default=0.2, ge=0.0, le=1.0)
        max_tokens: int = Field(default=4096, gt=0)
        top_p: float | None = Field(default=None, gt=0.0, le=1.0)
        region: str = "us-west-2"
        max_attempts: int = Field(default=3, ge=1)

    def __init__(self, params: dict[str, Any] | None = None, client: Any | None = None) -> None:
        if not params or "model_id" not in params:
            raise ConfigError("The bedrock model needs params.model_id in the spec")
        self.params = self.Params(**params)
        self.model_id = self.params.model_id
        self._client = client or boto3.client(
            "bedrock-runtime",
            region_name=self.params.region,
            config=Config(
                retries={"mode": "adaptive", "max_attempts": self.params.max_attempts},
                read_timeout=120,
                connect_timeout=10,
            ),
        )

    # -- request --------------------------------------------------------------------------

    def build_request(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[ToolSpec],
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if params and "model_id" in params and params["model_id"] != self.model_id:
            raise ConfigError("The model ID can only come from the spec (FR-1.5)")
        inference: dict[str, Any] = {
            "maxTokens": self.params.max_tokens,
            "temperature": self.params.temperature,
        }
        if self.params.top_p is not None:
            inference["topP"] = self.params.top_p
        for key, target in _OVERRIDABLE.items():
            if params and params.get(key) is not None:
                inference[target] = params[key]

        request: dict[str, Any] = {
            "modelId": self.model_id,
            "messages": messages,
            "inferenceConfig": inference,
        }
        if system:
            request["system"] = [{"text": system}]
        if tools:
            request["toolConfig"] = {"tools": [_tool_entry(t) for t in tools]}
        return request

    # -- call -----------------------------------------------------------------------------

    def converse(
        self,
        messages: list[dict[str, Any]],
        system: str,
        tools: list[ToolSpec],
        params: dict[str, Any],
    ) -> ModelResponse:
        request = self.build_request(messages, system, tools, params)
        t0 = time.monotonic()
        try:
            raw = self._client.converse(**request)
        except ClientError as exc:
            raise classify_client_error(exc) from exc
        except (NoCredentialsError, PartialCredentialsError, ProfileNotFound) as exc:
            raise ConfigError(f"AWS credentials problem: {exc}", kind="credentials") from exc
        except ParamValidationError as exc:
            raise ConfigError(f"Invalid Converse request: {exc}", kind="invalid_request") from exc
        except BotoCoreError as exc:
            raise InfraError("network", f"{type(exc).__name__}: {exc}") from exc
        except (TimeoutError, ConnectionError) as exc:
            raise InfraError("network", f"{type(exc).__name__}: {exc}") from exc
        wall_ms = (time.monotonic() - t0) * 1000
        return self.parse_response(cast(dict[str, Any], raw), wall_ms)

    def parse_response(self, raw: dict[str, Any], wall_ms: float | None = None) -> ModelResponse:
        message = raw.get("output", {}).get("message") or {"role": "assistant", "content": []}
        content = message.get("content", [])
        text_parts: list[str] = []
        uses: list[ToolUse] = []
        for block in content:
            if "text" in block:
                text_parts.append(block["text"])
            elif "toolUse" in block:
                tu = block["toolUse"]
                uses.append(
                    ToolUse(
                        tool_use_id=tu.get("toolUseId", ""),
                        name=tu.get("name", ""),
                        input=tu.get("input", {}),
                    )
                )
        usage = raw.get("usage", {})
        metrics = raw.get("metrics", {})
        latency = metrics.get("latencyMs")
        return ModelResponse(
            message=message,
            text="".join(text_parts),
            tool_uses=uses,
            stop_reason=raw.get("stopReason"),
            input_tokens=int(usage.get("inputTokens", 0)),
            output_tokens=int(usage.get("outputTokens", 0)),
            latency_ms=float(latency) if latency is not None else wall_ms,
            model_id=self.model_id,
        )


def _tool_entry(tool: ToolSpec) -> dict[str, Any]:
    spec: dict[str, Any] = {
        "name": tool.model_name,
        "inputSchema": {"json": tool.input_schema},
    }
    if tool.description:
        spec["description"] = tool.description
    return {"toolSpec": spec}
