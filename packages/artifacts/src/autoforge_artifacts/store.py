"""Artifact Store — storage abstraction and local implementation — Phase 12.

Separates the Artifact domain from physical storage via a minimal protocol.
The ``LocalArtifactStore`` provides an in-memory implementation with
thread-safe concurrency control for conflict detection.

Design rules
------------
- Storage is content-addressed by SHA-256 hash where practical.
- Version sequence numbers are monotonically increasing per artifact.
- Thread-safe: ``threading.Lock`` prevents silent lost updates.
- No cloud dependencies (S3/GCS/Azure).
- No distributed locking infrastructure.
"""

from __future__ import annotations

import threading
import uuid
from typing import Any, Protocol, runtime_checkable

from autoforge_artifacts.errors import (
    ArtifactConflictError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStorageError,
    ArtifactValidationError,
)
from autoforge_artifacts.models import (
    Artifact,
    ArtifactLineageEntry,
    ArtifactState,
    ArtifactVersion,
    PublicationRecord,
    RollbackRecord,
    compute_content_hash,
)


@runtime_checkable
class ArtifactStoreProtocol(Protocol):
    """Minimal storage contract for the Artifact Platform."""

    def create(self, artifact: Artifact) -> Artifact: ...

    def get(self, artifact_id: uuid.UUID) -> Artifact | None: ...

    def update(self, artifact: Artifact) -> Artifact: ...

    def list_artifacts(self, project_id: uuid.UUID | None = None) -> list[Artifact]: ...

    def store_version(self, version: ArtifactVersion) -> ArtifactVersion: ...

    def get_version(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> ArtifactVersion | None: ...

    def list_versions(self, artifact_id: uuid.UUID) -> list[ArtifactVersion]: ...

    def get_latest_version(self, artifact_id: uuid.UUID) -> ArtifactVersion | None: ...

    def verify_integrity(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> bool: ...

    def store_lineage(self, entry: ArtifactLineageEntry) -> None: ...

    def get_lineage_parents(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]: ...

    def get_lineage_children(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]: ...

    def store_publication(self, record: PublicationRecord) -> None: ...

    def get_publications(self, artifact_id: uuid.UUID) -> list[PublicationRecord]: ...

    def store_rollback(self, record: RollbackRecord) -> None: ...

    def get_rollbacks(self, artifact_id: uuid.UUID) -> list[RollbackRecord]: ...


class LocalArtifactStore:
    """Thread-safe in-memory artifact store.

    Provides the canonical local-first storage backend for Phase 12.
    Content integrity is verified by SHA-256 recomputation.  Concurrent
    version creation is protected by a per-artifact lock.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._artifacts: dict[uuid.UUID, Artifact] = {}
        self._versions: dict[uuid.UUID, list[ArtifactVersion]] = {}
        self._version_index: dict[uuid.UUID, ArtifactVersion] = {}
        self._lineage_parents: dict[uuid.UUID, list[ArtifactLineageEntry]] = {}
        self._lineage_children: dict[uuid.UUID, list[ArtifactLineageEntry]] = {}
        self._publications: dict[uuid.UUID, list[PublicationRecord]] = {}
        self._rollbacks: dict[uuid.UUID, list[RollbackRecord]] = {}

    # ── Artifact CRUD ──────────────────────────────────────────────────

    def create(self, artifact: Artifact) -> Artifact:
        """Register a new artifact.  Raises on duplicate ID."""
        with self._lock:
            if artifact.artifact_id in self._artifacts:
                raise ArtifactConflictError(
                    f"Artifact {artifact.artifact_id} already exists",
                    details={"artifact_id": str(artifact.artifact_id)},
                )
            self._artifacts[artifact.artifact_id] = artifact
            self._versions[artifact.artifact_id] = []
        return artifact

    def get(self, artifact_id: uuid.UUID) -> Artifact | None:
        """Retrieve an artifact by ID, or None."""
        return self._artifacts.get(artifact_id)

    def update(self, artifact: Artifact) -> Artifact:
        """Replace artifact metadata (immutable state update pattern)."""
        with self._lock:
            if artifact.artifact_id not in self._artifacts:
                raise ArtifactNotFoundError(
                    f"Artifact {artifact.artifact_id} not found",
                    details={"artifact_id": str(artifact.artifact_id)},
                )
            self._artifacts[artifact.artifact_id] = artifact
        return artifact

    def list_artifacts(self, project_id: uuid.UUID | None = None) -> list[Artifact]:
        """List artifacts, optionally filtered by project."""
        if project_id is None:
            return list(self._artifacts.values())
        return [a for a in self._artifacts.values() if a.project_id == project_id]

    # ── Version CRUD ───────────────────────────────────────────────────

    def store_version(self, version: ArtifactVersion) -> ArtifactVersion:
        """Store an immutable version.

        Raises ``ArtifactConflictError`` if version_number already exists
        for this artifact (concurrent update detection).
        """
        with self._lock:
            if version.artifact_id not in self._artifacts:
                raise ArtifactNotFoundError(
                    f"Artifact {version.artifact_id} not found",
                    details={"artifact_id": str(version.artifact_id)},
                )
            existing = self._versions.get(version.artifact_id, [])
            for v in existing:
                if v.version_number == version.version_number:
                    raise ArtifactConflictError(
                        f"Version {version.version_number} already exists for "
                        f"artifact {version.artifact_id}",
                        details={
                            "artifact_id": str(version.artifact_id),
                            "version_number": version.version_number,
                        },
                    )
                if v.version_id == version.version_id:
                    raise ArtifactConflictError(
                        f"Version ID {version.version_id} already exists",
                        details={"version_id": str(version.version_id)},
                    )
            self._versions.setdefault(version.artifact_id, []).append(version)
            self._version_index[version.version_id] = version
        return version

    def get_version(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> ArtifactVersion | None:
        """Retrieve a specific version."""
        return self._version_index.get(version_id)

    def list_versions(self, artifact_id: uuid.UUID) -> list[ArtifactVersion]:
        """List all versions of an artifact, ordered by version_number."""
        versions = self._versions.get(artifact_id, [])
        return sorted(versions, key=lambda v: v.version_number)

    def get_latest_version(self, artifact_id: uuid.UUID) -> ArtifactVersion | None:
        """Get the latest (highest version_number) version."""
        versions = self.list_versions(artifact_id)
        return versions[-1] if versions else None

    # ── Integrity ──────────────────────────────────────────────────────

    def verify_integrity(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> bool:
        """Verify content integrity by recomputing hash.

        Returns True if stored hash matches recomputed hash.
        Raises ``ArtifactNotFoundError`` if version doesn't exist or belongs to another artifact.
        """
        version = self.get_version(artifact_id, version_id)
        if version is None or version.artifact_id != artifact_id:
            raise ArtifactNotFoundError(
                f"Version {version_id} not found for artifact {artifact_id}",
                details={
                    "artifact_id": str(artifact_id),
                    "version_id": str(version_id),
                },
            )
        recomputed = compute_content_hash(version.content)
        return recomputed == version.content_hash

    # ── Lineage ────────────────────────────────────────────────────────

    def store_lineage(self, entry: ArtifactLineageEntry) -> None:
        """Record a lineage relationship."""
        with self._lock:
            self._lineage_children.setdefault(
                entry.parent_artifact_id, []
            ).append(entry)
            self._lineage_parents.setdefault(
                entry.child_artifact_id, []
            ).append(entry)

    def get_lineage_parents(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get all lineage entries where this artifact is the child."""
        return list(self._lineage_parents.get(artifact_id, []))

    def get_lineage_children(
        self, artifact_id: uuid.UUID
    ) -> list[ArtifactLineageEntry]:
        """Get all lineage entries where this artifact is the parent."""
        return list(self._lineage_children.get(artifact_id, []))

    # ── Publication ────────────────────────────────────────────────────

    def store_publication(self, record: PublicationRecord) -> None:
        """Record a publication."""
        with self._lock:
            self._publications.setdefault(record.artifact_id, []).append(record)

    def get_publications(self, artifact_id: uuid.UUID) -> list[PublicationRecord]:
        """Get all publications for an artifact."""
        return list(self._publications.get(artifact_id, []))

    # ── Rollback ───────────────────────────────────────────────────────

    def store_rollback(self, record: RollbackRecord) -> None:
        """Record a rollback operation."""
        with self._lock:
            self._rollbacks.setdefault(record.artifact_id, []).append(record)

    def get_rollbacks(self, artifact_id: uuid.UUID) -> list[RollbackRecord]:
        """Get all rollback records for an artifact."""
        return list(self._rollbacks.get(artifact_id, []))
