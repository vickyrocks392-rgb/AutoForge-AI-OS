"""Behavioral tests for the Artifact Platform — Phase 12.

Covers all required verification paths in the implementation plan.
"""

from __future__ import annotations

import uuid
import pytest
from datetime import datetime, timezone

from autoforge_artifacts import (
    build_artifact_platform,
    CanonicalArtifactType,
    ArtifactState,
    ArtifactValidationError,
    ArtifactNotFoundError,
    ArtifactConflictError,
    ArtifactIntegrityError,
    ArtifactAuthorizationError,
    ArtifactRollbackError,
)
from autoforge_artifacts.models import (
    ArtifactLineageEntry,
    compute_content_hash,
)
from autoforge_artifacts.provenance import (
    build_provenance,
    from_execution_provenance,
)
from autoforge_artifacts.policies import (
    ArtifactPolicy,
    PublicationPolicy,
    RollbackPolicy,
)


class MockEventSink:
    """Mock event sink to verify event emission and correlation propagation."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


# Helper to create dummy class simulating Phase 10 ArtifactProvenance
class DummyPhase10Provenance:
    def __init__(self, task_id, worker_id, workflow_id, correlation_id, attempt_number=1, iteration=1, metadata=None):
        self.task_id = task_id
        self.worker_id = worker_id
        self.workflow_id = workflow_id
        self.correlation_id = correlation_id
        self.attempt_number = attempt_number
        self.iteration = iteration
        self.metadata = metadata or {}


def test_artifact_creation_and_identity():
    """Verify artifact creation and stable identity properties."""
    platform = build_artifact_platform()
    manager = platform.manager

    # Successful creation
    artifact = manager.create_artifact(
        name="test-artifact",
        artifact_type=CanonicalArtifactType.SOURCE,
        project_id=uuid.uuid4(),
    )
    assert artifact.name == "test-artifact"
    assert artifact.artifact_type == CanonicalArtifactType.SOURCE
    assert artifact.state == ArtifactState.CREATED
    assert isinstance(artifact.artifact_id, uuid.UUID)

    # Rejection of empty/whitespace name
    with pytest.raises(ArtifactValidationError):
        manager.create_artifact(name="", artifact_type=CanonicalArtifactType.SOURCE)
    
    with pytest.raises(ArtifactValidationError):
        manager.create_artifact(name="   ", artifact_type=CanonicalArtifactType.SOURCE)


def test_content_hashing_deterministic():
    """Verify that content hashing is SHA-256 and fully deterministic."""
    content1 = "hello world"
    content2 = "hello world"
    content3 = "hello world updated"

    hash1 = compute_content_hash(content1)
    hash2 = compute_content_hash(content2)
    hash3 = compute_content_hash(content3)

    assert hash1 == hash2
    assert hash1 != hash3
    # Check it's a valid hex SHA-256 hash (64 chars)
    assert len(hash1) == 64
    assert all(c in "0123456789abcdef" for c in hash1)


def test_version_creation_and_immutability():
    """Verify version creation, incrementing numbers, and immutability."""
    platform = build_artifact_platform()
    manager = platform.manager

    artifact = manager.create_artifact(
        name="app.py",
        artifact_type=CanonicalArtifactType.SOURCE,
    )

    # v1 creation
    v1 = manager.create_version(artifact.artifact_id, "print('hello v1')")
    assert v1.version_number == 1
    assert v1.content == "print('hello v1')"
    assert v1.parent_version_id is None

    # v2 creation
    v2 = manager.create_version(artifact.artifact_id, "print('hello v2')")
    assert v2.version_number == 2
    assert v2.content == "print('hello v2')"
    assert v2.parent_version_id == v1.version_id

    # Verify latest
    latest = manager.get_latest_version(artifact.artifact_id)
    assert latest.version_id == v2.version_id

    # Verify version count on artifact object
    retrieved = manager.get_artifact(artifact.artifact_id)
    assert retrieved.version_count == 2
    assert retrieved.current_version_id == v2.version_id
    assert retrieved.state == ArtifactState.VERSIONED


def test_version_history_and_parent_chain():
    """Verify full version history listing and parent chain traversal."""
    platform = build_artifact_platform()
    manager = platform.manager

    artifact = manager.create_artifact(
        name="document.md",
        artifact_type=CanonicalArtifactType.DOCUMENTATION,
    )

    v1 = manager.create_version(artifact.artifact_id, "v1 content")
    v2 = manager.create_version(artifact.artifact_id, "v2 content")
    v3 = manager.create_version(artifact.artifact_id, "v3 content")

    history = manager.list_versions(artifact.artifact_id)
    assert len(history) == 3
    assert [v.version_number for v in history] == [1, 2, 3]

    # Get parent chain of v3
    chain = manager.get_parent_chain(artifact.artifact_id, v3.version_id)
    assert len(chain) == 3
    assert chain[0].version_id == v1.version_id
    assert chain[1].version_id == v2.version_id
    assert chain[2].version_id == v3.version_id


def test_lineage_recording_and_traversal():
    """Verify lineage edge registration and BFS traversal (ancestors & descendants)."""
    platform = build_artifact_platform()
    manager = platform.manager

    # Setup parent-child chain
    # research -> architecture -> spec -> source_code -> build_output
    research = manager.create_artifact("Research Doc", CanonicalArtifactType.RESEARCH)
    arch = manager.create_artifact("Arch Doc", CanonicalArtifactType.ARCHITECTURE)
    spec = manager.create_artifact("Spec Doc", CanonicalArtifactType.PLAN)
    src = manager.create_artifact("src/main.py", CanonicalArtifactType.SOURCE)
    build = manager.create_artifact("main.bin", CanonicalArtifactType.BUILD_OUTPUT)

    # Connect them via lineage
    manager.record_lineage(ArtifactLineageEntry(parent_artifact_id=research.artifact_id, child_artifact_id=arch.artifact_id))
    manager.record_lineage(ArtifactLineageEntry(parent_artifact_id=arch.artifact_id, child_artifact_id=spec.artifact_id))
    manager.record_lineage(ArtifactLineageEntry(parent_artifact_id=spec.artifact_id, child_artifact_id=src.artifact_id))
    manager.record_lineage(ArtifactLineageEntry(parent_artifact_id=src.artifact_id, child_artifact_id=build.artifact_id))

    # Test direct parents and children
    assert len(manager.get_lineage_parents(arch.artifact_id)) == 1
    assert manager.get_lineage_parents(arch.artifact_id)[0].parent_artifact_id == research.artifact_id

    assert len(manager.get_lineage_children(spec.artifact_id)) == 1
    assert manager.get_lineage_children(spec.artifact_id)[0].child_artifact_id == src.artifact_id

    # Test ancestors of build (BFS traversal)
    ancestors = manager.get_ancestors(build.artifact_id)
    # BFS path starting from build: parents are src, parents of src is spec, parent of spec is arch, parent of arch is research
    ancestor_ids = [e.parent_artifact_id for e in ancestors]
    assert src.artifact_id in ancestor_ids
    assert spec.artifact_id in ancestor_ids
    assert arch.artifact_id in ancestor_ids
    assert research.artifact_id in ancestor_ids

    # Test descendants of research
    descendants = manager.get_descendants(research.artifact_id)
    descendant_ids = [e.child_artifact_id for e in descendants]
    assert arch.artifact_id in descendant_ids
    assert spec.artifact_id in descendant_ids
    assert src.artifact_id in descendant_ids
    assert build.artifact_id in descendant_ids


def test_provenance_assembly_and_compatibility():
    """Verify provenance builder, Phase 10 adapter, and key scrubbing (no secrets)."""
    # 1. Provenance builder and secret scrubbing
    prov = build_provenance(
        task_id="task-123",
        actor="worker-agent",
        metadata={
            "api_key": "secret-token-123",
            "password": "my-password",
            "non-secret-key": "public-val",
        }
    )
    assert prov.task_id == "task-123"
    assert prov.actor == "worker-agent"
    # Secrets should be removed
    assert "api_key" not in prov.metadata
    assert "password" not in prov.metadata
    assert prov.metadata["non-secret-key"] == "public-val"

    # 2. Phase 10 adapter test
    phase10_prov = DummyPhase10Provenance(
        task_id="task-p10",
        worker_id="worker-p10",
        workflow_id=uuid.uuid4(),
        correlation_id=uuid.uuid4(),
        metadata={"token": "some-secret", "key": "value"}
    )
    adapted = from_execution_provenance(phase10_prov)
    assert adapted.task_id == "task-p10"
    assert adapted.worker_id == "worker-p10"
    assert adapted.workflow_id == phase10_prov.workflow_id
    assert adapted.correlation_id == phase10_prov.correlation_id
    assert "token" not in adapted.metadata
    assert adapted.metadata["key"] == "value"


def test_publishing_gated_by_hitl():
    """Verify explicit publishing and HITL gating rules."""
    policy = ArtifactPolicy(
        publication=PublicationPolicy(
            hitl_required_types=frozenset({CanonicalArtifactType.DEPLOYMENT}),
            hitl_required_destinations=frozenset({"production"})
        )
    )
    sink = MockEventSink()
    platform = build_artifact_platform(policy=policy, event_sink=sink)
    manager = platform.manager

    # Create artifacts
    doc = manager.create_artifact("doc", CanonicalArtifactType.DOCUMENTATION)
    v_doc = manager.create_version(doc.artifact_id, "doc content")

    deploy = manager.create_artifact("deploy", CanonicalArtifactType.DEPLOYMENT)
    v_deploy = manager.create_version(deploy.artifact_id, "deploy content")

    # 1. Publish doc to staging: no HITL required, should succeed
    pub1 = manager.publish(doc.artifact_id, v_doc.version_id, destination="staging")
    assert pub1.destination == "staging"
    assert not pub1.requires_hitl
    assert pub1.approved_by is None

    # Verify state transitioned to PUBLISHED
    assert manager.get_artifact(doc.artifact_id).state == ArtifactState.PUBLISHED

    # 2. Publish deploy to staging: Deployment type requires HITL
    with pytest.raises(ArtifactAuthorizationError):
        manager.publish(deploy.artifact_id, v_deploy.version_id, destination="staging", hitl_approved=False)

    # With HITL approval: should succeed
    pub2 = manager.publish(
        deploy.artifact_id, v_deploy.version_id, destination="staging",
        hitl_approved=True, approved_by="admin-user"
    )
    assert pub2.requires_hitl
    assert pub2.approved_by == "admin-user"

    # 3. Publish doc to production: Destination requires HITL
    with pytest.raises(ArtifactAuthorizationError):
        manager.publish(doc.artifact_id, v_doc.version_id, destination="production", hitl_approved=False)

    # With HITL approval: should succeed
    pub3 = manager.publish(
        doc.artifact_id, v_doc.version_id, destination="production",
        hitl_approved=True, approved_by="operator"
    )
    assert pub3.requires_hitl
    assert pub3.approved_by == "operator"


def test_rollback_history_preserving():
    """Verify history-preserving rollback: target validation, integrity check, new version creation."""
    policy = ArtifactPolicy(
        rollback=RollbackPolicy(
            hitl_required_for_published=True,
            hitl_required_types=frozenset({CanonicalArtifactType.DEPLOYMENT})
        )
    )
    platform = build_artifact_platform(policy=policy)
    manager = platform.manager

    artifact = manager.create_artifact("main.py", CanonicalArtifactType.SOURCE)
    v1 = manager.create_version(artifact.artifact_id, "content v1")
    v2 = manager.create_version(artifact.artifact_id, "content v2")
    v3 = manager.create_version(artifact.artifact_id, "content v3")

    # 1. Rollback v3 to v1. Current state is VERSIONED, not PUBLISHED yet, so no HITL required.
    rb = manager.rollback(
        artifact.artifact_id, v1.version_id, actor="developer", reason="v3 is buggy"
    )
    assert rb.from_version_id == v3.version_id
    assert rb.to_version_id == v1.version_id
    assert isinstance(rb.new_version_id, uuid.UUID)

    # Verify history is preserved by checking v4 content and parenthood
    v4 = manager.get_latest_version(artifact.artifact_id)
    assert v4.version_number == 4
    assert v4.content == "content v1"
    assert v4.parent_version_id == v3.version_id
    assert v4.is_rollback
    assert v4.rollback_source_version_id == v1.version_id

    # 2. Rollback validation: target version belongs to another artifact
    artifact2 = manager.create_artifact("other.py", CanonicalArtifactType.SOURCE)
    v_other = manager.create_version(artifact2.artifact_id, "other content")
    with pytest.raises(ArtifactNotFoundError):
        manager.rollback(artifact.artifact_id, uuid.uuid4())
    
    with pytest.raises(ArtifactRollbackError):
        manager.rollback(artifact.artifact_id, v_other.version_id)

    # 3. Rollback target validation: integrity corruption
    # Manually corrupt the content in the store to trigger integrity error
    v1_stored = platform.store.get_version(artifact.artifact_id, v1.version_id)
    # We must violate type validation or use a custom dict manipulation on internal store since the model is frozen,
    # but the LocalArtifactStore internally holds the object. We can replace it in the store:
    corrupted_v1 = v1_stored.model_copy(update={"content": "corrupted content"})
    # Put it back to trigger integrity check failure
    platform.store._version_index[v1.version_id] = corrupted_v1
    
    with pytest.raises(ArtifactIntegrityError):
        manager.rollback(artifact.artifact_id, v1.version_id)


def test_rollback_gated_by_hitl():
    """Verify HITL gating for rollbacks on published artifacts or specific types."""
    policy = ArtifactPolicy(
        rollback=RollbackPolicy(
            hitl_required_for_published=True,
            hitl_required_types=frozenset({CanonicalArtifactType.DEPLOYMENT})
        )
    )
    platform = build_artifact_platform(policy=policy)
    manager = platform.manager

    # 1. Published source artifact rollback requires HITL
    artifact = manager.create_artifact("published.py", CanonicalArtifactType.SOURCE)
    v1 = manager.create_version(artifact.artifact_id, "v1")
    v2 = manager.create_version(artifact.artifact_id, "v2")
    
    # Mark as published
    manager.publish(artifact.artifact_id, v2.version_id)
    assert manager.get_artifact(artifact.artifact_id).state == ArtifactState.PUBLISHED

    with pytest.raises(ArtifactAuthorizationError):
        manager.rollback(artifact.artifact_id, v1.version_id, hitl_approved=False)

    # Rollback succeeds with approval
    rb1 = manager.rollback(artifact.artifact_id, v1.version_id, hitl_approved=True)
    assert rb1.to_version_id == v1.version_id

    # 2. Deployment artifact rollback always requires HITL (even if not published)
    deploy = manager.create_artifact("deploy-config", CanonicalArtifactType.DEPLOYMENT)
    vd1 = manager.create_version(deploy.artifact_id, "vd1")
    vd2 = manager.create_version(deploy.artifact_id, "vd2")

    with pytest.raises(ArtifactAuthorizationError):
        manager.rollback(deploy.artifact_id, vd1.version_id, hitl_approved=False)

    rb2 = manager.rollback(deploy.artifact_id, vd1.version_id, hitl_approved=True)
    assert rb2.to_version_id == vd1.version_id


def test_integrity_verification():
    """Verify store integrity verification logic on hash mismatch."""
    platform = build_artifact_platform()
    manager = platform.manager

    artifact = manager.create_artifact("file.txt", CanonicalArtifactType.OTHER)
    version = manager.create_version(artifact.artifact_id, "clean content")

    # True initially
    assert manager.verify_integrity(artifact.artifact_id, version.version_id)

    # Corrupt content
    corrupted = version.model_copy(update={"content": "dirty content"})
    platform.store._version_index[version.version_id] = corrupted

    # Integrity verification returns False
    assert not manager.verify_integrity(artifact.artifact_id, version.version_id)


def test_concurrent_version_conflict_detection():
    """Verify concurrent version conflict detection prevents lost updates."""
    platform = build_artifact_platform()
    manager = platform.manager

    artifact = manager.create_artifact("shared.py", CanonicalArtifactType.SOURCE)
    v1 = manager.create_version(artifact.artifact_id, "v1")

    # Manually try to store another version with the same version number
    from autoforge_artifacts.models import ArtifactVersion
    duplicate_v2 = ArtifactVersion.create(
        artifact_id=artifact.artifact_id,
        version_number=1,
        content="duplicate v1 content",
    )

    with pytest.raises(ArtifactConflictError):
        platform.store.store_version(duplicate_v2)


def test_path_traversal_protection():
    """Verify absolute paths and parent directory relative paths are rejected."""
    platform = build_artifact_platform()
    manager = platform.manager

    # Rejection of absolute path
    with pytest.raises(ArtifactValidationError) as exc:
        manager.create_artifact("test", CanonicalArtifactType.SOURCE, path="/etc/passwd")
    assert "Absolute paths are not allowed" in str(exc.value)

    # Rejection of directory traversal path
    with pytest.raises(ArtifactValidationError) as exc:
        manager.create_artifact("test", CanonicalArtifactType.SOURCE, path="src/../../passwd")
    assert "Path traversal detected" in str(exc.value)

    # Accepted relative path
    a = manager.create_artifact("test", CanonicalArtifactType.SOURCE, path="src/app.py")
    assert a.path == "src/app.py"


def test_event_emission_and_correlation():
    """Verify that event sink receives correct events with correct correlation_id."""
    sink = MockEventSink()
    platform = build_artifact_platform(event_sink=sink)
    manager = platform.manager
    corr_id = uuid.uuid4()

    # 1. Create artifact triggers ARTIFACT_CREATED
    a = manager.create_artifact(
        "script.py", CanonicalArtifactType.SOURCE, correlation_id=corr_id
    )
    assert len(sink.events) == 1
    event1 = sink.events[-1]
    assert event1.event_type.value == "artifact.created"
    assert event1.aggregate_id == a.artifact_id
    assert event1.correlation_id == corr_id

    # 2. Create version triggers ARTIFACT_UPDATED
    prov = build_provenance(correlation_id=corr_id)
    v = manager.create_version(a.artifact_id, "print(1)", provenance=prov)
    assert len(sink.events) == 2
    event2 = sink.events[-1]
    assert event2.event_type.value == "artifact.updated"
    assert event2.aggregate_id == a.artifact_id
    assert event2.correlation_id == corr_id
    assert "version" in event2.updated_fields
    assert event2.new_content_hash == v.content_hash

    # 3. Publish triggers ARTIFACT_UPDATED
    manager.publish(a.artifact_id, v.version_id, correlation_id=corr_id)
    assert len(sink.events) == 3
    event3 = sink.events[-1]
    assert event3.event_type.value == "artifact.updated"
    assert event3.aggregate_id == a.artifact_id
    assert event3.correlation_id == corr_id
    assert "state" in event3.updated_fields
    assert event3.new_values["state"] == "published"

    # 4. Rollback triggers ARTIFACT_UPDATED
    manager.rollback(a.artifact_id, v.version_id, correlation_id=corr_id, hitl_approved=True)
    assert len(sink.events) == 4
    event4 = sink.events[-1]
    assert event4.event_type.value == "artifact.updated"
    assert event4.aggregate_id == a.artifact_id
    assert event4.correlation_id == corr_id
    assert "rollback" in event4.updated_fields
