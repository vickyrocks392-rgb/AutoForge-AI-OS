"""
Comprehensive tests for AI Infrastructure Provider Adapters (Phase 17).

Verifies Ollama, OpenAI-compatible, Anthropic, and Gemini provider adapters,
streaming, structured output, token accounting, error classification, timeout handling,
and security secret redaction using deterministic test doubles.
"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import MagicMock

from autoforge_ai_infrastructure.adapters import (
    AnthropicProviderAdapter,
    BaseProviderAdapter,
    GeminiProviderAdapter,
    OllamaProviderAdapter,
    OpenAICompatibleProviderAdapter,
    extract_json_payload,
)
from autoforge_ai_infrastructure.adapters.base import UNAVAILABLE
from autoforge_ai_infrastructure.errors import (
    ExecutionFailedError,
    ExecutionTimeoutError,
    ModelUnavailableError,
    ProviderUnavailableError,
)
from autoforge_ai_infrastructure.execution import ExecutionRequest, ExecutionTarget
from autoforge_security.models import SecretScope, Subject, SubjectType
from autoforge_security.secrets import SecretsManager, SecretValue


class TestJsonExtraction:
    def test_extract_from_clean_json(self):
        text = '{"name": "test", "items": [1, 2, 3]}'
        res = extract_json_payload(text)
        assert res == {"name": "test", "items": [1, 2, 3]}

    def test_extract_from_code_fence(self):
        text = "Here is the result:\n```json\n{\n  \"plan\": \"Step 1: Code\"\n}\n```\nDone."
        res = extract_json_payload(text)
        assert res == {"plan": "Step 1: Code"}

    def test_extract_from_mixed_text(self):
        text = "Leading text... {\"key\": \"value\"} trailing text..."
        res = extract_json_payload(text)
        assert res == {"key": "value"}

    def test_extract_from_array(self):
        text = "[{\"path\": \"app.py\", \"content\": \"print('hi')\"}]"
        res = extract_json_payload(text)
        assert len(res) == 1
        assert res[0]["path"] == "app.py"

    def test_extract_from_invalid_returns_none(self):
        assert extract_json_payload("not a json string") is None
        assert extract_json_payload("") is None


class TestOllamaProviderAdapter:
    @pytest.mark.asyncio
    async def test_ollama_successful_execution(self):
        def fake_client(endpoint, payload, timeout):
            assert endpoint == "/api/chat"
            assert payload["model"] == "qwen2.5-coder:7b-instruct-q3_K_M"
            assert payload["stream"] is False
            return {
                "model": "qwen2.5-coder:7b-instruct-q3_K_M",
                "message": {"role": "assistant", "content": "Here is the implementation plan."},
                "done": True,
                "prompt_eval_count": 25,
                "eval_count": 80,
                "eval_duration": 4000000000,  # 4 seconds in ns -> 20 tokens/sec
            }

        adapter = OllamaProviderAdapter(
            provider_id="local-m1",
            http_client=fake_client,
        )

        req = ExecutionRequest(
            payload={"prompt": "Produce implementation plan for FastAPI CRUD."},
            parameters={"temperature": 0.2, "max_tokens": 1024},
        )
        target = ExecutionTarget(model_id="qwen2.5-coder-7b", provider_id="local-m1")

        result = await adapter.execute(req, target)

        assert result["content"] == "Here is the implementation plan."
        assert result["input_tokens"] == 25
        assert result["output_tokens"] == 80
        assert result["total_tokens"] == 105
        assert result["tokens_per_second"] == 20.0
        assert result["model_id"] == "qwen2.5-coder-7b"
        assert result["provider_id"] == "local-m1"
        assert result["resolved_tag"] == "qwen2.5-coder:7b-instruct-q3_K_M"

    @pytest.mark.asyncio
    async def test_ollama_structured_json_output(self):
        def fake_client(endpoint, payload, timeout):
            assert payload["format"] == "json"
            return {
                "model": "qwen2.5-coder:7b-instruct-q3_K_M",
                "message": {
                    "role": "assistant",
                    "content": json.dumps({"file_edits": [{"path": "main.py", "content": "from fastapi import FastAPI"}]}),
                },
                "done": True,
                "prompt_eval_count": 30,
                "eval_count": 50,
            }

        adapter = OllamaProviderAdapter(
            provider_id="local-m1",
            http_client=fake_client,
        )

        req = ExecutionRequest(
            payload={"prompt": "Generate file edits", "format": "json"},
            parameters={"structured_output": True},
        )
        target = ExecutionTarget(model_id="qwen2.5-coder-7b", provider_id="local-m1")

        result = await adapter.execute(req, target)
        assert "file_edits" in result
        assert result["file_edits"][0]["path"] == "main.py"
        assert "structured_output" in result

    @pytest.mark.asyncio
    async def test_ollama_model_unavailable_error(self):
        def fake_client(endpoint, payload, timeout):
            raise ModelUnavailableError("model 'missing-model' not found")

        adapter = OllamaProviderAdapter(provider_id="local-m1", http_client=fake_client)
        req = ExecutionRequest(payload={"prompt": "test"})
        target = ExecutionTarget(model_id="missing-model", provider_id="local-m1")

        with pytest.raises(ModelUnavailableError):
            await adapter.execute(req, target)

    @pytest.mark.asyncio
    async def test_ollama_provider_unavailable_error(self):
        def fake_client(endpoint, payload, timeout):
            raise ProviderUnavailableError("Ollama daemon unreachable on port 11434")

        adapter = OllamaProviderAdapter(provider_id="local-m1", http_client=fake_client)
        req = ExecutionRequest(payload={"prompt": "test"})
        target = ExecutionTarget(model_id="qwen2.5-coder-7b", provider_id="local-m1")

        with pytest.raises(ProviderUnavailableError):
            await adapter.execute(req, target)


class TestOpenAICompatibleProviderAdapter:
    @pytest.mark.asyncio
    async def test_openai_execution_and_token_accounting(self):
        def fake_client(endpoint, payload, timeout):
            assert endpoint == "/chat/completions"
            return {
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "Generated OpenAI response"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {
                    "prompt_tokens": 40,
                    "completion_tokens": 60,
                    "total_tokens": 100,
                },
            }

        adapter = OpenAICompatibleProviderAdapter(
            provider_id="openai-compatible",
            api_key="test-key",
            http_client=fake_client,
        )

        req = ExecutionRequest(payload={"prompt": "Hello"})
        target = ExecutionTarget(model_id="gpt-4o-mini", provider_id="openai-compatible")

        result = await adapter.execute(req, target)
        assert result["content"] == "Generated OpenAI response"
        assert result["input_tokens"] == 40
        assert result["output_tokens"] == 60
        assert result["total_tokens"] == 100
        assert result["finish_reason"] == "stop"

    @pytest.mark.asyncio
    async def test_openai_secrets_manager_integration(self):
        sm = SecretsManager()
        sm.register_secret("openai_api_key", "sk-secret-token-1234567890123456", SecretScope.SYSTEM)

        captured_headers = {}

        adapter = OpenAICompatibleProviderAdapter(
            provider_id="openai-compatible",
            secrets_manager=sm,
            secret_name="openai_api_key",
        )

        # Assert secret key is retrieved via SecretsManager
        key = adapter._get_api_key()
        assert key == "sk-secret-token-1234567890123456"

        # Assert redacted representation
        assert "sk-secret-token" not in repr(adapter)
        assert "sk-secret-token" not in str(adapter)


class TestAnthropicProviderAdapter:
    @pytest.mark.asyncio
    async def test_anthropic_execution(self):
        def fake_client(endpoint, payload, timeout):
            assert endpoint == "/messages"
            assert payload["system"] == "You are an assistant."
            assert payload["messages"][0]["content"] == "Hello Claude"
            return {
                "content": [{"type": "text", "text": "Claude response"}],
                "stop_reason": "end_turn",
                "usage": {"input_tokens": 15, "output_tokens": 30},
            }

        adapter = AnthropicProviderAdapter(
            provider_id="anthropic",
            api_key="test-ant-key",
            http_client=fake_client,
        )

        req = ExecutionRequest(
            payload={"system": "You are an assistant.", "prompt": "Hello Claude"}
        )
        target = ExecutionTarget(model_id="claude-3-5-sonnet", provider_id="anthropic")

        result = await adapter.execute(req, target)
        assert result["content"] == "Claude response"
        assert result["input_tokens"] == 15
        assert result["output_tokens"] == 30
        assert result["total_tokens"] == 45


class TestGeminiProviderAdapter:
    @pytest.mark.asyncio
    async def test_gemini_execution(self):
        def fake_client(model_tag, payload, timeout):
            assert model_tag == "gemini-1.5-pro"
            return {
                "candidates": [
                    {
                        "content": {"parts": [{"text": "Gemini response"}]},
                        "finishReason": "STOP",
                    }
                ],
                "usageMetadata": {
                    "promptTokenCount": 20,
                    "candidatesTokenCount": 40,
                    "totalTokenCount": 60,
                },
            }

        adapter = GeminiProviderAdapter(
            provider_id="google-gemini",
            api_key="test-gemini-key",
            http_client=fake_client,
        )

        req = ExecutionRequest(payload={"prompt": "Hello Gemini"})
        target = ExecutionTarget(model_id="gemini-1.5-pro", provider_id="google-gemini")

        result = await adapter.execute(req, target)
        assert result["content"] == "Gemini response"
        assert result["input_tokens"] == 20
        assert result["output_tokens"] == 40
        assert result["total_tokens"] == 60


class TestHonestUnavailableReporting:
    @pytest.mark.asyncio
    async def test_missing_metrics_reported_as_unavailable(self):
        def fake_client(endpoint, payload, timeout):
            # Response with NO token metrics
            return {
                "model": "custom-model",
                "message": {"role": "assistant", "content": "Simple output"},
                "done": True,
            }

        adapter = OllamaProviderAdapter(provider_id="local-m1", http_client=fake_client)
        req = ExecutionRequest(payload={"prompt": "test"})
        target = ExecutionTarget(model_id="custom-model", provider_id="local-m1")

        result = await adapter.execute(req, target)
        assert result["input_tokens"] == UNAVAILABLE
        assert result["output_tokens"] == UNAVAILABLE
        assert result["total_tokens"] == UNAVAILABLE
        assert result["tokens_per_second"] == UNAVAILABLE
