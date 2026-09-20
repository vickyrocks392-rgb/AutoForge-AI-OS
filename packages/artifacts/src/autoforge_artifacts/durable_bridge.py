"""Durable Artifact Store Bridge — Phase 18-K Artifact Platform Integration.

Bridges the Phase 12 Artifact Platform domain model (Artifact, ArtifactVersion,
lineage, publications, rollbacks) to the authoritative runtime
DurableArtifactCatalog and PhysicalArtifactStore.

Architectural Rule:
- Runtime owns: durable artifact identity, lifecycle state machine, physical file state, crash recovery, integrity.
- Artifact Platform owns: domain semantics, versioning, lineage, publication, rollback, policy.
"""

from __future__ import annotations

import logging
import threading
import uuid
from pathlib import Path
from typing import Any

from autoforge_artifacts.errors import (
    ArtifactConflictError as DomainConflictError,
    ArtifactIntegrityError,
    ArtifactNotFoundError,
    ArtifactStorageError,
)
from autoforge_artifacts.models import (
    Artifact,
    ArtifactLineageEntry,
    ArtifactState,
    ArtifactVersion,
    CanonicalArtifactType,
    PublicationRecord,
    RollbackRecord,
    compute_content_hash,
)
from autoforge_artifacts.store import ArtifactStoreProtocol
from autoforge_runtime.artifact_catalog import (
    DurableArtifactCatalog,
    derive_artifact_key,
)
from autoforge_runtime.models import DurableArtifactState, DurableArtifactStatus
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore

logger = logging.getLogger("autoforge.artifacts.durable_bridge")


class DurableArtifactStoreBridge(ArtifactStoreProtocol):
    """Bridge connecting Artifact Platform domain services to DurableArtifactCatalog and PhysicalArtifactStore."""

    def __init__(
        self,
        catalog: DurableArtifactCatalog,
        physical_store: PhysicalArtifactStore,
        *,
        owner_id: str | None = None,
    ) -> None:
        self.catalog = catalog
        self.physical_store = physical_store
        self.owner_id = owner_id or catalog.owner_id
        self._lock = threading.Lock()

        # Domain metadata caches preserved for domain features (lineage, publications, rollbacks)
        self._artifacts: dict[uuid.UUID, Artifact] = {}
        self._versions: dict[uuid.UUID, list[ArtifactVersion]] = {}
        self._version_index: dict[uuid.UUID, ArtifactVersion] = {}
        self._lineage_parents: dict[uuid.UUID, list[ArtifactLineageEntry]] = {}
        self._lineage_children: dict[uuid.UUID, list[ArtifactLineageEntry]] = {}
        self._publications: dict[uuid.UUID, list[PublicationRecord]] = {}
        self._rollbacks: dict[uuid.UUID, list[RollbackRecord]] = {}

    def create(self, artifact: Artifact) -> Artifact:
        """Register domain artifact and record in authoritative durable catalog."""
        with self._lock:
            if artifact.artifact_id in self._artifacts:
                raise DomainConflictError(
                    f"Artifact with ID {artifact.artifact_id} already exists",
                    details={"artifact_id": str(artifact.artifact_id)},
                )

            key = derive_artifact_key(
                artifact_name=artifact.name,
                workflow_id=artifact.project_id,
                operation_type=artifact.artifact_type.value,
            )

            durable_state = self.catalog.register_artifact(
                artifact_key=key,
                artifact_name=artifact.name,
                artifact_type=artifact.artifact_type.value,
                workflow_id=artifact.project_id,
                metadata=artifact.metadata,
            )

            # Bind artifact_id to authoritative durable identity
            bound_artifact = artifact.model_copy(
                update={"artifact_id": durable_state.artifact_id}
            )
            self._artifacts[bound_artifact.artifact_id] = bound_artifact
            self._versions.setdefault(bound_artifact.artifact_id, [])
            return bound_artifact

    def get(self, artifact_id: uuid.UUID) -> Artifact | None:
        with self._lock:
            if artifact_id in self._artifacts:
                return self._artifacts[artifact_id]

            # Try loading from durable catalog
            state = self.catalog.get_artifact(artifact_id)
            if state is not None:
                art = Artifact(
                    artifact_id=state.artifact_id,
                    project_id=state.workflow_id or uuid.uuid4(),
                    name=state.artifact_name,
                    artifact_type=CanonicalArtifactType.SOURCE,
                    state=ArtifactState.VERSIONED if state.status == DurableArtifactStatus.COMMITTED else ArtifactState.CREATED,
                    latest_version_number=state.logical_version,
                    metadata=state.metadata,
                )
                self._artifacts[state.artifact_id] = art
                return art
            return None

    def update(self, artifact: Artifact) -> Artifact:
        with self._lock:
            if artifact.artifact_id not in self._artifacts:
                raise ArtifactNotFoundError(
                    f"Artifact {artifact.artifact_id} not found",
                    details={"artifact_id": str(artifact.artifact_id)},
                )
            self._artifacts[artifact.artifact_id] = artifact
            return artifact

    def list_artifacts(self, project_id: uuid.UUID | None = None) -> list[Artifact]:
        with self._lock:
            if project_id is not None:
                # Query durable catalog
                states = self.catalog.find_by_workflow(project_id)
                for s in states:
                    if s.artifact_id not in self._artifacts:
                        self._artifacts[s.artifact_id] = Artifact(
                            artifact_id=s.artifact_id,
                            project_id=s.workflow_id or project_id,
                            name=s.artifact_name,
                            artifact_type=CanonicalArtifactType.SOURCE,
                            state=ArtifactState.VERSIONED if s.status == DurableArtifactStatus.COMMITTED else ArtifactState.CREATED,
                            latest_version_number=s.logical_version,
                            metadata=s.metadata,
                        )
                return [a for a in self._artifacts.values() if a.project_id == project_id]
            return list(self._artifacts.values())

    def store_version(self, version: ArtifactVersion) -> ArtifactVersion:
        """Durable version storage: writes to PhysicalArtifactStore and commits to DurableArtifactCatalog."""
        with self._lock:
            artifact = self.get(version.artifact_id)
            if artifact is None:
                raise ArtifactNotFoundError(
                    f"Artifact {version.artifact_id} does not exist",
                    details={"artifact_id": str(version.artifact_id)},
                )

            # Compute content hash
            computed_hash = compute_content_hash(version.content)
            if version.content_hash and version.content_hash != computed_hash:
                raise ArtifactIntegrityError(
                    f"Version content hash mismatch for artifact {version.artifact_id}",
                    details={
                        "artifact_id": str(version.artifact_id),
                        "declared_hash": version.content_hash,
                        "computed_hash": computed_hash,
                    },
                )

            # Physical write via staging and atomic publish
            key = derive_artifact_key(
                artifact_name=f"{artifact.name}_v{version.version_number}",
                workflow_id=artifact.project_id,
                operation_type=artifact.artifact_type.value,
            )
            durable_state = self.catalog.register_artifact(
                artifact_key=key,
                artifact_name=artifact.name,
                artifact_type=artifact.artifact_type.value,
                workflow_id=artifact.project_id,
                logical_version=version.version_number,
                parent_artifact_id=version.parent_version_id,
            )

            staging_path = self.physical_store.create_staging_file(key)
            self.catalog.begin_staging(durable_state.artifact_id, staging_path=str(staging_path))
            c_hash, s_bytes = self.physical_store.write_staging_text(staging_path, version.content)

            target_filename = f"{artifact.name}.v{version.version_number}"
            published_path = self.physical_store.atomic_publish(
                staging_path,
                target_filename,
                expected_hash=c_hash,
                expected_size=s_bytes,
            )

            self.catalog.commit_artifact(
                durable_state.artifact_id,
                storage_path=str(published_path),
                content_hash=c_hash,
                size_bytes=s_bytes,
            )

            stored_version = version.model_copy(
                update={
                    "content_hash": c_hash,
                    "size_bytes": s_bytes,
                }
            )

            self._versions.setdefault(version.artifact_id, []).append(stored_version)
            self._version_index[stored_version.version_id] = stored_version

            # Update parent artifact latest version
            updated_art = artifact.model_copy(
                update={
                    "latest_version_number": version.version_number,
                    "state": ArtifactState.VERSIONED,
                }
            )
            self._artifacts[artifact.artifact_id] = updated_art

            return stored_version

    def get_version(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> ArtifactVersion | None:
        with self._lock:
            v = self._version_index.get(version_id)
            if v is not None and v.artifact_id == artifact_id:
                return v
            return None

    def list_versions(self, artifact_id: uuid.UUID) -> list[ArtifactVersion]:
        with self._lock:
            return list(self._versions.get(artifact_id, []))

    def get_latest_version(self, artifact_id: uuid.UUID) -> ArtifactVersion | None:
        with self._lock:
            versions = self._versions.get(artifact_id, [])
            if not versions:
                return None
            return max(versions, key=lambda v: v.version_number)

    def verify_integrity(self, artifact_id: uuid.UUID, version_id: uuid.UUID) -> bool:
        with self._lock:
            v = self.get_version(artifact_id, version_id)
            if v is None:
                return False
            # Verify in-memory content hash
            computed = compute_content_hash(v.content)
            return computed == v.content_hash

    def store_lineage(self, entry: ArtifactLineageEntry) -> None:
        with self._lock:
            self._lineage_parents.setdefault(entry.child_artifact_id, []).append(entry)
            self._lineage_children.setdefault(entry.parent_artifact_id, []).append(entry)

    def get_lineage_parents(self, artifact_id: uuid.UUID) -> list[ArtifactLineageEntry]:
        with self._lock:
            return list(self._lineage_parents.get(artifact_id, []))

    def get_lineage_children(self, artifact_id: uuid.UUID) -> list[ArtifactLineageEntry]:
        with self._lock:
            return list(self._lineage_children.get(artifact_id, []))

    def store_publication(self, record: PublicationRecord) -> None:
        with self._lock:
            self._publications.setdefault(record.artifact_id, []).append(record)

    def get_publications(self, artifact_id: uuid.UUID) -> list[PublicationRecord]:
        with self._lock:
            return list(self._publications.get(artifact_id, []))

    def store_rollback(self, record: RollbackRecord) -> None:
        with self._lock:
            self._rollbacks.setdefault(record.artifact_id, []).append(record)

    def get_rollbacks(self, artifact_id: uuid.UUID) -> list[RollbackRecord]:
        with self._lock:
            return list(self._rollbacks.get(artifact_id, []))
