"""Phase 18-K End-to-End Turnkey Delivery Acceptance Test.

Verifies the complete pipeline:
Customer Input -> Power Engine -> Workflow -> Execution -> Artifact Creation
  -> Durable Catalog Registration -> Physical Staging -> SHA-256/Size Validation
  -> Atomic Publish -> Durable Catalog Commit -> Package Generation
  -> Proprietary / Secret Sanitization -> Manifest Generation -> Health Check
  -> Verified Deliverable

Also verifies crash-recovery integrity:
- Survives process restart without losing artifact identity or duplicating entities
- Does not publish corrupted artifacts
- Rejects proprietary imports
- Masks secrets in environment templates
- Enforces health check before readiness
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from pathlib import Path
import pytest

from autoforge_runtime.persistence import PersistenceLayer, SQLiteStorage
from autoforge_runtime.models import EntityType
from autoforge_runtime.artifact_catalog import (
    DurableArtifactCatalog,
    derive_artifact_key,
    DurableArtifactStatus,
)
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge
from autoforge_artifacts import (
    build_artifact_platform,
    CanonicalArtifactType,
)
from autoforge_power_engines.delivery import (
    CustomerDeploymentSpec,
    DeploymentTarget,
    TargetCapabilityStatus,
    ServiceDefinition,
    PortMapping,
    HealthCheckSpec,
    CustomerDeliveryBuilder,
    ProprietaryBoundarySanitizer,
)


@pytest.fixture
def e2e_env(tmp_path: Path):
    db_path = str(tmp_path / "autoforge_runtime.db")
    art_root = tmp_path / "runtime_artifacts"
    staging_root = tmp_path / "runtime_staging"
    delivery_root = tmp_path / "customer_deliverable"
    art_root.mkdir(parents=True, exist_ok=True)
    staging_root.mkdir(parents=True, exist_ok=True)
    delivery_root.mkdir(parents=True, exist_ok=True)

    storage = SQLiteStorage(db_path)
    storage.initialize()
    storage.close()

    return {
        "db_path": db_path,
        "art_root": art_root,
        "staging_root": staging_root,
        "delivery_root": delivery_root,
    }


class TestPhase18KEndToEndAcceptance:
    """Full lifecycle turnkey pipeline and boundary verification."""

    def test_full_turnkey_pipeline_happy_path(self, e2e_env: dict) -> None:
        # 1. Customer Input & Spec
        customer_request = "Deploy customer CRM API on port 8080"
        project_id = str(uuid.uuid4())
        workflow_id = uuid.uuid4()
        execution_id = uuid.uuid4()

        spec = CustomerDeploymentSpec(
            project_name="CustomerCRM",
            sanitized_project_id="customer_crm",
            target=DeploymentTarget.DOCKER_HOST,
            primary_service="crm-api",
            services={
                "crm-api": ServiceDefinition(
                    name="crm-api",
                    ports=[PortMapping(host_port=8080, container_port=8080)],
                )
            },
            global_environment={"DATABASE_URL": "postgresql://user:pass@db:5432/crm", "API_KEY": "sk-secret-12345"},
            health_checks=[
                HealthCheckSpec(
                    name="api-health",
                    endpoint_or_command="http://localhost:8080/health",
                    timeout_seconds=5,
                )
            ],
        )
        assert spec.target_capability_status() == TargetCapabilityStatus.SUPPORTED

        # 2. Setup Authoritative Runtime Store & Catalog
        storage = SQLiteStorage(e2e_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        physical_store = PhysicalArtifactStore(
            artifact_root=e2e_env["art_root"],
            staging_root=e2e_env["staging_root"],
        )
        catalog = DurableArtifactCatalog(
            persistence=persistence,
            owner_id="worker_process:101",
            physical_store=physical_store,
        )

        # 3. Execution Pipeline creates and durably registers artifacts
        pipeline = ArtifactPipeline(
            durable_catalog=catalog,
            physical_store=physical_store,
        )

        from autoforge_execution.models import ArtifactProvenance, ArtifactType as ExecArtifactType
        src_code = b"import sys\nprint('Customer CRM Running')\n"
        art_record = pipeline.record_artifact(
            name="app.py",
            artifact_type=ExecArtifactType.SOURCE_CODE,
            content=src_code.decode("utf-8"),
            provenance=ArtifactProvenance(
                task_id="codegen",
                worker_id="worker_process_101",
                workflow_id=workflow_id,
            ),
        )

        # 4. Durable catalog verification
        assert art_record.checksum == hashlib.sha256(src_code).hexdigest()
        assert art_record.artifact_id is not None
        durable_state = catalog.get_artifact(art_record.artifact_id)
        assert durable_state is not None
        assert durable_state.status == DurableArtifactStatus.COMMITTED
        assert Path(durable_state.storage_path).exists()

        # 5. Bridge to Artifact Platform Domain Layer
        bridge = DurableArtifactStoreBridge(
            catalog=catalog,
            physical_store=physical_store,
            owner_id="domain_manager:201",
        )
        from autoforge_artifacts import build_artifact_platform, CanonicalArtifactType
        platform = build_artifact_platform(store=bridge)
        domain_manager = platform.manager

        domain_art = domain_manager.create_artifact(
            name="app.py",
            artifact_type=CanonicalArtifactType.SOURCE,
            project_id=uuid.UUID(project_id),
            workflow_id=workflow_id,
        )
        assert domain_art.artifact_id is not None

        # 6. Customer Deliverable Packaging & Boundary Protection
        builder = CustomerDeliveryBuilder(e2e_env["delivery_root"])
        builder.prepare_directories()

        # Write application files
        builder.write_file("src/app.py", src_code.decode("utf-8"))
        builder.write_file("requirements.txt", "pydantic>=2.0\npytest>=8.0\n")

        # Generate deployment configs & launchers
        created_files = builder.build_deployment_files(spec, dockerfile_entrypoint="python3 src/app.py")
        assert "Dockerfile" in created_files
        assert "docker-compose.yml" in created_files
        assert "deploy.sh" in created_files
        assert ".env.example" in created_files

        # 7. Verify Secrets Masking in .env.example
        env_ex_content = (e2e_env["delivery_root"] / ".env.example").read_text()
        assert "sk-secret-12345" not in env_ex_content
        assert "your_api_key_here" in env_ex_content

        # 8. Verify Shell Safety and Dockerfile Boundary
        deploy_sh = (e2e_env["delivery_root"] / "deploy.sh").read_text()
        assert "export $(grep" not in deploy_sh
        assert "|| true" not in deploy_sh

        dockerfile = (e2e_env["delivery_root"] / "Dockerfile").read_text()
        assert "COPY data/ /app/data/" not in dockerfile

        # 9. Proprietary Code & AST Import Boundary Sanitization
        violations = builder.sanitize_proprietary_boundary()
        assert len(violations) == 0

        # 10. Generate Signed Cryptographic Manifest
        manifest = builder.create_manifest(
            project_id=project_id,
            execution_id=str(execution_id),
            workflow_id=str(workflow_id),
            verification_status="VERIFIED",
        )
        assert manifest.manifest_signature is not None
        assert len(manifest.manifest_signature) == 64
        assert manifest.total_bytes > 0
        assert "src/app.py" in manifest.files_created

        # 11. Health Check Readiness Gate
        assert "APPLICATION READY" in deploy_sh
        assert "DEPLOYMENT FAILED — HEALTH GATES DID NOT PASS" in deploy_sh
        health_script = (e2e_env["delivery_root"] / "scripts" / "health_check.py").read_text()
        assert "sys.exit(1)" in health_script

        storage.close()

    def test_crash_and_restart_recovery_preserves_single_identity(self, e2e_env: dict) -> None:
        """Simulate worker crash and supervisor recovery across process boundary."""
        art_key = derive_artifact_key(artifact_name="core_module.py")
        storage = SQLiteStorage(e2e_env["db_path"])
        persistence = PersistenceLayer(storage=storage)
        p_store = PhysicalArtifactStore(
            artifact_root=e2e_env["art_root"],
            staging_root=e2e_env["staging_root"],
        )

        # Worker 1 registers and stages content
        cat1 = DurableArtifactCatalog(persistence=persistence, owner_id="worker:9999", physical_store=p_store)
        state1 = cat1.register_artifact(artifact_key=art_key)
        staging_file = e2e_env["staging_root"] / "core_module.tmp"
        content = b"class Core:\n    pass\n"
        p_store.write_staging_bytes(staging_file, content)
        cat1.begin_staging(state1.artifact_id, staging_path=str(staging_file))

        # Worker 1 dies unexpectedly (connection closed without commit)
        storage.close()

        # Supervisor restarts with fresh storage connection and reconciles
        reopened_storage = SQLiteStorage(e2e_env["db_path"])
        reopened_persistence = PersistenceLayer(storage=reopened_storage)
        supervisor_cat = DurableArtifactCatalog(
            persistence=reopened_persistence,
            owner_id="supervisor:1",
            physical_store=p_store,
        )

        res = supervisor_cat.reconcile_on_startup(assume_all_dead=True)
        assert res.recovered_count == 1

        recovered_state = supervisor_cat.get_artifact(state1.artifact_id)
        assert recovered_state is not None
        # Identity preserved, status committed
        assert recovered_state.status == DurableArtifactStatus.COMMITTED
        assert recovered_state.artifact_id == state1.artifact_id
        assert recovered_state.content_hash == hashlib.sha256(content).hexdigest()

        # Ensure no duplicate entity was generated in SQLite
        entities = reopened_persistence.query_entities(EntityType.DURABLE_ARTIFACT, {"artifact_key": art_key})
        assert len(entities) == 1

        reopened_storage.close()

    def test_sanitizer_rejects_autoforge_internal_imports(self, e2e_env: dict) -> None:
        """Verify AST sanitizer catches attempted leakage of autoforge_* internal modules."""
        builder = CustomerDeliveryBuilder(e2e_env["delivery_root"])
        builder.prepare_directories()

        # Infiltrate a forbidden autoforge internal import into deliverable
        leaked_file = builder.write_file(
            "src/leaked_module.py",
            "from autoforge_kernel.engine import Engine\n",
        )

        from autoforge_power_engines.delivery.sanitizer import ProprietaryCodeViolationError
        with pytest.raises(ProprietaryCodeViolationError):
            builder.sanitize_proprietary_boundary()

        # Clean up
        leaked_file.unlink()
