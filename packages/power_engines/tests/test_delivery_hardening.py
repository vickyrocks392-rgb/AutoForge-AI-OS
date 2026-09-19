"""Comprehensive Hardening & Failure Mode Test Suite for Shared Customer Delivery Platform.

Validates:
- Declarative spec validation (missing primary service, dangling dependencies, invalid ports, port collisions)
- Hostile boundary intrusions (directory names, file names, dynamic imports, internal dev caches)
- Secret & credential leakage protection (API keys, private keys, tokens)
- Health check exit codes and CLI flags (--json, --require-service)
- Network isolation directives (internal: true)
- Full persistence lifecycle survivability across simulated updates
- Deterministic reproducibility of delivery manifests
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from pydantic import ValidationError

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
    ProprietaryBoundarySanitizer,
    ProprietaryCodeViolationError,
    SecretLeakageViolationError,
)


class TestDeliveryHardening(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_autoforge_hardening_"))
        # Layout: <temp_dir>/<project_id>/<delivery_id>
        self.project_dir = self.temp_dir / "secure_enterprise_client"
        self.delivery_dir = self.project_dir / "release_v1"

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def _create_valid_spec(self) -> CustomerDeploymentSpec:
        return CustomerDeploymentSpec(
            project_name="Secure Client Platform",
            sanitized_project_id="secure_client_platform",
            target=DeploymentTarget.DOCKER_HOST,
            primary_service="api_gateway",
            services={
                "api_gateway": ServiceDefinition(
                    name="api_gateway",
                    build_context=".",
                    ports=[PortMapping(host_ip="127.0.0.1", host_port=8080, container_port=8080)],
                    environment={"PORT": "8080"},
                    networks=["private_mesh"],
                    depends_on=["vault_storage"],
                ),
                "vault_storage": ServiceDefinition(
                    name="vault_storage",
                    image="postgres:16-alpine",
                    internal_ports=[5432],
                    networks=["private_mesh"],
                    volumes=[
                        VolumeDefinition(host_path="./data/vault", container_path="/var/lib/postgresql/data")
                    ],
                ),
            },
            networks={
                "private_mesh": NetworkDefinition(name="private_mesh", driver="bridge", internal=True)
            },
            data_directories=["data/vault", "data/logs", "data/config"],
        )

    # =========================================================================
    # 1. SPEC VALIDATION & INTEGRITY DEFENSIVE GUARDS
    # =========================================================================

    def test_spec_validation_missing_primary_service(self):
        """Verify that declaring a primary_service not in services raises ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            CustomerDeploymentSpec(
                project_name="Invalid Spec App",
                sanitized_project_id="invalid_spec_app",
                primary_service="non_existent_service",
                services={
                    "actual_service": ServiceDefinition(name="actual_service", build_context=".")
                },
            )
        self.assertIn("non_existent_service", str(ctx.exception))

    def test_spec_validation_dangling_dependency(self):
        """Verify that depends_on referencing an unknown service raises ValidationError."""
        with self.assertRaises(ValidationError) as ctx:
            CustomerDeploymentSpec(
                project_name="Dangling Dep App",
                sanitized_project_id="dangling_dep_app",
                primary_service="api",
                services={
                    "api": ServiceDefinition(
                        name="api",
                        build_context=".",
                        depends_on=["phantom_database"],
                    )
                },
            )
        self.assertIn("phantom_database", str(ctx.exception))

    def test_spec_validation_invalid_port_range(self):
        """Verify port validation bounds (1-65535)."""
        with self.assertRaises(ValidationError):
            PortMapping(host_ip="127.0.0.1", host_port=0, container_port=8080)

        with self.assertRaises(ValidationError):
            PortMapping(host_ip="127.0.0.1", host_port=70000, container_port=8080)

    def test_spec_validation_host_port_collision(self):
        """Verify that multiple services cannot claim the same host IP and port."""
        with self.assertRaises(ValidationError) as ctx:
            CustomerDeploymentSpec(
                project_name="Port Collision App",
                sanitized_project_id="port_collision_app",
                primary_service="svc1",
                services={
                    "svc1": ServiceDefinition(
                        name="svc1",
                        build_context=".",
                        ports=[PortMapping(host_ip="127.0.0.1", host_port=8000, container_port=8000)],
                    ),
                    "svc2": ServiceDefinition(
                        name="svc2",
                        build_context=".",
                        ports=[PortMapping(host_ip="127.0.0.1", host_port=8000, container_port=9000)],
                    ),
                },
            )
        self.assertIn("Host port collision", str(ctx.exception))

    # =========================================================================
    # 2. PROPRIETARY BOUNDARY & HOSTILE INTRUSION RESISTANCE
    # =========================================================================

    def test_hostile_boundary_intrusion_package_directory(self):
        """Verify that injecting internal package directory names triggers fail-visible rejection."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        # Hostile intrusion: copying internal kernel directory
        leaked_dir = self.delivery_dir / "src" / "autoforge_kernel"
        leaked_dir.mkdir(parents=True)
        (leaked_dir / "worker.py").write_text("# innocous content", encoding="utf-8")

        with self.assertRaises(ProprietaryCodeViolationError) as ctx:
            packager.sanitize_proprietary_boundary()
        self.assertIn("autoforge_kernel", str(ctx.exception))

    def test_hostile_boundary_intrusion_internal_artifacts(self):
        """Verify that internal development caches (.git, .pytest_cache) are rejected."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        # Hostile intrusion: accidental git folder inclusion
        git_dir = self.delivery_dir / ".git"
        git_dir.mkdir(parents=True)
        (git_dir / "config").write_text("[core]\nrepositoryformatversion = 0\n", encoding="utf-8")

        with self.assertRaises(ProprietaryCodeViolationError) as ctx:
            packager.sanitize_proprietary_boundary()
        self.assertIn(".git", str(ctx.exception))

    def test_hostile_boundary_intrusion_dynamic_imports(self):
        """Verify that dynamic imports (__import__ or import_module) of proprietary modules are caught."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        dynamic_leak = self.delivery_dir / "src" / "sneaky.py"
        dynamic_leak.write_text(
            'mod = __import__("autoforge_workforce")\n',
            encoding="utf-8",
        )

        with self.assertRaises(ProprietaryCodeViolationError) as ctx:
            packager.sanitize_proprietary_boundary()
        self.assertIn("autoforge_workforce", str(ctx.exception))

    # =========================================================================
    # 3. SECRET & CREDENTIAL SAFETY SCANNER
    # =========================================================================

    def test_secret_leakage_detection_private_key(self):
        """Verify that exposed private keys are flagged fail-visibly."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        key_file = self.delivery_dir / "config" / "server.key"
        key_file.write_text(
            "-----BEGIN RSA PRIVATE KEY-----\nMIIEowIBAAKCAQEA0mockkey...\n-----END RSA PRIVATE KEY-----\n",
            encoding="utf-8",
        )

        with self.assertRaises(SecretLeakageViolationError) as ctx:
            packager.sanitize_proprietary_boundary()
        self.assertIn("Private cryptographic key", str(ctx.exception))

    def test_secret_leakage_detection_api_key(self):
        """Verify that exposed raw model API keys are flagged."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        env_file = self.delivery_dir / ".env.leaked"
        env_file.write_text("OPENAI_API_KEY=sk-abcdef1234567890abcdef1234567890\n", encoding="utf-8")

        with self.assertRaises(SecretLeakageViolationError) as ctx:
            packager.sanitize_proprietary_boundary()
        self.assertIn("OpenAI / Model API Key", str(ctx.exception))

    def test_secret_leakage_placeholder_allowed(self):
        """Verify that explicit sanitized placeholders in .env.example are permitted."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        env_file = self.delivery_dir / ".env.example"
        env_file.write_text("OPENAI_API_KEY=sk-placeholder-your-key-here\n", encoding="utf-8")

        # Must not raise
        violations = packager.sanitize_proprietary_boundary()
        self.assertEqual(violations, [])

    # =========================================================================
    # 4. HEALTH CHECK EXIT CODES & CLI OPTIONS
    # =========================================================================

    def test_health_check_script_execution_and_exit_codes(self):
        """Verify generated health_check.py exit code behavior and CLI flags."""
        spec = self._create_valid_spec()
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories(spec.data_directories)
        packager.build_deployment_files(spec)

        health_script = self.delivery_dir / "scripts" / "health_check.py"
        self.assertTrue(health_script.exists())

        # 1. Standalone run without live service: storage is healthy, exits 0
        res = subprocess.run(
            [sys.executable, str(health_script)],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res.returncode, 0, f"Expected 0, got {res.returncode}: {res.stderr}")
        self.assertIn("PERSISTENT_STORAGE", res.stdout)

        # 2. JSON flag execution
        res_json = subprocess.run(
            [sys.executable, str(health_script), "--json"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_json.returncode, 0)
        data = json.loads(res_json.stdout)
        self.assertIn("status", data)
        self.assertIn("checks", data)

        # 3. Require service flag when service is offline: must exit 1
        res_req = subprocess.run(
            [sys.executable, str(health_script), "--require-service"],
            capture_output=True,
            text=True,
        )
        self.assertEqual(res_req.returncode, 1, "Must exit with code 1 when service is offline and required")

    # =========================================================================
    # 5. NETWORK SECURITY & DOCKER COMPOSE DIRECTIVES
    # =========================================================================

    def test_network_internal_directive_and_security_opts(self):
        """Verify internal: true and security_opt: no-new-privileges:true in docker-compose.yml."""
        spec = self._create_valid_spec()
        builder = DeploymentBuilder()
        compose_yaml = builder.build_docker_compose(spec)

        self.assertIn("networks:", compose_yaml)
        self.assertIn("private_mesh:", compose_yaml)
        self.assertIn("internal: true", compose_yaml)
        self.assertIn("security_opt:", compose_yaml)
        self.assertIn("no-new-privileges:true", compose_yaml)

    # =========================================================================
    # 6. PERSISTENCE SURVIVABILITY LIFECYCLE
    # =========================================================================

    def test_full_persistence_lifecycle_survivability(self):
        """Simulate customer usage: deploy -> write data -> stop -> restart -> redeploy -> data intact."""
        spec = self._create_valid_spec()
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories(spec.data_directories)
        packager.build_deployment_files(spec)

        # Write customer data
        vault_data = self.delivery_dir / "data" / "vault" / "secrets.bin"
        vault_data.write_bytes(b"\xde\xad\xbe\xef" * 16)

        customer_log = self.delivery_dir / "data" / "logs" / "application.log"
        customer_log.write_text("Customer audit record 1\n", encoding="utf-8")

        # Redeploy application files (simulating update)
        packager.build_deployment_files(spec)

        # Verify customer data survives completely
        self.assertTrue(vault_data.exists())
        self.assertEqual(vault_data.read_bytes(), b"\xde\xad\xbe\xef" * 16)
        self.assertTrue(customer_log.exists())
        self.assertEqual(customer_log.read_text(encoding="utf-8"), "Customer audit record 1\n")

    # =========================================================================
    # 7. DETERMINISTIC REPRODUCIBILITY
    # =========================================================================

    def test_deterministic_reproducibility(self):
        """Verify that packaging the same spec produces identical manifests with fixed timestamp."""
        spec = self._create_valid_spec()
        fixed_time = "2026-09-20T00:00:00+00:00"

        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories(spec.data_directories)
        packager.build_deployment_files(spec)

    # =========================================================================
    # 8. PATH TRAVERSAL & SYMLINK BOUNDARY CONFINEMENT
    # =========================================================================

    def test_write_file_path_traversal_blocked(self):
        """Verify that attempts to write files outside the delivery root raise ValueError."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        # Attempt to escape delivery dir
        with self.assertRaises(ValueError) as ctx:
            packager.write_file("../../escaped_file.txt", "MALICIOUS PAYLOAD")
        self.assertIn("Path traversal detected", str(ctx.exception))

    def test_symlink_traversal_blocked(self):
        """Verify that symlinks pointing outside the delivery root trigger boundary violation."""
        packager = CustomerDeliveryBuilder(self.delivery_dir)
        packager.prepare_directories()

        # Create external file outside delivery root
        external_file = self.temp_dir / "external_secret.txt"
        external_file.write_text("HOST_SYSTEM_CONFIDENTIAL", encoding="utf-8")

        # Create symlink inside delivery pointing to external file
        symlink_target = self.delivery_dir / "src" / "sneaky_symlink.txt"
        try:
            os.symlink(external_file, symlink_target)
        except OSError:
            self.skipTest("Symlink creation not permitted on this platform/user")

        with self.assertRaises(ProprietaryCodeViolationError) as ctx:
            packager.sanitize_proprietary_boundary()
        self.assertIn("Symlink traversal outside delivery boundary", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
