"""Comprehensive Automated Tests for Shared Customer Delivery & Deployment Platform."""

import json
import os
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
    PersistenceMode,
    DeploymentBuilder,
    HealthCheckBuilder,
    CustomerDeliveryBuilder,
    CustomerDocumentationBuilder,
    ProprietaryBoundarySanitizer,
    ProprietaryCodeViolationError,
)


class TestSharedDeliveryPlatform(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_autoforge_shared_delivery_"))

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_sample_generic_spec(self, project_name: str = "Enterprise FinTech Ledger") -> CustomerDeploymentSpec:
        """Creates an arbitrary generic (non-RAG) workload deployment spec."""
        services = {
            "web_api": ServiceDefinition(
                name="web_api",
                build_context=".",
                dockerfile="Dockerfile",
                container_name=f"customer_web_api_{project_name.lower().replace(' ', '_')}",
                restart_policy=RestartPolicy.UNLESS_STOPPED,
                ports=[PortMapping(host_ip="127.0.0.1", host_port=9000, container_port=9000)],
                environment={"PORT": "9000", "DB_HOST": "db_internal"},
                volumes=[
                    VolumeDefinition(host_path="./data/workspace", container_path="/app/data/workspace"),
                    VolumeDefinition(host_path="./config", container_path="/app/config"),
                ],
                networks=["internal_net"],
                depends_on=["db_internal"],
                extra_hosts=["host.docker.internal:host-gateway"],
            ),
            "db_internal": ServiceDefinition(
                name="db_internal",
                image="postgres:16-alpine",
                container_name=f"customer_db_{project_name.lower().replace(' ', '_')}",
                restart_policy=RestartPolicy.UNLESS_STOPPED,
                internal_ports=[5432],
                environment={"POSTGRES_DB": "app_db", "POSTGRES_PASSWORD": "secure_secret_pass"},
                volumes=[
                    VolumeDefinition(host_path="./data/database", container_path="/var/lib/postgresql/data")
                ],
                networks=["internal_net"],
            ),
        }

        networks = {
            "internal_net": NetworkDefinition(name="internal_net", driver="bridge", internal=True)
        }

        return CustomerDeploymentSpec(
            project_name=project_name,
            sanitized_project_id=project_name.lower().replace(" ", "_"),
            target=DeploymentTarget.DOCKER_HOST,
            primary_service="web_api",
            services=services,
            networks=networks,
            global_environment={"ENV": "production", "LOG_LEVEL": "info"},
            persistent_storage=True,
            private_networking=True,
            auto_open_browser=False,
            data_directories=["data/workspace", "data/database", "data/logs", "data/config"],
            metadata={"workload_type": "enterprise_ledger", "sla": "mission_critical"},
        )

    def test_generic_deployment_spec_representation(self):
        """Verify that arbitrary customer workloads can be represented generically."""
        spec = self._create_sample_generic_spec()
        self.assertEqual(spec.project_name, "Enterprise FinTech Ledger")
        self.assertEqual(spec.primary_service, "web_api")
        self.assertEqual(spec.get_primary_port(), 9000)
        self.assertEqual(spec.get_primary_host(), "127.0.0.1")
        self.assertIn("web_api", spec.services)
        self.assertIn("db_internal", spec.services)
        self.assertEqual(len(spec.data_directories), 4)

    def test_generic_service_generation(self):
        """Verify DeploymentBuilder generates multi-service topology with internal exposure."""
        spec = self._create_sample_generic_spec()
        builder = DeploymentBuilder()

        dc_yaml = builder.build_docker_compose(spec)
        self.assertIn("web_api:", dc_yaml)
        self.assertIn("db_internal:", dc_yaml)
        self.assertIn("127.0.0.1:9000:9000", dc_yaml)
        # Database must only be exposed internally, never bound to public host port
        self.assertIn('expose:\n      - "5432"', dc_yaml)
        self.assertNotIn("5432:5432", dc_yaml)
        self.assertIn("internal_net", dc_yaml)

        # Dockerfile verification
        df_text = builder.build_dockerfile(entrypoint_cmd="python3 src/main.py", expose_port=9000)
        self.assertIn("FROM python:3.11-slim", df_text)
        self.assertIn("useradd -r -g appuser appuser", df_text)
        self.assertIn("USER appuser", df_text)
        self.assertIn("EXPOSE 9000", df_text)

    def test_generic_launcher_generation(self):
        """Verify launchers are completely free of RAG-specific terminology."""
        spec = self._create_sample_generic_spec()
        builder = DeploymentBuilder()

        deploy_sh = builder.build_deploy_sh(spec)
        deploy_cmd = builder.build_deploy_command()
        deploy_bat = builder.build_deploy_bat(spec)
        manage_sh = builder.build_manage_sh(spec)

        for script in [deploy_sh, deploy_cmd, deploy_bat, manage_sh]:
            lower = script.lower()
            self.assertNotIn("qdrant", lower, "Shared launchers must not reference Qdrant")
            self.assertNotIn("vector_store", lower, "Shared launchers must not reference vector_store")
            self.assertNotIn("retriever", lower, "Shared launchers must not reference retriever")

        self.assertIn("PORT=\"${PORT:-9000}\"", deploy_sh)
        self.assertIn("data/workspace data/database", deploy_sh)
        self.assertIn("./manage.sh {start|stop|restart|status|logs}", manage_sh)

    def test_generic_persistence_model(self):
        """Verify persistent volume partitions survive updates and container rebuilds."""
        spec = self._create_sample_generic_spec()
        packager = CustomerDeliveryBuilder(self.temp_dir)
        packager.prepare_directories(spec.data_directories)
        packager.build_deployment_files(spec)

        # Write customer data into persistent partitions
        db_file = self.temp_dir / "data" / "database" / "ledger.db"
        db_file.write_text("INIT_LEDGER_TRANSACTIONS", encoding="utf-8")

        # Redeploy application files
        packager.build_deployment_files(spec)

        # Customer data must survive
        self.assertTrue(db_file.exists())
        self.assertEqual(db_file.read_text(encoding="utf-8"), "INIT_LEDGER_TRANSACTIONS")

    def test_generic_health_check_framework(self):
        """Verify HealthCheckBuilder generates functional diagnostic harness."""
        spec = self._create_sample_generic_spec()
        health_builder = HealthCheckBuilder()
        script_content = health_builder.build_health_script(spec)

        self.assertIn("def check_persistent_storage()", script_content)
        self.assertIn("def check_service_readiness()", script_content)
        self.assertIn("run_all_checks()", script_content)

    def test_generic_proprietary_boundary(self):
        """Verify boundary sanitizer catches and blocks proprietary AutoForge code."""
        packager = CustomerDeliveryBuilder(self.temp_dir)
        packager.prepare_directories()

        clean_file = self.temp_dir / "src" / "worker.py"
        clean_file.write_text("import json\nimport requests\nprint('Clean customer code')\n", encoding="utf-8")

        # Clean check passes
        violations = packager.sanitize_proprietary_boundary()
        self.assertEqual(violations, [])

        # Inject proprietary leakage
        leaked_file = self.temp_dir / "src" / "leak.py"
        leaked_file.write_text("from autoforge_kernel.orchestrator import Engine\n", encoding="utf-8")

        with self.assertRaises(ProprietaryCodeViolationError):
            packager.sanitize_proprietary_boundary()

    def test_customer_data_isolation(self):
        """Verify customer packages generated for tenant A and tenant B remain 100% isolated."""
        dir_a = self.temp_dir / "customer_a" / "delivery_01"
        dir_b = self.temp_dir / "customer_b" / "delivery_02"

        spec_a = self._create_sample_generic_spec("ClientAlpha Platform")
        spec_b = self._create_sample_generic_spec("ClientBeta Platform")

        pack_a = CustomerDeliveryBuilder(dir_a)
        pack_b = CustomerDeliveryBuilder(dir_b)

        pack_a.prepare_directories(spec_a.data_directories)
        pack_b.prepare_directories(spec_b.data_directories)

        pack_a.build_deployment_files(spec_a)
        pack_b.build_deployment_files(spec_b)

        manifest_a = pack_a.create_manifest()
        manifest_b = pack_b.create_manifest()

        self.assertNotEqual(manifest_a.delivery_dir, manifest_b.delivery_dir)
        self.assertEqual(manifest_a.project_name, "customer_a")
        self.assertEqual(manifest_b.project_name, "customer_b")
        self.assertEqual(manifest_a.delivery_id, "delivery_01")
        self.assertEqual(manifest_b.delivery_id, "delivery_02")

    def test_deployment_idempotency(self):
        """Verify repeated packaging produces identical, uncorrupted deployment artifacts."""
        spec = self._create_sample_generic_spec()
        packager = CustomerDeliveryBuilder(self.temp_dir)
        packager.prepare_directories(spec.data_directories)

        packager.build_deployment_files(spec)
        manifest1 = packager.create_manifest()

        packager.build_deployment_files(spec)
        manifest2 = packager.create_manifest()

        self.assertEqual(manifest1.files_created, manifest2.files_created)
        self.assertEqual(manifest1.total_bytes, manifest2.total_bytes)
        self.assertEqual(manifest1.sha256_checksums, manifest2.sha256_checksums)

    def test_customer_documentation_builder(self):
        """Verify CustomerDocumentationBuilder generates exact canonical 15 sections."""
        spec = self._create_sample_generic_spec()
        doc_builder = CustomerDocumentationBuilder()

        readme = doc_builder.generate_readme(
            spec=spec,
            what_you_received_items=["Standalone Core Service (`src/app.py`)"],
            config_table_rows=[{"variable": "LOG_LEVEL", "default": "info", "description": "Logging level"}],
            troubleshooting_items=["Docker daemon unreachable: verify Docker Desktop is running."],
            architecture_overview="Enterprise Financial Ledger Service.",
            verification_summary="100% Behavioral Tests Passed.",
        )

        required_sections = [
            "## 1. What You Received",
            "## 2. System Requirements",
            "## 3. One-Click Deployment",
            "## 4. One-Command Deployment Fallback",
            "## 5. Configuration",
            "## 6. How to Start / Stop",
            "## 7. How to Update",
            "## 8. Where Customer Data is Stored",
            "## 9. How Backups Work",
            "## 10. How to Inspect Logs",
            "## 11. Troubleshooting",
            "## 12. Security Notes",
            "## 13. Optional Remote Deployment Service",
            "## 14. Architecture Overview",
            "## 15. Verification / Evidence",
        ]

        last_pos = -1
        for sec in required_sections:
            pos = readme.find(sec)
            self.assertGreater(pos, last_pos, f"Section {sec} is missing or out of canonical sequence")
            last_pos = pos

        # Verify delivery report
        report = doc_builder.generate_delivery_report(
            spec=spec,
            execution_id="exec-12345",
            delivery_dir=str(self.temp_dir),
            stages_executed=["INTAKE", "PLAN", "EXECUTE", "PACKAGE", "DELIVER"],
            repair_cycles=0,
            workload_scorecard_rows=[{"metric": "Ledger Validation", "result": "100% Consistency", "target": "100%", "status": "PASS"}],
            scope_description="Automated enterprise ledger deployment.",
            evidence_summary="Verified zero-drift ledger consistency.",
            provenance_count=12,
        )
        self.assertIn("OFFICIAL CUSTOMER DELIVERY REPORT", report)
        self.assertIn("Ledger Validation", report)
        self.assertIn("Proprietary Boundary Compliance", report)


if __name__ == "__main__":
    unittest.main()
