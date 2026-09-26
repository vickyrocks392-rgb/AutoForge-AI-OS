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
        self._lock = threading.RLock()

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
                    version_count=state.logical_version or 0,
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
                            version_count=s.logical_version or 0,
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

            # 18-J defect repair: ``register_artifact`` is idempotent, so replaying
            # an already-materialised version returns the EXISTING record (which
            # may be COMMITTED) instead of a fresh CREATED one. The state machine
            # is correct — COMMITTED only exits via RETIRED — so the caller must
            # honour the returned status rather than re-staging unconditionally.
            # A new version_number derives a NEW key, so it legitimately reaches
            # the CREATED -> STAGING -> COMMITTED path below.
            if durable_state.status == DurableArtifactStatus.COMMITTED:
                from autoforge_runtime.artifact_catalog import ArtifactConflictError

                if durable_state.content_hash and durable_state.content_hash != computed_hash:
                    raise ArtifactConflictError(
                        f"Version {version.version_number} of artifact "
                        f"{artifact.artifact_id} is already committed with "
                        f"different content; refusing to silently overwrite.",
                        details={
                            "artifact_id": str(durable_state.artifact_id),
                            "artifact_key": durable_state.artifact_key,
                            "committed_content_hash": durable_state.content_hash,
                            "incoming_content_hash": computed_hash,
                        },
                    )
                # Idempotent replay: the version is already durable.
                replayed = version.model_copy(
                    update={
                        "version_id": durable_state.artifact_id,
                        "content_hash": durable_state.content_hash or computed_hash,
                        "size_bytes": durable_state.size_bytes
                        or len(version.content.encode("utf-8")),
                    }
                )
                cur = self._versions.setdefault(artifact.artifact_id, [])
                if replayed.version_id not in self._version_index:
                    self._version_index[replayed.version_id] = replayed
                    if not any(e.version_id == replayed.version_id for e in cur):
                        cur.append(replayed)
                return replayed

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
                    "version_id": durable_state.artifact_id,
                    "content_hash": c_hash,
                    "size_bytes": s_bytes,
                }
            )

            self._versions.setdefault(version.artifact_id, []).append(stored_version)
            self._version_index[stored_version.version_id] = stored_version

            # Update parent artifact latest version
            updated_art = artifact.with_version(
                version_id=stored_version.version_id,
                version_count=len(self._versions[artifact.artifact_id]),
            )
            self._artifacts[artifact.artifact_id] = updated_art

            return stored_version

    def _populate_versions_from_catalog(self, artifact_id: uuid.UUID) -> None:
        """Reconstruct version metadata from the authoritative DurableArtifactCatalog on restart."""
        artifact = self.get(artifact_id)
        if artifact is None or not artifact.project_id:
            return
        states = self.catalog.find_by_workflow(artifact.project_id)
        for s in states:
            if s.status == DurableArtifactStatus.COMMITTED and s.logical_version is not None:
                if s.artifact_name == artifact.name or s.artifact_name.startswith(f"{artifact.name}_v"):
                    content = ""
                    if s.storage_path and Path(s.storage_path).is_file():
                        try:
                            content = Path(s.storage_path).read_text(encoding="utf-8")
                        except Exception:
                            content = ""
                    v = ArtifactVersion(
                        version_id=s.artifact_id,
                        artifact_id=artifact_id,
                        version_number=s.logical_version,
                        content=content,
                        content_hash=s.content_hash or "",
                        size_bytes=s.size_bytes or len(content.encode("utf-8")),
                        parent_version_id=s.parent_artifact_id,
                    )
                    if v.version_id not in self._version_index:
                        self._version_index[v.version_id] = v
                        cur_list = self._versions.setdefault(artifact_id, [])
                        if not any(existing.version_id == v.version_id for existing in cur_list):
                            cur_list.append(v)

    def get_version(
        self, artifact_id: uuid.UUID, version_id: uuid.UUID
    ) -> ArtifactVersion | None:
        with self._lock:
            v = self._version_index.get(version_id)
            if v is not None and v.artifact_id == artifact_id:
                return v
            self._populate_versions_from_catalog(artifact_id)
            v = self._version_index.get(version_id)
            if v is not None and v.artifact_id == artifact_id:
                return v
            return None

    def list_versions(self, artifact_id: uuid.UUID) -> list[ArtifactVersion]:
        with self._lock:
            if not self._versions.get(artifact_id):
                self._populate_versions_from_catalog(artifact_id)
            return list(self._versions.get(artifact_id, []))

    def get_latest_version(self, artifact_id: uuid.UUID) -> ArtifactVersion | None:
        with self._lock:
            if not self._versions.get(artifact_id):
                self._populate_versions_from_catalog(artifact_id)
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
            if computed != v.content_hash:
                return False
            # Verify physical file state on disk via physical store
            state = self.catalog.get_artifact(version_id)
            if state and state.storage_path:
                try:
                    self.physical_store.validate_integrity(
                        state.storage_path,
                        expected_hash=v.content_hash,
                        expected_size=v.size_bytes,
                    )
                except Exception:
                    return False
            return True

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
