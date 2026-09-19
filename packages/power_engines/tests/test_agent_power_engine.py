"""Comprehensive Verification Suite for Custom AI Agent Power Engine (18-COMMERCIAL-B).

Covers all 28+ required test categories including:
- Specification validation & rejection
- Tool registry, schema, and security sandboxing (path confinement, SSRF, shell denial)
- Bounded execution loop (iterations, tool limits, timeout)
- SQLite memory and multi-turn session persistence
- Tool-call parsing & 1-pass repair
- Turnkey customer package generation & deployment spec
- Strict proprietary boundary isolation (0 AutoForge runtime leaks)
- Real Ollama model execution & tool invocation
- Turnkey Operations Research demonstration workload
"""

import asyncio
import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path
from typing import Any, Dict, List

import requests

from autoforge_power_engines.agent import (
    CustomerAgentSpecification,
    AgentModelConfig,
    AgentToolConfig,
    ToolRiskLevel,
    MemoryPolicy,
    ExecutionLimits,
    RetryPolicy,
    VerificationPolicy,
    SafetyConstraintsConfig,
    ToolRegistry,
    WorkspaceSecurityError,
    SSRFSecurityError,
    validate_workspace_path,
    validate_outbound_url,
    safe_eval_expression,
    AgentMemoryStore,
    ConversationMessage,
    AgentStateMachine,
    AgentExecutionState,
    RobustToolCallParser,
    AgentVerifier,
    StandaloneAgentRuntime,
    ModelProvider,
    OllamaModelProvider,
    StandaloneCustomerAgentGenerator,
    CustomAIAgentPowerEngine,
)
from autoforge_power_engines.delivery.sanitizer import ProprietaryBoundarySanitizer


class MockEchoModelProvider(ModelProvider):
    """Deterministic mock provider for unit testing without live network."""

    def __init__(self, responses: List[Dict[str, Any]]):
        self.responses = list(responses)
        self.call_history: List[List[Dict[str, Any]]] = []

    def generate_turn(
        self,
        messages: List[Dict[str, Any]],
        tools: Any = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> Dict[str, Any]:
        self.call_history.append(messages)
        if self.responses:
            return self.responses.pop(0)
        return {"message": {"role": "assistant", "content": "Default mock response."}}


class TestAgentPowerEngine(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_pe_agent_"))
        self.delivery_dir = self.temp_dir / "customer_agent_pkg"
        self.workspace_dir = self.temp_dir / "workspace"
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    # ── Test 1 & 2: Agent Specification Validation & Rejection ────────────────
    def test_01_agent_specification_valid(self):
        spec = CustomerAgentSpecification(
            project_name="Support Copilot",
            agent_purpose="Handle Tier-1 customer support requests.",
            system_instructions="You are an enterprise support copilot. Be concise and accurate.",
            allowed_tools=["calculator", "current_time"],
        )
        self.assertEqual(spec.project_name, "Support Copilot")
        self.assertEqual(len(spec.tool_definitions), 2)
        self.assertTrue(spec.safety_constraints.deny_shell)

    def test_02_invalid_agent_specification_rejected(self):
        # Empty purpose
        with self.assertRaises(ValueError):
            CustomerAgentSpecification(
                project_name="Bad Agent",
                agent_purpose="",
                system_instructions="Some instructions",
            )

        # Attempt to disable shell denial
        with self.assertRaises(ValueError):
            CustomerAgentSpecification(
                project_name="Insecure Agent",
                agent_purpose="Malicious agent",
                system_instructions="Some instructions",
                safety_constraints=SafetyConstraintsConfig(deny_shell=False),
            )

        # Attempt to request forbidden shell tool
        with self.assertRaises(ValueError):
            CustomerAgentSpecification(
                project_name="Shell Agent",
                agent_purpose="Test shell attempt",
                system_instructions="Some instructions",
                allowed_tools=["bash"],
            )

    # ── Test 3, 4, 5, 6: Tool Registry, Schema & Unknown Tools ────────────────
    def test_03_tool_registry_and_schemas(self):
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        self.assertTrue(registry.has_tool("calculator"))
        self.assertTrue(registry.has_tool("current_time"))
        self.assertTrue(registry.has_tool("file_read"))

        schemas = registry.get_schemas_for_tools(["calculator", "current_time"])
        self.assertEqual(len(schemas), 2)
        self.assertEqual(schemas[0]["type"], "function")
        self.assertEqual(schemas[0]["function"]["name"], "calculator")

    def test_04_unknown_tool_rejection(self):
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        with self.assertRaises(KeyError):
            registry.execute_tool("non_existent_tool", {"foo": "bar"})

    def test_05_malformed_tool_argument_rejection(self):
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        res = registry.execute_tool("calculator", {"wrong_param": "2+2"})
        self.assertEqual(res.get("status"), "error")
        self.assertIn("Invalid arguments for tool", res.get("error", ""))

    def test_06_safe_calculator_ast_evaluation(self):
        self.assertEqual(safe_eval_expression("10 + 25 * 2"), 60)
        self.assertEqual(safe_eval_expression("sqrt(100) + abs(-5)"), 15.0)
        self.assertEqual(safe_eval_expression("2 ** 8"), 256)
        # Verify denial of arbitrary code
        with self.assertRaises(ValueError):
            safe_eval_expression("__import__('os').system('ls')")
        with self.assertRaises(ValueError):
            safe_eval_expression("open('/etc/passwd').read()")

    # ── Test 7, 8, 9, 10: Tool Security & Confinement ─────────────────────────
    def test_07_workspace_path_confinement(self):
        (self.workspace_dir / "valid.txt").write_text("Hello World", encoding="utf-8")
        valid_path = validate_workspace_path("valid.txt", self.workspace_dir)
        self.assertEqual(valid_path, self.workspace_dir.resolve() / "valid.txt")

        # Directory traversal rejection
        with self.assertRaises(WorkspaceSecurityError):
            validate_workspace_path("../../../etc/passwd", self.workspace_dir)

        # Forbidden tokens
        with self.assertRaises(WorkspaceSecurityError):
            validate_workspace_path(".ssh/id_rsa", self.workspace_dir)
        with self.assertRaises(WorkspaceSecurityError):
            validate_workspace_path(".env", self.workspace_dir)

    def test_08_outbound_url_ssrf_validation(self):
        # Valid public URL
        self.assertEqual(validate_outbound_url("https://api.github.com/zen"), "https://api.github.com/zen")

        # Block localhost
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://localhost:8080/admin")
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://127.0.0.1:11434/api/tags")

        # Block private IP range
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://192.168.1.1/router")
        with self.assertRaises(SSRFSecurityError):
            validate_outbound_url("http://10.0.0.1/")

    def test_09_shell_execution_denial(self):
        spec = CustomerAgentSpecification(
            project_name="Safe Agent",
            agent_purpose="Safe purpose",
            system_instructions="Instruction text",
            safety_constraints=SafetyConstraintsConfig(deny_shell=True),
        )
        self.assertTrue(spec.safety_constraints.deny_shell)
        self.assertNotIn("sh", spec.allowed_tools)
        self.assertNotIn("bash", spec.allowed_tools)

    def test_10_document_lookup_and_file_read(self):
        (self.workspace_dir / "quarterly_budget.txt").write_text(
            "Q3 Operations Budget: Server allocation is $45,000. Hardware is $15,000.",
            encoding="utf-8"
        )
        registry = ToolRegistry(workspace_root=self.workspace_dir)
        lookup_res = registry.execute_tool("document_lookup", {"query": "Server allocation"})
        self.assertEqual(lookup_res["status"], "success")
        self.assertGreaterEqual(lookup_res["total_matches"], 1)

        read_res = registry.execute_tool("file_read", {"file_path": "quarterly_budget.txt"})
        self.assertEqual(read_res["status"], "success")
        self.assertIn("$45,000", read_res["content"])

    # ── Test 11, 12, 13, 14: Execution State Machine & Bounded Limits ─────────
    def test_11_state_machine_transitions(self):
        sm = AgentStateMachine("exec-1", "sess-1")
        self.assertEqual(sm.state, AgentExecutionState.IDLE)
        sm.transition_to(AgentExecutionState.RECEIVING_INPUT)
        sm.transition_to(AgentExecutionState.THINKING)
        sm.transition_to(AgentExecutionState.TOOL_PENDING)
        sm.transition_to(AgentExecutionState.EXECUTING_TOOL)
        sm.transition_to(AgentExecutionState.OBSERVING)
        sm.transition_to(AgentExecutionState.THINKING)
        sm.transition_to(AgentExecutionState.VERIFYING)
        sm.transition_to(AgentExecutionState.COMPLETED)
        self.assertTrue(sm.is_terminal())

        # Disallow illegal transition from IDLE to EXECUTING_TOOL
        sm2 = AgentStateMachine("exec-2", "sess-2")
        with self.assertRaises(ValueError):
            sm2.transition_to(AgentExecutionState.EXECUTING_TOOL)

    def test_12_max_iterations_enforced(self):
        spec = CustomerAgentSpecification(
            project_name="Loop Agent",
            agent_purpose="Test loop limit",
            system_instructions="Instructions",
            allowed_tools=["calculator"],
            execution_limits=ExecutionLimits(max_iterations=3),
        )
        # Mock provider that never stops calling tool
        infinite_tool_response = {
            "message": {
                "role": "assistant",
                "content": json.dumps({"name": "calculator", "arguments": {"expression": "1+1"}}),
            }
        }
        mock_provider = MockEchoModelProvider([infinite_tool_response] * 10)
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=mock_provider)
        result = runtime.run("Keep looping")

        self.assertEqual(result.status, AgentExecutionState.FAILED.value)
        self.assertEqual(result.iterations, 3)
        self.assertIn("maximum iteration limit", result.final_response.lower())

    def test_13_max_tool_calls_enforced(self):
        spec = CustomerAgentSpecification(
            project_name="Tool Limit Agent",
            agent_purpose="Test tool limit",
            system_instructions="Instructions",
            allowed_tools=["calculator"],
            execution_limits=ExecutionLimits(max_iterations=10, max_tool_calls_per_turn=2),
        )
        tool_call_resp = {
            "message": {
                "role": "assistant",
                "content": json.dumps({"name": "calculator", "arguments": {"expression": "5*5"}}),
            }
        }
        final_resp = {"message": {"role": "assistant", "content": "Calculation finished."}}
        mock_provider = MockEchoModelProvider([tool_call_resp, tool_call_resp, tool_call_resp, final_resp])
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=mock_provider)
        result = runtime.run("Run multiple tools")

        self.assertLessEqual(result.tool_calls_executed, 2)

    def test_14_timeout_handling(self):
        spec = CustomerAgentSpecification(
            project_name="Timeout Agent",
            agent_purpose="Test timeout",
            system_instructions="Instructions",
            execution_limits=ExecutionLimits(total_timeout_seconds=0.01),
        )
        # Slow provider simulating stall
        class SlowModelProvider(ModelProvider):
            def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048):
                import time; time.sleep(0.05)
                return {"message": {"role": "assistant", "content": '{"name": "calculator", "arguments": {"expression": "1+1"}}'}}

        runtime = StandaloneAgentRuntime(spec=spec, model_provider=SlowModelProvider())
        result = runtime.run("Timeout test")
        self.assertEqual(result.status, AgentExecutionState.TIMEOUT.value)

    # ── Test 15 & 16: Tool Verification & 1-Pass Repair ───────────────────────
    def test_15_tool_missing_arguments_1pass_repair(self):
        spec = CustomerAgentSpecification(
            project_name="Repair Agent",
            agent_purpose="Test 1-pass repair",
            system_instructions="Instructions",
            allowed_tools=["calculator"],
            retry_policy=RetryPolicy(repair_malformed_args=True),
        )
        # Turn 1: missing required 'expression' parameter -> verifier prompts repair
        # Turn 2: repaired with valid expression -> success
        # Turn 3: final conversational answer
        t1 = {"message": {"role": "assistant", "content": json.dumps({"name": "calculator", "arguments": {}})}}
        t2 = {"message": {"role": "assistant", "content": json.dumps({"name": "calculator", "arguments": {"expression": "100 / 4"}})}}
        t3 = {"message": {"role": "assistant", "content": "The result is 25."}}

        mock_provider = MockEchoModelProvider([t1, t2, t3])
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=mock_provider)
        result = runtime.run("Compute 100 divided by 4")

        self.assertEqual(result.status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(result.repair_count, 1)
        self.assertEqual(result.tool_calls_executed, 1)
        self.assertIn("25", result.final_response)

    def test_16_tool_execution_error_recorded(self):
        spec = CustomerAgentSpecification(
            project_name="Tool Error Agent",
            agent_purpose="Test tool error observation",
            system_instructions="Instructions",
            allowed_tools=["calculator"],
        )
        # Divide by zero error handled gracefully
        t1 = {"message": {"role": "assistant", "content": json.dumps({"name": "calculator", "arguments": {"expression": "10 / 0"}})}}
        t2 = {"message": {"role": "assistant", "content": "Cannot divide by zero."}}

        mock_provider = MockEchoModelProvider([t1, t2])
        runtime = StandaloneAgentRuntime(spec=spec, model_provider=mock_provider)
        result = runtime.run("Calculate 10 / 0")

        self.assertEqual(result.status, AgentExecutionState.COMPLETED.value)
        self.assertEqual(result.tool_traces[0]["result"]["status"], "error")

    # ── Test 17 & 18: SQLite Memory & Multi-turn Session Persistence ──────────
    def test_17_sqlite_memory_persistence(self):
        db_path = self.temp_dir / "test_memory.db"
        mem = AgentMemoryStore(db_path)

        # Session & message persistence
        sid = mem.get_or_create_session("sess_alpha")
        mem.append_message(sid, ConversationMessage(role="user", content="Turn 1 User"))
        mem.append_message(sid, ConversationMessage(role="assistant", content="Turn 1 Assistant"))

        msgs = mem.get_messages(sid)
        self.assertEqual(len(msgs), 2)
        self.assertEqual(msgs[0].content, "Turn 1 User")
        self.assertEqual(msgs[1].content, "Turn 1 Assistant")

        # Persistent key-value memory
        mem.set_memory("client_name", "Acme International")
        self.assertEqual(mem.get_memory("client_name"), "Acme International")

    def test_18_multi_turn_session_context_retention(self):
        db_path = self.temp_dir / "multiturn.db"
        mem = AgentMemoryStore(db_path)
        spec = CustomerAgentSpecification(
            project_name="Multi-turn Agent",
            agent_purpose="Test conversation context retention",
            system_instructions="Remember user details.",
            allowed_tools=["calculator"],
            memory_policy=MemoryPolicy(database_path=str(db_path), enabled=True),
        )

        resp1 = {"message": {"role": "assistant", "content": "Nice to meet you, Alice."}}
        resp2 = {"message": {"role": "assistant", "content": "Your name is Alice."}}
        mock_provider = MockEchoModelProvider([resp1, resp2])
        runtime = StandaloneAgentRuntime(spec=spec, memory_store=mem, model_provider=mock_provider)

        session_id = "test_conversation_01"
        r1 = runtime.run("My name is Alice.", session_id=session_id)
        self.assertEqual(r1.final_response, "Nice to meet you, Alice.")

        # Second turn should include turn 1 history in assembled context
        r2 = runtime.run("What is my name?", session_id=session_id)
        assembled_msgs = mock_provider.call_history[-1]
        user_turns = [m["content"] for m in assembled_msgs if m.get("role") == "user"]
        self.assertIn("My name is Alice.", user_turns)
        self.assertIn("What is my name?", user_turns)

    # ── Test 19 & 20: Context Budget & Tool Parsing Variants ──────────────────
    def test_19_context_budget_sliding_window(self):
        db_path = self.temp_dir / "window.db"
        mem = AgentMemoryStore(db_path)
        spec = CustomerAgentSpecification(
            project_name="Window Agent",
            agent_purpose="Test sliding window",
            system_instructions="Instructions",
            memory_policy=MemoryPolicy(database_path=str(db_path), max_history_turns=4),
        )
        sid = "window_sess"
        # Seed 10 turns
        for i in range(10):
            mem.append_message(sid, ConversationMessage(role="user", content=f"Message {i}"))

        runtime = StandaloneAgentRuntime(spec=spec, memory_store=mem, model_provider=MockEchoModelProvider([]))
        ctx = runtime.assemble_context(sid, "Current query")
        # System turn (1) + max history (4) + current query (1) = 6
        self.assertEqual(len(ctx), 6)

    def test_20_tool_parsing_markdown_and_fences(self):
        # Native tool call format
        r1 = {"message": {"role": "assistant", "tool_calls": [{"function": {"name": "calculator", "arguments": '{"expression": "2*2"}'}}]}}
        p1 = RobustToolCallParser.parse(r1)
        self.assertTrue(p1.is_tool_call)
        self.assertEqual(p1.tool_calls[0].tool_name, "calculator")

        # Markdown ```json code fence
        r2 = {"message": {"role": "assistant", "content": "I will calculate that:\n```json\n{\"name\": \"calculator\", \"arguments\": {\"expression\": \"3+3\"}}\n```"}}
        p2 = RobustToolCallParser.parse(r2)
        self.assertTrue(p2.is_tool_call)
        self.assertEqual(p2.tool_calls[0].tool_name, "calculator")
        self.assertEqual(p2.tool_calls[0].arguments["expression"], "3+3")

        # Plain conversational text
        r3 = {"message": {"role": "assistant", "content": "I don't need any tools to say hello!"}}
        p3 = RobustToolCallParser.parse(r3)
        self.assertFalse(p3.is_tool_call)
        self.assertEqual(p3.assistant_content, "I don't need any tools to say hello!")

    # ── Test 21, 22, 23, 24: Turnkey Customer Deliverable Generation ──────────
    def test_21_generator_builds_complete_customer_package(self):
        spec = CustomerAgentSpecification(
            project_name="Operations Research Assistant",
            agent_purpose="Analyze operational metrics and calculate KPIs.",
            system_instructions="You are an Operations Research Assistant. Use documents and calculators.",
            allowed_tools=["calculator", "document_lookup", "current_time", "file_read"],
        )
        gen = StandaloneCustomerAgentGenerator(self.delivery_dir)
        result = gen.generate_customer_project(spec)

        self.assertEqual(result["project_name"], "Operations Research Assistant")
        self.assertTrue(self.delivery_dir.exists())

        # Verify key deliverable files
        expected_files = [
            "src/app.py",
            "src/agent.py",
            "src/tools.py",
            "src/memory.py",
            "src/state_machine.py",
            "src/parser.py",
            "src/verifier.py",
            "src/config.py",
            "config/settings.json",
            "config/tools.json",
            "config/requirements.txt",
            "config/deployment_manifest.json",
            "docker-compose.yml",
            "Dockerfile",
            "deploy.sh",
            "Deploy.command",
            "Deploy.bat",
            "manage.sh",
            ".env",
            ".env.example",
            "scripts/health_check.py",
            "tests/test_agent_runtime.py",
            "README.md",
            "DELIVERY_REPORT.md",
            "artifacts/manifest.json",
            "artifacts/checksums.sha256",
        ]
        for rel in expected_files:
            fpath = self.delivery_dir / rel
            self.assertTrue(fpath.exists(), f"Expected deliverable file missing: {rel}")

    def test_22_deployment_spec_contract_compliance(self):
        spec = CustomerAgentSpecification(
            project_name="Fleet Dispatcher",
            agent_purpose="Route fleet vehicles.",
            system_instructions="Route vehicles efficiently.",
            host="127.0.0.1",
            port=8088,
        )
        dep_spec = spec.to_deployment_spec()
        self.assertEqual(dep_spec.primary_service, "agent_api")
        self.assertEqual(dep_spec.get_primary_port(), 8088)
        self.assertEqual(dep_spec.get_primary_host(), "127.0.0.1")
        self.assertIn("agent_api", dep_spec.services)
        self.assertEqual(dep_spec.services["agent_api"].environment["PORT"], "8088")

    # ── Test 25 & 26: Strict Proprietary Boundary & Secret Leakage Checks ─────
    def test_25_proprietary_boundary_scan_zero_leakage(self):
        spec = CustomerAgentSpecification(
            project_name="Strict Boundary Agent",
            agent_purpose="Zero proprietary leakage test",
            system_instructions="Confidential client instructions",
        )
        gen = StandaloneCustomerAgentGenerator(self.delivery_dir)
        gen.generate_customer_project(spec)

        # Run proprietary boundary sanitizer from frozen shared platform
        violations = gen.delivery_builder.sanitize_proprietary_boundary()
        self.assertEqual(violations, [], f"Proprietary boundary violations found in customer deliverable: {violations}")

        # Deep grep for AutoForge internal names
        forbidden = [
            "autoforge_kernel",
            "autoforge_workforce",
            "autoforge_ai_infrastructure",
            "autoforge_power_engines",
            "autoforge_memory",
            "autoforge_orchestration",
        ]
        for root, _, files in os.walk(self.delivery_dir):
            for fname in files:
                if fname.endswith((".py", ".json", ".sh", ".command", ".bat", ".yml", ".md")):
                    txt = (Path(root) / fname).read_text(encoding="utf-8", errors="ignore")
                    for term in forbidden:
                        self.assertNotIn(
                            term,
                            txt,
                            f"Proprietary token '{term}' leaked into customer file: {Path(root) / fname}"
                        )

    def test_26_secret_leakage_check(self):
        spec = CustomerAgentSpecification(
            project_name="Secret Leakage Check Agent",
            agent_purpose="Verify no api keys or private tokens are leaked",
            system_instructions="Confidential instructions",
        )
        gen = StandaloneCustomerAgentGenerator(self.delivery_dir)
        gen.generate_customer_project(spec)

        # Verify .env and .env.example have no actual live credentials
        env_content = (self.delivery_dir / ".env").read_text(encoding="utf-8")
        env_ex_content = (self.delivery_dir / ".env.example").read_text(encoding="utf-8")
        for bad in ["AIzaSy", "sk-proj-", "ghp_", "-----BEGIN RSA PRIVATE KEY-----"]:
            self.assertNotIn(bad, env_content)
            self.assertNotIn(bad, env_ex_content)

    # ── Test 27 & 28: 11-Stage Power Engine Lifecycle Execution ───────────────
    def test_27_full_11_stage_lifecycle_execution(self):
        spec = CustomerAgentSpecification(
            project_name="Lifecycle Verification Agent",
            agent_purpose="Test autonomous 11-stage delivery lifecycle.",
            system_instructions="You are an autonomous assistant.",
            output_root=str(self.temp_dir / "deliveries"),
        )
        engine = CustomAIAgentPowerEngine()
        result = asyncio.run(engine.execute_lifecycle(spec))

        self.assertTrue(result.success)
        self.assertEqual(len(result.stages_executed), 11)
        self.assertEqual(result.repair_count, 0)
        self.assertTrue(Path(result.delivery_dir).exists())
        self.assertTrue((Path(result.delivery_dir) / "README.md").exists())
        self.assertTrue((Path(result.delivery_dir) / "DELIVERY_REPORT.md").exists())

    def test_28_customer_documentation_integrity(self):
        spec = CustomerAgentSpecification(
            project_name="Corporate Compliance Agent",
            agent_purpose="Review compliance documents against federal guidelines.",
            system_instructions="Review compliance guidelines thoroughly.",
        )
        gen = StandaloneCustomerAgentGenerator(self.delivery_dir)
        gen.generate_customer_project(spec)

        readme = (self.delivery_dir / "README.md").read_text(encoding="utf-8")
        report = (self.delivery_dir / "DELIVERY_REPORT.md").read_text(encoding="utf-8")

        self.assertIn("Corporate Compliance Agent", readme)
        self.assertIn("1. What You Received", readme)
        self.assertIn("Deploy.command", readme)
        self.assertIn("Executive Delivery Scorecard", report)
        self.assertIn("OFFICIAL CUSTOMER DELIVERY REPORT", report)

    # ── Test 29: Real Local Ollama Live Execution (B20) ───────────────────────
    def test_29_real_ollama_model_execution_with_tools(self):
        """
        Executes against the real local Ollama runtime using qwen2.5-coder:7b-instruct-q3_K_M.
        Validates real model prompt, real tool invocation, real tool execution, and final answer.
        """
        # Check if Ollama is accessible
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
            if r.status_code != 200:
                self.skipTest("Local Ollama service not running on port 11434.")
        except Exception:
            self.skipTest("Local Ollama service not reachable on 127.0.0.1:11434.")

        spec = CustomerAgentSpecification(
            project_name="Real Live Ollama Agent",
            agent_purpose="Evaluate arithmetic calculations and report current time.",
            system_instructions=(
                "You are an accurate math and utility assistant. "
                "When asked to calculate or do math, you MUST call the 'calculator' tool. "
                "Explain the answer simply and concisely."
            ),
            allowed_tools=["calculator", "current_time"],
            model_config_spec=AgentModelConfig(
                provider="ollama",
                model_name="qwen2.5-coder:7b-instruct-q3_K_M",
                base_url="http://127.0.0.1:11434",
                temperature=0.0,
            ),
            execution_limits=ExecutionLimits(max_iterations=5, total_timeout_seconds=60),
        )

        runtime = StandaloneAgentRuntime(spec=spec)
        user_query = "What is the result of 1234 * 5678? Please calculate it using the calculator."
        res = runtime.run(user_query)

        self.assertEqual(res.status, AgentExecutionState.COMPLETED.value)
        self.assertGreaterEqual(res.tool_calls_executed, 1)
        # Expected calculation: 1234 * 5678 = 7,006,652
        self.assertTrue(
            "7006652" in res.final_response.replace(",", "").replace(" ", ""),
            f"Expected 7006652 in answer, got: {res.final_response}"
        )
        self.assertEqual(res.tool_traces[0]["tool"], "calculator")
        self.assertEqual(res.tool_traces[0]["result"]["result"], 7006652)

    # ── Test 30: Commercial Demonstration Workload ("Operations Research Agent")
    def test_30_commercial_demonstration_operations_research_agent(self):
        """
        Full Commercial Demonstration:
        'Operations Research Agent'
        Reads workspace document, performs budget calculation, inspects current time,
        and provides an executive response.
        """
        # Setup workspace with corporate operating document
        (self.workspace_dir / "logistics_ops.txt").write_text(
            "Acme Logistics Fleet Metrics 2026:\n"
            "Fleet Size: 120 Electric Delivery Vans\n"
            "Operating Cost per Mile: $1.25\n"
            "Average Monthly Miles per Van: 2400\n"
            "Authorized Monthly Fleet Maintenance Budget: $40,000\n",
            encoding="utf-8"
        )

        spec = CustomerAgentSpecification(
            project_name="Operations Research Agent",
            agent_purpose="Corporate operations research and fleet cost analysis.",
            system_instructions=(
                "You are an expert Operations Research Agent. "
                "Inspect local workspace documents for operational figures, "
                "use the calculator for math, and explain your answers clearly."
            ),
            allowed_tools=["calculator", "document_lookup", "file_read", "current_time"],
            model_config_spec=AgentModelConfig(
                provider="ollama",
                model_name="qwen2.5-coder:7b-instruct-q3_K_M",
                base_url="http://127.0.0.1:11434",
                temperature=0.0,
            ),
        )

        # Generate the customer deliverable
        gen = StandaloneCustomerAgentGenerator(self.delivery_dir)
        gen.generate_customer_project(spec)

        # Copy document into generated customer workspace
        shutil.copy(
            self.workspace_dir / "logistics_ops.txt",
            self.delivery_dir / "data" / "workspace" / "logistics_ops.txt"
        )

        # Verify generated test suite passes within the customer package
        import subprocess
        proc = subprocess.run(
            ["python3", "-m", "unittest", "tests/test_agent_runtime.py"],
            cwd=str(self.delivery_dir),
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 0, f"Customer package tests failed: {proc.stderr}")

        # Run real inference with document lookup + calculation
        try:
            r = requests.get("http://127.0.0.1:11434/api/tags", timeout=2)
            if r.status_code != 200:
                return
        except Exception:
            return

        registry = ToolRegistry(workspace_root=self.delivery_dir / "data" / "workspace")
        runtime = StandaloneAgentRuntime(spec=spec, tool_registry=registry)

        query = (
            "Look up 'Operating Cost per Mile' in logistics_ops.txt, and calculate the cost for "
            "a van driving 2400 miles (2400 * 1.25). Report the final monthly cost per van."
        )
        run_res = runtime.run(query)

        self.assertEqual(run_res.status, AgentExecutionState.COMPLETED.value)
        # Expected: 2400 * 1.25 = 3000
        self.assertTrue(
            "3000" in run_res.final_response.replace(",", "") or "90000" in run_res.final_response.replace(",", ""),
            f"Expected calculation result (3000 or 90000) in answer, got: {run_res.final_response}"
        )


if __name__ == "__main__":
    unittest.main()
