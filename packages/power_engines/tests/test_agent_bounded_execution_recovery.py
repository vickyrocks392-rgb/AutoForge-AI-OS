"""Phase 20-C Gate 3 — Bounded Execution and Recovery Test Suite.

Deterministic validation of all 24 required adversarial, timeout, cancellation,
state integrity, and recovery scenarios for the Custom AI Agent Commercial Power Engine.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import tempfile
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import unittest

from autoforge_power_engines.agent.spec import (
    CustomerAgentSpecification,
    ExecutionLimits,
    RetryPolicy,
    VerificationPolicy,
    ToolRiskLevel,
    AgentToolConfig,
)
from autoforge_power_engines.agent.tools import ToolRegistry
from autoforge_power_engines.agent.memory import AgentMemoryStore, ConversationMessage
from autoforge_power_engines.agent.state_machine import AgentStateMachine, AgentExecutionState
from autoforge_power_engines.agent.runtime import (
    StandaloneAgentRuntime,
    ModelProvider,
    CancellationToken,
)
from autoforge_power_engines.base import PowerEngineResult
from autoforge_composition.capability_router import RoutedExecution
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus


class MockScriptedModelProvider(ModelProvider):
    """Deterministic scriptable model provider for testing bounded execution."""

    def __init__(self, turns: List[Dict[str, Any]]):
        self.turns = list(turns)
        self.call_count = 0
        self.received_messages: List[List[Dict[str, Any]]] = []
        self.on_generate: Optional[Any] = None

    def generate_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
        timeout: Optional[float] = None,
    ) -> Dict[str, Any]:
        self.call_count += 1
        self.received_messages.append(messages)
        if self.on_generate:
            self.on_generate(self.call_count)
        if self.turns:
            return self.turns.pop(0)
        return {"message": {"role": "assistant", "content": "Default empty completion."}}


class TestBoundedExecutionAndRecovery(unittest.TestCase):
    """24 Required Adversarial and Recovery Tests for Phase 20-C Gate 3."""

    def setUp(self):
        self.test_dir = Path(tempfile.mkdtemp(prefix="gate3_test_"))
        self.db_path = self.test_dir / "agent_state.db"
        self.workspace_dir = self.test_dir / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_spec(self, **kwargs) -> CustomerAgentSpecification:
        base_limits = kwargs.pop("execution_limits", ExecutionLimits(max_iterations=5, max_tool_calls_per_turn=5, total_timeout_seconds=30.0))
        base_retry = kwargs.pop("retry_policy", RetryPolicy(max_retries=2, backoff_seconds=0.01))
        allowed = kwargs.pop("allowed_tools", ["calculator", "file_read", "document_lookup"])
        tool_defs = list(kwargs.pop("tool_definitions", []))
        builtins = {"calculator", "current_time", "document_lookup", "file_read", "structured_http"}
        for t in allowed:
            if t not in builtins and not any(td.name == t for td in tool_defs):
                tool_defs.append(AgentToolConfig(name=t, description=f"Custom tool {t}"))
        return CustomerAgentSpecification(
            project_name="Gate3 Test Agent",
            agent_purpose="Certify bounded execution and recovery.",
            system_instructions="You are a bounded commercial operations agent.",
            allowed_tools=allowed,
            tool_definitions=tool_defs,
            execution_limits=base_limits,
            retry_policy=base_retry,
            output_root=str(self.test_dir),
            **kwargs,
        )

    # ── Test 1: Normal completion within configured bounds ────────────────────
    def test_01_normal_completion_within_configured_bounds(self):
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": '{"expression": "25 * 4"}'}
                    }]
                }
            },
            {
                "message": {
                    "role": "assistant",
                    "content": "The calculated total is 100."
                }
            }
        ])
        spec = self._create_spec()
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("What is 25 * 4?")
        self.assertEqual(result.status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(result.iterations, 2)
        self.assertEqual(result.tool_calls_executed, 1)
        self.assertIn("100", result.final_response)

    # ── Test 2: Iteration limit reached exactly at the boundary ───────────────
    def test_02_iteration_limit_reached_at_boundary(self):
        infinite_tool_response = {
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "call_inf",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "1 + 1"}'}
                }]
            }
        }
        provider = MockScriptedModelProvider([infinite_tool_response] * 10)
        spec = self._create_spec(execution_limits=ExecutionLimits(max_iterations=3, max_tool_calls_per_turn=10, total_timeout_seconds=30.0))
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("Run indefinitely.")
        self.assertEqual(result.status, AgentExecutionState.FAILED.value)
        self.assertEqual(result.iterations, 3)
        self.assertIn("maximum iteration limit (3) exhausted", result.final_response.lower())

    # ── Test 3: Repeated model responses that make no progress ────────────────
    def test_03_repeated_model_responses_no_progress(self):
        # Model repeatedly returns identical malformed JSON tool requests making no progress
        bad_syntax_turn = {
            "message": {
                "role": "assistant",
                "content": '```json\n{"name": "calculator", "arguments": "malformed_not_dict"}\n```',
            }
        }
        provider = MockScriptedModelProvider([bad_syntax_turn] * 5)
        spec = self._create_spec(
            execution_limits=ExecutionLimits(max_iterations=10, total_timeout_seconds=30.0),
            retry_policy=RetryPolicy(max_retries=1, repair_malformed_args=True)
        )
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("Execute query.")
        self.assertEqual(result.status, AgentExecutionState.FAILED.value)
        self.assertTrue(result.telemetry.retry_count >= 1 or len(result.telemetry.errors) >= 1)

    # ── Test 4: Repeated tool-call cycles ─────────────────────────────────────
    def test_04_repeated_tool_call_cycles(self):
        cycle_turn = {
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "c_cycle",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "42"}'}
                }]
            }
        }
        provider = MockScriptedModelProvider([cycle_turn] * 8)
        spec = self._create_spec(execution_limits=ExecutionLimits(max_iterations=10, max_tool_calls_per_turn=10, total_timeout_seconds=30.0))
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("Trigger tool cycle.")
        self.assertEqual(result.status, AgentExecutionState.FAILED.value)
        self.assertIn("tool-call cycle detected", result.final_response.lower())

    # ── Test 5: Model timeout ─────────────────────────────────────────────────
    def test_05_model_timeout(self):
        class TimingOutModelProvider(ModelProvider):
            def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
                raise TimeoutError("Inference gateway timed out after 5.00s")

        spec = self._create_spec()
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=TimingOutModelProvider())
        result = runtime.run("Query slow model.")
        self.assertEqual(result.status, AgentExecutionState.TIMEOUT.value)
        self.assertIn("timed out", result.final_response.lower())

    # ── Test 6: Tool timeout ──────────────────────────────────────────────────
    def test_06_tool_timeout(self):
        def hanging_tool(**kwargs):
            time.sleep(2.0)
            return {"result": "done"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(
            AgentToolConfig(name="slow_tool", description="Slow tool", timeout_seconds=0.1),
            hanging_tool,
        )
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_slow",
                        "type": "function",
                        "function": {"name": "slow_tool", "arguments": "{}"}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Tool failed with timeout, proceeding to answer."}
            }
        ])
        spec = self._create_spec(allowed_tools=["slow_tool"])
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("Run slow tool.")
        self.assertTrue(len(result.tool_traces) > 0)
        self.assertEqual(result.tool_traces[0]["result"]["status"], "timeout")
        self.assertTrue(result.tool_traces[0]["result"]["timed_out"])

    # ── Test 7: Tool exception ────────────────────────────────────────────────
    def test_07_tool_exception(self):
        def failing_tool(**kwargs):
            raise RuntimeError("Database connection reset by peer")

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(
            AgentToolConfig(name="crash_tool", description="Crashing tool"),
            failing_tool,
        )
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_crash",
                        "type": "function",
                        "function": {"name": "crash_tool", "arguments": "{}"}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Observed crash, concluded gracefully."}
            }
        ])
        spec = self._create_spec(allowed_tools=["crash_tool"])
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("Run crash tool.")
        self.assertEqual(result.status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(result.tool_traces[0]["result"]["status"], "error")
        self.assertEqual(result.tool_traces[0]["result"]["exception"], "RuntimeError")

    # ── Test 8: Malformed tool result ─────────────────────────────────────────
    def test_08_malformed_tool_result(self):
        def bad_output_tool(**kwargs):
            return {"status": "error", "error": "corrupted payload schema"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(
            AgentToolConfig(name="bad_tool", description="Bad output tool"),
            bad_output_tool,
        )
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_bad",
                        "type": "function",
                        "function": {"name": "bad_tool", "arguments": "{}"}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Observed failure."}
            }
        ])
        spec = self._create_spec(allowed_tools=["bad_tool"])
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)

        result = runtime.run("Run bad tool.")
        self.assertGreaterEqual(result.telemetry.failure_count, 1)

    # ── Test 9: Deadline expiration immediately before a tool call ────────────
    def test_09_deadline_expiration_immediately_before_tool_call(self):
        called = {"tool_executed": False}
        def dummy_tool(**kwargs):
            called["tool_executed"] = True
            return {"result": "ok"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="dummy_tool", description="Dummy"), dummy_tool)

        class DelayModelProvider(ModelProvider):
            def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
                time.sleep(0.3)
                return {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [{
                            "id": "c1",
                            "type": "function",
                            "function": {"name": "dummy_tool", "arguments": "{}"}
                        }]
                    }
                }

        spec = self._create_spec(
            allowed_tools=["dummy_tool"],
            execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=0.25)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=DelayModelProvider())
        result = runtime.run("Execute with tight deadline.")

        self.assertEqual(result.status, AgentExecutionState.TIMEOUT.value)
        self.assertFalse(called["tool_executed"])

    # ── Test 10: Deadline expiration during an operation ──────────────────────
    def test_10_deadline_expiration_during_operation(self):
        def slow_step(**kwargs):
            time.sleep(0.4)
            return {"result": "done"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="slow_step", description="Slow", timeout_seconds=1.0), slow_step)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_slow",
                        "type": "function",
                        "function": {"name": "slow_step", "arguments": "{}"}
                    }]
                }
            }
        ])
        spec = self._create_spec(
            allowed_tools=["slow_step"],
            execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=0.2)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Expire during op.")

        self.assertEqual(result.status, AgentExecutionState.TIMEOUT.value)

    # ── Test 11: Retry exhaustion ─────────────────────────────────────────────
    def test_11_retry_exhaustion(self):
        attempts = {"count": 0}
        def flaky_tool(**kwargs):
            attempts["count"] += 1
            return {"status": "error", "error": "Transient upstream 503"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="flaky_tool", description="Flaky"), flaky_tool)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_flaky",
                        "type": "function",
                        "function": {"name": "flaky_tool", "arguments": "{}"}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Handled retry exhaustion."}
            }
        ])
        spec = self._create_spec(
            allowed_tools=["flaky_tool"],
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.001)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Trigger retry exhaustion.")

        # Initial attempt + 2 retries = 3 attempts total
        self.assertEqual(attempts["count"], 3)
        self.assertEqual(result.telemetry.retry_count, 2)

    # ── Test 12: Non-retryable failure ────────────────────────────────────────
    def test_12_non_retryable_failure(self):
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_unauth",
                        "type": "function",
                        "function": {"name": "file_read", "arguments": '{"file_path": "test.txt"}'}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Acknowledged permission denial."}
            }
        ])
        # Allowed tools only has calculator; file_read is unauthorized
        spec = self._create_spec(
            allowed_tools=["calculator"],
            retry_policy=RetryPolicy(max_retries=3, backoff_seconds=0.01)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Attempt unauthorized tool.")

        # Must not retry authorization denials
        self.assertEqual(result.telemetry.retry_count, 0)
        self.assertEqual(result.status, AgentExecutionState.COMPLETED.value)

    # ── Test 13: Uncertain side-effect status after timeout ────────────────────
    def test_13_uncertain_side_effect_status_after_timeout(self):
        def slow_writer(**kwargs):
            time.sleep(1.0)
            return {"status": "success", "written": True}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(
            AgentToolConfig(
                name="workspace_writer",
                description="Mutating writer tool",
                risk_level=ToolRiskLevel.WORKSPACE_WRITE,
                timeout_seconds=0.05
            ),
            slow_writer,
        )
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c_write",
                        "type": "function",
                        "function": {"name": "workspace_writer", "arguments": "{}"}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Handled uncertain write failure."}
            }
        ])
        spec = self._create_spec(
            allowed_tools=["workspace_writer"],
            retry_policy=RetryPolicy(max_retries=3, backoff_seconds=0.01)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Perform mutating write.")

        trace = result.tool_traces[0]["result"]
        self.assertEqual(trace["status"], "timeout")
        self.assertTrue(trace["side_effect_uncertain"])
        # Non-idempotent uncertain tool MUST NOT be automatically retried
        self.assertEqual(result.telemetry.retry_count, 0)

    # ── Test 14: Cancellation before execution begins ─────────────────────────
    def test_14_cancellation_before_execution_begins(self):
        provider = MockScriptedModelProvider([])
        token = CancellationToken()
        token.cancel("Cancelled before launch by caller.")

        spec = self._create_spec()
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=provider)
        result = runtime.run("Start task.", cancellation_token=token)

        self.assertEqual(result.status, AgentExecutionState.CANCELLED.value)
        self.assertEqual(result.iterations, 0)
        self.assertEqual(result.tool_calls_executed, 0)
        self.assertEqual(provider.call_count, 0)

    # ── Test 15: Cancellation during model generation ─────────────────────────
    def test_15_cancellation_during_model_generation(self):
        token = CancellationToken()
        called_tools = []

        def dummy_calc(**kwargs):
            called_tools.append(kwargs)
            return {"result": 42}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="calculator", description="Calc"), dummy_calc)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": '{"expression": "42"}'}
                    }]
                }
            }
        ])

        def on_gen(count):
            token.cancel("Interrupted while model generating.")

        provider.on_generate = on_gen

        spec = self._create_spec(allowed_tools=["calculator"])
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Run calc.", cancellation_token=token)

        self.assertEqual(result.status, AgentExecutionState.CANCELLED.value)
        self.assertEqual(len(called_tools), 0)

    # ── Test 16: Cancellation during tool execution ───────────────────────────
    def test_16_cancellation_during_tool_execution(self):
        token = CancellationToken()
        executed_second = {"called": False}

        def tool_one(**kwargs):
            token.cancel("Cancelled during tool_one execution")
            return {"result": "step1"}

        def tool_two(**kwargs):
            executed_second["called"] = True
            return {"result": "step2"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="tool_one", description="Tool 1"), tool_one)
        registry.register_tool(AgentToolConfig(name="tool_two", description="Tool 2"), tool_two)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [
                        {"id": "c1", "type": "function", "function": {"name": "tool_one", "arguments": "{}"}},
                        {"id": "c2", "type": "function", "function": {"name": "tool_two", "arguments": "{}"}},
                    ]
                }
            }
        ])

        spec = self._create_spec(allowed_tools=["tool_one", "tool_two"])
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Run both tools.", cancellation_token=token)

        self.assertEqual(result.status, AgentExecutionState.CANCELLED.value)
        self.assertFalse(executed_second["called"])

    # ── Test 17: Cancellation during recovery or cleanup ──────────────────────
    def test_17_cancellation_during_recovery(self):
        token = CancellationToken()
        attempt = {"count": 0}

        def flaky_with_cancel(**kwargs):
            attempt["count"] += 1
            token.cancel("Cancelled during retry backoff")
            return {"status": "error", "error": "Transient fault"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="flaky_cancel", description="Flaky"), flaky_with_cancel)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "flaky_cancel", "arguments": "{}"}
                    }]
                }
            }
        ])

        spec = self._create_spec(
            allowed_tools=["flaky_cancel"],
            retry_policy=RetryPolicy(max_retries=5, backoff_seconds=0.01)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Run flaky.", cancellation_token=token)

        self.assertEqual(result.status, AgentExecutionState.CANCELLED.value)
        self.assertEqual(attempt["count"], 1)

    # ── Test 18: Shutdown during active execution ─────────────────────────────
    def test_18_shutdown_during_active_execution(self):
        token = CancellationToken()
        spec = self._create_spec(
            allowed_tools=["slow_step"],
            memory_policy={"enabled": True, "database_path": str(self.db_path)}
        )
        mem = AgentMemoryStore(self.db_path)

        def slow_step(**kwargs):
            # Simulate external SIGTERM arriving
            token.cancel("SIGTERM received: initiating graceful shutdown")
            return {"result": "partial"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="slow_step", description="Slow"), slow_step)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "slow_step", "arguments": "{}"}
                    }]
                }
            }
        ])

        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, memory_store=mem, model_provider=provider)
        result = runtime.run("Run and shutdown.", cancellation_token=token)

        self.assertEqual(result.status, AgentExecutionState.CANCELLED.value)
        # Check SQLite persistence recorded CANCELLED status truthfully
        with sqlite3.connect(str(self.db_path)) as conn:
            row = conn.execute("SELECT status FROM execution_runs WHERE execution_id = ?", (result.execution_id,)).fetchone()
            self.assertIsNotNone(row)
            self.assertEqual(row[0], "CANCELLED")

    # ── Test 19: Recovery from a recoverable failure ──────────────────────────
    def test_19_recovery_from_recoverable_failure(self):
        attempts = {"count": 0}

        def recoverable_tool(**kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return {"status": "error", "error": "Temporary network timeout"}
            return {"status": "success", "data": "ledger_recovered"}

        registry = ToolRegistry(workspace_root=self.workspace_dir)
        registry.register_tool(AgentToolConfig(name="recoverable_tool", description="Recoverable"), recoverable_tool)

        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "tool_calls": [{
                        "id": "c1",
                        "type": "function",
                        "function": {"name": "recoverable_tool", "arguments": "{}"}
                    }]
                }
            },
            {
                "message": {"role": "assistant", "content": "Recovered successfully: ledger_recovered."}
            }
        ])

        spec = self._create_spec(
            allowed_tools=["recoverable_tool"],
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.001)
        )
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry, model_provider=provider)
        result = runtime.run("Recover tool.")

        self.assertEqual(result.status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(attempts["count"], 2)
        self.assertEqual(result.telemetry.retry_count, 1)

    # ── Test 20: Refusal to resume when recorded state is invalid or incomplete
    def test_20_refusal_to_resume_when_recorded_state_invalid(self):
        mem = AgentMemoryStore(self.db_path)
        mem.set_memory("user_pref", {"theme": "dark"})

        # Intentionally corrupt SQLite database entry with malformed JSON
        with sqlite3.connect(str(self.db_path)) as conn:
            conn.execute("UPDATE persistent_memory SET value_json = 'CORRUPT_NOT_JSON{' WHERE key = 'user_pref'")
            conn.commit()

        spec = self._create_spec(memory_policy={"enabled": True, "database_path": str(self.db_path)})
        runtime = StandaloneAgentRuntime(spec=spec, memory_store=mem)

        with self.assertRaises(ValueError) as ctx:
            runtime.assemble_context("sess-1", "Hello")
        self.assertIn("Corrupted memory entry", str(ctx.exception))

    # ── Test 21: Failure during final validation or delivery ──────────────────
    def test_21_failure_during_final_validation(self):
        provider = MockScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "content": "   "  # Empty whitespace response
                }
            }
        ])
        spec = self._create_spec(verification_policy=VerificationPolicy(verify_final_state=True))
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=provider)
        result = runtime.run("Produce blank.")

        self.assertEqual(result.status, AgentExecutionState.FAILED.value)
        self.assertTrue(any("EMPTY_FINAL_RESPONSE" in e for e in result.telemetry.errors))

    # ── Test 22: Concurrent executions with independent budgets and terminal states
    def test_22_concurrent_executions_independent_budgets(self):
        spec1 = self._create_spec(execution_limits=ExecutionLimits(max_iterations=3, total_timeout_seconds=30.0))
        spec2 = self._create_spec(execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=30.0))

        provider1 = MockScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Done turn 1"}}
        ])
        provider2 = MockScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Done turn 2"}}
        ])

        runtime1 = StandaloneAgentRuntime(spec=spec1, model_provider=provider1)
        runtime2 = StandaloneAgentRuntime(spec=spec2, model_provider=provider2)

        results = {}

        def thread_task(idx, rt, prompt):
            results[idx] = rt.run(prompt, session_id=f"sess-{idx}")

        t1 = threading.Thread(target=thread_task, args=(1, runtime1, "Task 1"))
        t2 = threading.Thread(target=thread_task, args=(2, runtime2, "Task 2"))

        t1.start()
        t2.start()
        t1.join()
        t2.join()

        self.assertEqual(results[1].status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(results[2].status, AgentExecutionState.COMPLETED.value)
        self.assertNotEqual(results[1].execution_id, results[2].execution_id)
        self.assertNotEqual(results[1].session_id, results[2].session_id)
        self.assertEqual(results[1].iterations, 1)
        self.assertEqual(results[2].iterations, 1)

    # ── Test 23: Verification that no additional calls occur after terminal failure
    def test_23_verification_no_additional_calls_after_terminal_failure(self):
        sm = AgentStateMachine("exec-term", "sess-term")
        sm.transition_to(AgentExecutionState.RECEIVING_INPUT)
        sm.transition_to(AgentExecutionState.THINKING)
        sm.transition_to(AgentExecutionState.FAILED, reason="Hard failure")
        self.assertTrue(sm.is_terminal())

        # An immutable terminal state strictly rejects transitions out of terminal
        with self.assertRaises(ValueError) as ctx:
            sm.transition_to(AgentExecutionState.THINKING)
        self.assertIn("cannot transition", str(ctx.exception).lower())

        with self.assertRaises(ValueError) as ctx:
            sm.transition_to(AgentExecutionState.COMPLETED)
        self.assertIn("cannot transition", str(ctx.exception).lower())

    # ── Test 24: Failed or unresolved execution cannot produce falsely successful ExecutionOutcome
    def test_24_failed_or_unresolved_execution_cannot_produce_false_success_outcome(self):
        # 1. From PowerEngineResult failed
        pe_fail = PowerEngineResult(
            success=False,
            execution_id="pe-fail-001",
            project_name="Failed Agent Project",
            delivery_dir="/tmp/dummy",
            stages_executed=["INTAKE", "PLAN"],
            error_message="Stage EXECUTE failed: resource exhausted",
        )
        outcome_fail = ExecutionOutcome.from_power_engine_result(
            pe_fail,
            loop_type="coding",
            capability="custom_ai_agent",
            engine_class="CustomAIAgentPowerEngine",
        )
        self.assertFalse(outcome_fail.passed)
        self.assertEqual(outcome_fail.status, OutcomeStatus.REMEDIATE)
        self.assertIn("resource exhausted", outcome_fail.findings[0])

        # 2. From RoutedExecution timed out / failed
        routed_fail = RoutedExecution(
            capability="custom_ai_agent",
            engine_class="CustomAIAgentPowerEngine",
            success=False,
            status="remediate",
            stages_executed=["INTAKE", "PLAN", "EXECUTE"],
            error_message="Execution deadline expired",
        )
        outcome_routed = ExecutionOutcome.from_routed_execution(routed_fail, loop_type="coding")
        self.assertFalse(outcome_routed.passed)
        self.assertEqual(outcome_routed.status, OutcomeStatus.REMEDIATE)
        self.assertIn("Execution deadline expired", outcome_routed.findings[0])

        # 3. From RoutedExecution waiting for approval (unresolved)
        routed_waiting = RoutedExecution(
            capability="custom_ai_agent",
            engine_class="CustomAIAgentPowerEngine",
            success=False,
            status="escalate",
            stages_executed=["INTAKE", "WAITING_FOR_HUMAN_APPROVAL"],
        )
        outcome_waiting = ExecutionOutcome.from_routed_execution(routed_waiting, loop_type="coding")
        self.assertFalse(outcome_waiting.passed)
        self.assertEqual(outcome_waiting.status, OutcomeStatus.ESCALATE)


if __name__ == "__main__":
    unittest.main()
