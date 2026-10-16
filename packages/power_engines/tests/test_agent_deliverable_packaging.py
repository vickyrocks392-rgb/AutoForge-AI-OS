"""Phase 20-C Gate 3 Deliverable Generation, Packaging & Verification Regression Suite.

Tests the end-to-end deliverable generation, packaging reproducibility, manifest
integrity, and independent verification of the Custom AI Agent deliverable.
"""

import asyncio
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
import unittest
from pathlib import Path

from autoforge_api.models import IntentExecutionRequest
from autoforge_api.service import AutoForgeApiService
from autoforge_composition.capability_router import CAPABILITY_AGENT
from autoforge_power_engines.agent import CustomAIAgentPowerEngine, StandaloneCustomerAgentGenerator
from autoforge_power_engines.agent.spec import (
    CustomerAgentSpecification,
    AgentToolConfig,
    AgentModelConfig,
    ExecutionLimits,
)
from autoforge_power_engines.delivery.packaging import CustomerDeliveryBuilder

AUTHORIZED_MLX_PORT = 19801
AUTHORIZED_MLX_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"


class TestAgentDeliverableStructure(unittest.TestCase):
    """Validates structural integrity, security configuration, and completeness of generated files."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate3_struct_"))
        self.delivery_dir = self.temp_dir / "deliveries" / "gate3_struct_test"
        self.spec = CustomerAgentSpecification(
            project_name="Gate 3 Verification Agent",
            agent_purpose="Autonomous customer agent with memory and safety limits",
            system_instructions="You are an autonomous assistant with strict safety invariants.",
            output_root=str(self.temp_dir / "deliveries"),
            delivery_id="gate3_struct_test",
            allowed_tools=["read_file", "write_file", "list_directory", "calculator"],
            tool_definitions=[
                AgentToolConfig(name="read_file", description="Read file", enabled=True),
                AgentToolConfig(name="write_file", description="Write file", enabled=True),
                AgentToolConfig(name="list_directory", description="List dir", enabled=True),
                AgentToolConfig(name="calculator", description="Math eval", enabled=True),
            ],
            port=8080,
            model_config_spec=AgentModelConfig(
                model_name=AUTHORIZED_MLX_MODEL,
                provider="mlx",
                port=AUTHORIZED_MLX_PORT,
            ),
        )
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_deliverable_file_existence_and_non_empty(self):
        """All required deliverable source files, tests, launchers, and docs must exist and be non-empty."""
        self.generator.generate_customer_project(self.spec)
        self.assertTrue(self.delivery_dir.exists())

        required_relative_paths = [
            "src/app.py",
            "src/agent.py",
            "src/tools.py",
            "src/memory.py",
            "src/config.py",
            "src/state_machine.py",
            "src/parser.py",
            "src/verifier.py",
            "README.md",
            "DELIVERY_REPORT.md",
            "SECURITY_AND_LIMITATIONS.md",
            "docs/SECURITY_AND_LIMITATIONS.md",
            "deploy.sh",
            "Deploy.command",
            "manage.sh",
            "config/requirements.txt",
            "tests/__init__.py",
            "tests/test_agent_runtime.py",
            "artifacts/manifest.json",
            "artifacts/checksums.sha256",
        ]

        for rel_path in required_relative_paths:
            file_path = self.delivery_dir / rel_path
            self.assertTrue(file_path.exists(), f"Missing required file: {rel_path}")
            self.assertGreater(file_path.stat().st_size, 0, f"File is empty: {rel_path}")

    def test_no_ollama_or_forbidden_endpoints(self):
        """Generated deliverable must not contain Ollama or unauthorized ports/hosts."""
        self.generator.generate_customer_project(self.spec)

        forbidden_strings = ["ollama", "localhost:11434", "11434"]
        text_extensions = {".py", ".sh", ".json", ".md", ".txt", ".yaml", ".yml"}

        for p in self.delivery_dir.rglob("*"):
            if p.is_file() and p.suffix in text_extensions:
                content = p.read_text(encoding="utf-8").lower()
                for forbidden in forbidden_strings:
                    self.assertNotIn(
                        forbidden,
                        content,
                        f"Found forbidden string '{forbidden}' in deliverable file: {p.relative_to(self.delivery_dir)}"
                    )

    def test_security_invariants_and_approved_inference(self):
        """Generated config and runtime must target MLX 19801 and approved model."""
        self.generator.generate_customer_project(self.spec)
        config_path = self.delivery_dir / "src" / "config.py"
        content = config_path.read_text(encoding="utf-8")

        self.assertIn("19801", content)
        self.assertIn("Qwen3-Coder-30B-A3B", content)

        tools_path = self.delivery_dir / "src" / "tools.py"
        tools_content = tools_path.read_text(encoding="utf-8")
        self.assertIn("calculator", tools_content)
        self.assertIn("file_read", tools_content)
        self.assertIn("document_lookup", tools_content)
        self.assertIn("structured_http", tools_content)


class TestAgentPackagingAndReproducibility(unittest.TestCase):
    """Validates archive packaging, manifest accuracy, extraction, and reproducibility."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate3_pack_"))
        self.delivery_dir = self.temp_dir / "deliveries" / "gate3_repro_test"
        self.spec = CustomerAgentSpecification(
            project_name="Reproducible Packaging Agent",
            agent_purpose="Agent for testing package reproducibility and extraction",
            system_instructions="You are an autonomous assistant.",
            output_root=str(self.temp_dir / "deliveries"),
            delivery_id="gate3_repro_test",
        )
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_reproducible_archive_creation(self):
        """Two archives created from the same directory with reproducible=True must have identical SHA-256."""
        builder = CustomerDeliveryBuilder(self.delivery_dir)
        archive_path_1 = self.temp_dir / "dist1" / "bundle1.tar.gz"
        archive_path_2 = self.temp_dir / "dist2" / "bundle2.tar.gz"

        builder.create_archive(archive_path=archive_path_1, reproducible=True, fixed_mtime=1700000000)
        builder.create_archive(archive_path=archive_path_2, reproducible=True, fixed_mtime=1700000000)

        sha1 = hashlib.sha256(archive_path_1.read_bytes()).hexdigest()
        sha2 = hashlib.sha256(archive_path_2.read_bytes()).hexdigest()

        self.assertEqual(sha1, sha2, f"Archives are not byte-identical: {sha1} != {sha2}")

    def test_archive_extraction_and_manifest_checksum_verification(self):
        """Extracted files must match the SHA-256 hashes recorded in artifacts/manifest.json."""
        builder = CustomerDeliveryBuilder(self.delivery_dir)
        archive_path = self.temp_dir / "distribution.tar.gz"
        builder.create_archive(archive_path=archive_path, reproducible=True)

        extract_dir = self.temp_dir / "extracted_verify"
        extract_dir.mkdir(parents=True)

        with tarfile.open(archive_path, "r:gz") as tar:
            tar.extractall(extract_dir)

        manifest_file = extract_dir / "artifacts" / "manifest.json"
        self.assertTrue(manifest_file.exists(), "Extracted manifest does not exist")

        with open(manifest_file, "r") as f:
            manifest = json.load(f)

        checksums_map = manifest.get("sha256_checksums", {})
        self.assertGreater(len(checksums_map), 15, "Manifest contains too few checksums")

        for rel_path, expected_sha in checksums_map.items():
            extracted_file = extract_dir / rel_path
            self.assertTrue(extracted_file.exists(), f"Extracted file {rel_path} does not exist")
            actual_sha = hashlib.sha256(extracted_file.read_bytes()).hexdigest()
            self.assertEqual(
                actual_sha,
                expected_sha,
                f"Checksum mismatch for {rel_path}: expected {expected_sha}, got {actual_sha}"
            )


class TestAgentIndependentVerification(unittest.TestCase):
    """Independent verification of the deliverable from its extracted package."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate3_indep_"))
        self.delivery_dir = self.temp_dir / "deliveries" / "gate3_indep_test"
        self.spec = CustomerAgentSpecification(
            project_name="Independent Verification Agent",
            agent_purpose="Agent for running standalone unit tests and syntax checks",
            system_instructions="You are an autonomous assistant.",
            output_root=str(self.temp_dir / "deliveries"),
            delivery_id="gate3_indep_test",
        )
        self.generator = StandaloneCustomerAgentGenerator(self.delivery_dir)
        self.generator.generate_customer_project(self.spec)

        builder = CustomerDeliveryBuilder(self.delivery_dir)
        self.archive_path = self.temp_dir / "package.tar.gz"
        builder.create_archive(archive_path=self.archive_path, reproducible=True)

        self.extracted_dir = self.temp_dir / "verified_package"
        with tarfile.open(self.archive_path, "r:gz") as tar:
            tar.extractall(self.extracted_dir)

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_python_syntax_and_compilation(self):
        """All python files in extracted package must compile without syntax errors."""
        py_files = list(self.extracted_dir.rglob("*.py"))
        self.assertGreater(len(py_files), 5)

        for py_path in py_files:
            res = subprocess.run(
                [sys.executable, "-m", "py_compile", str(py_path)],
                capture_output=True,
                text=True
            )
            self.assertEqual(res.returncode, 0, f"Compilation failed for {py_path}: {res.stderr}")

    def test_run_customer_unit_tests_in_extracted_package(self):
        """Customer unit tests must execute and pass in the isolated extracted directory."""
        env = dict(os.environ)
        env["PYTHONPATH"] = str(self.extracted_dir)
        res = subprocess.run(
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
            cwd=str(self.extracted_dir),
            env=env,
            capture_output=True,
            text=True
        )
        self.assertEqual(
            res.returncode,
            0,
            f"Customer unit tests failed in extracted package:\nSTDOUT:\n{res.stdout}\nSTDERR:\n{res.stderr}"
        )
        self.assertIn("Ran 10 tests", res.stderr)
        self.assertIn("OK", res.stderr)


class TestCanonicalIngressPackaging(unittest.TestCase):
    """End-to-end integration through canonical AutoForge ingress pipeline."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate3_ingress_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_canonical_ingress_agent_execution_and_packaging(self):
        """AutoForgeApiService.execute_intent_pipeline produces verified deliverable and archive."""
        service = AutoForgeApiService()
        req = IntentExecutionRequest(
            prompt="Build an enterprise AI Agent for data processing with workspace sandboxing and SQLite memory",
            intent_type=CAPABILITY_AGENT,
            context={
                "capability": CAPABILITY_AGENT,
                "project_name": "Canonical-Ingress-Agent",
                "output_root": str(self.temp_dir),
                "authorized_tools": ["read_file", "write_file", "list_directory", "calculator"],
                "enable_memory": True,
            }
        )

        resp = service.execute_intent_pipeline(req)

        self.assertEqual(resp.status, "COMPLETED")
        self.assertTrue(resp.execution_id.startswith("exec-int-"))

        # Locate delivery directory under self.temp_dir (must be a directory)
        delivery_dirs = [d for d in self.temp_dir.rglob("delivery-*") if d.is_dir()]
        self.assertTrue(len(delivery_dirs) > 0, f"No delivery directory found in {self.temp_dir}")
        delivery_dir = delivery_dirs[0]

        # Check that manifest and checksums exist inside delivery directory
        manifest_path = delivery_dir / "artifacts" / "manifest.json"
        checksums_path = delivery_dir / "artifacts" / "checksums.sha256"
        self.assertTrue(manifest_path.exists())
        self.assertTrue(checksums_path.exists())

        # Check distribution archive exists
        archives = list(delivery_dir.parent.glob("*.tar.gz"))
        self.assertTrue(len(archives) > 0, "No distribution archive created")
        self.assertGreater(archives[0].stat().st_size, 1000)


class TestNegativeAndFailClosedPackaging(unittest.TestCase):
    """Negative tests: tampered deliverable and failing tests must trigger fail-closed rejection."""

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_gate3_failclosed_"))

    def tearDown(self):
        shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_failing_customer_tests_trigger_fail_closed_in_engine(self):
        """If customer unit tests fail, verification records defect and re-verify raises RuntimeError."""
        spec = CustomerAgentSpecification(
            project_name="FailClosed Test Agent",
            agent_purpose="Agent for testing fail-closed verification",
            system_instructions="You are a fail-closed test agent",
            output_root=str(self.temp_dir),
        )
        engine = CustomAIAgentPowerEngine()
        ctx = engine.create_context(spec)

        asyncio.run(engine._stage_intake(ctx))
        asyncio.run(engine._stage_understand_analyze(ctx))
        asyncio.run(engine._stage_plan(ctx))
        asyncio.run(engine._stage_execute(ctx))
        asyncio.run(engine._stage_observe(ctx))

        # Deliberately sabotage test file
        test_file = ctx.delivery_dir / "tests" / "test_agent_runtime.py"
        test_file.write_text(
            "import unittest\nclass SabotagedTest(unittest.TestCase):\n    def test_fail(self):\n        self.assertEqual(1, 2)\n"
        )

        res = asyncio.run(engine._stage_verify(ctx))
        self.assertFalse(res["customer_tests_passed"])
        self.assertGreater(res["defects_count"], 0)

        # Re-verify stage must raise RuntimeError and fail-closed
        with self.assertRaises(RuntimeError) as exc_ctx:
            asyncio.run(engine._stage_re_verify(ctx))
        self.assertIn("customer tests failed", str(exc_ctx.exception))


if __name__ == "__main__":
    unittest.main()
