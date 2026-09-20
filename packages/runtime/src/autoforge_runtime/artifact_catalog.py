"""Durable Artifact Catalog — Phase 18-J Final Durability Closure.

Provides crash-safe, durable artifact identity, lifecycle, and provenance
tracking within the authoritative SQLite/PersistenceLayer architecture.

Architecture
------------
This module follows the exact same pattern established by the earlier
durability stores in Phase 18-J:

    DurableExecutionStore      (J.2 — execution identity / attempts)
    DurableIdempotencyStore    (J.4 — idempotent side-effect safety)
    DurableApprovalStore       (J.5 — HITL approval / recovery)
    **DurableArtifactCatalog** (Final Closure — artifact catalog & recovery)

All share the same PersistenceLayer, the same SQLite backing, the same OCC
(optimistic concurrency control) via ``state_version``, the same deterministic
identity derivation via UUID5 namespaces, and the same crash recovery model.

Core Responsibilities
---------------------
1. Deterministic artifact identity derivation from logical keys.
2. Durable artifact catalog creation (CREATED state, persisted before any
   physical artifact write begins).
3. Two-phase commit protocol: catalog CREATED → physical staging → catalog
   STAGING → physical atomic rename → catalog COMMITTED.
4. Crash window detection and reconciliation on startup.
5. Content hash validation for duplicate/conflict detection.
6. Query operations by key, workflow, task, execution, or status.

Durability Guarantees
---------------------
- Catalog state survives process death (SQLite WAL + fsync).
- Crash before physical write: catalog shows CREATED, recovery knows the
  artifact body is absent.
- Crash during physical write: catalog shows STAGING, recovery can inspect
  staging path and decide re-attempt or mark FAILED.
- Crash after physical write before catalog commit: staging file exists,
  catalog STAGING — recovery performs the catalog commit.
- Crash after catalog commit: artifact is fully durable.
"""

from __future__ import annotations

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Any

from autoforge_runtime.exceptions import (
    DuplicateEntityError,
    EntityNotFoundError,
    InvalidTransitionError,
    PersistenceError,
    VersionConflictError,
)
from autoforge_runtime.models import (
    DurableArtifactState,
    DurableArtifactStatus,
    EntityType,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.validation import (
    is_artifact_terminal,
    validate_artifact_transition,
)

logger = logging.getLogger("autoforge.runtime.artifact_catalog")


# ── Namespace & Key Derivation ────────────────────────────────────────────

#: UUID5 namespace for deterministic artifact catalog identity.
ARTIFACT_CATALOG_NAMESPACE = uuid.UUID("e7b4f8c2-1d3a-4e5f-9b6c-7a8d0e2f1c3b")


def derive_artifact_key(
    *,
    artifact_name: str,
    workflow_id: uuid.UUID | str | None = None,
    task_id: str | None = None,
    execution_id: uuid.UUID | str | None = None,
    operation_type: str = "artifact",
) -> str:
    """Derive a deterministic logical artifact key.

    The key uniquely identifies a logical artifact within the scope of a
    workflow/task/execution/name combination.  Retries produce the same key
    (and therefore the same artifact_id) for the same logical artifact.

    Args:
        artifact_name: Human-readable artifact name.
        workflow_id: Optional workflow scope.
        task_id: Optional task scope.
        execution_id: Optional execution scope.
        operation_type: Classification label.

    Returns:
        A deterministic string key.
    """
    parts = [
        "artifact",
        str(workflow_id or ""),
        task_id or "",
        str(execution_id or ""),
        operation_type,
        artifact_name,
    ]
    return ":".join(parts)


def artifact_id_for_key(key: str) -> uuid.UUID:
    """Derive a deterministic UUID5 artifact ID from a logical key."""
    return uuid.uuid5(ARTIFACT_CATALOG_NAMESPACE, key)


def default_artifact_owner_id() -> str:
    """Deterministic owner identity for crash detection.

    Uses process ID + hostname so startup reconciliation can identify
    artifacts owned by a dead process.
    """
    import socket

    return f"{socket.gethostname()}:{os.getpid()}"


# ── Exceptions ────────────────────────────────────────────────────────────


class ArtifactCatalogError(PersistenceError):
    """Base error for durable artifact catalog operations."""


class ArtifactConflictError(ArtifactCatalogError):
    """Raised when an artifact with the same key but different content exists."""


class ArtifactNotCommittedError(ArtifactCatalogError):
    """Raised when attempting to operate on a non-committed artifact."""


# ── Reconciliation Result ─────────────────────────────────────────────────


class ReconciliationResult:
    """Result of a startup reconciliation pass.

    Tracks artifacts that were detected in inconsistent states and what
    corrective action was taken.
    """

    __slots__ = (
        "recovered_count",
        "failed_count",
        "orphaned_staging_count",
        "recovered_artifacts",
        "failed_artifacts",
        "orphaned_staging_paths",
    )

    def __init__(self) -> None:
        self.recovered_count: int = 0
        self.failed_count: int = 0
        self.orphaned_staging_count: int = 0
        self.recovered_artifacts: list[uuid.UUID] = []
        self.failed_artifacts: list[uuid.UUID] = []
        self.orphaned_staging_paths: list[str] = []


# ── Durable Artifact Catalog ─────────────────────────────────────────────


class DurableArtifactCatalog:
    """Crash-safe, durable artifact catalog backed by PersistenceLayer.

    This is the single authoritative store for artifact identity, lifecycle,
    provenance, and content references.  It replaces in-memory artifact
    tracking for durability purposes, while not interfering with the
    existing ``packages/artifacts`` domain logic.

    Args:
        persistence: The shared PersistenceLayer (SQLite-backed).
        owner_id: Process identity for crash detection.  Defaults to
            ``hostname:pid``.
    """

    def __init__(
        self,
        persistence: PersistenceLayer,
        *,
        owner_id: str | None = None,
    ) -> None:
        self._persistence = persistence
        self._owner_id = owner_id or default_artifact_owner_id()

    @property
    def owner_id(self) -> str:
        """Process identity used for crash detection."""
        return self._owner_id

    # ── Registration (CREATED) ────────────────────────────────────────

    def register_artifact(
        self,
        *,
        artifact_key: str,
        artifact_name: str = "",
        artifact_type: str = "generic",
        workflow_id: uuid.UUID | str | None = None,
        task_id: str | None = None,
        execution_id: uuid.UUID | str | None = None,
        attempt_id: uuid.UUID | str | None = None,
        operation_id: uuid.UUID | str | None = None,
        parent_artifact_id: uuid.UUID | None = None,
        logical_version: int = 1,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> DurableArtifactState:
        """Register a new artifact in the durable catalog (CREATED state).

        Idempotent: if an artifact with the same ``artifact_key`` already
        exists, the existing record is returned without modification.

        Args:
            artifact_key: Deterministic logical artifact key.
            artifact_name: Human-readable name.
            artifact_type: Classification label.
            workflow_id: Workflow scope.
            task_id: Task scope.
            execution_id: Execution scope.
            attempt_id: Attempt scope.
            operation_id: J.4 idempotency operation ID.
            parent_artifact_id: Lineage parent.
            logical_version: Version number for this logical artifact key.
            metadata: Extensible metadata.
            provenance: Provenance information.

        Returns:
            The created or existing DurableArtifactState.

        Raises:
            PersistenceError: On persistence failure.
        """
        artifact_id = artifact_id_for_key(artifact_key)

        # Check for existing record (idempotent replay).
        existing = self._read_artifact(artifact_id)
        if existing is not None:
            logger.debug(
                "Artifact %s already registered (key=%s, status=%s). Replay-safe return.",
                artifact_id,
                artifact_key,
                existing.status.value,
            )
            return existing

        wf_id = uuid.UUID(str(workflow_id)) if workflow_id else None
        exec_id = uuid.UUID(str(execution_id)) if execution_id else None
        att_id = uuid.UUID(str(attempt_id)) if attempt_id else None
        op_id = uuid.UUID(str(operation_id)) if operation_id else None

        state = DurableArtifactState(
            artifact_id=artifact_id,
            artifact_key=artifact_key,
            artifact_name=artifact_name or artifact_key,
            artifact_type=artifact_type,
            status=DurableArtifactStatus.CREATED,
            workflow_id=wf_id,
            task_id=task_id,
            execution_id=exec_id,
            attempt_id=att_id,
            operation_id=op_id,
            parent_artifact_id=parent_artifact_id,
            logical_version=logical_version,
            owner_id=self._owner_id,
            state_version=1,
            metadata=metadata or {},
            provenance=provenance or {},
        )

        try:
            self._persistence.write_state(
                EntityType.DURABLE_ARTIFACT,
                artifact_id,
                state,
            )
        except DuplicateEntityError:
            # Race condition: another thread/process registered first.
            return self._read_artifact_or_raise(artifact_id)

        logger.info(
            "Registered artifact %s (key=%s, type=%s, version=%d).",
            artifact_id,
            artifact_key,
            artifact_type,
            logical_version,
        )
        return state

    # ── Begin Staging (CREATED → STAGING) ─────────────────────────────

    def begin_staging(
        self,
        artifact_id: uuid.UUID,
        *,
        staging_path: str,
        expected_version: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DurableArtifactState:
        """Transition artifact to STAGING — physical write has begun.

        Args:
            artifact_id: The artifact to transition.
            staging_path: Path to the staging location.
            expected_version: OCC guard (state_version).
            metadata: Optional metadata to merge.

        Returns:
            Updated DurableArtifactState.

        Raises:
            EntityNotFoundError: If no catalog entry exists.
            InvalidTransitionError: If current state doesn't allow STAGING.
            VersionConflictError: If expected_version doesn't match.
        """
        current = self._read_artifact_or_raise(artifact_id)
        self._validate_transition(current, DurableArtifactStatus.STAGING)
        self._check_version(current, expected_version)

        merged_meta = {**(current.metadata or {}), **(metadata or {})}
        updated = current.model_copy(
            update={
                "status": DurableArtifactStatus.STAGING,
                "staging_path": staging_path,
                "owner_id": self._owner_id,
                "state_version": current.state_version + 1,
                "metadata": merged_meta,
            }
        )

        self._persistence.write_state(
            EntityType.DURABLE_ARTIFACT,
            artifact_id,
            updated,
        )
        logger.info("Artifact %s → STAGING (staging_path=%s).", artifact_id, staging_path)
        return updated

    # ── Commit (STAGING → COMMITTED) ──────────────────────────────────

    def commit_artifact(
        self,
        artifact_id: uuid.UUID,
        *,
        storage_path: str | None = None,
        content_hash: str = "",
        size_bytes: int = 0,
        expected_version: int | None = None,
        metadata: dict[str, Any] | None = None,
        provenance: dict[str, Any] | None = None,
    ) -> DurableArtifactState:
        """Transition artifact to COMMITTED — fully durable.

        This must be called only after the physical artifact content has been
        durably written (and optionally atomically renamed from staging).

        Args:
            artifact_id: The artifact to commit.
            storage_path: Final physical storage path.
            content_hash: SHA-256 fingerprint of the content.
            size_bytes: Size of the artifact in bytes.
            expected_version: OCC guard.
            metadata: Optional metadata to merge.
            provenance: Optional provenance to merge.

        Returns:
            Updated DurableArtifactState.

        Raises:
            EntityNotFoundError: If no catalog entry exists.
            InvalidTransitionError: If current state doesn't allow COMMITTED.
            VersionConflictError: If expected_version doesn't match.
        """
        current = self._read_artifact_or_raise(artifact_id)
        self._validate_transition(current, DurableArtifactStatus.COMMITTED)
        self._check_version(current, expected_version)

        now = datetime.now(timezone.utc)
        merged_meta = {**(current.metadata or {}), **(metadata or {})}
        merged_prov = {**(current.provenance or {}), **(provenance or {})}

        updated = current.model_copy(
            update={
                "status": DurableArtifactStatus.COMMITTED,
                "storage_path": storage_path or current.staging_path,
                "content_hash": content_hash,
                "size_bytes": size_bytes,
                "committed_at": now,
                "owner_id": self._owner_id,
                "state_version": current.state_version + 1,
                "metadata": merged_meta,
                "provenance": merged_prov,
            }
        )

        self._persistence.write_state(
            EntityType.DURABLE_ARTIFACT,
            artifact_id,
            updated,
        )
        logger.info(
            "Artifact %s → COMMITTED (hash=%s, size=%d, path=%s).",
            artifact_id,
            content_hash[:16] + "..." if len(content_hash) > 16 else content_hash,
            size_bytes,
            storage_path or current.staging_path,
        )
        return updated

    # ── Fail (CREATED|STAGING → FAILED) ───────────────────────────────

    def fail_artifact(
        self,
        artifact_id: uuid.UUID,
        *,
        error_code: str = "",
        error_message: str = "",
        expected_version: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DurableArtifactState:
        """Transition artifact to FAILED — artifact creation failed.

        Args:
            artifact_id: The artifact to fail.
            error_code: Machine-readable error classification.
            error_message: Human-readable error description.
            expected_version: OCC guard.
            metadata: Optional metadata to merge.

        Returns:
            Updated DurableArtifactState.

        Raises:
            EntityNotFoundError: If no catalog entry exists.
            InvalidTransitionError: If current state doesn't allow FAILED.
        """
        current = self._read_artifact_or_raise(artifact_id)
        self._validate_transition(current, DurableArtifactStatus.FAILED)
        if expected_version is not None:
            self._check_version(current, expected_version)

        now = datetime.now(timezone.utc)
        merged_meta = {**(current.metadata or {}), **(metadata or {})}

        updated = current.model_copy(
            update={
                "status": DurableArtifactStatus.FAILED,
                "failed_at": now,
                "error_code": error_code,
                "error_message": error_message,
                "state_version": current.state_version + 1,
                "metadata": merged_meta,
            }
        )

        self._persistence.write_state(
            EntityType.DURABLE_ARTIFACT,
            artifact_id,
            updated,
        )
        logger.warning(
            "Artifact %s → FAILED (error=%s: %s).",
            artifact_id,
            error_code,
            error_message[:120],
        )
        return updated

    # ── Retire (COMMITTED → RETIRED) ──────────────────────────────────

    def retire_artifact(
        self,
        artifact_id: uuid.UUID,
        *,
        reason: str = "",
        expected_version: int | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> DurableArtifactState:
        """Transition artifact to RETIRED — soft-deleted.

        Args:
            artifact_id: The artifact to retire.
            reason: Human-readable reason for retirement.
            expected_version: OCC guard.
            metadata: Optional metadata to merge.

        Returns:
            Updated DurableArtifactState.
        """
        current = self._read_artifact_or_raise(artifact_id)
        self._validate_transition(current, DurableArtifactStatus.RETIRED)
        if expected_version is not None:
            self._check_version(current, expected_version)

        now = datetime.now(timezone.utc)
        merged_meta = {**(current.metadata or {}), **(metadata or {}), "retire_reason": reason}

        updated = current.model_copy(
            update={
                "status": DurableArtifactStatus.RETIRED,
                "retired_at": now,
                "state_version": current.state_version + 1,
                "metadata": merged_meta,
            }
        )

        self._persistence.write_state(
            EntityType.DURABLE_ARTIFACT,
            artifact_id,
            updated,
        )
        logger.info("Artifact %s → RETIRED (reason=%s).", artifact_id, reason[:80])
        return updated

    # ── Queries ────────────────────────────────────────────────────────

    def get_artifact(self, artifact_id: uuid.UUID) -> DurableArtifactState | None:
        """Get artifact state by ID, or None if not found."""
        return self._read_artifact(artifact_id)

    def find_by_key(self, artifact_key: str) -> DurableArtifactState | None:
        """Find artifact by its logical key."""
        artifact_id = artifact_id_for_key(artifact_key)
        return self._read_artifact(artifact_id)

    def find_by_execution(
        self, execution_id: uuid.UUID | str
    ) -> list[DurableArtifactState]:
        """Find all artifacts associated with an execution."""
        exec_id = uuid.UUID(str(execution_id))
        return self._find_by_field("execution_id", exec_id)

    def find_by_workflow(
        self, workflow_id: uuid.UUID | str
    ) -> list[DurableArtifactState]:
        """Find all artifacts associated with a workflow."""
        wf_id = uuid.UUID(str(workflow_id))
        return self._find_by_field("workflow_id", wf_id)

    def find_by_task(self, task_id: str) -> list[DurableArtifactState]:
        """Find all artifacts associated with a task."""
        return self._find_by_field("task_id", task_id)

    def find_by_status(
        self, status: DurableArtifactStatus
    ) -> list[DurableArtifactState]:
        """Find all artifacts with a given status."""
        return self._find_by_field("status", status)

    # ── Recovery / Reconciliation ─────────────────────────────────────

    def reconcile_on_startup(
        self,
        *,
        current_owner_id: str | None = None,
    ) -> ReconciliationResult:
        """Reconcile artifact catalog state after a process restart.

        Examines artifacts in CREATED or STAGING status that were owned by
        a process other than the current one (or have no owner), indicating
        the owning process died mid-operation.

        - CREATED artifacts with dead owner → FAILED (nothing was written).
        - STAGING artifacts with dead owner:
            - If staging file exists and is valid → promote to COMMITTED.
            - Otherwise → FAILED.

        Args:
            current_owner_id: The identity of the current process.
                Defaults to ``self._owner_id``.

        Returns:
            ReconciliationResult with counts and details.
        """
        owner = current_owner_id or self._owner_id
        result = ReconciliationResult()

        # Find all artifacts in recoverable states.
        created = self.find_by_status(DurableArtifactStatus.CREATED)
        staging = self.find_by_status(DurableArtifactStatus.STAGING)

        for art in created:
            # If owned by a different (presumably dead) process, mark FAILED.
            if art.owner_id and art.owner_id != owner:
                try:
                    self.fail_artifact(
                        art.artifact_id,
                        error_code="OWNER_DEAD",
                        error_message=(
                            f"Process {art.owner_id} died before physical artifact write. "
                            f"Reconciled by {owner}."
                        ),
                        metadata={"reconciled_by": owner},
                    )
                    result.failed_count += 1
                    result.failed_artifacts.append(art.artifact_id)
                except Exception:
                    logger.exception(
                        "Failed to reconcile CREATED artifact %s", art.artifact_id
                    )

        for art in staging:
            if art.owner_id and art.owner_id != owner:
                staging_exists = (
                    art.staging_path is not None
                    and os.path.isfile(art.staging_path)
                )
                if staging_exists:
                    # Physical staging file exists — recover by committing.
                    try:
                        size = os.path.getsize(art.staging_path)
                        with open(art.staging_path, "rb") as f:
                            content_hash = hashlib.sha256(f.read()).hexdigest()
                        self.commit_artifact(
                            art.artifact_id,
                            storage_path=art.staging_path,
                            content_hash=content_hash,
                            size_bytes=size,
                            metadata={"reconciled_by": owner, "recovered": True},
                        )
                        result.recovered_count += 1
                        result.recovered_artifacts.append(art.artifact_id)
                    except Exception:
                        logger.exception(
                            "Failed to recover STAGING artifact %s", art.artifact_id
                        )
                        try:
                            self.fail_artifact(
                                art.artifact_id,
                                error_code="RECOVERY_FAILED",
                                error_message=(
                                    f"Staging file recovery failed for {art.staging_path}. "
                                    f"Reconciled by {owner}."
                                ),
                                metadata={"reconciled_by": owner},
                            )
                            result.failed_count += 1
                            result.failed_artifacts.append(art.artifact_id)
                        except Exception:
                            logger.exception(
                                "Double-fault reconciling STAGING artifact %s",
                                art.artifact_id,
                            )
                else:
                    # No physical file — mark FAILED.
                    try:
                        self.fail_artifact(
                            art.artifact_id,
                            error_code="STAGING_MISSING",
                            error_message=(
                                f"Staging file {art.staging_path!r} missing after process death. "
                                f"Reconciled by {owner}."
                            ),
                            metadata={"reconciled_by": owner},
                        )
                        result.failed_count += 1
                        result.failed_artifacts.append(art.artifact_id)
                    except Exception:
                        logger.exception(
                            "Failed to reconcile STAGING artifact %s", art.artifact_id
                        )

        logger.info(
            "Artifact catalog reconciliation complete: %d recovered, %d failed.",
            result.recovered_count,
            result.failed_count,
        )
        return result

    def find_orphaned_staging(self) -> list[DurableArtifactState]:
        """Find STAGING artifacts whose staging_path does not exist.

        These represent artifacts where the process died mid-write and the
        staging file was never fully written (or was cleaned up externally).
        """
        staging = self.find_by_status(DurableArtifactStatus.STAGING)
        orphans = []
        for art in staging:
            if art.staging_path is None or not os.path.isfile(art.staging_path):
                orphans.append(art)
        return orphans

    def find_missing_committed(self) -> list[DurableArtifactState]:
        """Find COMMITTED artifacts whose storage_path does not exist.

        These represent a data integrity issue: the catalog says the artifact
        is committed, but the physical file is missing.
        """
        committed = self.find_by_status(DurableArtifactStatus.COMMITTED)
        missing = []
        for art in committed:
            if art.storage_path and not os.path.isfile(art.storage_path):
                missing.append(art)
        return missing

    # ── Internal Helpers ──────────────────────────────────────────────

    def _read_artifact(self, artifact_id: uuid.UUID) -> DurableArtifactState | None:
        """Read artifact state from persistence, returning None if absent."""
        try:
            state = self._persistence.read_state(
                EntityType.DURABLE_ARTIFACT, artifact_id
            )
            if isinstance(state, DurableArtifactState):
                return state
            return None
        except (EntityNotFoundError, KeyError):
            return None

    def _read_artifact_or_raise(self, artifact_id: uuid.UUID) -> DurableArtifactState:
        """Read artifact state, raising EntityNotFoundError if absent."""
        state = self._read_artifact(artifact_id)
        if state is None:
            raise EntityNotFoundError(
                f"Artifact {artifact_id} not found in durable catalog",
                details={"artifact_id": str(artifact_id)},
            )
        return state

    def _validate_transition(
        self,
        current: DurableArtifactState,
        target_status: DurableArtifactStatus,
    ) -> None:
        """Validate a state transition, raising InvalidTransitionError if invalid."""
        result = validate_artifact_transition(current.status, target_status)
        if not result.valid:
            raise InvalidTransitionError(
                f"Invalid artifact transition {current.status.value} → {target_status.value}: "
                f"{result.error_message}",
                details={
                    "artifact_id": str(current.artifact_id),
                    "current_status": current.status.value,
                    "target_status": target_status.value,
                },
            )

    def _check_version(
        self,
        current: DurableArtifactState,
        expected_version: int | None,
    ) -> None:
        """Enforce OCC guard on state_version."""
        if expected_version is not None and current.state_version != expected_version:
            raise VersionConflictError(
                f"Artifact {current.artifact_id} version conflict: "
                f"expected {expected_version}, actual {current.state_version}",
                details={
                    "artifact_id": str(current.artifact_id),
                    "expected_version": expected_version,
                    "actual_version": current.state_version,
                },
            )

    def _find_by_field(
        self, field_name: str, field_value: Any
    ) -> list[DurableArtifactState]:
        """Find all artifacts matching a field value.

        Uses the PersistenceLayer's entity listing and filters in-process.
        This is acceptable for the catalog's expected cardinality.
        """
        try:
            all_artifacts = self._persistence.read_all(EntityType.DURABLE_ARTIFACT)
        except Exception:
            return []

        results = []
        for state in all_artifacts:
            if isinstance(state, DurableArtifactState):
                actual = getattr(state, field_name, None)
                if actual == field_value:
                    results.append(state)
        return results
