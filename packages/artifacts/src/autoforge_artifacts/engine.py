"""Artifact Manager — central facade for the Artifact Platform — Phase 12.

Composes all artifact subsystems (store, versioning, lineage, publishing,
rollback, events) into a single operational facade.

Design rules
------------
- Single entry point for all artifact operations.
- Dependencies are injectable (no global singletons).
- Clear construction boundary via ``build_artifact_platform()``.
- No business logic — pure composition and delegation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from autoforge_artifacts.errors import (
    ArtifactNotFoundError,
    ArtifactValidationError,
)
from autoforge_artifacts.events import ArtifactEventSinkProtocol, ArtifactEvents
from autoforge_artifacts.lineage import LineageService
from autoforge_artifacts.models import (
    Artifact,
    ArtifactLineageEntry,
    ArtifactState,
    ArtifactVersion,
    CanonicalArtifactType,
    CanonicalProvenance,
    PublicationRecord,
    RollbackRecord,
)
from autoforge_artifacts.policies import ArtifactPolicy
from autoforge_artifacts.publishing import PublishingService
from autoforge_artifacts.rollback import RollbackService
from autoforge_artifacts.store import ArtifactStoreProtocol, LocalArtifactStore
from autoforge_artifacts.versioning import VersioningService


class ArtifactManager:
    """Central facade for all Artifact Platform operations.

    This is the single entry point for creating, versioning, publishing,
    rolling back, and tracing artifacts.
    """

    def __init__(
        self,
        store: ArtifactStoreProtocol,
        versioning: VersioningService,
        lineage: LineageService,
        publishing: PublishingService,
        rollback: RollbackService,
        events: ArtifactEvents,
    ) -> None:
        self._store = store
        self._versioning = versioning
        self._lineage = lineage
        self._publishing = publishing
        self._rollback = rollback
        self._events = events

    # ── Artifact CRUD ──────────────────────────────────────────────────

    def create_artifact(
        self,
        name: str,
        artifact_type: CanonicalArtifactType,
        *,
        project_id: uuid.UUID | None = None,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        created_by: str | None = None,
        path: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> Artifact:
        """Create and register a new artifact."""
        if not name or not name.strip():
            raise ArtifactValidationError("Artifact name must not be empty")

        # Path traversal protection.
        if path is not None:
            _validate_path(path)

        artifact = Artifact(
            name=name,
            artifact_type=artifact_type,
            project_id=project_id,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            created_by=created_by,
            path=path,
            metadata=metadata or {},
        )
        created = self._store.create(artifact)

        self._events.emit_artifact_created(
            artifact_id=created.artifact_id,
            artifact_name=created.name,
            artifact_type=created.artifact_type.value,
            project_id=project_id,
            correlation_id=correlation_id,
        )
        return created

    def get_artifact(self, artifact_id: uuid.UUID) -> Artifact | None:
        """Retrieve an artifact by ID."""
        return self._store.get(artifact_id)

    def list_artifacts(
        self, project_id: uuid.UUID | None = None
    ) -> list[Artifact]:
        """List artifacts, optionally filtered by project."""
        return self._store.list_artifacts(project_id)

    # ── Versioning ─────────────────────────────────────────────────────

    def create_version(
        self,
        artifact_id: uuid.UUID,
        content: str,
        *,
        provenance: CanonicalProvenance | None = None,
        created_by: str | None = None,
    ) -> ArtifactVersion:
        """Create a new immutable version of an artifact."""
        version = self._versioning.create_version(
            artifact_id,
            content,
            provenance=provenance,
            created_by=created_by,
        )

        artifact = self._store.get(artifact_id)
        self._events.emit_artifact_versioned(
            artifact_id=artifact_id,
            version_id=version.version_id,
            version_number=version.version_number,
            project_id=artifact.project_id if artifact else None,
            content_hash=version.content_hash,
            correlation_id=provenance.correlation_id if provenance else None,
        )
        return version

    def get_version(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> ArtifactVersion | None:
        """Get a specific version."""
        return self._versioning.get_version(artifact_id, version_id)

    def list_versions(self, artifact_id: uuid.UUID) -> list[ArtifactVersion]:
        """List all versions, ordered by version_number."""
        return self._versioning.get_history(artifact_id)

    def get_latest_version(
        self, artifact_id: uuid.UUID
    ) -> ArtifactVersion | None:
        """Get the latest version."""
        return self._versioning.get_latest(artifact_id)

    def get_parent_chain(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> list[ArtifactVersion]:
        """Get the parent chain from a version back to v1."""
        return self._versioning.get_parent_chain(artifact_id, version_id)

    # ── Integrity ──────────────────────────────────────────────────────

    def verify_integrity(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> bool:
        """Verify content integrity of a specific version."""
        return self._store.verify_integrity(artifact_id, version_id)

    # ── Lineage ────────────────────────────────────────────────────────

    def record_lineage(self, entry: ArtifactLineageEntry) -> None:
        """Record a derivation relationship between artifacts."""
        self._lineage.record_lineage(entry)

    def get_lineage_parents(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get direct parents."""
        return self._lineage.get_parents(artifact_id)

    def get_lineage_children(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get direct children."""
        return self._lineage.get_children(artifact_id)

    def get_ancestors(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get all ancestors (transitive)."""
        return self._lineage.get_ancestors(artifact_id)

    def get_descendants(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get all descendants (transitive)."""
        return self._lineage.get_descendants(artifact_id)

    def get_full_lineage(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get the full lineage chain."""
        return self._lineage.get_lineage_chain(artifact_id)

    # ── Publishing ─────────────────────────────────────────────────────

    def publish(
        self,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        *,
        actor: str | None = None,
        destination: str = "default",
        correlation_id: uuid.UUID | None = None,
        hitl_approved: bool = False,
        approved_by: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> PublicationRecord:
        """Publish a specific artifact version."""
        record = self._publishing.publish(
            artifact_id,
            version_id,
            actor=actor,
            destination=destination,
            correlation_id=correlation_id,
            hitl_approved=hitl_approved,
            approved_by=approved_by,
            metadata=metadata,
        )

        artifact = self._store.get(artifact_id)
        self._events.emit_artifact_published(
            artifact_id=artifact_id,
            version_id=version_id,
            destination=destination,
            project_id=artifact.project_id if artifact else None,
            correlation_id=correlation_id,
        )
        return record

    def get_publications(
        self, artifact_id: uuid.UUID
    ) -> list[PublicationRecord]:
        """Get all publications for an artifact."""
        return self._publishing.get_publications(artifact_id)

    # ── Rollback ───────────────────────────────────────────────────────

    def rollback(
        self,
        artifact_id: uuid.UUID,
        target_version_id: uuid.UUID,
        *,
        actor: str | None = None,
        reason: str = "",
        correlation_id: uuid.UUID | None = None,
        hitl_approved: bool = False,
        metadata: dict[str, Any] | None = None,
    ) -> RollbackRecord:
        """Rollback an artifact to a previous version."""
        record = self._rollback.rollback(
            artifact_id,
            target_version_id,
            actor=actor,
            reason=reason,
            correlation_id=correlation_id,
            hitl_approved=hitl_approved,
            metadata=metadata,
        )

        artifact = self._store.get(artifact_id)
        self._events.emit_artifact_rolled_back(
            artifact_id=artifact_id,
            from_version_id=record.from_version_id,
            to_version_id=record.to_version_id,
            new_version_id=record.new_version_id,
            project_id=artifact.project_id if artifact else None,
            correlation_id=correlation_id,
        )
        return record

    def get_rollbacks(self, artifact_id: uuid.UUID) -> list[RollbackRecord]:
        """Get all rollback records."""
        return self._rollback.get_rollbacks(artifact_id)


# ── Path traversal protection ──────────────────────────────────────────


def _validate_path(path: str) -> None:
    """Validate a path against traversal attacks."""
    if ".." in path:
        raise ArtifactValidationError(
            f"Path traversal detected: {path!r}",
            details={"path": path},
        )
    if path.startswith("/"):
        raise ArtifactValidationError(
            f"Absolute paths are not allowed: {path!r}",
            details={"path": path},
        )


# ── Platform Services Construction ─────────────────────────────────────


@dataclass
class ArtifactPlatformServices:
    """Groups all Artifact Platform services for injection."""

    store: ArtifactStoreProtocol
    manager: ArtifactManager
    versioning: VersioningService
    lineage: LineageService
    publishing: PublishingService
    rollback: RollbackService
    events: ArtifactEvents
    policy: ArtifactPolicy


def build_artifact_platform(
    *,
    event_sink: ArtifactEventSinkProtocol | None = None,
    policy: ArtifactPolicy | None = None,
    store: ArtifactStoreProtocol | None = None,
) -> ArtifactPlatformServices:
    """Construct and wire the complete Artifact Platform.

    Every dependency is injected; no subsystem constructs another.
    """
    artifact_policy = policy or ArtifactPolicy()
    artifact_store = store or LocalArtifactStore()
    events = ArtifactEvents(sink=event_sink)
    versioning = VersioningService(artifact_store)
    lineage_svc = LineageService(artifact_store)
    publishing = PublishingService(
        artifact_store, policy=artifact_policy.publication
    )
    rollback_svc = RollbackService(
        artifact_store, versioning, policy=artifact_policy.rollback
    )

    manager = ArtifactManager(
        store=artifact_store,
        versioning=versioning,
        lineage=lineage_svc,
        publishing=publishing,
        rollback=rollback_svc,
        events=events,
    )

    return ArtifactPlatformServices(
        store=artifact_store,
        manager=manager,
        versioning=versioning,
        lineage=lineage_svc,
        publishing=publishing,
        rollback=rollback_svc,
        events=events,
        policy=artifact_policy,
    )
