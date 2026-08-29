"""
OpenAI-Compatible Provider Adapter for AI Infrastructure (Phase 17).

Connects AutoForge to any OpenAI-compatible API (vLLM, llama-server, LocalAI,
OpenAI, Groq, DeepSeek, Together, OpenRouter, etc.), integrating with Phase 15 SecretsManager.
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


class OpenAICompatibleProviderAdapter(BaseProviderAdapter):
    """
    Adapter for OpenAI-compatible HTTP endpoints.
    """

    def __init__(
        self,
        provider_id: str = "openai-compatible",
        base_url: str = "https://api.openai.com/v1",
        *,
        api_key: Optional[str] = None,
        api_key_resolver: Optional[Callable[[], Optional[str]]] = None,
        secrets_manager: Any = None,
        secret_name: Optional[str] = None,
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
        self._http_client = http_client

    @property
    def base_url(self) -> str:
        return self._base_url

    def _get_api_key(self) -> Optional[str]:
        """Retrieve API key securely via SecretsManager or resolver."""
        if self._secrets_manager and self._secret_name:
            try:
                # Resolve through SecretsManager if available
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
        """Synchronous HTTP request to OpenAI-compatible endpoint."""
        if self._http_client is not None:
            return self._http_client(endpoint, payload, timeout)

        url = f"{self._base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        key = self._get_api_key()
        if key:
            headers["Authorization"] = f"Bearer {key}"

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (401, 403):
                raise ExecutionFailedError(
                    f"Authentication error ({e.code}) against {self.provider_id}",
                    details={"provider_id": self.provider_id, "status_code": e.code},
                ) from e
            elif e.code == 404:
                raise ModelUnavailableError(
                    f"Model not found at {url}: {err_body}",
                    details={"provider_id": self.provider_id, "status_code": e.code},
                ) from e
            raise ExecutionFailedError(
                f"Provider {self.provider_id} returned HTTP {e.code}: {err_body}",
                details={"provider_id": self.provider_id, "status_code": e.code},
            ) from e
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            raise ProviderUnavailableError(
                f"Provider endpoint {self._base_url} unreachable: {e}",
                details={"provider_id": self.provider_id, "error": str(e)},
            ) from e
        except TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Request to {self.provider_id} timed out after {timeout}s",
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

        params = dict(request.parameters or {})
        payload: dict[str, Any] = {
            "model": resolved_tag,
            "messages": messages,
            "stream": False,
        }

        if "temperature" in params:
            payload["temperature"] = float(params["temperature"])
        if "max_tokens" in params:
            payload["max_tokens"] = int(params["max_tokens"])
        elif "max_output_tokens" in params:
            payload["max_tokens"] = int(params["max_output_tokens"])
        if "top_p" in params:
            payload["top_p"] = float(params["top_p"])

        # Structured output format
        structured_requested = (
            params.get("structured_output")
            or params.get("response_format") == "json"
            or request.payload.get("format") == "json"
            or request.payload.get("structured_output")
        )
        if structured_requested:
            payload["response_format"] = {"type": "json_object"}

        start_time = time.perf_counter()
        try:
            raw_response = await asyncio.wait_for(
                asyncio.to_thread(self._sync_request, "/chat/completions", payload, timeout),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Execution for model '{target.model_id}' timed out after {timeout}s",
                details={"model_id": target.model_id, "provider_id": self.provider_id, "timeout": timeout},
            ) from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Extract content
        choices = raw_response.get("choices", [])
        content = ""
        finish_reason = ""
        if choices and isinstance(choices[0], dict):
            first_choice = choices[0]
            content = str(first_choice.get("message", {}).get("content", ""))
            finish_reason = str(first_choice.get("finish_reason", ""))

        # Token accounting
        usage = raw_response.get("usage") or {}
        input_tokens = usage.get("prompt_tokens", UNAVAILABLE)
        output_tokens = usage.get("completion_tokens", UNAVAILABLE)
        total_tokens = usage.get("total_tokens", UNAVAILABLE)

        tokens_per_sec: Union[float, str] = UNAVAILABLE
        if isinstance(output_tokens, (int, float)) and duration_ms > 0:
            tokens_per_sec = round((output_tokens / (duration_ms / 1000.0)), 2)

        parsed_json = extract_json_payload(content) if structured_requested else None

        output: dict[str, Any] = {
            "content": content,
            "model_id": target.model_id,
            "provider_id": self.provider_id,
            "resolved_tag": resolved_tag,
            "finish_reason": finish_reason,
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
