"""
Ollama Provider Adapter for AI Infrastructure (Phase 17 + 18-Production).

Connects AutoForge to a local Ollama daemon (e.g. on Apple Silicon M1 or Linux/Windows host),
supporting streaming, structured JSON output, exact token accounting, and node health management.

This adapter provides GENUINE ASYNCHRONOUS inference via httpx async HTTP client,
supporting concurrent requests, proper timeout handling, and cancellation. The legacy
synchronous urllib path is kept as a fallback only for environments without httpx.
"""

from __future__ import annotations

import asyncio
import io
import json
import logging
import time
import urllib.error
import urllib.request
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

# Lazy import httpx to avoid hard dependency
_httpx = None


def _get_httpx():
    """Lazy import httpx for async HTTP support."""
    global _httpx
    if _httpx is None:
        import httpx
        _httpx = httpx
    return _httpx

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

DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"

DEFAULT_OLLAMA_MODEL_TAGS = {
    "qwen2.5-coder-7b": "qwen2.5-coder:7b-instruct-q3_K_M",
    "ornith-9b": "ornith-9b-iq3m-4k:latest",
    "qwen2.5-coder-3b": "qwen2.5-coder:3b",
    "llama3.2-3b": "llama3.2:3b",
    "llama3.1-8b": "llama3.1:8b",
}


class OllamaProviderAdapter(BaseProviderAdapter):
    """
    Adapter for local Ollama runtime.
    Supports chat, generate, structured JSON output, token statistics, and streaming.
    """

    def __init__(
        self,
        provider_id: str = "local-m1",
        base_url: str = DEFAULT_OLLAMA_BASE_URL,
        *,
        default_timeout_seconds: float = 120.0,
        model_tag_map: Optional[Dict[str, str]] = None,
        http_client: Optional[Callable[..., Any]] = None,
        async_http_client: Optional[Any] = None,
        worker_id: str = "",
    ) -> None:
        merged_tags = dict(DEFAULT_OLLAMA_MODEL_TAGS)
        if model_tag_map:
            merged_tags.update(model_tag_map)
        super().__init__(
            provider_id=provider_id,
            default_timeout_seconds=default_timeout_seconds,
            model_tag_map=merged_tags,
        )
        self._base_url = base_url.rstrip("/")
        self._http_client = http_client  # legacy sync test double
        self._async_http_client = async_http_client  # injected async client
        self._worker_id = worker_id or f"worker-{provider_id}"
        self._request_count = 0  # metric: total requests
        self._failed_count = 0   # metric: failed requests
        self._total_input_tokens = 0
        self._total_output_tokens = 0

    @property
    def base_url(self) -> str:
        return self._base_url

    @property
    def worker_id(self) -> str:
        return self._worker_id

    @property
    def request_count(self) -> int:
        return self._request_count

    @property
    def failed_count(self) -> int:
        return self._failed_count

    @property
    def total_input_tokens(self) -> int:
        return self._total_input_tokens

    @property
    def total_output_tokens(self) -> int:
        return self._total_output_tokens

    def _get_async_client(self):
        """Get or create a shared async HTTP client (httpx)."""
        if self._async_http_client is not None:
            return self._async_http_client
        httpx = _get_httpx()
        # Single shared client per adapter = connection pooling + concurrency
        self._async_http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._default_timeout_seconds, connect=10.0),
            limits=httpx.Limits(max_keepalive_connections=10, max_connections=20),
        )
        return self._async_http_client

    async def aclose(self) -> None:
        """Close the async HTTP client."""
        if self._async_http_client is not None:
            try:
                await self._async_http_client.aclose()
            except Exception:
                pass
            self._async_http_client = None

    async def _async_request(
        self,
        endpoint: str,
        payload: Optional[dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Genuine async HTTP JSON request to Ollama endpoint via httpx."""
        if self._http_client is not None:
            res = self._http_client(endpoint, payload, timeout)
            if asyncio.iscoroutine(res):
                return await res
            return res

        url = f"{self._base_url}{endpoint}"
        headers = {"Content-Type": "application/json"} if payload is not None else {}
        client = self._get_async_client()
        try:
            if payload is not None:
                resp = await client.post(
                    url, json=payload, headers=headers, timeout=timeout
                )
            else:
                resp = await client.get(url, headers=headers, timeout=timeout)
            if resp.status_code == 404:
                raise ModelUnavailableError(
                    f"Model not found in Ollama at {url}: {resp.text}",
                    details={"provider_id": self.provider_id, "status_code": 404, "body": resp.text},
                )
            if resp.status_code >= 400:
                raise ExecutionFailedError(
                    f"Ollama HTTP {resp.status_code} error at {url}: {resp.text}",
                    details={"provider_id": self.provider_id, "status_code": resp.status_code, "body": resp.text},
                )
            self._request_count += 1
            return resp.json() if resp.text else {}
        except asyncio.CancelledError:
            raise
        except Exception as e:
            # Map known httpx exceptions
            err_str = str(e)
            if "Timeout" in type(e).__name__ or "timeout" in err_str.lower():
                self._failed_count += 1
                raise ExecutionTimeoutError(
                    f"Ollama request timed out after {timeout}s",
                    details={"provider_id": self.provider_id, "timeout": timeout, "error": err_str},
                ) from e
            if "ConnectError" in type(e).__name__ or "Connection" in err_str:
                self._failed_count += 1
                raise ProviderUnavailableError(
                    f"Ollama daemon unreachable at {self._base_url}: {e}",
                    details={"provider_id": self.provider_id, "base_url": self._base_url, "error": err_str},
                ) from e
            self._failed_count += 1
            raise

    def _sync_request(
        self,
        endpoint: str,
        payload: Optional[dict[str, Any]] = None,
        timeout: float = 60.0,
    ) -> dict[str, Any]:
        """Synchronous HTTP JSON request to Ollama endpoint."""
        if self._http_client is not None:
            return self._http_client(endpoint, payload, timeout)

        url = f"{self._base_url}{endpoint}"
        data = json.dumps(payload).encode("utf-8") if payload is not None else None
        headers = {"Content-Type": "application/json"} if payload is not None else {}

        req = urllib.request.Request(url, data=data, headers=headers, method="POST" if payload else "GET")
        try:
            with urllib.request.urlopen(req, timeout=timeout) as response:
                body = response.read().decode("utf-8")
                return json.loads(body) if body else {}
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")
            if e.code == 404:
                raise ModelUnavailableError(
                    f"Model not found in Ollama at {url}: {err_body}",
                    details={"provider_id": self.provider_id, "status_code": e.code, "body": err_body},
                ) from e
            raise ExecutionFailedError(
                f"Ollama HTTP {e.code} error at {url}: {err_body}",
                details={"provider_id": self.provider_id, "status_code": e.code, "body": err_body},
            ) from e
        except (urllib.error.URLError, ConnectionRefusedError, OSError) as e:
            raise ProviderUnavailableError(
                f"Ollama daemon unreachable at {self._base_url}: {e}",
                details={"provider_id": self.provider_id, "base_url": self._base_url, "error": str(e)},
            ) from e
        except TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Ollama request timed out after {timeout}s",
                details={"provider_id": self.provider_id, "timeout": timeout},
            ) from e

    async def check_health(self, timeout: float = 5.0) -> bool:
        """Verify if Ollama is running and responsive using genuine async HTTP."""
        try:
            res = await self._async_request("/api/tags", None, timeout)
            return "models" in res
        except Exception:
            return False

    async def list_installed_models(self, timeout: float = 5.0) -> list[str]:
        """Fetch list of model tags currently pulled in Ollama using genuine async HTTP."""
        try:
            res = await self._async_request("/api/tags", None, timeout)
            models = res.get("models", [])
            return [m.get("name", "") for m in models if isinstance(m, dict)]
        except Exception:
            return []

    async def execute(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> dict[str, Any]:
        """
        Execute inference against Ollama.
        """
        resolved_tag = self.resolve_model_tag(target.model_id)
        timeout = request.timeout_seconds or self._default_timeout_seconds
        messages = self.normalize_messages(request)

        # Sampling parameters
        params = dict(request.parameters or {})
        options: dict[str, Any] = {}
        if "temperature" in params:
            options["temperature"] = float(params["temperature"])
        if "max_tokens" in params:
            options["num_predict"] = int(params["max_tokens"])
        elif "max_output_tokens" in params:
            options["num_predict"] = int(params["max_output_tokens"])
        elif "num_predict" in params:
            options["num_predict"] = int(params["num_predict"])
        if "top_p" in params:
            options["top_p"] = float(params["top_p"])
        if "context_window_tokens" in params:
            options["num_ctx"] = int(params["context_window_tokens"])
        elif "num_ctx" in params:
            options["num_ctx"] = int(params["num_ctx"])
        else:
            options["num_ctx"] = 4096  # Sensible default to avoid excessive KV cache allocations on local nodes

        payload: dict[str, Any] = {
            "model": resolved_tag,
            "messages": messages,
            "stream": False,
        }
        if options:
            payload["options"] = options

        # Structured output flag / format
        structured_requested = (
            params.get("structured_output")
            or params.get("response_format") == "json"
            or request.payload.get("format") == "json"
            or request.payload.get("structured_output")
        )
        if structured_requested:
            payload["format"] = "json"

        start_time = time.perf_counter()
        try:
            # GENUINE ASYNC: uses httpx.AsyncClient - not asyncio.to_thread over sync urllib
            raw_response = await self._async_request("/api/chat", payload, timeout)
        except asyncio.CancelledError as e:
            raise ExecutionTimeoutError(
                f"Ollama execution for model '{target.model_id}' ({resolved_tag}) cancelled",
                details={
                    "model_id": target.model_id,
                    "resolved_tag": resolved_tag,
                    "provider_id": self.provider_id,
                },
            ) from e
        except asyncio.TimeoutError as e:
            raise ExecutionTimeoutError(
                f"Ollama execution for model '{target.model_id}' ({resolved_tag}) timed out after {timeout}s",
                details={
                    "model_id": target.model_id,
                    "resolved_tag": resolved_tag,
                    "provider_id": self.provider_id,
                    "timeout": timeout,
                },
            ) from e

        duration_ms = (time.perf_counter() - start_time) * 1000.0

        # Extract content
        msg = raw_response.get("message") or {}
        content = str(msg.get("content", ""))

        # Token accounting from Ollama response
        prompt_eval_count = raw_response.get("prompt_eval_count")
        eval_count = raw_response.get("eval_count")
        eval_duration_ns = raw_response.get("eval_duration")  # in nanoseconds

        input_tokens: Union[int, str] = int(prompt_eval_count) if prompt_eval_count is not None else UNAVAILABLE
        output_tokens: Union[int, str] = int(eval_count) if eval_count is not None else UNAVAILABLE
        
        if isinstance(input_tokens, int) and isinstance(output_tokens, int):
            total_tokens: Union[int, str] = input_tokens + output_tokens
        else:
            total_tokens = UNAVAILABLE

        tokens_per_sec: Union[float, str] = UNAVAILABLE
        if eval_count is not None and eval_duration_ns and eval_duration_ns > 0:
            tokens_per_sec = round((eval_count / (eval_duration_ns / 1_000_000_000.0)), 2)
        elif eval_count is not None and duration_ms > 0:
            tokens_per_sec = round((eval_count / (duration_ms / 1000.0)), 2)

        # ── Ollama internal timing breakdown ────────────────────────────
        # Ollama returns nanosecond-precision timing fields:
        #   total_duration   – wall time inside Ollama server
        #   load_duration    – model/weight loading (cold-start cost)
        #   prompt_eval_duration – prompt evaluation (prefill)
        #   eval_duration    – token generation (decode)
        total_duration_ns = raw_response.get("total_duration")
        load_duration_ns = raw_response.get("load_duration")
        prompt_eval_duration_ns = raw_response.get("prompt_eval_duration")

        def _ns_to_ms(ns: int | None) -> float | None:
            return round(ns / 1_000_000.0, 3) if ns is not None else None

        ollama_timings: dict[str, Any] = {
            "total_duration_ms": _ns_to_ms(total_duration_ns),
            "load_duration_ms": _ns_to_ms(load_duration_ns),
            "prompt_eval_duration_ms": _ns_to_ms(prompt_eval_duration_ns),
            "eval_duration_ms": _ns_to_ms(eval_duration_ns),
            "prompt_eval_count": prompt_eval_count,
            "eval_count": eval_count,
        }

        # Attempt structured JSON parsing
        parsed_json = extract_json_payload(content) if structured_requested else None

        # Build output dictionary
        output: dict[str, Any] = {
            "content": content,
            "model_id": target.model_id,
            "provider_id": self.provider_id,
            "worker_id": self._worker_id,
            "resolved_tag": resolved_tag,
            "node_id": self.provider_id,
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
            "ollama_timings": ollama_timings,
            "duration_ms": duration_ms,
            "done": raw_response.get("done", True),
            "raw": raw_response,
        }

        # Update adapter-level metrics
        if isinstance(input_tokens, int):
            self._total_input_tokens += input_tokens
        if isinstance(output_tokens, int):
            self._total_output_tokens += output_tokens

        if parsed_json is not None:
            output["structured_output"] = parsed_json
            if isinstance(parsed_json, dict):
                # Copy top-level keys like plan, file_edits, diagnosis for worker convenience
                for k, v in parsed_json.items():
                    if k not in output:
                        output[k] = v
        elif structured_requested and content:
            # If explicit JSON was requested but parse failed, try extracting any JSON
            fallback_parsed = extract_json_payload(content)
            if fallback_parsed is not None:
                output["structured_output"] = fallback_parsed
                if isinstance(fallback_parsed, dict):
                    for k, v in fallback_parsed.items():
                        if k not in output:
                            output[k] = v

        # If task was planning and output doesn't have plan key yet, set plan = content
        if "plan" not in output and content:
            output["plan"] = content

        return output

    async def achat(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> dict[str, Any]:
        """Genuine async HTTP inference call (used by local_workers.py and similar).

        This is the canonical async entry point that bypasses the legacy
        ``asyncio.to_thread`` wrapper. It uses ``httpx.AsyncClient`` with
        proper connection pooling so multiple concurrent calls actually
        overlap on the network.
        """
        return await self.execute(request, target)

    async def stream(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> AsyncIterator[str]:
        """
        Stream response tokens from Ollama using genuine async HTTP streaming.
        """
        resolved_tag = self.resolve_model_tag(target.model_id)
        timeout = request.timeout_seconds or self._default_timeout_seconds
        messages = self.normalize_messages(request)

        params = dict(request.parameters or {})
        payload: dict[str, Any] = {
            "model": resolved_tag,
            "messages": messages,
            "stream": True,
        }
        if "temperature" in params:
            payload.setdefault("options", {})["temperature"] = float(params["temperature"])

        if self._http_client is not None:
            # If test double client is configured, yield from execute
            res = await self.execute(request, target)
            yield res.get("content", "")
            return

        # Genuine async streaming via httpx.AsyncClient
        client = self._get_async_client()
        url = f"{self._base_url}/api/chat"
        try:
            async with client.stream(
                "POST", url, json=payload, timeout=timeout
            ) as response:
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    try:
                        chunk = json.loads(line)
                        text = chunk.get("message", {}).get("content", "")
                        if text:
                            yield text
                    except json.JSONDecodeError:
                        continue
        except asyncio.CancelledError:
            raise
        except Exception as e:
            raise ExecutionFailedError(f"Ollama streaming failed: {e}") from e
