"""Automated Tests for Customer Deployment & One-Click Delivery Extension (Phase 18-COMMERCIAL-A)."""

import json
import os
import shutil
import tempfile
import unittest
from pathlib import Path

from autoforge_power_engines.packaging import CustomerProjectPackager
from autoforge_power_engines.rag.generator import StandaloneCustomerRAGGenerator
from autoforge_power_engines.rag.ingestion import KnowledgeChunkRecord, ProcessedDocument
from autoforge_power_engines.specification import (
    CustomerDeploymentProfile,
    CustomerProjectSpecification,
    DeploymentPreference,
    DeploymentTarget,
    EmbeddingProviderType,
    KnowledgeSourceSpec,
    LLMProviderType,
    SourceType,
    VectorStoreType,
)


class TestCustomerDeployment(unittest.TestCase):

    def setUp(self):
        self.temp_dir = Path(tempfile.mkdtemp(prefix="test_autoforge_deployment_"))
        self.packager = CustomerProjectPackager(self.temp_dir)
        self.generator = StandaloneCustomerRAGGenerator(self.packager)

        self.spec = CustomerProjectSpecification(
            project_name="Acme Enterprise Knowledge Assistant",
            project_description="Enterprise technical documentation assistant with zero-trust local deployment.",
            knowledge_sources=[
                KnowledgeSourceSpec(
                    source_id="doc1",
                    source_type=SourceType.DOCUMENT,
                    content="Acme platform policy requires multi-factor authentication for all administrators. Transactions exceeding $10,000 require manual compliance sign-off.",
                )
            ],
            deployment_preference=DeploymentPreference.CONTAINER,
            deployment_profile=CustomerDeploymentProfile(
                target=DeploymentTarget.DOCKER_HOST,
                vector_store=VectorStoreType.LOCAL_IN_MEMORY,
                embedding_provider=EmbeddingProviderType.LOCAL,
                llm_provider=LLMProviderType.OLLAMA,
                llm_model="qwen2.5-coder:7b-instruct-q3_K_M",
                port=8080,
                persistent_storage=True,
                private_networking=True,
                auto_open_browser=False,
            ),
        )

        self.docs = [
            ProcessedDocument(
                source_id="doc1",
                file_path="compliance_policy.txt",
                document_type="document",
                language="en",
                size_bytes=150,
                content_hash="hash123",
                chunks_count=1,
            )
        ]
        self.chunks = [
            KnowledgeChunkRecord(
                chunk_id="chk-001",
                source_id="doc1",
                file_path="compliance_policy.txt",
                document_type="document",
                language="en",
                chunk_index=0,
                content="Acme platform policy requires multi-factor authentication for all administrators. Transactions exceeding $10,000 require manual compliance sign-off.",
                line_start=1,
                line_end=5,
                content_hash="hashchunk123",
            )
        ]

    def tearDown(self):
        if self.temp_dir.exists():
            shutil.rmtree(self.temp_dir, ignore_errors=True)

    def test_deployment_manifest_validity(self):
        """Verify the generated deployment manifest has all required fields and matches profile."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)
        manifest_path = self.temp_dir / "config" / "deployment_manifest.json"
        self.assertTrue(manifest_path.exists(), "deployment_manifest.json must exist")

        data = json.loads(manifest_path.read_text(encoding="utf-8"))
        self.assertEqual(data["deployment_version"], "1.0")
        self.assertEqual(data["target"], "docker_host")
        self.assertEqual(data["vector_store"], "local_in_memory")
        self.assertEqual(data["llm_provider"], "ollama")
        self.assertEqual(data["llm_model"], "qwen2.5-coder:7b-instruct-q3_K_M")
        self.assertTrue(data["persistent_storage"])
        self.assertTrue(data["private_networking"])
        self.assertEqual(data["ports"]["rag_api"], 8080)
        self.assertIn("data/index", data["data_directories"])
        self.assertIn("data/qdrant", data["data_directories"])

    def test_package_completeness(self):
        """Verify all required deployment scripts, launchers, configs, and containers exist."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)

        expected_files = [
            "Deploy.command",
            "deploy.sh",
            "Deploy.bat",
            "manage.sh",
            "docker-compose.yml",
            "Dockerfile",
            ".env.example",
            ".env",
            "config/deployment_manifest.json",
            "config/settings.json",
            "config/requirements.txt",
            "src/app.py",
            "src/retriever.py",
            "src/models.py",
            "src/health.py",
            "scripts/run.sh",
            "scripts/query.sh",
            "scripts/test.sh",
            "scripts/health_check.py",
            "artifacts/knowledge_index.json",
            "data/index/knowledge_index.json",
        ]

        for rel in expected_files:
            target = self.temp_dir / rel
            self.assertTrue(target.exists(), f"Expected deliverable file {rel} is missing")

        # Check executable bits on launchers
        for script in ["Deploy.command", "deploy.sh", "manage.sh", "scripts/health_check.py"]:
            path = self.temp_dir / script
            self.assertTrue(os.access(path, os.X_OK), f"Script {script} must be executable")

    def test_proprietary_isolation(self):
        """Verify zero AutoForge proprietary source code or imports cross into customer delivery."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)
        # Should execute without raising ProprietaryCodeViolationError
        violations = self.packager.sanitize_proprietary_boundary()
        self.assertEqual(violations, [])

    def test_environment_configuration(self):
        """Verify .env and .env.example are generated without hardcoded secrets."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)
        env_text = (self.temp_dir / ".env").read_text(encoding="utf-8")

        self.assertIn("PORT=8080", env_text)
        self.assertIn("VECTOR_STORE=local_in_memory", env_text)
        self.assertIn("LLM_PROVIDER=ollama", env_text)
        self.assertIn("LLM_MODEL=qwen2.5-coder:7b-instruct-q3_K_M", env_text)
        # Auth token must not be hardcoded in environment template
        self.assertIn("AUTH_TOKEN=", env_text)

    def test_persistence_isolation(self):
        """Verify customer mutable data partitions exist and survive updates."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)

        # Write custom customer data into persistent partitions
        customer_custom_file = self.temp_dir / "data" / "uploads" / "custom_doc.txt"
        customer_custom_file.write_text("Confidential customer contract data", encoding="utf-8")

        # Re-run generator (simulating application update / redeployment)
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)

        # Ensure persistent customer upload remained intact
        self.assertTrue(customer_custom_file.exists(), "Customer uploads must not be overwritten on redeploy")
        self.assertEqual(customer_custom_file.read_text(encoding="utf-8"), "Confidential customer contract data")

    def test_deployment_idempotency(self):
        """Verify running deployment multiple times does not corrupt files or duplicate state."""
        res1 = self.generator.generate_customer_project(self.spec, self.docs, self.chunks)
        res2 = self.generator.generate_customer_project(self.spec, self.docs, self.chunks)

        self.assertEqual(res1["chunks_indexed"], res2["chunks_indexed"])
        self.assertEqual(res1["documents_indexed"], res2["documents_indexed"])

        index_file = self.temp_dir / "data" / "index" / "knowledge_index.json"
        self.assertTrue(index_file.exists())
        data = json.loads(index_file.read_text(encoding="utf-8"))
        self.assertEqual(len(data["chunks"]), 1)

    def test_docker_compose_private_network_isolation(self):
        """Verify docker-compose.yml does NOT expose Qdrant to public internet (0.0.0.0)."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)
        dc_text = (self.temp_dir / "docker-compose.yml").read_text(encoding="utf-8")

        # Qdrant must be on rag_internal_network and expose 6333 internally, NOT ports: ["6333:6333"] or 0.0.0.0
        self.assertIn("rag_internal_network", dc_text)
        self.assertIn("expose:\n      - \"6333\"", dc_text)
        self.assertNotIn("0.0.0.0:6333", dc_text)
        self.assertNotIn("\"6333:6333\"", dc_text)

    def test_customer_health_verification(self):
        """Verify standalone src/health.py can run and detect healthy status."""
        self.generator.generate_customer_project(self.spec, self.docs, self.chunks)

        import sys
        src_path = str(self.temp_dir / "src")
        sys.path.insert(0, src_path)
        try:
            from health import run_health_verification
            report = run_health_verification()
            self.assertEqual(report["status"], "healthy")
            components = {c["component"] for c in report["checks"]}
            self.assertIn("vector_store", components)
            self.assertIn("llm_provider", components)
            self.assertIn("retrieval_smoke", components)
            self.assertIn("grounding_verifier", components)
        finally:
            if src_path in sys.path:
                sys.path.remove(src_path)

    def test_customer_readme_sections_order(self):
        """Verify customer README contains the required 15 sections in exact specified order."""
        self.packager.prepare_directories()
        readme = self.packager.generate_readme(
            spec=self.spec,
            architecture_summary="Turnkey customer RAG assistant",
            run_command="python3 src/app.py",
            knowledge_sources_summary=["compliance_policy.txt"],
            test_summary="1/1 Passed",
            verification_summary="1.00 Grounding",
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

        last_idx = -1
        for sec in required_sections:
            idx = readme.find(sec)
            self.assertNotEqual(idx, -1, f"Missing section '{sec}' in customer README")
            self.assertGreater(idx, last_idx, f"Section '{sec}' appears out of order in customer README")
            last_idx = idx


if __name__ == "__main__":
    unittest.main()
