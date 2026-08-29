"""
Google Gemini Provider Adapter for AI Infrastructure (Phase 17).

Connects AutoForge to the Google Gemini API, integrating with Phase 15 SecretsManager.
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


class GeminiProviderAdapter(BaseProviderAdapter):
    """
    Adapter for Google Gemini API (generateContent).
    """

    def __init__(
        self,
        provider_id: str = "google-gemini",
        base_url: str = "https://generativelanguage.googleapis.com/v1beta",
        *,
        api_key: Optional[str] = None,
        api_key_resolver: Optional[Callable[[], Optional[str]]] = None,
        secrets_manager: Any = None,
        secret_name: Optional[str] = "gemini_api_key",
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
        model_tag: str,
        payload: dict[str, Any],
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        if self._http_client is not None:
            return self._http_client(model_tag, payload, timeout)

        key = self._get_api_key() or ""
        url = f"{self._base_url}/models/{model_tag}:generateContent?key={key}"
        data = json.dumps(payload).encode("utf-8")
        headers = {"Content-Type": "application/json"}

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code in (400, 403):
                raise ExecutionFailedError(
                    f"Gemini API error ({e.code}): {err_body}",
                    details={"provider_id": self.provider_id, "status_code": e.code},
                ) from e
            elif e.code == 404:
                raise ModelUnavailableError(
                    f"Model '{model_tag}' not found in Gemini API: {err_body}",
                    details={"provider_id": self.provider_id, "status_code": e.code},
                ) from e
            raise ExecutionFailedError(
                f"Gemini returned HTTP {e.code}: {err_body}",
                details={"provider_id": self.provider_id, "status_code": e.code},
            ) from e
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            raise ProviderUnavailableError(
                f"Gemini API unreachable: {e}",
                details={"provider_id": self.provider_id, "error": str(e)},
            ) from e
        except TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Gemini request timed out after {timeout}s",
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

        # Gemini contents format: parts array
        contents: list[dict[str, Any]] = []
        system_instruction = None

        for msg in messages:
            if msg["role"] == "system":
                system_instruction = {"parts": [{"text": msg["content"]}]}
            else:
                role = "user" if msg["role"] == "user" else "model"
                contents.append({"role": role, "parts": [{"text": msg["content"]}]})

        if not contents:
            contents.append({"role": "user", "parts": [{"text": ""}]})

        params = dict(request.parameters or {})
        generation_config: dict[str, Any] = {}
        if "temperature" in params:
            generation_config["temperature"] = float(params["temperature"])
        if "max_tokens" in params or "max_output_tokens" in params:
            generation_config["maxOutputTokens"] = int(params.get("max_tokens") or params.get("max_output_tokens"))
        if "top_p" in params:
            generation_config["topP"] = float(params["top_p"])

        structured_requested = (
            params.get("structured_output")
            or request.payload.get("format") == "json"
            or request.payload.get("structured_output")
        )
        if structured_requested:
            generation_config["responseMimeType"] = "application/json"

        payload: dict[str, Any] = {"contents": contents}
        if system_instruction:
            payload["systemInstruction"] = system_instruction
        if generation_config:
            payload["generationConfig"] = generation_config

        start_time = time.perf_counter()
        try:
            raw_response = await asyncio.wait_for(
                asyncio.to_thread(self._sync_request, resolved_tag, payload, timeout),
                timeout=timeout,
            )
        except asyncio.TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Gemini execution for model '{target.model_id}' timed out after {timeout}s",
                details={"model_id": target.model_id, "provider_id": self.provider_id, "timeout": timeout},
            ) from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Extract text from candidates
        candidates = raw_response.get("candidates", [])
        content = ""
        finish_reason = ""
        if candidates and isinstance(candidates[0], dict):
            cand = candidates[0]
            finish_reason = str(cand.get("finishReason", ""))
            content_obj = cand.get("content", {})
            parts = content_obj.get("parts", []) if isinstance(content_obj, dict) else []
            content = "".join(p.get("text", "") for p in parts if isinstance(p, dict))

        # Token accounting from usageMetadata
        usage = raw_response.get("usageMetadata") or {}
        input_tokens = usage.get("promptTokenCount", UNAVAILABLE)
        output_tokens = usage.get("candidatesTokenCount", UNAVAILABLE)
        total_tokens = usage.get("totalTokenCount", UNAVAILABLE)

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
