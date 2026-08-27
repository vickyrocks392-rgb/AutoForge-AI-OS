"""Artifact publishing — Phase 12.

Controlled publication of artifacts with HITL governance integration.

Design rules
------------
- Publication is explicit (never automatic).
- HITL requirements are evaluated by deterministic policy.
- Uses Phase 9 ApprovalGate pattern (does not create second framework).
- Publication registry is in-memory.
"""

from __future__ import annotations

import uuid

from autoforge_artifacts.errors import (
    ArtifactAuthorizationError,
    ArtifactNotFoundError,
    ArtifactPublicationError,
    ArtifactValidationError,
)
from autoforge_artifacts.models import (
    Artifact,
    ArtifactState,
    CanonicalArtifactType,
    PublicationRecord,
    is_valid_state_transition,
)
from autoforge_artifacts.policies import PublicationPolicy
from autoforge_artifacts.store import ArtifactStoreProtocol


class PublishingService:
    """Manages controlled artifact publication."""

    def __init__(
        self,
        store: ArtifactStoreProtocol,
        policy: PublicationPolicy | None = None,
    ) -> None:
        self._store = store
        self._policy = policy or PublicationPolicy()

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
        """Publish a specific artifact version.

        Raises ``ArtifactAuthorizationError`` if HITL is required but
        ``hitl_approved`` is False.
        """
        artifact = self._store.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(
                f"Artifact {artifact_id} not found",
                details={"artifact_id": str(artifact_id)},
            )

        version = self._store.get_version(artifact_id, version_id)
        if version is None:
            raise ArtifactNotFoundError(
                f"Version {version_id} not found for artifact {artifact_id}",
                details={
                    "artifact_id": str(artifact_id),
                    "version_id": str(version_id),
                },
            )

        # Check HITL requirements.
        requires_hitl = self._policy.requires_hitl(
            artifact.artifact_type, destination
        )
        if requires_hitl and not hitl_approved:
            raise ArtifactAuthorizationError(
                f"Publication of {artifact.artifact_type.value} to "
                f"'{destination}' requires HITL approval",
                details={
                    "artifact_id": str(artifact_id),
                    "artifact_type": artifact.artifact_type.value,
                    "destination": destination,
                },
            )

        # Create publication record.
        record = PublicationRecord(
            artifact_id=artifact_id,
            version_id=version_id,
            published_by=actor,
            destination=destination,
            correlation_id=correlation_id,
            requires_hitl=requires_hitl,
            approved_by=approved_by if requires_hitl else None,
            metadata=metadata or {},
        )
        self._store.store_publication(record)

        # Transition artifact state to PUBLISHED.
        if is_valid_state_transition(artifact.state, ArtifactState.PUBLISHED):
            updated = artifact.with_state(ArtifactState.PUBLISHED)
            self._store.update(updated)

        return record

    def get_publications(
        self, artifact_id: uuid.UUID
    ) -> list[PublicationRecord]:
        """Get all publications for an artifact."""
        return self._store.get_publications(artifact_id)

    def is_published(self, artifact_id: uuid.UUID) -> bool:
        """Check if an artifact has been published."""
        artifact = self._store.get(artifact_id)
        if artifact is None:
            return False
        return artifact.state == ArtifactState.PUBLISHED


# Needed for type annotation in publish method.
from typing import Any  # noqa: E402
