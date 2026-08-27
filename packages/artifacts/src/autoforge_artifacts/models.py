"""Artifact Platform domain models — Phase 12.

Defines the canonical Artifact, ArtifactVersion, lineage, publication, and
rollback models.  These extend and formalize the Phase 10 ``ArtifactRecord``
and ``ArtifactProvenance`` models without duplicating them.

Design rules
------------
- Identity is stable and deterministic (UUIDs, SHA-256 hashes).
- Versions are immutable: content change = new version.
- Provenance captures who/what/when/from-what without embedding secrets.
- State transitions are deterministic — no AI controls artifact truth.
- Models are Pydantic frozen (immutable) value objects.
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    return uuid.uuid4()


# ── Artifact State ─────────────────────────────────────────────────────────


class ArtifactState(str, Enum):
    """Explicit lifecycle state for a canonical artifact.

    Transitions (deterministic):
        CREATED    → VERSIONED
        VERSIONED  → REVIEWABLE | APPROVED | PUBLISHED
        REVIEWABLE → APPROVED | VERSIONED
        APPROVED   → PUBLISHED | VERSIONED
        PUBLISHED  → SUPERSEDED | VERSIONED
        SUPERSEDED (terminal unless re-published via new version)
    """

    CREATED = "created"
    """Artifact registered; no version yet."""

    VERSIONED = "versioned"
    """At least one immutable version exists."""

    REVIEWABLE = "reviewable"
    """Artifact is ready for review."""

    APPROVED = "approved"
    """Artifact passed review gates."""

    PUBLISHED = "published"
    """Artifact is an authoritative published output."""

    SUPERSEDED = "superseded"
    """A newer published version has replaced this one."""


# Deterministic state transition table.
VALID_STATE_TRANSITIONS: dict[ArtifactState, frozenset[ArtifactState]] = {
    ArtifactState.CREATED: frozenset({ArtifactState.VERSIONED}),
    ArtifactState.VERSIONED: frozenset({
        ArtifactState.REVIEWABLE,
        ArtifactState.APPROVED,
        ArtifactState.PUBLISHED,
    }),
    ArtifactState.REVIEWABLE: frozenset({
        ArtifactState.APPROVED,
        ArtifactState.VERSIONED,
    }),
    ArtifactState.APPROVED: frozenset({
        ArtifactState.PUBLISHED,
        ArtifactState.VERSIONED,
    }),
    ArtifactState.PUBLISHED: frozenset({
        ArtifactState.SUPERSEDED,
        ArtifactState.VERSIONED,
    }),
    ArtifactState.SUPERSEDED: frozenset({ArtifactState.VERSIONED}),
}


def is_valid_state_transition(current: ArtifactState, target: ArtifactState) -> bool:
    """Check whether a state transition is valid."""
    return target in VALID_STATE_TRANSITIONS.get(current, frozenset())


# ── Canonical Artifact Type ────────────────────────────────────────────────


class CanonicalArtifactType(str, Enum):
    """Full artifact type taxonomy.

    Extends Phase 10's execution-scoped ``ArtifactType`` with the complete
    engineering output taxonomy required by the Artifact Platform.
    """

    SOURCE = "source"
    GENERATED_CODE = "generated_code"
    CONFIGURATION = "configuration"
    TEST_RESULT = "test_result"
    BUILD_OUTPUT = "build_output"
    REVIEW_REPORT = "review_report"
    DIAGNOSIS_REPORT = "diagnosis_report"
    PLAN = "plan"
    ARCHITECTURE = "architecture"
    RESEARCH = "research"
    DOCUMENTATION = "documentation"
    DEPLOYMENT = "deployment"
    DIFF = "diff"
    EXECUTION_LOG = "execution_log"
    EVALUATION_REPORT = "evaluation_report"
    REPAIR_PLAN = "repair_plan"
    OTHER = "other"


# Mapping from Phase 10 ArtifactType values to canonical types.
_PHASE10_TYPE_MAP: dict[str, CanonicalArtifactType] = {
    "source_code": CanonicalArtifactType.SOURCE,
    "diff": CanonicalArtifactType.DIFF,
    "test_report": CanonicalArtifactType.TEST_RESULT,
    "execution_log": CanonicalArtifactType.EXECUTION_LOG,
    "evaluation_report": CanonicalArtifactType.EVALUATION_REPORT,
    "diagnosis_report": CanonicalArtifactType.DIAGNOSIS_REPORT,
    "repair_plan": CanonicalArtifactType.REPAIR_PLAN,
    "summary": CanonicalArtifactType.DOCUMENTATION,
    "metric": CanonicalArtifactType.OTHER,
}


def map_phase10_artifact_type(phase10_value: str) -> CanonicalArtifactType:
    """Map a Phase 10 ``ArtifactType`` string value to a canonical type."""
    return _PHASE10_TYPE_MAP.get(phase10_value, CanonicalArtifactType.OTHER)


# ── Content Hashing ────────────────────────────────────────────────────────

HASH_ALGORITHM = "sha256"
"""Explicit, deterministic hash algorithm used for content identity."""


def compute_content_hash(content: str | bytes) -> str:
    """Compute deterministic SHA-256 hash of content.

    Content is normalised to UTF-8 bytes before hashing.
    """
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


# ── Canonical Provenance ───────────────────────────────────────────────────


class CanonicalProvenance(BaseModel):
    """Canonical provenance model for the Artifact Platform.

    Extends Phase 10's ``ArtifactProvenance`` with additional lifecycle
    identifiers required for full traceability.

    No secrets are stored in provenance metadata.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: str | None = Field(default=None)
    worker_id: str | None = Field(default=None)
    workflow_id: uuid.UUID | None = Field(default=None)
    project_id: uuid.UUID | None = Field(default=None)
    execution_id: str | None = Field(default=None)
    review_id: str | None = Field(default=None)
    parent_artifact_id: uuid.UUID | None = Field(default=None)
    attempt_id: str | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)
    attempt_number: int = Field(default=1, ge=1)
    iteration: int = Field(default=1, ge=1)
    created_at: datetime = Field(default_factory=_utc_now)
    actor: str | None = Field(default=None, description="Who/what produced the artifact.")
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Artifact Version ──────────────────────────────────────────────────────


class ArtifactVersion(BaseModel):
    """An immutable version of an artifact.

    Once created, version content and metadata are never mutated.
    Content changes produce a new ``ArtifactVersion`` with a new
    ``version_id`` and incremented ``version_number``.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    version_id: uuid.UUID = Field(default_factory=_new_uuid)
    artifact_id: uuid.UUID = Field(...)
    version_number: int = Field(..., ge=1)
    parent_version_id: uuid.UUID | None = Field(default=None)
    content: str = Field(default="")
    content_hash: str = Field(default="")
    size_bytes: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str | None = Field(default=None)
    provenance: CanonicalProvenance = Field(default_factory=CanonicalProvenance)
    is_rollback: bool = Field(
        default=False,
        description="True if this version was created by a rollback operation.",
    )
    rollback_source_version_id: uuid.UUID | None = Field(
        default=None,
        description="The version this rollback restored from, if applicable.",
    )

    @classmethod
    def create(
        cls,
        *,
        artifact_id: uuid.UUID,
        version_number: int,
        content: str,
        provenance: CanonicalProvenance | None = None,
        parent_version_id: uuid.UUID | None = None,
        created_by: str | None = None,
        is_rollback: bool = False,
        rollback_source_version_id: uuid.UUID | None = None,
    ) -> ArtifactVersion:
        """Factory method that computes content hash and size."""
        content_bytes = content.encode("utf-8")
        return cls(
            artifact_id=artifact_id,
            version_number=version_number,
            parent_version_id=parent_version_id,
            content=content,
            content_hash=compute_content_hash(content_bytes),
            size_bytes=len(content_bytes),
            provenance=provenance or CanonicalProvenance(),
            created_by=created_by,
            is_rollback=is_rollback,
            rollback_source_version_id=rollback_source_version_id,
        )


# ── Canonical Artifact ────────────────────────────────────────────────────


class Artifact(BaseModel):
    """A canonical engineering artifact with stable identity.

    The Artifact model captures identity and lifecycle state without
    embedding domain-specific business logic.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    artifact_id: uuid.UUID = Field(default_factory=_new_uuid)
    name: str = Field(..., min_length=1)
    artifact_type: CanonicalArtifactType = Field(...)
    state: ArtifactState = Field(default=ArtifactState.CREATED)
    project_id: uuid.UUID | None = Field(default=None)
    workflow_id: uuid.UUID | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)
    current_version_id: uuid.UUID | None = Field(default=None)
    version_count: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=_utc_now)
    created_by: str | None = Field(default=None)
    path: str | None = Field(default=None, description="Workspace path if file-based.")
    metadata: dict[str, Any] = Field(default_factory=dict)

    def with_state(self, new_state: ArtifactState) -> Artifact:
        """Return a copy with updated state (immutable update)."""
        return self.model_copy(update={"state": new_state})

    def with_version(
        self,
        version_id: uuid.UUID,
        version_count: int,
    ) -> Artifact:
        """Return a copy with updated current version (immutable update)."""
        return self.model_copy(update={
            "current_version_id": version_id,
            "version_count": version_count,
            "state": ArtifactState.VERSIONED,
        })


# ── Lineage ────────────────────────────────────────────────────────────────


class ArtifactLineageEntry(BaseModel):
    """A single edge in the artifact lineage graph.

    Represents a parent→child derivation relationship between artifacts
    or artifact versions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    lineage_id: uuid.UUID = Field(default_factory=_new_uuid)
    parent_artifact_id: uuid.UUID = Field(...)
    parent_version_id: uuid.UUID | None = Field(default=None)
    child_artifact_id: uuid.UUID = Field(...)
    child_version_id: uuid.UUID | None = Field(default=None)
    transformation: str = Field(
        default="derived",
        description="Action that produced the child from the parent.",
    )
    actor: str | None = Field(default=None)
    execution_id: str | None = Field(default=None)
    workflow_id: uuid.UUID | None = Field(default=None)
    correlation_id: uuid.UUID | None = Field(default=None)
    timestamp: datetime = Field(default_factory=_utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Publication ────────────────────────────────────────────────────────────


class PublicationRecord(BaseModel):
    """Record of a controlled artifact publication."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    publication_id: uuid.UUID = Field(default_factory=_new_uuid)
    artifact_id: uuid.UUID = Field(...)
    version_id: uuid.UUID = Field(...)
    published_by: str | None = Field(default=None)
    published_at: datetime = Field(default_factory=_utc_now)
    destination: str = Field(default="default")
    correlation_id: uuid.UUID | None = Field(default=None)
    requires_hitl: bool = Field(default=False)
    approved_by: str | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)


# ── Rollback ──────────────────────────────────────────────────────────────


class RollbackRecord(BaseModel):
    """Record of a history-preserving rollback operation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    rollback_id: uuid.UUID = Field(default_factory=_new_uuid)
    artifact_id: uuid.UUID = Field(...)
    from_version_id: uuid.UUID = Field(...)
    to_version_id: uuid.UUID = Field(
        ..., description="The target version being rolled back to."
    )
    new_version_id: uuid.UUID = Field(
        ..., description="The new version created by the rollback."
    )
    reason: str = Field(default="")
    rolled_back_by: str | None = Field(default=None)
    rolled_back_at: datetime = Field(default_factory=_utc_now)
    correlation_id: uuid.UUID | None = Field(default=None)
    metadata: dict[str, Any] = Field(default_factory=dict)
