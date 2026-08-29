"""
Anthropic Provider Adapter for AI Infrastructure (Phase 17).

Connects AutoForge to the Anthropic Messages API, integrating with Phase 15 SecretsManager.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from autoforge_ai_infrastructure.adapters.base import (
    UNAVAILABLE,
    BaseProviderAdapter,
    extract_json_payload,
)
from autoforge_ai_infrastructure.errors import (
    ExecutionFailedError,
    ExecutionTimeoutError,
    ModelUnavailableError,
    ProviderUnavailableError,
)
from autoforge_ai_infrastructure.execution import ExecutionRequest, ExecutionTarget

logger = logging.getLogger(__name__)


class AnthropicProviderAdapter(BaseProviderAdapter):
    """
    Adapter for Anthropic Claude Messages API.
    """

    def __init__(
        self,
        provider_id: str = "anthropic",
        base_url: str = "https://api.anthropic.com/v1",
        *,
        api_key: Optional[str] = None,
        api_key_resolver: Optional[Callable[[], Optional[str]]] = None,
        secrets_manager: Any = None,
        secret_name: Optional[str] = "anthropic_api_key",
        anthropic_version: str = "2023-06-01",
        default_timeout_seconds: float = 60.0,
        model_tag_map: Optional[Dict[str, str]] = None,
        http_client: Optional[Callable[..., Any]] = None,
    ) -> None:
        super().__init__(
            provider_id=provider_id,
            default_timeout_seconds=default_timeout_seconds,
            model_tag_map=model_tag_map,
        )
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._api_key_resolver = api_key_resolver
        self._secrets_manager = secrets_manager
        self._secret_name = secret_name
        self._anthropic_version = anthropic_version
        self._http_client = http_client

    def _get_api_key(self) -> Optional[str]:
        if self._secrets_manager and self._secret_name:
            try:
                from autoforge_security.models import Subject, SubjectType
                system_subject = Subject(
                    subject_id="system-model-adapter",
                    display_name="System Model Adapter",
                    subject_type=SubjectType.SERVICE,
                )
                secret = self._secrets_manager.get_secret(self._secret_name, system_subject)
                return secret.raw_value
            except Exception as e:
                logger.warning(f"Could not retrieve secret '{self._secret_name}' from SecretsManager: {e}")

        if self._api_key_resolver:
            return self._api_key_resolver()

        return self._api_key

    def _sync_request(
        self,
        endpoint: str,
        payload: dict[str, Any],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if self._http_client is not None:
            return self._http_client(endpoint, payload, timeout)

        url = f"{self._base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "anthropic-version": self._anthropic_version,
        }

        key = self._get_api_key()
        if key:
            headers["x-api-key"] = key

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise ExecutionFailedError(
                    f"Authentication failed for Anthropic: HTTP {e.code}",
                    details={"provider_id": self.provider_id, "status_code": e.code},
                ) from e
            elif e.code == 404:
                raise ModelUnavailableError(
                    f"Model not found at Anthropic endpoint: {err_body}",
                    details={"provider_id": self.provider_id, "status_code": e.code},
                ) from e
            raise ExecutionFailedError(
                f"Anthropic returned HTTP {e.code}: {err_body}",
                details={"provider_id": self.provider_id, "status_code": e.code},
            ) from e
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            raise ProviderUnavailableError(
                f"Anthropic endpoint {self._base_url} unreachable: {e}",
                details={"provider_id": self.provider_id, "error": str(e)},
            ) from e
        except TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Anthropic request timed out after {timeout}s",
                details={"provider_id": self.provider_id, "timeout": timeout},
            ) from e

    async def execute(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> dict[str, Any]:
        resolved_tag = self.resolve_model_tag(target.model_id)
        timeout = request.timeout_seconds or self._default_timeout_seconds
        messages = self.normalize_messages(request)

        # Anthropic messages format: system prompt is top-level parameter
        system_content = ""
        user_messages: list[dict[str, str]] = []
        for msg in messages:
            if msg["role"] == "system":
                system_content = msg["content"]
            else:
                user_messages.append({"role": msg["role"], "content": msg["content"]})

        if not user_messages:
            user_messages.append({"role": "user", "content": ""})

        params = dict(request.parameters or {})
        max_tokens = int(params.get("max_tokens") or params.get("max_output_tokens") or 4096)

        payload: dict[str, Any] = {
            "model": resolved_tag,
            "messages": user_messages,
            "max_tokens": max_tokens,
        }
        if system_content:
            payload["system"] = system_content
        if "temperature" in params:
            payload["temperature"] = float(params["temperature"])
        if "top_p" in params:
            payload["top_p"] = float(params["top_p"])

        start_time = time.perf_counter()
        try:
            raw_response = await asyncio.wait_for(
                asyncio.to_thread(self._sync_request, "/messages", payload, timeout),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Anthropic execution for model '{target.model_id}' timed out after {timeout}s",
                details={"model_id": target.model_id, "provider_id": self.provider_id, "timeout": timeout},
            ) from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Extract text blocks
        content_blocks = raw_response.get("content", [])
        content_parts = []
        if isinstance(content_blocks, list):
            for block in content_blocks:
                if isinstance(block, dict) and block.get("type") == "text":
                    content_parts.append(block.get("text", ""))
        content = "".join(content_parts)

        # Token accounting
        usage = raw_response.get("usage") or {}
        input_tokens = usage.get("input_tokens", UNAVAILABLE)
        output_tokens = usage.get("output_tokens", UNAVAILABLE)
        total_tokens = (
            (input_tokens + output_tokens)
            if isinstance(input_tokens, int) and isinstance(output_tokens, int)
            else UNAVAILABLE
        )

        tokens_per_sec: Union[float, str] = UNAVAILABLE
        if isinstance(output_tokens, (int, float)) and duration_ms > 0:
            tokens_per_sec = round((output_tokens / (duration_ms / 1000.0)), 2)

        structured_requested = (
            params.get("structured_output")
            or request.payload.get("format") == "json"
            or request.payload.get("structured_output")
        )
        parsed_json = extract_json_payload(content) if structured_requested else None

        output: dict[str, Any] = {
            "content": content,
            "model_id": target.model_id,
            "provider_id": self.provider_id,
            "resolved_tag": resolved_tag,
            "stop_reason": raw_response.get("stop_reason", ""),
            "input_tokens": input_tokens,
            "output_tokens": output_tokens,
            "total_tokens": total_tokens,
            "tokens_per_second": tokens_per_sec,
            "tokens": {
                "input_tokens": input_tokens,
                "output_tokens": output_tokens,
                "total_tokens": total_tokens,
                "tokens_per_second": tokens_per_sec,
            },
            "duration_ms": duration_ms,
            "raw": raw_response,
        }

        if parsed_json is not None:
            output["structured_output"] = parsed_json
            if isinstance(parsed_json, dict):
                for k, v in parsed_json.items():
                    if k not in output:
                        output[k] = v
        elif structured_requested and content:
            fallback_parsed = extract_json_payload(content)
            if fallback_parsed is not None:
                output["structured_output"] = fallback_parsed
                if isinstance(fallback_parsed, dict):
                    for k, v in fallback_parsed.items():
                        if k not in output:
                            output[k] = v

        if "plan" not in output and content:
            output["plan"] = content

        return output
