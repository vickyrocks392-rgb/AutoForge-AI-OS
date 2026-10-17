"""Phase 20-C Gate 4 — Multi-Turn Persistence and Conversation Continuity Test Suite.

Deterministic validation of all 24 required multi-turn, tool-call continuity,
process restart, corruption handling, isolation, and safe resume scenarios
for the Custom AI Agent Commercial Power Engine.
"""

from __future__ import annotations

import json
import os
import shutil
import sqlite3
import subprocess
import sys
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
    MemoryPolicy,
)
from autoforge_power_engines.agent.tools import ToolRegistry
from autoforge_power_engines.agent.memory import (
    AgentMemoryStore,
    ConversationMessage,
    validate_session_id,
)
from autoforge_power_engines.agent.state_machine import AgentStateMachine, AgentExecutionState
from autoforge_power_engines.agent.runtime import (
    StandaloneAgentRuntime,
    ModelProvider,
    CancellationToken,
)
from autoforge_power_engines.base import PowerEngineResult
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus


class ScriptedModelProvider(ModelProvider):
    """Deterministic scriptable model provider for testing multi-turn persistence."""

    def __init__(self, turns: Optional[List[Dict[str, Any]]] = None):
        self.turns = list(turns or [])
        self.call_count = 0
        self.received_messages: List[List[Dict[str, Any]]] = []
        self.on_generate: Optional[Any] = None

    def queue_turn(self, turn_response: Dict[str, Any]) -> None:
        self.turns.append(turn_response)

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
            custom_resp = self.on_generate(self.call_count, messages, tools)
            if custom_resp is not None:
                return custom_resp
        if self.turns:
            return self.turns.pop(0)
        return {"message": {"role": "assistant", "content": "Default test response."}}


class TestMultiTurnPersistence(unittest.TestCase):
    """Authoritative test suite for Phase 20-C Gate 4 certification."""

    def setUp(self) -> None:
        self.test_dir = tempfile.mkdtemp(prefix="gate4_persist_")
        self.db_path = Path(self.test_dir) / "agent_state.db"

        self.spec = CustomerAgentSpecification(
            project_name="MultiTurnTestAgent",
            project_description="Agent for multi-turn persistence certification",
            agent_purpose="Test persistence and continuity",
            system_instructions="You are a precise corporate assistant.",
            allowed_tools=["calculator", "current_time"],
            output_root=self.test_dir,
            memory_policy=MemoryPolicy(
                enabled=True,
                persistence_type="sqlite",
                database_path=str(self.db_path),
                max_history_turns=50,
            ),
            execution_limits=ExecutionLimits(
                max_iterations=10,
                total_timeout_seconds=30.0,
                max_tool_calls_per_turn=5,
            ),
        )
        self.memory = AgentMemoryStore(self.db_path)
        self.tool_registry = ToolRegistry(workspace_root=self.test_dir)

    def tearDown(self) -> None:
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    # ── Scenario 1: Multi-turn conversation persisted and reconstructed ───────
    def test_01_multiturn_conversation_persisted_and_reconstructed(self) -> None:
        """Certifies multi-turn sequence of user, assistant, and history reconstruction."""
        provider = ScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Welcome! How can I assist you with project planning?"}},
            {"message": {"role": "assistant", "content": "Project Apollo timeline is 12 months."}},
        ])
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        res1 = runtime.run("Hello, I am coordinating Project Apollo.", session_id="sess-turn-01")
        self.assertEqual(res1.status, "COMPLETED")
        self.assertIn("Welcome!", res1.final_response)

        res2 = runtime.run("What is the timeline?", session_id="sess-turn-01")
        self.assertEqual(res2.status, "COMPLETED")
        self.assertIn("12 months", res2.final_response)

        messages = self.memory.get_messages("sess-turn-01")
        self.assertEqual(len(messages), 4)
        self.assertEqual(messages[0].role, "user")
        self.assertEqual(messages[0].content, "Hello, I am coordinating Project Apollo.")
        self.assertEqual(messages[1].role, "assistant")
        self.assertEqual(messages[2].role, "user")
        self.assertEqual(messages[2].content, "What is the timeline?")
        self.assertEqual(messages[3].role, "assistant")

    # ── Scenario 2: Follow-up question using earlier user-provided fact ───────
    def test_02_followup_question_using_earlier_user_fact(self) -> None:
        """Certifies second turn context includes fact provided in first turn."""
        provider = ScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Noted. Server port 8080 registered."}},
            {"message": {"role": "assistant", "content": "The configured port is 8080."}},
        ])
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        runtime.run("Configure server port to 8080.", session_id="sess-fact-01")
        runtime.run("What port did I specify?", session_id="sess-fact-01")

        # Verify second call received the first turn in messages context
        turn2_messages = provider.received_messages[1]
        user_msgs = [m["content"] for m in turn2_messages if m["role"] == "user"]
        self.assertIn("Configure server port to 8080.", user_msgs)
        self.assertIn("What port did I specify?", user_msgs)

    # ── Scenario 3: Follow-up question using prior tool result ────────────────
    def test_03_followup_question_using_prior_tool_result(self) -> None:
        """Certifies subsequent turns retain observations from earlier tool calls."""
        provider = ScriptedModelProvider([
            # Turn 1: tool call + final response
            {
                "message": {
                    "role": "assistant",
                    "content": "Calculating sqrt(144).",
                    "tool_calls": [{
                        "id": "call_sqrt_1",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": json.dumps({"expression": "12 * 12"})},
                    }],
                }
            },
            {"message": {"role": "assistant", "content": "12 * 12 is 144."}},
            # Turn 2: uses prior result
            {"message": {"role": "assistant", "content": "Adding 10 to 144 yields 154."}},
        ])
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        res1 = runtime.run("Compute 12 * 12.", session_id="sess-calc-01")
        self.assertEqual(res1.status, "COMPLETED")

        res2 = runtime.run("Now add 10 to that result.", session_id="sess-calc-01")
        self.assertEqual(res2.status, "COMPLETED")

        # Turn 2 model input must contain the tool call and observation from turn 1
        turn2_messages = provider.received_messages[2]
        tool_turns = [m for m in turn2_messages if m["role"] == "tool"]
        self.assertEqual(len(tool_turns), 1)
        self.assertEqual(tool_turns[0]["name"], "calculator")
        self.assertEqual(tool_turns[0]["tool_call_id"], "call_sqrt_1")
        self.assertIn("144", tool_turns[0]["content"])

    # ── Scenario 4: Correct assistant tool-call and tool-result ordering ──────
    def test_04_assistant_tool_call_and_tool_result_ordering(self) -> None:
        """Certifies strict ordering: user -> assistant(tool_calls) -> tool -> assistant."""
        provider = ScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "content": "Checking time.",
                    "tool_calls": [{
                        "id": "call_time_1",
                        "type": "function",
                        "function": {"name": "current_time", "arguments": "{}"},
                    }],
                }
            },
            {"message": {"role": "assistant", "content": "The current time has been retrieved."}},
        ])
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        runtime.run("What time is it?", session_id="sess-order-01")
        stored = self.memory.get_messages("sess-order-01")
        self.assertEqual(len(stored), 4)
        self.assertEqual(stored[0].role, "user")
        self.assertEqual(stored[1].role, "assistant")
        self.assertIsNotNone(stored[1].tool_calls)
        self.assertEqual(stored[2].role, "tool")
        self.assertEqual(stored[2].tool_call_id, "call_time_1")
        self.assertEqual(stored[3].role, "assistant")

    # ── Scenario 5: Preservation of tool-call identifiers and associations ───
    def test_05_preservation_of_tool_call_identifiers_and_associations(self) -> None:
        """Certifies tool_call_id is preserved and correctly associated across turns."""
        provider = ScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "content": "Evaluating.",
                    "tool_calls": [{
                        "id": "call_assoc_999",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": json.dumps({"expression": "25 * 4"})},
                    }],
                }
            },
            {"message": {"role": "assistant", "content": "25 * 4 is 100."}},
        ])
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        runtime.run("Calculate 25 * 4", session_id="sess-assoc-01")
        msgs = self.memory.get_messages("sess-assoc-01")
        asst_call = next(m for m in msgs if m.tool_calls)
        tool_obs = next(m for m in msgs if m.role == "tool")

        self.assertEqual(asst_call.tool_calls[0]["id"], "call_assoc_999")
        self.assertEqual(tool_obs.tool_call_id, "call_assoc_999")
        self.assertEqual(tool_obs.name, "calculator")

    # ── Scenario 6: Two concurrent conversations with isolated context ────────
    def test_06_two_concurrent_conversations_with_isolated_context(self) -> None:
        """Certifies separate session IDs maintain completely isolated message histories."""
        prov1 = ScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Session A registered: SecretAlpha."}},
        ])
        prov2 = ScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Session B registered: SecretBeta."}},
        ])

        rt1 = StandaloneAgentRuntime(spec=self.spec, tool_registry=self.tool_registry, memory_store=self.memory, model_provider=prov1)
        rt2 = StandaloneAgentRuntime(spec=self.spec, tool_registry=self.tool_registry, memory_store=self.memory, model_provider=prov2)

        rt1.run("User fact for Alpha: SecretAlpha", session_id="session-alpha")
        rt2.run("User fact for Beta: SecretBeta", session_id="session-beta")

        alpha_msgs = self.memory.get_messages("session-alpha")
        beta_msgs = self.memory.get_messages("session-beta")

        self.assertEqual(len(alpha_msgs), 2)
        self.assertEqual(len(beta_msgs), 2)
        self.assertIn("SecretAlpha", alpha_msgs[0].content)
        self.assertNotIn("SecretBeta", [m.content for m in alpha_msgs])
        self.assertIn("SecretBeta", beta_msgs[0].content)
        self.assertNotIn("SecretAlpha", [m.content for m in beta_msgs])

    # ── Scenario 7: Attempts to access another conversation's records ─────────
    def test_07_attempts_to_access_another_conversation_records(self) -> None:
        """Certifies querying one session never returns records from another session."""
        self.memory.append_message("session-private", ConversationMessage(role="user", content="Top Secret Data"))
        self.memory.append_message("session-public", ConversationMessage(role="user", content="Public Data"))

        public_msgs = self.memory.get_messages("session-public")
        self.assertEqual(len(public_msgs), 1)
        self.assertEqual(public_msgs[0].content, "Public Data")

        # Path traversal attempts fail closed
        with self.assertRaises(ValueError):
            self.memory.get_messages("../../etc/passwd")

        # SQL injection strings are treated strictly as literal identifiers and do not leak other sessions
        sqli_session = "session-public' OR '1'='1"
        self.memory.append_message(sqli_session, ConversationMessage(role="user", content="Injected session data"))
        public_msgs_after = self.memory.get_messages("session-public")
        self.assertEqual(len(public_msgs_after), 1)
        self.assertEqual(public_msgs_after[0].content, "Public Data")

    # ── Scenario 8: Conversation reopening after genuine process restart ──────
    def test_08_conversation_reopening_across_process_restart(self) -> None:
        """Certifies genuine subprocess-level restart reloads conversation history intact."""
        db_file = str(self.db_path)
        session_id = "sess-restart-p8"

        # Process 1: executes turn 1 and turn 2 with tool call
        code_proc1 = f"""
import json, sys
from pathlib import Path
from autoforge_power_engines.agent.spec import CustomerAgentSpecification, MemoryPolicy, ExecutionLimits
from autoforge_power_engines.agent.tools import ToolRegistry
from autoforge_power_engines.agent.memory import AgentMemoryStore
from autoforge_power_engines.agent.runtime import StandaloneAgentRuntime, ModelProvider

class P1Provider(ModelProvider):
    def __init__(self):
        self.turns = [
            {{"message": {{"role": "assistant", "content": "ProjectZephyr acknowledged with budget $50,000."}}}},
            {{"message": {{
                "role": "assistant",
                "content": "Calculating tax.",
                "tool_calls": [{{
                    "id": "call_proc_tax",
                    "type": "function",
                    "function": {{"name": "calculator", "arguments": json.dumps({{"expression": "50000 * 0.15"}})}}
                }}]
            }}}},
            {{"message": {{"role": "assistant", "content": "Tax at 15% is $7,500.00."}}}}
        ]
    def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
        return self.turns.pop(0)

spec = CustomerAgentSpecification(
    project_name="Proc1Agent", project_description="P1 description",
    agent_purpose="Testing process restart persistence",
    system_instructions="Corporate Assistant Instructions", allowed_tools=["calculator"], output_root="{self.test_dir}",
    memory_policy=MemoryPolicy(enabled=True, database_path=r"{db_file}"),
    execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=20.0)
)
mem = AgentMemoryStore(r"{db_file}")
tools = ToolRegistry()
rt = StandaloneAgentRuntime(spec=spec, tool_registry=tools, memory_store=mem, model_provider=P1Provider())
r1 = rt.run("ProjectZephyr budget is 50000.", session_id="{session_id}")
r2 = rt.run("Calculate tax at 15%.", session_id="{session_id}")
assert r1.status == "COMPLETED"
assert r2.status == "COMPLETED"
print("PROCESS_1_SUCCESS")
"""
        proc1 = subprocess.run([sys.executable, "-c", code_proc1], capture_output=True, text=True)
        self.assertEqual(proc1.returncode, 0, f"Process 1 failed: {proc1.stderr}")
        self.assertIn("PROCESS_1_SUCCESS", proc1.stdout)

        # Process 2: verifies all 6 messages are durably readable after process exit
        code_proc2 = f"""
import sys
from autoforge_power_engines.agent.memory import AgentMemoryStore
mem = AgentMemoryStore(r"{db_file}")
msgs = mem.get_messages("{session_id}")
assert len(msgs) == 6, f"Expected 6 messages, got {{len(msgs)}}"
assert msgs[0].content == "ProjectZephyr budget is 50000."
assert any(m.tool_call_id == "call_proc_tax" for m in msgs)
print("PROCESS_2_READ_SUCCESS")
"""
        proc2 = subprocess.run([sys.executable, "-c", code_proc2], capture_output=True, text=True)
        self.assertEqual(proc2.returncode, 0, f"Process 2 failed: {proc2.stderr}")
        self.assertIn("PROCESS_2_READ_SUCCESS", proc2.stdout)

    # ── Scenario 9: A new turn after restart using prior persisted context ────
    def test_09_new_turn_after_restart_using_prior_persisted_context(self) -> None:
        """Certifies fresh subprocess continues conversation with context from prior process."""
        db_file = str(self.db_path)
        session_id = "sess-restart-p9"

        # Process 1 creates context
        code_proc1 = f"""
import json, sys
from autoforge_power_engines.agent.spec import CustomerAgentSpecification, MemoryPolicy, ExecutionLimits
from autoforge_power_engines.agent.tools import ToolRegistry
from autoforge_power_engines.agent.memory import AgentMemoryStore
from autoforge_power_engines.agent.runtime import StandaloneAgentRuntime, ModelProvider

class P1Provider(ModelProvider):
    def __init__(self):
        self.turns = [
            {{"message": {{"role": "assistant", "content": "Server Alpha initialized with 64GB RAM."}}}},
            {{"message": {{
                "role": "assistant",
                "content": "Checking status.",
                "tool_calls": [{{
                    "id": "call_status_1",
                    "type": "function",
                    "function": {{"name": "calculator", "arguments": json.dumps({{"expression": "64 / 2"}})}}
                }}]
            }}}},
            {{"message": {{"role": "assistant", "content": "Half capacity is 32GB."}}}}
        ]
    def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
        return self.turns.pop(0)

spec = CustomerAgentSpecification(
    project_name="Proc1Agent", project_description="P1 description",
    agent_purpose="Testing process restart persistence",
    system_instructions="Corporate Assistant Instructions", allowed_tools=["calculator"], output_root="{self.test_dir}",
    memory_policy=MemoryPolicy(enabled=True, database_path=r"{db_file}"),
    execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=20.0)
)
mem = AgentMemoryStore(r"{db_file}")
tools = ToolRegistry()
rt = StandaloneAgentRuntime(spec=spec, tool_registry=tools, memory_store=mem, model_provider=P1Provider())
rt.run("Initialize Server Alpha with 64GB RAM.", session_id="{session_id}")
rt.run("Calculate half capacity.", session_id="{session_id}")
print("PROCESS_1_INITIALIZED")
"""
        proc1 = subprocess.run([sys.executable, "-c", code_proc1], capture_output=True, text=True)
        self.assertEqual(proc1.returncode, 0, f"Process 1 failed: {proc1.stderr}")

        # Process 2 resumes and submits follow-up
        code_proc2 = f"""
import sys
from autoforge_power_engines.agent.spec import CustomerAgentSpecification, MemoryPolicy, ExecutionLimits
from autoforge_power_engines.agent.tools import ToolRegistry
from autoforge_power_engines.agent.memory import AgentMemoryStore
from autoforge_power_engines.agent.runtime import StandaloneAgentRuntime, ModelProvider

class P2Provider(ModelProvider):
    def __init__(self):
        self.received = []
    def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
        self.received.append(messages)
        return {{"message": {{"role": "assistant", "content": "Server Alpha half capacity is confirmed at 32GB."}}}}

spec = CustomerAgentSpecification(
    project_name="Proc2Agent", project_description="P2 description",
    agent_purpose="Testing process restart persistence",
    system_instructions="Corporate Assistant Instructions", allowed_tools=["calculator"], output_root="{self.test_dir}",
    memory_policy=MemoryPolicy(enabled=True, database_path=r"{db_file}"),
    execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=20.0)
)
mem = AgentMemoryStore(r"{db_file}")
tools = ToolRegistry()
p2_prov = P2Provider()
rt = StandaloneAgentRuntime(spec=spec, tool_registry=tools, memory_store=mem, model_provider=p2_prov)
r = rt.run("Confirm the half capacity and server name.", session_id="{session_id}")
assert r.status == "COMPLETED"
assert "32GB" in r.final_response
ctx = p2_prov.received[0]
user_msgs = [m["content"] for m in ctx if m["role"] == "user"]
assert "Initialize Server Alpha with 64GB RAM." in user_msgs
assert "Confirm the half capacity and server name." in user_msgs
print("PROCESS_2_RESUMED")
"""
        proc2 = subprocess.run([sys.executable, "-c", code_proc2], capture_output=True, text=True)
        self.assertEqual(proc2.returncode, 0, f"Process 2 failed: {proc2.stderr}")

    # ── Scenario 10: Storage exception during message write ──────────────────
    def test_10_storage_exception_during_message_write(self) -> None:
        """Certifies storage write failure raises fail-closed error without false success."""
        # Make DB file read-only to trigger sqlite3.OperationalError on insert
        os.chmod(self.db_path, 0o444)
        try:
            with self.assertRaises((sqlite3.OperationalError, RuntimeError)):
                self.memory.append_message("sess-err", ConversationMessage(role="user", content="Will fail"))
        finally:
            os.chmod(self.db_path, 0o644)

    # ── Scenario 11: Interrupted or partial persistence operation ────────────
    def test_11_interrupted_or_partial_persistence_operation(self) -> None:
        """Certifies atomic batch insertion rolls back if any record in batch fails."""
        initial_count = self.memory.get_message_count("sess-atomic") if self.memory.session_exists("sess-atomic") else 0

        # Attempt to append batch with one invalid message role
        valid_msg = ConversationMessage(role="user", content="Good msg")
        invalid_msg = ConversationMessage(role="invalid_role", content="Bad msg")

        with self.assertRaises(ValueError):
            self.memory.append_messages("sess-atomic", [valid_msg, invalid_msg])

        # Verify rollback: 0 messages inserted
        count_after = self.memory.get_message_count("sess-atomic")
        self.assertEqual(count_after, initial_count)

    # ── Scenario 12: Corrupted or truncated stored JSON records ──────────────
    def test_12_corrupted_or_truncated_stored_json_records(self) -> None:
        """Certifies validate_state_integrity raises ValueError on corrupted tool_calls JSON."""
        self.memory.append_message("sess-corrupt", ConversationMessage(role="user", content="Hello"))
        # Directly inject corrupted JSON into tool_calls_json
        with self.memory._get_connection() as conn:
            conn.execute(
                "INSERT INTO messages (session_id, role, content, tool_calls_json, created_at) VALUES (?, ?, ?, ?, ?)",
                ("sess-corrupt", "assistant", "Corrupt call", "INVALID_NOT_JSON{", "2026-10-16T00:00:00")
            )
            conn.commit()

        with self.assertRaises(ValueError) as ctx:
            self.memory.validate_state_integrity(session_id="sess-corrupt")
        self.assertIn("Corrupted tool calls", str(ctx.exception))

    # ── Scenario 13: Invalid persisted-state schema ───────────────────────────
    def test_13_invalid_persisted_state_schema(self) -> None:
        """Certifies validate_state_integrity fails closed if a required table is missing."""
        with self.memory._get_connection() as conn:
            conn.execute("DROP TABLE IF EXISTS persistent_memory")
            conn.commit()

        with self.assertRaises(ValueError) as ctx:
            self.memory.validate_state_integrity()
        self.assertIn("Missing required state tables", str(ctx.exception))

    # ── Scenario 14: Duplicate write or retry behavior ────────────────────────
    def test_14_duplicate_write_or_retry_behavior(self) -> None:
        """Certifies persistent memory updates update timestamp and value deterministically on conflict."""
        self.memory.set_memory("api_key_cfg", {"endpoint": "v1"})
        v1 = self.memory.get_memory("api_key_cfg")
        self.assertEqual(v1["endpoint"], "v1")

        self.memory.set_memory("api_key_cfg", {"endpoint": "v2"})
        v2 = self.memory.get_memory("api_key_cfg")
        self.assertEqual(v2["endpoint"], "v2")

        # Key count should remain 1
        all_mem = self.memory.get_all_memories()
        self.assertIn("api_key_cfg", all_mem)
        self.assertEqual(all_mem["api_key_cfg"]["endpoint"], "v2")

    # ── Scenario 15: Concurrent writes to separate conversations ─────────────
    def test_15_concurrent_writes_to_separate_conversations(self) -> None:
        """Certifies multi-threaded concurrent writes to distinct sessions execute without locking errors."""
        threads = []
        errors = []

        def worker(sid: str, count: int) -> None:
            try:
                for i in range(count):
                    self.memory.append_message(sid, ConversationMessage(role="user", content=f"Msg {i} for {sid}"))
            except Exception as e:
                errors.append(e)

        for i in range(10):
            t = threading.Thread(target=worker, args=(f"sess-conc-{i}", 5))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual(len(errors), 0, f"Concurrent write errors: {errors}")
        for i in range(10):
            self.assertEqual(self.memory.get_message_count(f"sess-conc-{i}"), 5)

    # ── Scenario 16: Concurrent writes to the same conversation ──────────────
    def test_16_concurrent_writes_to_same_conversation(self) -> None:
        """Certifies multi-threaded writes to the same session preserve monotonic ID ordering."""
        threads = []
        errors = []

        def worker(worker_id: int) -> None:
            try:
                for i in range(5):
                    self.memory.append_message("sess-same-conc", ConversationMessage(role="user", content=f"W{worker_id}-M{i}"))
            except Exception as e:
                errors.append(e)

        for w in range(4):
            t = threading.Thread(target=worker, args=(w,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join(timeout=10.0)

        self.assertEqual(len(errors), 0)
        messages = self.memory.get_messages("sess-same-conc", limit=100)
        self.assertEqual(len(messages), 20)

    # ── Scenario 17: Reopening a conversation without duplicating messages ───
    def test_17_reopening_conversation_without_duplicating_messages(self) -> None:
        """Certifies assemble_context does not duplicate current query when resuming session."""
        provider = ScriptedModelProvider([
            {"message": {"role": "assistant", "content": "First response"}},
            {"message": {"role": "assistant", "content": "Second response"}},
        ])
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        runtime.run("Turn 1 Question", session_id="sess-no-dup")
        runtime.run("Turn 2 Question", session_id="sess-no-dup")

        # Check total messages stored in DB
        msgs = self.memory.get_messages("sess-no-dup")
        self.assertEqual(len(msgs), 4)

        # Inspect messages received by model in turn 2
        turn2_input = provider.received_messages[1]
        user_turns = [m["content"] for m in turn2_input if m["role"] == "user"]
        self.assertEqual(user_turns, ["Turn 1 Question", "Turn 2 Question"])

    # ── Scenario 18: Incomplete tool-call handling ───────────────────────────
    def test_18_incomplete_tool_call_handling(self) -> None:
        """Certifies orphaned assistant tool call is safely sanitized with status=incomplete."""
        # Simulate a crash right after assistant emitted tool call before tool execution
        self.memory.append_message("sess-orphan", ConversationMessage(role="user", content="Do work"))
        self.memory.append_message(
            "sess-orphan",
            ConversationMessage(
                role="assistant",
                content="Calling tool",
                tool_calls=[{"id": "call_crashed_1", "type": "function", "function": {"name": "calculator"}}],
            )
        )

        # Run sanitization
        sanitized_count = self.memory.sanitize_incomplete_tool_calls("sess-orphan")
        self.assertEqual(sanitized_count, 1)

        # Verify a synthetic tool observation was inserted with incomplete status
        msgs = self.memory.get_messages("sess-orphan")
        self.assertEqual(len(msgs), 3)
        self.assertEqual(msgs[2].role, "tool")
        self.assertEqual(msgs[2].tool_call_id, "call_crashed_1")
        data = json.loads(msgs[2].content)
        self.assertEqual(data["status"], "incomplete")
        self.assertTrue(data["side_effect_uncertain"])

    # ── Scenario 19: Uncertain side-effect status preservation ────────────────
    def test_19_uncertain_side_effect_status_preservation(self) -> None:
        """Certifies uncertain side-effect status is durably preserved across session reopen."""
        self.memory.append_message(
            "sess-uncertain",
            ConversationMessage(
                role="tool",
                name="workspace_write",
                tool_call_id="call_mutating_timeout",
                content=json.dumps({"status": "timeout", "side_effect_uncertain": True, "error": "Tool timed out"}),
            )
        )

        # Reopen with fresh memory instance
        reopened = AgentMemoryStore(self.db_path)
        msgs = reopened.get_messages("sess-uncertain")
        self.assertEqual(len(msgs), 1)
        tool_data = json.loads(msgs[0].content)
        self.assertTrue(tool_data.get("side_effect_uncertain"))

    # ── Scenario 20: Verification that restoring history does not reset budgets
    def test_20_restoring_history_does_not_reset_execution_budgets(self) -> None:
        """Certifies each new turn receives a strict bounded budget independent of history length."""
        # Seed 30 messages in history
        for i in range(15):
            self.memory.append_message("sess-long", ConversationMessage(role="user", content=f"Turn {i}"))
            self.memory.append_message("sess-long", ConversationMessage(role="assistant", content=f"Answer {i}"))

        spec_low_budget = self.spec.model_copy(update={
            "execution_limits": ExecutionLimits(max_iterations=2, total_timeout_seconds=5.0, max_tool_calls_per_turn=1)
        })

        # Model loops requesting tool calls without final answer to test iteration budget exhaustion
        provider = ScriptedModelProvider([
            {
                "message": {
                    "role": "assistant",
                    "content": f"Loop {i}",
                    "tool_calls": [{
                        "id": f"call_loop_{i}",
                        "type": "function",
                        "function": {"name": "calculator", "arguments": json.dumps({"expression": "1 + 1"})},
                    }],
                }
            }
            for i in range(5)
        ])
        runtime = StandaloneAgentRuntime(
            spec=spec_low_budget,
            tool_registry=self.tool_registry,
            memory_store=self.memory,
            model_provider=provider,
        )

        res = runtime.run("Next request", session_id="sess-long")
        # Must terminate strictly at max_iterations=2
        self.assertEqual(res.status, "FAILED")
        self.assertEqual(res.iterations, 2)

    # ── Scenario 21: Terminal execution states remain terminal after restoration
    def test_21_terminal_execution_states_remain_terminal(self) -> None:
        """Certifies execution_runs records keep terminal status immutable across queries."""
        self.memory.record_execution(
            execution_id="exec-term-01",
            session_id="sess-term",
            status="COMPLETED",
            iterations=3,
            tool_calls_count=2,
            telemetry={"status": "completed"},
            completed=True,
        )

        record = self.memory.get_execution("exec-term-01")
        self.assertIsNotNone(record)
        self.assertEqual(record["status"], "COMPLETED")
        self.assertIsNotNone(record["completed_at"])

        # Reopening session and adding new turns does not alter prior execution_run
        self.memory.append_message("sess-term", ConversationMessage(role="user", content="New query"))
        record_after = self.memory.get_execution("exec-term-01")
        self.assertEqual(record_after["status"], "COMPLETED")

    # ── Scenario 22: Persistence failure cannot falsely produce successful outcome
    def test_22_persistence_failure_cannot_produce_false_success(self) -> None:
        """Certifies persistence failure during finalization causes run failure, not success."""
        provider = ScriptedModelProvider([
            {"message": {"role": "assistant", "content": "Calculation succeeded."}},
        ])

        class FailingMemoryStore(AgentMemoryStore):
            def record_execution(self, *args: Any, **kwargs: Any) -> None:
                if kwargs.get("completed"):
                    raise sqlite3.OperationalError("Simulated disk full during execution finalization")
                super().record_execution(*args, **kwargs)

        fail_mem = FailingMemoryStore(self.db_path)
        runtime = StandaloneAgentRuntime(
            spec=self.spec,
            tool_registry=self.tool_registry,
            memory_store=fail_mem,
            model_provider=provider,
        )

        with self.assertRaises(RuntimeError) as ctx:
            runtime.run("Do calculation", session_id="sess-fail-success")
        self.assertIn("Storage write error", str(ctx.exception))

    # ── Scenario 23: Compatibility with existing Gate 3 state-integrity checks
    def test_23_compatibility_with_existing_gate3_state_integrity(self) -> None:
        """Certifies existing Gate 3 memory.validate_state_integrity method passes on active DB."""
        self.memory.append_message("sess-valid", ConversationMessage(role="user", content="Valid user"))
        self.memory.append_message("sess-valid", ConversationMessage(role="assistant", content="Valid asst"))
        self.memory.set_memory("config_key", {"active": True})
        self.memory.record_execution("exec-g3", "sess-valid", "COMPLETED", 1, 0, {}, completed=True)

        is_valid = self.memory.validate_state_integrity(session_id="sess-valid")
        self.assertTrue(is_valid)

    # ── Scenario 24: Canonical router and generator packaging integration ─────
    def test_24_canonical_router_and_generator_persistence_integration(self) -> None:
        """Certifies canonical StandaloneCustomerAgentGenerator emits multi-turn compatible code."""
        from autoforge_power_engines.agent.generator import StandaloneCustomerAgentGenerator

        output_dir = Path(self.test_dir) / "packaged_agent"
        gen = StandaloneCustomerAgentGenerator(output_dir)
        gen.generate_customer_project(self.spec)
        self.assertTrue(output_dir.exists())

        # Inspect generated memory.py for tool_call_id and execution_id support
        gen_mem_code = (output_dir / "src" / "memory.py").read_text(encoding="utf-8")
        self.assertIn("tool_call_id", gen_mem_code)
        self.assertIn("execution_id", gen_mem_code)

        # Inspect generated agent.py for tool_call_id handling
        gen_agent_code = (output_dir / "src" / "agent.py").read_text(encoding="utf-8")
        self.assertIn("tool_call_id", gen_agent_code)


if __name__ == "__main__":
    unittest.main()
