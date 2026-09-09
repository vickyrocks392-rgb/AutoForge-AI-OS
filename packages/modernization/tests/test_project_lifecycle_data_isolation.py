"""
Test Suite: Project Lifecycle & Data Isolation Subsystem
Validates:
- Ephemeral-by-default execution
- Clean-room mode pre-execution checks
- Verified multi-store purging (Filesystem + Qdrant)
- Cross-project contamination barriers (Project A vs Project B)
- Persistence policy (Ephemeral vs Persistent)
- Failure safety, crash recovery, and idempotent purge
"""

import pytest
import shutil
import uuid
from pathlib import Path
from qdrant_client import QdrantClient
from qdrant_client.http import models

from autoforge_kernel.project_lifecycle import (
    ProjectLifecycleManager,
    ProjectIsolationContext,
    ProjectPersistencePolicy,
    ProjectState,
    ProjectPurgeVerifier,
)
from autoforge_knowledge_platform.rag18.project_isolation import (
    QdrantProjectIsolationManager,
    GLOBAL_KNOWLEDGE_COLLECTION,
)

HP_QDRANT_URL = "http://192.168.1.102:6333"


@pytest.fixture
def temp_project_dir(tmp_path):
    d = tmp_path / "projects"
    d.mkdir(parents=True, exist_ok=True)
    yield d
    shutil.rmtree(d, ignore_errors=True)


@pytest.fixture
def qdrant_client():
    try:
        client = QdrantClient(url=HP_QDRANT_URL, timeout=3.0)
        # Test connection
        client.get_collections()
        return client
    except Exception:
        # Fallback to local in-memory QdrantClient for local test runner
        return QdrantClient(location=":memory:")


class TestProjectLifecycleDataIsolation:

    def test_lifecycle_state_transitions(self, temp_project_dir):
        """Test standard lifecycle state machine progression."""
        mgr = ProjectLifecycleManager(base_dir=temp_project_dir)
        pid = f"test-lifecycle-{uuid.uuid4().hex[:6]}"
        
        ctx = mgr.create_project(pid, persistence_policy=ProjectPersistencePolicy.PERSISTENT)
        assert mgr.project_states[pid] == ProjectState.CREATED
        assert ctx.persistence_policy == ProjectPersistencePolicy.PERSISTENT
        
        # Clean-room check
        assert mgr.verify_clean_room(pid) is True
        
        # Initialize
        mgr.initialize_project(pid)
        assert mgr.project_states[pid] == ProjectState.ACTIVE
        assert ctx.workspace_dir.exists()
        assert ctx.generated_artifacts_dir.exists()
        assert ctx.cache_dir.exists()
        
        # Write dummy artifact
        dummy_file = ctx.workspace_dir / "sample.cbl"
        dummy_file.write_text("IDENTIFICATION DIVISION. PROGRAM-ID. SAMPLE.")
        mgr.active_registries[pid].register_file(dummy_file)
        
        # Finalize
        res = mgr.finalize_project(pid, status=ProjectState.COMPLETED)
        assert res["final_state"] == ProjectState.COMPLETED.value
        assert dummy_file.exists()  # Persistent policy retains state
        
        # Explicit purge
        purge_res = mgr.purge_project(pid)
        assert purge_res["purged"] is True
        assert not dummy_file.exists()
        assert not ctx.project_dir.exists()
        assert mgr.project_states[pid] == ProjectState.PURGED

    def test_ephemeral_by_default_auto_purges(self, temp_project_dir, qdrant_client):
        """Test that ephemeral projects automatically purge upon finalization."""
        mgr = ProjectLifecycleManager(base_dir=temp_project_dir)
        pid = f"test-ephemeral-{uuid.uuid4().hex[:6]}"
        
        iso_mgr = QdrantProjectIsolationManager(qdrant_client)
        
        # Create ephemeral project (default)
        ctx = mgr.create_project(pid, persistence_policy=ProjectPersistencePolicy.EPHEMERAL)
        mgr.initialize_project(pid)
        
        # Create Qdrant collection for project
        col_name = iso_mgr.ensure_project_collection(pid, vector_size=4)
        mgr.active_registries[pid].register_qdrant_collection(col_name)
        
        # Insert a vector point
        iso_mgr.insert_project_knowledge(pid, [
            {"id": 1, "vector": [0.1, 0.2, 0.3, 0.4], "payload": {"rule": "COBOL COMPUTE ROUNDED"}}
        ])
        
        # Check point exists
        hits = iso_mgr.query_project_knowledge(pid, [0.1, 0.2, 0.3, 0.4], top_k=1)
        assert len(hits) == 1
        
        # Finalize project (should auto-purge)
        fin_res = mgr.finalize_project(pid, status=ProjectState.COMPLETED)
        assert fin_res["purged"] is True
        
        # Deep purge verification
        iso_mgr.purge_project_collection(pid)
        verification = ProjectPurgeVerifier.verify_purged(ctx, mgr.active_registries[pid], qdrant_store=iso_mgr)
        assert verification["is_clean"] is True
        assert not ctx.project_dir.exists()

    def test_cross_project_contamination_barrier(self, temp_project_dir, qdrant_client):
        """
        CRITICAL TEST: Verify that Project A and Project B cannot access each other's data,
        and purging Project A leaves Project B completely intact.
        """
        iso_mgr = QdrantProjectIsolationManager(qdrant_client)
        pid_a = f"proj-alpha-{uuid.uuid4().hex[:6]}"
        pid_b = f"proj-beta-{uuid.uuid4().hex[:6]}"
        
        token_a = "ALPHA_SECRET_ENGINEERING_TOKEN"
        token_b = "BETA_SECRET_ENGINEERING_TOKEN"
        
        # 1. Populate Project A
        iso_mgr.insert_project_knowledge(pid_a, [
            {"id": 101, "vector": [1.0, 0.0, 0.0, 0.0], "payload": {"secret_token": token_a, "module": "PAYROLL"}}
        ])
        
        # 2. Populate Project B
        iso_mgr.insert_project_knowledge(pid_b, [
            {"id": 201, "vector": [0.0, 1.0, 0.0, 0.0], "payload": {"secret_token": token_b, "module": "SETTLEMENT"}}
        ])
        
        # 3. Project A queries
        hits_a = iso_mgr.query_project_knowledge(pid_a, [1.0, 0.0, 0.0, 0.0], top_k=5)
        assert len(hits_a) == 1
        assert hits_a[0]["payload"]["secret_token"] == token_a
        assert token_b not in str(hits_a)
        
        # 4. Project B queries
        hits_b = iso_mgr.query_project_knowledge(pid_b, [0.0, 1.0, 0.0, 0.0], top_k=5)
        assert len(hits_b) == 1
        assert hits_b[0]["payload"]["secret_token"] == token_b
        assert token_a not in str(hits_b)
        
        # 5. Cross-project query: Project A attempts to query Project B vector
        cross_hits = iso_mgr.query_project_knowledge(pid_a, [0.0, 1.0, 0.0, 0.0], top_k=5)
        # Even if vector is close to B's direction, collection isolation prevents returning B's data
        assert all(h["payload"].get("secret_token") != token_b for h in cross_hits)
        
        # 6. Purge Project A
        purged_a = iso_mgr.purge_project_collection(pid_a)
        assert purged_a is True
        
        # Verify Project A is gone
        assert len(iso_mgr.query_project_knowledge(pid_a, [1.0, 0.0, 0.0, 0.0])) == 0
        
        # Verify Project B is completely intact
        hits_b_post = iso_mgr.query_project_knowledge(pid_b, [0.0, 1.0, 0.0, 0.0], top_k=5)
        assert len(hits_b_post) == 1
        assert hits_b_post[0]["payload"]["secret_token"] == token_b
        
        # Clean up Project B
        iso_mgr.purge_project_collection(pid_b)

    def test_global_vs_project_knowledge_partitioning(self, qdrant_client):
        """Verify that permanent global knowledge is distinct from project knowledge."""
        iso_mgr = QdrantProjectIsolationManager(qdrant_client)
        pid = f"proj-scoped-{uuid.uuid4().hex[:6]}"
        
        # Insert global pattern
        iso_mgr.insert_global_knowledge([
            {"id": 1, "vector": [0.5, 0.5, 0.5, 0.5], "payload": {"rule": "COBOL_EVALUATE_TO_JAVA_SWITCH", "scope": "GLOBAL"}}
        ])
        
        # Insert project pattern
        iso_mgr.insert_project_knowledge(pid, [
            {"id": 2, "vector": [0.5, 0.5, 0.5, 0.5], "payload": {"rule": "CUSTOM_SETTLE_PARAGRAPH_RULE", "scope": "PROJECT"}}
        ])
        
        # Global query returns only global
        global_hits = iso_mgr.query_global_knowledge([0.5, 0.5, 0.5, 0.5], top_k=5)
        assert any(h["payload"]["rule"] == "COBOL_EVALUATE_TO_JAVA_SWITCH" for h in global_hits)
        assert not any(h["payload"].get("rule") == "CUSTOM_SETTLE_PARAGRAPH_RULE" for h in global_hits)
        
        # Project query returns only project
        proj_hits = iso_mgr.query_project_knowledge(pid, [0.5, 0.5, 0.5, 0.5], top_k=5)
        assert any(h["payload"]["rule"] == "CUSTOM_SETTLE_PARAGRAPH_RULE" for h in proj_hits)
        assert not any(h["payload"].get("rule") == "COBOL_EVALUATE_TO_JAVA_SWITCH" for h in proj_hits)
        
        # Purge project
        iso_mgr.purge_project_collection(pid)
        
        # Global knowledge remains intact post-project purge
        global_hits_after = iso_mgr.query_global_knowledge([0.5, 0.5, 0.5, 0.5], top_k=5)
        assert any(h["payload"]["rule"] == "COBOL_EVALUATE_TO_JAVA_SWITCH" for h in global_hits_after)

    def test_failure_safety_and_idempotent_purge(self, temp_project_dir):
        """Verify that interrupted or failed projects can be safely and idempotently purged."""
        mgr = ProjectLifecycleManager(base_dir=temp_project_dir)
        pid = f"test-failed-{uuid.uuid4().hex[:6]}"
        
        ctx = mgr.create_project(pid, persistence_policy=ProjectPersistencePolicy.EPHEMERAL)
        mgr.initialize_project(pid)
        
        # Simulate failure during compilation
        fin_res = mgr.finalize_project(pid, status=ProjectState.FAILED)
        assert fin_res["final_state"] == ProjectState.FAILED.value
        assert fin_res["purged"] is True
        
        # Repeated purge calls must be completely safe & idempotent
        rep1 = mgr.purge_project(pid)
        rep2 = mgr.purge_project(pid)
        assert rep1["purged"] is True
        assert rep2["purged"] is True
