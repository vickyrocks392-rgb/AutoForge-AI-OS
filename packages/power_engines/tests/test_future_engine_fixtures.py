"""Architectural Readiness Fixtures for Future Commercial Power Engines (B, C, D).

Proves that the shared Customer Delivery & Deployment Platform can seamlessly represent
and deploy non-RAG workloads without modifications or hidden RAG assumptions.
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path

from autoforge_power_engines.delivery import (
    CustomerDeploymentSpec,
    ServiceDefinition,
    VolumeDefinition,
    PortMapping,
    NetworkDefinition,
    DeploymentTarget,
    RestartPolicy,
    DeploymentBuilder,
    CustomerDeliveryBuilder,
    CustomerDocumentationBuilder,
    HealthCheckSpec,
)


class TestFutureEngineFixtures(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_autoforge_future_pe_"))
        self.project_dir = self.temp_dir / "future_engine_workspace"
        self.delivery_dir = self.project_dir / "delivery_v1"

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_commercial_b_agent_power_engine_fixture(self):
        """
        Phase 18-COMMERCIAL-B Fixture: Custom AI Agent Power Engine.
        Topology:
          - agent_api (FastAPI HTTP interface)
          - tool_runtime (Sandboxed code execution runtime)
          - state_store (Redis / embedded state)
        """
        spec = CustomerDeploymentSpec(
            project_name="Support Copilot Autonomous Agent",
            sanitized_project_id="support_copilot_agent",
            target=DeploymentTarget.DOCKER_HOST,
            primary_service="agent_api",
            services={
                "agent_api": ServiceDefinition(
                    name="agent_api",
                    build_context=".",
                    dockerfile="Dockerfile",
                    container_name="customer_agent_api_support_copilot",
                    ports=[PortMapping(host_ip="127.0.0.1", host_port=8080, container_port=8080)],
                    environment={"PORT": "8080", "TOOL_RUNTIME_URL": "http://tool_runtime:9000"},
                    volumes=[
                        VolumeDefinition(host_path="./data/state", container_path="/app/data/state"),
                        VolumeDefinition(host_path="./config", container_path="/app/config"),
                    ],
                    networks=["agent_network"],
                    depends_on=["tool_runtime"],
                ),
                "tool_runtime": ServiceDefinition(
                    name="tool_runtime",
                    build_context="./tools",
                    container_name="customer_tool_runtime_support_copilot",
                    internal_ports=[9000],
                    environment={"MAX_MEMORY_MB": "1024", "SANDBOX_MODE": "strict"},
                    volumes=[
                        VolumeDefinition(host_path="./data/sandboxes", container_path="/sandboxes")
                    ],
                    networks=["agent_network"],
                ),
            },
            networks={
                "agent_network": NetworkDefinition(name="agent_network", driver="bridge", internal=True)
            },
            data_directories=["data/state", "data/sandboxes", "data/logs", "data/config"],
            health_checks=[
                HealthCheckSpec(name="agent_api", endpoint_or_command="http://127.0.0.1:8080/health"),
                HealthCheckSpec(name="tool_runtime", endpoint_or_command="http://tool_runtime:9000/ping"),
            ],
            metadata={"power_engine": "18-COMMERCIAL-B", "workload": "custom_ai_agent"},
        )

        delivery = CustomerDeliveryBuilder(self.delivery_dir)
        delivery.prepare_directories(spec.data_directories)
        delivery.build_deployment_files(spec)

        # Write clean workload placeholder
        (self.delivery_dir / "src" / "agent.py").write_text("# autonomous agent loop\n", encoding="utf-8")

        # Verify zero proprietary leakage
        violations = delivery.sanitize_proprietary_boundary()
        self.assertEqual(violations, [])

        manifest = delivery.create_manifest()
        self.assertIn("docker-compose.yml", manifest.files_created)
        self.assertIn("deploy.sh", manifest.files_created)
        self.assertIn("Deploy.command", manifest.files_created)
        self.assertIn("manage.sh", manifest.files_created)

        dc_text = (self.delivery_dir / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("agent_api:", dc_text)
        self.assertIn("tool_runtime:", dc_text)
        self.assertIn("agent_network", dc_text)
        self.assertNotIn("qdrant", dc_text)
        self.assertNotIn("retrieval", dc_text)

        # Documentation generation
        docs = CustomerDocumentationBuilder()
        readme = docs.generate_readme(
            spec=spec,
            what_you_received_items=["Autonomous Support Copilot Agent", "Sandboxed Tool Runtime"],
            config_table_rows=[{"variable": "TOOL_RUNTIME_URL", "default": "http://tool_runtime:9000", "description": "Tool execution sandbox"}],
            troubleshooting_items=["Tool timeout: increase MAX_MEMORY_MB in .env"],
            architecture_overview="Multi-container Agent Runtime with isolated tool execution.",
            verification_summary="100% Agent tool invocation tests passing.",
        )
        self.assertIn("## 1. What You Received", readme)
        self.assertIn("## 15. Verification / Evidence", readme)

    def test_commercial_c_automation_power_engine_fixture(self):
        """
        Phase 18-COMMERCIAL-C Fixture: AI Automation Power Engine.
        Topology:
          - automation_api (Dashboard & webhook ingestion)
          - scheduler (Workflow cron / trigger engine)
          - worker (Parallel task execution worker)
          - database (PostgreSQL backend)
        """
        spec = CustomerDeploymentSpec(
            project_name="Procurement Flow Automation",
            sanitized_project_id="procurement_flow_automation",
            target=DeploymentTarget.DOCKER_HOST,
            primary_service="automation_api",
            services={
                "automation_api": ServiceDefinition(
                    name="automation_api",
                    build_context=".",
                    ports=[PortMapping(host_ip="127.0.0.1", host_port=8000, container_port=8000)],
                    environment={"DATABASE_URL": "postgresql://procure:pass@database:5432/procure_db"},
                    volumes=[VolumeDefinition(host_path="./data/uploads", container_path="/app/uploads")],
                    networks=["flow_network"],
                    depends_on=["database"],
                ),
                "scheduler": ServiceDefinition(
                    name="scheduler",
                    build_context=".",
                    command="python3 -m src.scheduler",
                    environment={"DATABASE_URL": "postgresql://procure:pass@database:5432/procure_db"},
                    networks=["flow_network"],
                    depends_on=["database"],
                ),
                "worker": ServiceDefinition(
                    name="worker",
                    build_context=".",
                    command="python3 -m src.worker --concurrency 4",
                    environment={"DATABASE_URL": "postgresql://procure:pass@database:5432/procure_db"},
                    networks=["flow_network"],
                    depends_on=["database"],
                ),
                "database": ServiceDefinition(
                    name="database",
                    image="postgres:16",
                    internal_ports=[5432],
                    environment={"POSTGRES_DB": "procure_db", "POSTGRES_PASSWORD": "pass"},
                    volumes=[VolumeDefinition(host_path="./data/database", container_path="/var/lib/postgresql/data")],
                    networks=["flow_network"],
                ),
            },
            networks={
                "flow_network": NetworkDefinition(name="flow_network", driver="bridge", internal=True)
            },
            data_directories=["data/uploads", "data/database", "data/logs", "data/config"],
            metadata={"power_engine": "18-COMMERCIAL-C", "workload": "workflow_automation"},
        )

        delivery = CustomerDeliveryBuilder(self.delivery_dir)
        delivery.prepare_directories(spec.data_directories)
        delivery.build_deployment_files(spec)

        (self.delivery_dir / "src" / "worker.py").write_text("# automation worker\n", encoding="utf-8")
        violations = delivery.sanitize_proprietary_boundary()
        self.assertEqual(violations, [])

        dc_text = (self.delivery_dir / "docker-compose.yml").read_text(encoding="utf-8")
        self.assertIn("automation_api:", dc_text)
        self.assertIn("scheduler:", dc_text)
        self.assertIn("worker:", dc_text)
        self.assertIn("database:", dc_text)
        self.assertNotIn("qdrant", dc_text)

        manifest = delivery.create_manifest()
        self.assertEqual(len(manifest.files_created), len(manifest.sha256_checksums))

    def test_commercial_d_migration_power_engine_fixture(self):
        """
        Phase 18-COMMERCIAL-D Fixture: Code Migration / Refactoring Power Engine.
        Topology:
          - migrated_app (Modernized application service)
          - database (Migrated relational schema)
        """
        spec = CustomerDeploymentSpec(
            project_name="Legacy COBOL to Java Modernization Delivery",
            sanitized_project_id="cobol_to_java_migrated",
            target=DeploymentTarget.DOCKER_HOST,
            primary_service="migrated_app",
            services={
                "migrated_app": ServiceDefinition(
                    name="migrated_app",
                    build_context=".",
                    ports=[PortMapping(host_ip="127.0.0.1", host_port=8080, container_port=8080)],
                    environment={"SPRING_PROFILES_ACTIVE": "prod"},
                    volumes=[VolumeDefinition(host_path="./data/storage", container_path="/app/data")],
                    networks=["migrated_net"],
                    depends_on=["database"],
                ),
                "database": ServiceDefinition(
                    name="database",
                    image="postgres:16-alpine",
                    internal_ports=[5432],
                    volumes=[VolumeDefinition(host_path="./data/db", container_path="/var/lib/postgresql/data")],
                    networks=["migrated_net"],
                ),
            },
            networks={
                "migrated_net": NetworkDefinition(name="migrated_net", driver="bridge", internal=True)
            },
            data_directories=["data/storage", "data/db", "data/logs"],
            metadata={"power_engine": "18-COMMERCIAL-D", "workload": "code_migration"},
        )

        delivery = CustomerDeliveryBuilder(self.delivery_dir)
        delivery.prepare_directories(spec.data_directories)
        delivery.build_deployment_files(spec)

        manifest = json.loads((self.delivery_dir / "config" / "deployment_manifest.json").read_text())
        self.assertEqual(manifest["primary_service"], "migrated_app")
        self.assertIn("migrated_app", manifest["services"])
        self.assertIn("database", manifest["services"])
        self.assertEqual(manifest["ports"]["migrated_app"], 8080)

        violations = delivery.sanitize_proprietary_boundary()
        self.assertEqual(violations, [])


if __name__ == "__main__":
    unittest.main()

