"""Phase 20-C Gate 1: Custom AI Agent Inference Provider Alignment Regression Suite.

Validates:
1. Default configuration resolves to the approved MLX endpoint and model.
2. Explicit configuration overrides (base_url, model_name, provider) are respected.
3. No implicit Ollama fallback occurs when MLX is unreachable or errors.
4. An unreachable endpoint produces a clear, bounded failure.
5. Malformed responses and provider errors are handled safely.
6. Existing agent tool-call parsing and execution contracts remain intact.
7. Unit tests run deterministically without requiring a live Ollama server or external network.
8. Live MLX smoke test against the authorized local MLX endpoint (when reachable).
"""

from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch
import requests

from autoforge_power_engines.agent.spec import (
    CustomerAgentSpecification,
    AgentModelConfig,
    ExecutionLimits,
)
from autoforge_power_engines.agent.runtime import (
    StandaloneAgentRuntime,
    GenericHTTPModelProvider,
    OllamaModelProvider,
    ModelProvider,
)
from autoforge_power_engines.agent.state_machine import AgentExecutionState
from autoforge_power_engines.agent.parser import RobustToolCallParser, ParsedToolCall


AUTHORIZED_MLX_BASE_URL = "http://127.0.0.1:19801/v1"
AUTHORIZED_MLX_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"


class MockEchoProvider(ModelProvider):
    """Deterministic mock provider that emits predefined responses."""

    def __init__(self, responses: list[dict]):
        self.responses = list(responses)
        self.call_history: list[dict] = []

    def generate_turn(
        self,
        messages: list[dict],
        tools: list[dict] | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> dict:
        self.call_history.append({
            "messages": messages,
            "tools": tools,
            "temperature": temperature,
            "max_tokens": max_tokens,
        })
        if self.responses:
            return self.responses.pop(0)
        return {"message": {"role": "assistant", "content": "Default response."}}


class TestAgentInferenceProviderAlignment(unittest.TestCase):
    """Phase 20-C Gate 1 Regression Suite."""

    # ── 1. Default configuration resolves to approved MLX endpoint and model ───
    def test_01_default_configuration_resolves_to_authorized_mlx(self):
        """Default AgentModelConfig must target authorized local MLX server and model."""
        cfg = AgentModelConfig()
        self.assertEqual(cfg.provider, "generic_http")
        self.assertEqual(cfg.base_url, AUTHORIZED_MLX_BASE_URL)
        self.assertEqual(cfg.model_name, AUTHORIZED_MLX_MODEL)

        spec = CustomerAgentSpecification(
            project_name="Default Config Test",
            agent_purpose="Test default provider resolution.",
            system_instructions="You are a test assistant.",
        )
        runtime = StandaloneAgentRuntime(spec=spec)
        self.assertIsInstance(runtime.model_provider, GenericHTTPModelProvider)
        self.assertEqual(runtime.model_provider.base_url, AUTHORIZED_MLX_BASE_URL)
        self.assertEqual(runtime.model_provider.model_name, AUTHORIZED_MLX_MODEL)

    # ── 2. Explicit configuration overrides still work ─────────────────────────
    def test_02_explicit_configuration_overrides(self):
        """Explicitly configured provider, base_url, or model_name must be honored."""
        # Generic HTTP override
        cfg_custom = AgentModelConfig(
            provider="generic_http",
            base_url="http://192.168.1.50:8000/v1",
            model_name="custom-hosted-model-v1",
            timeout_seconds=45.0,
        )
        spec_custom = CustomerAgentSpecification(
            project_name="Custom Config Agent",
            agent_purpose="Test explicit override.",
            system_instructions="You are a test assistant.",
            model_config_spec=cfg_custom,
        )
        runtime_custom = StandaloneAgentRuntime(spec=spec_custom)
        self.assertIsInstance(runtime_custom.model_provider, GenericHTTPModelProvider)
        self.assertEqual(runtime_custom.model_provider.base_url, "http://192.168.1.50:8000/v1")
        self.assertEqual(runtime_custom.model_provider.model_name, "custom-hosted-model-v1")
        self.assertEqual(runtime_custom.model_provider.timeout, 45.0)

        # Explicit Ollama provider is strictly rejected by AutoForge frozen inference policy
        cfg_ollama = AgentModelConfig(
            provider="ollama",
            base_url="http://127.0.0.1:11434",
            model_name="qwen2.5-coder:7b",
        )
        spec_ollama = CustomerAgentSpecification(
            project_name="Explicit Ollama Agent",
            agent_purpose="Test explicit ollama provider rejection.",
            system_instructions="You are an assistant.",
            model_config_spec=cfg_ollama,
        )
        with self.assertRaises(ValueError) as ctx:
            StandaloneAgentRuntime(spec=spec_ollama)
        self.assertIn("AutoForge frozen inference policy violation", str(ctx.exception))

        # Direct OllamaModelProvider execution fails closed
        ollama_p = OllamaModelProvider()
        with self.assertRaises(RuntimeError) as ctx_rt:
            ollama_p.generate_turn([{"role": "user", "content": "hi"}])
        self.assertIn("AutoForge frozen inference policy violation", str(ctx_rt.exception))

    # ── 3. No implicit Ollama fallback ─────────────────────────────────────────
    def test_03_no_implicit_ollama_fallback_on_failure(self):
        """A failure on the MLX endpoint must NOT silently fall back to Ollama."""
        spec = CustomerAgentSpecification(
            project_name="No Fallback Test",
            agent_purpose="Verify strict failure isolation.",
            system_instructions="You are a test assistant.",
            model_config_spec=AgentModelConfig(
                base_url="http://127.0.0.1:19999/v1",
                timeout_seconds=0.5,
            ),
        )
        runtime = StandaloneAgentRuntime(spec=spec)

        with patch("autoforge_power_engines.agent.runtime.OllamaModelProvider.generate_turn") as mock_ollama:
            res = runtime.run("Hello test")
            self.assertEqual(res.status, AgentExecutionState.FAILED.value)
            mock_ollama.assert_not_called()
            self.assertIn("Execution failed", res.final_response)

    # ── 4. Unreachable endpoint produces clear, bounded failure ────────────────
    def test_04_unreachable_endpoint_produces_bounded_failure(self):
        """An unreachable host/port must produce an explicit, bounded failure without hanging."""
        spec = CustomerAgentSpecification(
            project_name="Unreachable Endpoint Test",
            agent_purpose="Verify bounded timeout and error capture.",
            system_instructions="You are a test assistant.",
            model_config_spec=AgentModelConfig(
                base_url="http://127.0.0.1:19998/v1",
                timeout_seconds=1.0,
            ),
            execution_limits=ExecutionLimits(max_iterations=2, total_timeout_seconds=5.0),
        )
        runtime = StandaloneAgentRuntime(spec=spec)
        res = runtime.run("Ping")

        self.assertEqual(res.status, AgentExecutionState.FAILED.value)
        self.assertGreater(len(res.telemetry.errors), 0)
        self.assertIn("19998", str(res.telemetry.errors))
        self.assertEqual(res.iterations, 1)

    # ── 5. Malformed responses and provider errors handled safely ──────────────
    def test_05_malformed_responses_handled_safely(self):
        """Malformed or empty JSON responses from provider must be handled safely."""
        malformed_mock = MockEchoProvider([
            {"choices": []},  # Empty choices
            {"error": "Internal upstream error"},  # Error object without choices
        ])
        spec = CustomerAgentSpecification(
            project_name="Malformed Response Test",
            agent_purpose="Verify graceful handling of unexpected payloads.",
            system_instructions="You are a test assistant.",
            execution_limits=ExecutionLimits(max_iterations=2),
        )
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=malformed_mock)
        res = runtime.run("Test query")

        # Runtime should complete turn safely using default text or fail verification cleanly
        self.assertIn(res.status, [AgentExecutionState.COMPLETED.value, AgentExecutionState.FAILED.value])
        self.assertIsNotNone(res.final_response)

    # ── 6. Tool-call parsing and execution contracts remain intact ─────────────
    def test_06_tool_call_parsing_and_execution_intact(self):
        """Native OpenAI-style tool_calls and conversational responses parse accurately."""
        # A) Native OpenAI-style tool call (returned by GenericHTTPModelProvider from MLX)
        openai_payload = {
            "message": {
                "role": "assistant",
                "tool_calls": [
                    {
                        "id": "call-12345",
                        "type": "function",
                        "function": {
                            "name": "calculator",
                            "arguments": '{"expression": "42 * 10"}',
                        },
                    }
                ],
            }
        }
        res_a = RobustToolCallParser.parse(openai_payload)
        self.assertTrue(res_a.is_tool_call)
        self.assertEqual(len(res_a.tool_calls), 1)
        self.assertEqual(res_a.tool_calls[0].tool_name, "calculator")
        self.assertEqual(res_a.tool_calls[0].arguments, {"expression": "42 * 10"})
        self.assertEqual(res_a.tool_calls[0].call_id, "call-12345")

        # B) End-to-end execution loop with mock provider
        mock_provider = MockEchoProvider([
            # Turn 1: Model emits tool call
            openai_payload,
            # Turn 2: Model receives observation and emits final response
            {"message": {"role": "assistant", "content": "The result is 420."}},
        ])
        spec = CustomerAgentSpecification(
            project_name="Mock Tool Agent",
            agent_purpose="Test mock tool calling roundtrip.",
            system_instructions="You are an assistant.",
            allowed_tools=["calculator"],
            execution_limits=ExecutionLimits(max_iterations=5),
        )
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=mock_provider)
        run_res = runtime.run("What is 42 * 10?")

        self.assertEqual(run_res.status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(run_res.tool_calls_executed, 1)
        self.assertEqual(run_res.tool_traces[0]["tool"], "calculator")
        self.assertEqual(run_res.tool_traces[0]["result"]["result"], 420)
        self.assertEqual(run_res.final_response, "The result is 420.")

    # ── 7. Tests do not require a live Ollama server ───────────────────────────
    def test_07_no_live_ollama_required(self):
        """Validates that all default agent initialization and execution does not contact Ollama."""
        spec = CustomerAgentSpecification(
            project_name="Ollama Independence Test",
            agent_purpose="Verify zero Ollama calls in default lifecycle.",
            system_instructions="You are an assistant.",
        )
        mock = MockEchoProvider([
            {"message": {"role": "assistant", "content": "I operate without Ollama."}}
        ])
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=mock)
        with patch("requests.post") as mock_http:
            res = runtime.run("Verify")
            self.assertEqual(res.status, AgentExecutionState.COMPLETED.value)
            # Ensure no HTTP calls were made to 11434
            for call in mock_http.call_args_list:
                url = call[0][0] if call[0] else ""
                self.assertNotIn("11434", url)

    # ── 8. Live MLX Smoke Test (conditionally executed against local endpoint) ─
    def test_08_live_mlx_smoke_test(self):
        """Live smoke test against local MLX authority server on port 19801 (if active)."""
        try:
            r = requests.get(f"{AUTHORIZED_MLX_BASE_URL}/models", timeout=1.5)
            if r.status_code != 200:
                self.skipTest(f"Authorized MLX endpoint {AUTHORIZED_MLX_BASE_URL} returned status {r.status_code}")
        except Exception as e:
            self.skipTest(f"Authorized MLX endpoint {AUTHORIZED_MLX_BASE_URL} unreachable: {e}")

        spec = CustomerAgentSpecification(
            project_name="Live MLX Smoke Test Agent",
            agent_purpose="Execute single turn against authorized MLX authority.",
            system_instructions=(
                "You are a helpful assistant. When asked to evaluate math, "
                "you MUST call the 'calculator' tool."
            ),
            allowed_tools=["calculator"],
            model_config_spec=AgentModelConfig(
                temperature=0.0,
            ),
            execution_limits=ExecutionLimits(max_iterations=3, total_timeout_seconds=30),
        )
        runtime = StandaloneAgentRuntime(spec=spec)
        res = runtime.run("Calculate 99 * 101 using the calculator.")

        self.assertEqual(res.status, AgentExecutionState.COMPLETED.value)
        self.assertGreaterEqual(res.tool_calls_executed, 1)
        self.assertTrue(
            "9999" in res.final_response.replace(",", "").replace(" ", ""),
            f"Expected 9999 in answer, got: {res.final_response}"
        )


if __name__ == "__main__":
    unittest.main()
