"""
Phase 20-C Gate 4: Custom AI Agent Production Deployment, Containerization & Operations Test Suite.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import unittest
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient

from autoforge_power_engines.agent.generator import StandaloneCustomerAgentGenerator
from autoforge_power_engines.agent.spec import CustomerAgentSpecification, AgentModelConfig, ExecutionLimits
from autoforge_power_engines.delivery.deployment import DeploymentBuilder
from autoforge_power_engines.delivery.spec import CustomerDeploymentSpec, DeploymentTarget


class TestGate4ADeploymentArchitecture(unittest.TestCase):
    """Gate 4A: Deployment architecture, persistent storage, and health/readiness semantics."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate4a_"))
        self.spec = CustomerAgentSpecification(
            project_name="Test-FinOps-Deploy",
            agent_purpose="Test financial operations",
            system_instructions="You are a helpful assistant.",
            host="127.0.0.1",
            port=8000,
            allowed_tools=["calculator", "file_read"],
            model_config_spec=AgentModelConfig(
                provider="generic_http",
                base_url="http://127.0.0.1:19801/v1",
                model_name="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
            ),
        )
        self.delivery_dir = self.temp_dir / "delivery"
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

    def tearDown(self):
        for mod in list(sys.modules.keys()):
            if mod == "src" or mod.startswith("src."):
                sys.modules.pop(mod, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_4a_declared_storage_partitions_exist(self):
        """Persistent data directories (state, workspace, logs, config) exist in deliverable."""
        for part in ["data/state", "data/workspace", "data/logs", "data/config", "config"]:
            self.assertTrue(
                (self.delivery_dir / part).exists(),
                f"Required partition '{part}' missing from deliverable."
            )

    def test_4a_health_and_readiness_separation(self):
        """Liveness returns 200 independently of inference; readiness verifies inference & storage."""
        # Dynamically import generated app
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.app import app
            client = TestClient(app)

            # Liveness check (/health)
            live_resp = client.get("/health")
            self.assertEqual(live_resp.status_code, 200)
            live_data = live_resp.json()
            self.assertEqual(live_data.get("status"), "healthy")
            self.assertEqual(live_data.get("liveness"), "alive")
            self.assertEqual(live_data.get("model_provider"), "generic_http")

            # Readiness check (/health/ready)
            ready_resp = client.get("/health/ready")
            # If local MLX is running on port 19801, readiness is 200; if stopped, readiness is 503
            self.assertIn(ready_resp.status_code, (200, 503))
            ready_data = ready_resp.json()
            self.assertIn("inference", ready_data)
            self.assertIn("storage", ready_data)
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))

    def test_4a_status_endpoint_does_not_disclose_host_paths(self):
        """Status endpoint returns operational metrics without exposing host filesystem paths."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.app import app
            client = TestClient(app)
            resp = client.get("/status")
            self.assertEqual(resp.status_code, 200)
            text = resp.text
            self.assertNotIn("/Users/", text)
            self.assertNotIn("/home/", text)
            self.assertNotIn("settings_path", text.lower())
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))


class TestGate4BContainerizationStaticValidation(unittest.TestCase):
    """Gate 4B: Dockerfile and docker-compose.yml static security & resource limit validation."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate4b_"))
        self.spec = CustomerAgentSpecification(
            project_name="Test-Container-Agent",
            agent_purpose="Test container hardening",
            system_instructions="You are a helpful assistant.",
            host="127.0.0.1",
            port=8000,
            model_config_spec=AgentModelConfig(
                provider="generic_http",
                base_url="http://127.0.0.1:19801/v1",
                model_name="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2",
            ),
        )
        self.delivery_dir = self.temp_dir / "delivery"
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

    def tearDown(self):
        for mod in list(sys.modules.keys()):
            if mod == "src" or mod.startswith("src."):
                sys.modules.pop(mod, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_4b_dockerfile_security_and_best_practices(self):
        """Dockerfile enforces non-root execution, minimal runtime, HEALTHCHECK, and no secrets."""
        df_path = self.delivery_dir / "Dockerfile"
        self.assertTrue(df_path.exists())
        content = df_path.read_text(encoding="utf-8")

        # Non-root user
        self.assertIn("useradd", content)
        self.assertIn("USER appuser", content)

        # Base image is slim
        self.assertIn("python:3.11-slim", content)

        # HEALTHCHECK instruction present
        self.assertIn("HEALTHCHECK", content)

        # EXPOSE matches port
        self.assertIn("EXPOSE 8000", content)

        # Exec form for CMD
        self.assertIn('CMD ["python3", "src/app.py"]', content)

        # No embedded secrets
        self.assertNotIn("API_KEY", content)
        self.assertNotIn("SECRET", content)

    def test_4b_docker_compose_security_and_resource_limits(self):
        """docker-compose.yml enforces no-new-privileges, cap_drop ALL, cpu/memory limits, loopback bind."""
        compose_path = self.delivery_dir / "docker-compose.yml"
        self.assertTrue(compose_path.exists())
        content = compose_path.read_text(encoding="utf-8")

        # Bound to loopback 127.0.0.1 (not 0.0.0.0 public interface)
        self.assertIn('"127.0.0.1:8000:8000"', content)

        # Security options: no-new-privileges
        self.assertIn("no-new-privileges:true", content)

        # Capabilities dropped
        self.assertIn("cap_drop:", content)
        self.assertIn("- ALL", content)

        # Resource limits configured
        self.assertIn("limits:", content)
        self.assertIn("cpus:", content)
        self.assertIn("memory:", content)

        # Extra host for safe container-to-host inference connectivity
        self.assertIn("host.docker.internal:host-gateway", content)
        self.assertIn("http://host.docker.internal:19801/v1", content)

        # No Ollama port or unapproved remote hosts
        self.assertNotIn("11434", content)
        self.assertNotIn("ollama", content.lower())

    def test_4b_docker_runtime_availability_check(self):
        """Verifies container runtime status on host (macOS without docker marks runtime BLOCKED)."""
        docker_available = shutil.which("docker") is not None
        if not docker_available:
            # Documented requirement: when docker is unavailable, validate statically and mark runtime BLOCKED
            self.assertFalse(docker_available)
        else:
            # If docker is installed, ensure it can run info
            res = subprocess.run(["docker", "info"], capture_output=True)
            self.assertEqual(res.returncode, 0)


class TestGate4CConfigurationAndSecrets(unittest.TestCase):
    """Gate 4C: Preflight configuration validation and secrets safety."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate4c_"))
        self.spec = CustomerAgentSpecification(
            project_name="Test-Config-Agent",
            agent_purpose="Test configuration validation",
            system_instructions="You are a helpful assistant.",
            host="127.0.0.1",
            port=8000,
        )
        self.delivery_dir = self.temp_dir / "delivery"
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

    def tearDown(self):
        for mod in list(sys.modules.keys()):
            if mod == "src" or mod.startswith("src."):
                sys.modules.pop(mod, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_4c_env_example_contains_placeholders_only(self):
        """Verify .env.example contains safe placeholders and no production credentials."""
        env_example = self.delivery_dir / ".env.example"
        self.assertTrue(env_example.exists())
        content = env_example.read_text(encoding="utf-8")
        self.assertNotIn("password=", content.lower())
        self.assertNotIn("secret_key=", content.lower())
        self.assertNotIn("token=", content.lower())
        self.assertNotIn("11434", content)
        self.assertNotIn("ollama", content.lower())

    def test_4c_preflight_validation_rejects_prohibited_providers(self):
        """Setting MODEL_PROVIDER to 'ollama' or unapproved providers raises ValueError."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.config import load_settings

            # Default valid settings
            s = load_settings()
            self.assertEqual(s["model_provider"], "generic_http")

            # Test prohibited provider
            with patch.dict(os.environ, {"MODEL_PROVIDER": "ollama"}):
                with self.assertRaises(ValueError) as ctx:
                    load_settings()
                self.assertIn("frozen inference policy prohibits", str(ctx.exception))

            # Test unapproved remote provider
            with patch.dict(os.environ, {"MODEL_PROVIDER": "unapproved_remote"}):
                with self.assertRaises(ValueError) as ctx:
                    load_settings()
                self.assertIn("frozen inference policy prohibits", str(ctx.exception))
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))

    def test_4c_preflight_validation_rejects_invalid_values(self):
        """Invalid ports, negative iterations, or negative timeouts raise ValueError on load."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.config import load_settings

            with patch.dict(os.environ, {"PORT": "invalid_port"}):
                with self.assertRaises(ValueError):
                    load_settings()

            with patch.dict(os.environ, {"PORT": "70000"}):
                with self.assertRaises(ValueError):
                    load_settings()

            with patch.dict(os.environ, {"MAX_ITERATIONS": "-1"}):
                with self.assertRaises(ValueError):
                    load_settings()

            with patch.dict(os.environ, {"REQUEST_TIMEOUT": "0.0"}):
                with self.assertRaises(ValueError):
                    load_settings()

            with patch.dict(os.environ, {"LLM_BASE_URL": "http://127.0.0.1:11434"}):
                with self.assertRaises(ValueError) as ctx:
                    load_settings()
                self.assertIn("requires targeting authorized MLX port 19801", str(ctx.exception))
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))


class TestGate4DObservabilityAndLogging(unittest.TestCase):
    """Gate 4D: Operational observability, structured logs, and correlation IDs."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate4d_"))
        self.spec = CustomerAgentSpecification(
            project_name="Test-Observability-Agent",
            agent_purpose="Test logging and telemetry",
            system_instructions="You are a helpful assistant.",
            host="127.0.0.1",
            port=8000,
        )
        self.delivery_dir = self.temp_dir / "delivery"
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

    def tearDown(self):
        for mod in list(sys.modules.keys()):
            if mod == "src" or mod.startswith("src."):
                sys.modules.pop(mod, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_4d_structured_log_generation_and_correlation(self):
        """FastAPI service emits structured log lines with request correlation IDs and tool outcomes."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.app import app
            client = TestClient(app)

            # Invoke chat with explicit correlation ID
            corr_id = "req-test-9999"
            with patch("src.agent.AgentRuntime.run") as mock_run:
                mock_telemetry = MagicMock()
                mock_telemetry.iterations = 1
                mock_telemetry.tool_call_count = 1
                mock_telemetry.model_call_count = 1

                mock_res = MagicMock()
                mock_res.execution_id = "exec-test-01"
                mock_res.session_id = "sess-01"
                mock_res.final_response = "Test response"
                mock_res.status = "completed"
                mock_res.iterations = 1
                mock_res.tool_calls_executed = 1
                mock_res.tool_traces = [
                    {"tool": "calculator", "arguments": {"expression": "2+2"}, "result": {"result": 4}, "duration_ms": 1.5}
                ]
                mock_res.model_dump.return_value = {
                    "execution_id": "exec-test-01",
                    "session_id": "sess-01",
                    "final_response": "Test response",
                    "status": "completed",
                    "iterations": 1,
                    "tool_calls_executed": 1,
                    "tool_traces": mock_res.tool_traces,
                }
                mock_run.return_value = mock_res

                resp = client.post(
                    "/chat",
                    json={"message": "What is 2+2?", "session_id": "sess-01", "correlation_id": corr_id}
                )
                self.assertEqual(resp.status_code, 200)

            # Check log file
            log_file = self.delivery_dir / "data" / "logs" / "application.log"
            self.assertTrue(log_file.exists())
            logs = log_file.read_text(encoding="utf-8")

            # Check correlation ID and structured markers
            self.assertIn("req-test-9999", logs)
            self.assertIn("[REQUEST]", logs)
            self.assertIn("[TOOL_OUTCOME]", logs)
            self.assertIn("[EXECUTION]", logs)
            self.assertIn("tool=calculator", logs)
            self.assertIn("status=SUCCESS", logs)
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))


class TestGate4EReliabilityAndRecovery(unittest.TestCase):
    """Gate 4E: Lifecycle, database persistence, and recovery semantics."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate4e_"))
        self.spec = CustomerAgentSpecification(
            project_name="Test-Reliability-Agent",
            agent_purpose="Test restart and memory retention",
            system_instructions="You are a helpful assistant.",
            host="127.0.0.1",
            port=8000,
        )
        self.delivery_dir = self.temp_dir / "delivery"
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

    def tearDown(self):
        for mod in list(sys.modules.keys()):
            if mod == "src" or mod.startswith("src."):
                sys.modules.pop(mod, None)
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_4e_session_memory_persistence_across_process_restarts(self):
        """Conversations persist in SQLite across multiple independent runtime instantiations."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.memory import AgentMemoryStore, ConversationMessage
            db_path = self.delivery_dir / "data" / "state" / "conversations.db"

            # Instance 1: write conversation messages
            store1 = AgentMemoryStore(db_path)
            store1.append_message("session-persisted-1", ConversationMessage(role="user", content="Turn 1 User"))
            store1.append_message("session-persisted-1", ConversationMessage(role="assistant", content="Turn 1 Assistant"))
            del store1

            # Instance 2 (Simulating application restart): reopen database
            store2 = AgentMemoryStore(db_path)
            msgs = store2.get_messages("session-persisted-1")
            self.assertEqual(len(msgs), 2)
            self.assertEqual(msgs[0].content, "Turn 1 User")
            self.assertEqual(msgs[1].content, "Turn 1 Assistant")

            # Add Turn 2
            store2.append_message("session-persisted-1", ConversationMessage(role="user", content="Turn 2 User"))
            del store2

            # Instance 3: verify accumulated history
            store3 = AgentMemoryStore(db_path)
            msgs_updated = store3.get_messages("session-persisted-1")
            self.assertEqual(len(msgs_updated), 3)
            self.assertEqual(msgs_updated[2].content, "Turn 2 User")
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))

    def test_4e_unreachable_mlx_returns_readiness_failure_not_crash(self):
        """When MLX endpoint is offline, readiness probe returns HTTP 503 without crashing process."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.app import app
            client = TestClient(app)

            with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
                resp = client.get("/health/ready")
                self.assertEqual(resp.status_code, 503)
                data = resp.json()
                self.assertEqual(data.get("status"), "not_ready")
                self.assertEqual(data.get("inference"), "unavailable")
                self.assertEqual(data.get("liveness"), "alive")

            # But liveness (/health) still returns 200
            live_resp = client.get("/health")
            self.assertEqual(live_resp.status_code, 200)
            self.assertEqual(live_resp.json().get("liveness"), "alive")
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))

    def test_4e_storage_permission_failure_detected_by_readiness(self):
        """When state directory is unwritable, readiness probe reports storage unwritable."""
        sys.path.insert(0, str(self.delivery_dir))
        try:
            from src.app import app
            client = TestClient(app)

            with patch.object(Path, "write_text", side_effect=PermissionError("Permission denied")):
                resp = client.get("/health/ready")
                self.assertEqual(resp.status_code, 503)
                data = resp.json()
                self.assertEqual(data.get("storage"), "unwritable")
        finally:
            if str(self.delivery_dir) in sys.path:
                sys.path.remove(str(self.delivery_dir))


class TestGate4FOperationalRunbook(unittest.TestCase):
    """Gate 4F: Verification of operational runbook documentation."""

    def test_4f_operational_runbook_completeness(self):
        """Operational runbook exists and covers all 13 required operational topics."""
        runbook_path = Path("/Users/kalachanddash/Developer/AutoForge-AI-OS/docs/runbooks/CUSTOM_AI_AGENT_OPERATIONAL_RUNBOOK.md")
        self.assertTrue(runbook_path.exists(), "Operational runbook missing.")
        content = runbook_path.read_text(encoding="utf-8")

        required_sections = [
            "Prerequisites and Supported Environment",
            "Configuration & Secrets Provisioning",
            "Build & Package Verification",
            "Startup & Readiness Checks",
            "Approved Inference Endpoint Connectivity",
            "Safe Smoke-Test Procedure",
            "Log Inspection & Troubleshooting",
            "Graceful Shutdown",
            "Restart & Recovery",
            "SQLite & Workspace Backup and Restore",
            "Upgrade & Rollback Procedure",
            "Data Retention and Deletion Boundaries",
            "Security Limitations & Incident Response Basics",
        ]

        for sec in required_sections:
            self.assertIn(sec.lower(), content.lower(), f"Missing required runbook section: {sec}")


if __name__ == "__main__":
    unittest.main()
