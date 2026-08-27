"""Artifact versioning — Phase 12.

Immutable version creation, version history traversal, content-addressed
identity, and parent chain management.

Design rules
------------
- Every content change produces a new version with a new ``version_id``.
- Version numbers are monotonically increasing (1, 2, 3, …).
- Identical content produces identical ``content_hash``.
- Parent chain is explicit and queryable.
- No silent overwrites.
"""

from __future__ import annotations

import uuid

from autoforge_artifacts.errors import (
    ArtifactNotFoundError,
    ArtifactValidationError,
)
from autoforge_artifacts.models import (
    ArtifactVersion,
    CanonicalProvenance,
)
from autoforge_artifacts.store import ArtifactStoreProtocol


class VersioningService:
    """Manages immutable artifact version creation and history."""

    def __init__(self, store: ArtifactStoreProtocol) -> None:
        self._store = store

    def create_version(
        self,
        artifact_id: uuid.UUID,
        content: str,
        *,
        provenance: CanonicalProvenance | None = None,
        created_by: str | None = None,
    ) -> ArtifactVersion:
        """Create a new immutable version for an artifact.

        Automatically determines parent and version number from the
        existing version history.  The artifact must already exist in
        the store.
        """
        if not content and content != "":
            raise ArtifactValidationError("Content must not be None")

        artifact = self._store.get(artifact_id)
        if artifact is None:
            raise ArtifactNotFoundError(
                f"Artifact {artifact_id} not found",
                details={"artifact_id": str(artifact_id)},
            )

        latest = self._store.get_latest_version(artifact_id)
        version_number = (latest.version_number + 1) if latest else 1
        parent_version_id = latest.version_id if latest else None

        version = ArtifactVersion.create(
            artifact_id=artifact_id,
            version_number=version_number,
            content=content,
            provenance=provenance,
            parent_version_id=parent_version_id,
            created_by=created_by,
        )

        stored = self._store.store_version(version)

        # Update artifact to point to new version.
        updated = artifact.with_version(stored.version_id, version_number)
        self._store.update(updated)

        return stored

    def get_history(self, artifact_id: uuid.UUID) -> list[ArtifactVersion]:
        """Return the full version history, ordered by version_number."""
        return self._store.list_versions(artifact_id)

    def get_latest(self, artifact_id: uuid.UUID) -> ArtifactVersion | None:
        """Return the latest version, or None."""
        return self._store.get_latest_version(artifact_id)

    def get_version(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> ArtifactVersion | None:
        """Get a specific version by ID."""
        version = self._store.get_version(artifact_id, version_id)
        if version and version.artifact_id == artifact_id:
            return version
        return None

    def get_parent_chain(self, artifact_id: uuid.UUID, version_id: uuid.UUID) -> list[ArtifactVersion]:
        """Walk the parent chain from a version back to v1.

        Returns versions in order from oldest to the specified version.
        """
        chain: list[ArtifactVersion] = []
        current = self.get_version(artifact_id, version_id)
        while current is not None:
            chain.append(current)
            if current.parent_version_id is None:
                break
            current = self.get_version(artifact_id, current.parent_version_id)
        chain.reverse()
        return chain
