"""Artifact rollback — Phase 12.

History-preserving rollback that creates new versions rather than
deleting history.

Design rules
------------
- Rollback does NOT destroy history.
- Rollback creates a new version referencing the target's content.
- Rollback validates target existence, ownership, and integrity.
- Consequential rollback may require HITL approval.
- Full provenance of the rollback operation is preserved.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_artifacts.errors import (
    ArtifactAuthorizationError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactRollbackError,
    ArtifactValidationError,
)
from autoforge_artifacts.models import (
    ArtifactState,
    ArtifactVersion,
    CanonicalProvenance,
    RollbackRecord,
    compute_content_hash,
)
from autoforge_artifacts.policies import RollbackPolicy
from autoforge_artifacts.store import ArtifactStoreProtocol
from autoforge_artifacts.versioning import VersioningService


class RollbackService:
    """Manages history-preserving artifact rollback."""

    def __init__(
        self,
        store: ArtifactStoreProtocol,
        versioning: VersioningService,
        policy: RollbackPolicy | None = None,
    ) -> None:
        self._store = store
        self._versioning = versioning
        self._policy = policy or RollbackPolicy()

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
        """Rollback an artifact to a previous version.

        Creates a new version with the target version's content.
        History is preserved: v1 → v2 → v3 → rollback-to-v2 (v4).

        Raises:
            ArtifactNotFoundError: if artifact or target version not found.
            ArtifactRollbackError: if target version belongs to wrong artifact.
            ArtifactIntegrityError: if target version's content is corrupted.
            ArtifactAuthorizationError: if HITL is required but not approved.
        """
        # 1. Validate artifact exists.
        artifact = self._store.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(
                f"Artifact {artifact_id} not found",
                details={"artifact_id": str(artifact_id)},
            )

        # 2. Validate target version exists and belongs to this artifact.
        target_version = self._store.get_version(artifact_id, target_version_id)
        if target_version is None:
            raise ArtifactNotFoundError(
                f"Target version {target_version_id} not found for artifact {artifact_id}",
                details={
                    "artifact_id": str(artifact_id),
                    "target_version_id": str(target_version_id),
                },
            )
        if target_version.artifact_id != artifact_id:
            raise ArtifactRollbackError(
                f"Target version {target_version_id} does not belong to "
                f"artifact {artifact_id}",
                details={
                    "artifact_id": str(artifact_id),
                    "target_version_id": str(target_version_id),
                    "actual_artifact_id": str(target_version.artifact_id),
                },
            )

        # 3. Verify target content integrity.
        recomputed = compute_content_hash(target_version.content)
        if recomputed != target_version.content_hash:
            raise ArtifactIntegrityError(
                f"Target version {target_version_id} content integrity check failed",
                details={
                    "version_id": str(target_version_id),
                    "expected_hash": target_version.content_hash,
                    "actual_hash": recomputed,
                },
            )

        # 4. Check HITL policy.
        is_published = artifact.state == ArtifactState.PUBLISHED
        requires_hitl = self._policy.requires_hitl(
            artifact.artifact_type, is_published=is_published
        )
        if requires_hitl and not hitl_approved:
            raise ArtifactAuthorizationError(
                f"Rollback of artifact {artifact_id} requires HITL approval",
                details={
                    "artifact_id": str(artifact_id),
                    "is_published": is_published,
                    "artifact_type": artifact.artifact_type.value,
                },
            )

        # 5. Get current version for the rollback record.
        current_version = self._store.get_latest_version(artifact_id)
        from_version_id = current_version.version_id if current_version else target_version_id

        # 6. Create new version with target's content (history-preserving).
        latest = self._store.get_latest_version(artifact_id)
        new_version_number = (latest.version_number + 1) if latest else 1
        parent_version_id = latest.version_id if latest else None

        new_version = ArtifactVersion.create(
            artifact_id=artifact_id,
            version_number=new_version_number,
            content=target_version.content,
            provenance=CanonicalProvenance(
                actor=actor,
                correlation_id=correlation_id,
                metadata={"rollback_reason": reason, **(metadata or {})},
            ),
            parent_version_id=parent_version_id,
            created_by=actor,
            is_rollback=True,
            rollback_source_version_id=target_version_id,
        )

        stored_version = self._store.store_version(new_version)

        # 7. Update artifact to point to new version.
        updated = artifact.with_version(stored_version.version_id, new_version_number)
        self._store.update(updated)

        # 8. Record rollback.
        record = RollbackRecord(
            artifact_id=artifact_id,
            from_version_id=from_version_id,
            to_version_id=target_version_id,
            new_version_id=stored_version.version_id,
            reason=reason,
            rolled_back_by=actor,
            correlation_id=correlation_id,
            metadata=metadata or {},
        )
        self._store.store_rollback(record)

        return record

    def get_rollbacks(self, artifact_id: uuid.UUID) -> list[RollbackRecord]:
        """Get all rollback records for an artifact."""
        return self._store.get_rollbacks(artifact_id)
