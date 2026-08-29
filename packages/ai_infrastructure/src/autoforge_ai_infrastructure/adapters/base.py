"""
Base provider adapter abstraction for AI Infrastructure (Phase 17).

Provides common request normalization, prompt/message formatting,
streaming primitives, token accounting, error handling, and structured JSON parsing.
"""

from __future__ import annotations

import abc
import asyncio
import json
import logging
import re
import time
from typing import Any, AsyncIterator, Callable, Dict, List, Optional, Union

from autoforge_ai_infrastructure.errors import (
    ExecutionFailedError,
    ExecutionTimeoutError,
    ModelUnavailableError,
    ProviderUnavailableError,
)
from autoforge_ai_infrastructure.execution import ExecutionRequest, ExecutionTarget
from autoforge_ai_infrastructure.interfaces import ModelExecutor

logger = logging.getLogger(__name__)

UNAVAILABLE = "UNAVAILABLE"


def extract_json_payload(text: str) -> Optional[Union[dict, list]]:
    """
    Robustly extract and parse JSON payload from LLM generated text.
    Handles Markdown code fences (```json ... ```), raw JSON objects/arrays,
    and leading/trailing commentary.
    """
    if not text or not isinstance(text, str):
        return None

    cleaned = text.strip()

    # 1. Check for fenced code block: ```json ... ``` or ``` ... ```
    fence_pattern = re.compile(r"```(?:json)?\s*([\s\S]*?)\s*```", re.IGNORECASE)
    matches = fence_pattern.findall(cleaned)
    if matches:
        for match in matches:
            candidate = match.strip()
            try:
                return json.loads(candidate)
            except Exception:
                continue

    # 2. Try parsing full cleaned string
    try:
        return json.loads(cleaned)
    except Exception:
        pass

    # 3. Locate first '{' or '[' and last '}' or ']'
    first_brace = cleaned.find("{")
    first_bracket = cleaned.find("[")

    start_idx = -1
    end_idx = -1

    if first_brace != -1 and (first_bracket == -1 or first_brace < first_bracket):
        start_idx = first_brace
        end_idx = cleaned.rfind("}")
    elif first_bracket != -1:
        start_idx = first_bracket
        end_idx = cleaned.rfind("]")

    if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
        candidate = cleaned[start_idx : end_idx + 1]
        try:
            return json.loads(candidate)
        except Exception:
            pass

    return None


class BaseProviderAdapter(abc.ABC, ModelExecutor):
    """
    Abstract base provider adapter for local and cloud model execution.
    """

    def __init__(
        self,
        provider_id: str,
        *,
        default_timeout_seconds: float = 60.0,
        model_tag_map: Optional[Dict[str, str]] = None,
    ) -> None:
        self._provider_id = provider_id
        self._default_timeout_seconds = default_timeout_seconds
        self._model_tag_map = dict(model_tag_map or {})

    @property
    def provider_id(self) -> str:
        return self._provider_id

    def resolve_model_tag(self, model_id: str) -> str:
        """Map canonical model id to provider-specific model tag/name."""
        return self._model_tag_map.get(model_id, model_id)

    def register_model_alias(self, canonical_model_id: str, provider_model_tag: str) -> None:
        """Register a model tag mapping."""
        self._model_tag_map[canonical_model_id] = provider_model_tag

    def normalize_messages(self, request: ExecutionRequest) -> list[dict[str, str]]:
        """
        Normalize payload from ExecutionRequest into standard chat messages format:
        [{"role": "system", "content": "..."}, {"role": "user", "content": "..."}]
        """
        payload = request.payload or {}
        if "payload" in payload and isinstance(payload["payload"], dict) and any(
            k in payload["payload"] for k in ("prompt", "messages", "task", "system", "context")
        ):
            payload = payload["payload"]

        # 1. If explicit messages list is provided
        if "messages" in payload and isinstance(payload["messages"], list):
            return [
                {"role": str(m.get("role", "user")), "content": str(m.get("content", ""))}
                for m in payload["messages"]
                if isinstance(m, dict)
            ]

        messages: list[dict[str, str]] = []

        # 2. System prompt
        system_prompt = payload.get("system") or payload.get("system_prompt")
        if system_prompt:
            messages.append({"role": "system", "content": str(system_prompt)})

        # 3. Context / Task prompt
        prompt = payload.get("prompt")
        task = payload.get("task")
        context = payload.get("context")
        plan = payload.get("plan")
        evidence = payload.get("evidence")
        diagnosis = payload.get("diagnosis")

        if prompt:
            messages.append({"role": "user", "content": str(prompt)})
        elif task:
            parts = [f"Task: {task}"]
            if plan:
                parts.append(f"Plan:\n{plan}")
            if evidence:
                parts.append(f"Failure Evidence:\n{json.dumps(evidence, indent=2)}")
            if diagnosis:
                parts.append(f"Diagnosis Report:\n{json.dumps(diagnosis, indent=2)}")
            if context:
                parts.append(f"Context:\n{context}")
            messages.append({"role": "user", "content": "\n\n".join(parts)})
        elif context:
            messages.append({"role": "user", "content": str(context)})
        else:
            messages.append({"role": "user", "content": ""})

        return messages

    def extract_prompt_text(self, request: ExecutionRequest) -> str:
        """Convert normalized messages into a single text prompt."""
        messages = self.normalize_messages(request)
        return "\n\n".join(
            f"[{msg['role'].upper()}]: {msg['content']}" if msg["role"] != "user" else msg["content"]
            for msg in messages
            if msg.get("content")
        )

    @abc.abstractmethod
    async def execute(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> dict[str, Any]:
        """
        Execute request against target. Returns output dict satisfying ExecutionResult.output contract.
        """
        raise NotImplementedError

    async def stream(
        self,
        request: ExecutionRequest,
        target: ExecutionTarget,
    ) -> AsyncIterator[str]:
        """
        Stream output tokens for request against target.
        Default implementation yields the complete execution output once if streaming is not overridden.
        """
        res = await self.execute(request, target)
        content = res.get("content") or ""
        yield content
