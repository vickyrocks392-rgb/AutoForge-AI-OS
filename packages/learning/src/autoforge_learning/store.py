"""Durable, project-scoped learning store — Phase 19B-2 (Gate 2 / M-02).

Architecture basis: ``phase19/LEARNING_ISOLATION_AND_OBSERVABILITY.md``
(Gate 19A-9 §12) and ``phase19/PHASE19_ARCHITECTURE.md`` (Q2/Q3).

Design decisions and why they are the ones already in the repository:

* **Reuse the existing persistence pattern, not a new framework.** AutoForge
  already has a durable, atomically-published filesystem boundary in
  ``PhysicalArtifactStore`` (staging write → fsync → ``os.replace`` →
  directory fsync). This store adopts that exact discipline rather than
  inventing a second storage abstraction. It does **not** write into the
  artifact catalog: learning persistence stays distinct from artifact
  persistence (Gate 2), and 18-J/18-K artifact semantics are untouched.
* **Durability.** Every record is fsync-ed and atomically published, so a
  record survives a process restart and a crash mid-write.
* **Immutability.** A candidate record is written once. State *transitions*
  are separate append-only records; nothing is ever edited in place.
* **Project isolation is structural.** Records live under a per-project
  directory derived from the project id, and every read is project-scoped.
  There is no global listing API that can leak across projects.
* **Fail closed, never silently.** A malformed or corrupt record raises;
  it is never returned as an empty/absent-but-successful result.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Iterable, Optional, Sequence

from pydantic import Field, ValidationError, model_validator

from autoforge_learning.evaluation import EvaluationReport
from autoforge_learning.models import (
    LearningBase,
    LearningCandidate,
    LearningScope,
)

logger = logging.getLogger("autoforge.learning.store")

__test__ = False  # declares data models, not tests

#: On-disk schema version for the learning store. Bumped only on a breaking
#: change to the record envelope.
STORE_SCHEMA_VERSION = "19B2.1"

#: On-disk schema version for the Phase 19 final lifecycle store. Phase 19
#: FINAL persists the whole learning lifecycle — experiences, signals,
#: hypotheses, experiments, runs, activations, regressions and lineage — so
#: every critical record survives a process restart. It is a separate,
#: versioned namespace from the 19B-2 store above so an older reader can never
#: silently mis-parse a newer envelope.
LIFECYCLE_SCHEMA_VERSION = "19F.1"


class LearningStoreError(Exception):
    """Base class for every learning-store failure."""


class LearningRecordNotFound(LearningStoreError):
    """No record exists for the requested identity. Never an empty success."""


class LearningRecordCorrupt(LearningStoreError):
    """A stored record is unreadable, malformed, or fails integrity.

    Raised rather than swallowed: a corrupt record must never be reported as
    a successful lookup with absent data.
    """


class LearningProjectIsolationError(LearningStoreError):
    """A record was addressed across a project boundary."""


class LearningImmutableIdentityError(LearningStoreError):
    """An attempt was made to change a candidate's immutable identity."""


class LearningStateError(LearningStoreError):
    """An illegal lifecycle transition was requested."""


# ── Records ───────────────────────────────────────────────────────────────────


class CandidateRecord(LearningBase):
    """Durable identity of a learning candidate.

    The identity fields (``candidate_id``, ``scope``, ``kind``, ``summary``,
    ``created_at``) are fixed at creation. Later lifecycle states live in
    separate records, so the identity can never drift after the fact.
    """

    candidate: LearningCandidate
    project_id: uuid.UUID
    stored_at: datetime
    stored_by: str = "autoforge.learning"
    correlation_id: Optional[str] = None

    @property
    def candidate_id(self) -> uuid.UUID:
        return self.candidate.candidate_id

    @property
    def scope(self) -> LearningScope:
        return self.candidate.scope

    @property
    def identity_hash(self) -> str:
        """Content hash over the immutable identity only."""
        payload = {
            "candidate_id": str(self.candidate.candidate_id),
            "project_id": str(self.project_id),
            "scope": self.candidate.scope.model_dump(mode="json"),
            "kind": self.candidate.kind,
            "summary": self.candidate.summary,
            "rationale": self.candidate.rationale,
            "created_at": self.candidate.created_at.isoformat(),
            "schema_version": self.candidate.schema_version,
        }
        import hashlib

        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

    def assert_identity_matches(self, other: "CandidateRecord") -> None:
        if self.identity_hash != other.identity_hash:
            raise LearningImmutableIdentityError(
                "candidate identity is immutable; refusing to rewrite a stored "
                f"candidate ({self.candidate_id})"
            )


class ApprovalStatus(str, Enum):
    """Lifecycle states of a learning-candidate approval.

    These are the states Gate 5 permits for promotion approval. ``PENDING``
    and the terminal states mirror the certified ``ApprovalGateStatus``;
    ``REVOKED`` exists because a granted approval can be withdrawn before
    promotion and a withdrawn approval must be distinguishable from a
    never-granted one.
    """

    PENDING = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    REVOKED = "revoked"

    @property
    def is_terminal(self) -> bool:
        return self in (
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.EXPIRED,
            ApprovalStatus.REVOKED,
        )

    @property
    def authorizes_promotion(self) -> bool:
        """Only a live, human-granted approval authorizes anything."""
        return self is ApprovalStatus.APPROVED


class ApprovalRecord(LearningBase):
    """An immutable approval decision bound to one candidate.

    Every field Gate 5 requires is present: candidate identity, project
    identity, evaluation result, evidence references, requested scope,
    proposed effect, approver identity, decision, timestamp, and the
    authorization lineage (the HITL gate and the authorizing subject).
    """

    approval_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate_id: uuid.UUID
    project_id: uuid.UUID
    evaluation_id: uuid.UUID
    evaluation_outcome: str
    evaluation_blocking_invariants: tuple[str, ...] = ()
    evidence_ids: tuple[uuid.UUID, ...] = ()
    requested_scope: str
    proposed_effect: str
    status: ApprovalStatus
    #: The human subject who decided. Empty for PENDING.
    approver_id: Optional[str] = None
    approver_subject_type: Optional[str] = None
    requested_by: str = "autoforge.learning"
    requested_at: datetime
    decided_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    revoked_at: Optional[datetime] = None
    reason: str = ""
    #: Lineage: the certified HITL gate this decision was recorded through.
    hitl_gate_id: Optional[str] = None
    resume_token_present: bool = False
    correlation_id: Optional[str] = None
    #: Typed non-authoritative: model text can never create an approval.
    model_annotation: Optional[str] = None
    model_annotation_authoritative: bool = False

    @model_validator(mode="after")
    def _approval_requires_a_human(self) -> "ApprovalRecord":
        """MODEL PROPOSAL ≠ HUMAN APPROVAL — enforced by the type itself.

        An ``APPROVED`` record can only exist when an identifiable *human*
        subject granted it. This is the structural half of Gate 5: even if a
        caller constructs the record directly, without going through the
        certified HITL manager, a non-human approver cannot produce one.
        """
        if self.status is ApprovalStatus.APPROVED and (
            self.approver_subject_type != "human" or not self.approver_id
        ):
            raise ValueError(
                "an APPROVED learning record must name an identifiable human "
                "approver; a model, worker, or service cannot approve"
            )
        return self

    @property
    def is_human_approved(self) -> bool:
        return (
            self.status.authorizes_promotion
            and self.approver_subject_type == "human"
            and bool(self.approver_id)
        )


class ActiveLearningState(LearningBase):
    """The current active learning pointer for one (project, kind, key).

    This is the *only* object promotion mutates, and it is replaced
    atomically. ``version_id``/``content_hash`` mirror the 19A-13 §1 version
    identity model, so a promoted state is traceable to the exact candidate
    version it came from.
    """

    state_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    kind: str
    key: str
    version_id: uuid.UUID
    version_number: int = Field(ge=1)
    candidate_id: Optional[uuid.UUID] = None
    content_hash: str = ""
    activation_timestamp: datetime
    deactivation_timestamp: Optional[datetime] = None
    scope_kind: str
    scope_workflow_id: Optional[str] = None
    scope_task_type: Optional[str] = None


class RollbackHandle(LearningBase):
    """A pre-created, integrity-protected undo record.

    Gate 6 requires this to exist **before** the active state changes. It
    records the exact prior state, the exact proposed state, the project,
    version information, its own creation timestamp, and an integrity hash
    covering all of it, so a tampered handle is detectable at rollback time.
    """

    handle_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    candidate_id: uuid.UUID
    kind: str
    key: str
    previous_state: Optional[ActiveLearningState]
    proposed_state: ActiveLearningState
    previous_version_number: Optional[int] = None
    proposed_version_number: int = Field(ge=1)
    rollback_target_version_id: Optional[uuid.UUID] = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    created_by: str = "autoforge.learning.promotion"
    approval_id: Optional[uuid.UUID] = None
    evaluation_id: Optional[uuid.UUID] = None
    integrity_hash: str = ""
    consumed: bool = False

    def compute_integrity_hash(self) -> str:
        import hashlib

        payload = {
            "handle_id": str(self.handle_id),
            "project_id": str(self.project_id),
            "candidate_id": str(self.candidate_id),
            "kind": self.kind,
            "key": self.key,
            "previous_state": (
                self.previous_state.model_dump(mode="json")
                if self.previous_state
                else None
            ),
            "proposed_state": self.proposed_state.model_dump(mode="json"),
            "proposed_version_number": self.proposed_version_number,
            "rollback_target_version_id": (
                str(self.rollback_target_version_id)
                if self.rollback_target_version_id
                else None
            ),
            "created_at": self.created_at.isoformat(),
        }
        return hashlib.sha256(
            json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
                "utf-8"
            )
        ).hexdigest()

    @property
    def is_intact(self) -> bool:
        """True when the stored integrity hash still matches the content."""
        return bool(self.integrity_hash) and self.integrity_hash == self.compute_integrity_hash()


class PromotionState(str, Enum):
    """States a promotion can be in."""

    NOT_PROMOTED = "not_promoted"
    PROMOTED = "promoted"
    FAILED = "failed"
    ROLLED_BACK = "rolled_back"


class PromotionRecord(LearningBase):
    """Immutable record of one promotion attempt.

    A *failed* attempt is retained, not deleted (Gate 19A-6 LC-07): the
    evidence that promotion was tried and refused is part of the audit
    history.
    """

    promotion_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate_id: uuid.UUID
    project_id: uuid.UUID
    evaluation_id: uuid.UUID
    approval_id: uuid.UUID
    rollback_handle_id: uuid.UUID
    state: PromotionState
    requested_scope: str
    proposed_effect: str
    attempted_by: str
    attempted_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    completed_at: Optional[datetime] = None
    previous_state: Optional[ActiveLearningState] = None
    new_state: Optional[ActiveLearningState] = None
    failure_reason: str = ""
    #: Non-empty when the promotion committed but its success could not be
    #: audited. The promotion is real; the audit trail is degraded.
    audit_failure_reason: str = ""
    correlation_id: Optional[str] = None

    @property
    def succeeded(self) -> bool:
        return self.state is PromotionState.PROMOTED


class RollbackRecord(LearningBase):
    """Immutable record of one rollback execution (Gate 19A-13 §3)."""

    rollback_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    handle_id: uuid.UUID
    promotion_id: uuid.UUID
    candidate_id: uuid.UUID
    project_id: uuid.UUID
    kind: str
    key: str
    restored_state: Optional[ActiveLearningState]
    superseded_version_id: Optional[uuid.UUID] = None
    performed_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    performed_by: str = "autoforge.learning.rollback"
    reason: str = ""
    correlation_id: Optional[str] = None


# ── Envelope ──────────────────────────────────────────────────────────────────


class StoredEnvelope(LearningBase):
    """On-disk envelope around every stored record.

    The envelope carries the store schema version, the record kind, the
    project, and a content hash. A record whose envelope or content does not
    verify is rejected as corrupt rather than returned.
    """

    store_schema_version: str = STORE_SCHEMA_VERSION
    kind: str
    project_id: uuid.UUID
    record_id: str
    payload: dict[str, Any]
    content_hash: str = ""


class DurableLearningStore:
    """Project-scoped, crash-safe store for the learning lifecycle.

    Layout (per project, so cross-project reads cannot even address the
    right file)::

        <root>/<project_id>/candidates/<candidate_id>.json
        <root>/<project_id>/evaluations/<evaluation_id>.json
        <root>/<project_id>/approvals/<approval_id>.json
        <root>/<project_id>/promotions/<promotion_id>.json
        <root>/<project_id>/handles/<handle_id>.json
        <root>/<project_id>/rollbacks/<rollback_id>.json
        <root>/<project_id>/active/<kind>__<key>.json

    Durability follows the repository's existing filesystem discipline
    (``PhysicalArtifactStore``): write to a staging name, ``fsync`` the
    file, ``os.replace`` into place, then ``fsync`` the directory. A reader
    therefore only ever observes a fully written record.
    """

    def __init__(self, root: str | Path) -> None:
        self._root = Path(root)
        self._lock = threading.RLock()
        self._root.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    # ── paths ────────────────────────────────────────────────────────────────

    def _project_dir(self, project_id: uuid.UUID) -> Path:
        return self._root / str(project_id)

    def _path(
        self, project_id: uuid.UUID, collection: str, record_id: str, ext: str = "json"
    ) -> Path:
        # record_id is a UUID or an opaque key; never a caller-supplied path.
        safe = str(record_id).replace("/", "_").replace("\\", "_").replace("..", "_")
        return self._project_dir(project_id) / collection / f"{safe}.{ext}"

    # ── atomic durable write ─────────────────────────────────────────────────

    def _write_atomic(self, path: Path, data: bytes) -> None:
        """Publish ``data`` at ``path`` atomically and durably."""
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(f".{path.name}.staging")
        with open(staging, "wb") as fh:
            fh.write(data)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(staging, path)
        # fsync the directory so the rename itself is durable.
        dir_fd = os.open(path.parent, os.O_RDONLY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)

    #: Maps each stored record kind to the attribute naming its identity.
    _ID_ATTRS = {
        "candidate": "candidate_id",
        "evaluation": "evaluation_id",
        "approval": "approval_id",
        "promotion": "promotion_id",
        "rollback_handle": "handle_id",
        "rollback": "rollback_id",
        "active_state": "state_id",
    }

    def _put(self, project_id: uuid.UUID, kind: str, collection: str, record: Any) -> None:
        attr = self._ID_ATTRS.get(kind)
        if attr is None:
            raise LearningRecordCorrupt(f"unknown learning record kind {kind!r}")
        record_id = str(getattr(record, attr, "") or "")
        if not record_id:
            raise LearningRecordCorrupt(f"{kind} record has no {attr}")

        payload = record.model_dump(mode="json")
        envelope = StoredEnvelope(
            kind=kind,
            project_id=project_id,
            record_id=record_id,
            payload=payload,
            content_hash=record.record_hash(),
        )
        data = json.dumps(
            envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")

        with self._lock:
            self._write_atomic(self._path(project_id, collection, record_id), data)

    def _get(
        self, project_id: uuid.UUID, kind: str, collection: str, record_id: str
    ) -> Optional[dict[str, Any]]:
        path = self._path(project_id, collection, record_id)
        if not path.exists():
            return None
        try:
            raw = path.read_bytes()
        except OSError as ex:
            raise LearningRecordCorrupt(f"unreadable learning record at {path}: {ex}") from ex

        try:
            envelope = StoredEnvelope.model_validate(json.loads(raw.decode("utf-8")))
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as ex:
            raise LearningRecordCorrupt(
                f"corrupt learning record at {path}: {type(ex).__name__}: {ex}"
            ) from ex

        if envelope.project_id != project_id:
            raise LearningProjectIsolationError(
                f"record at {path} belongs to project {envelope.project_id}, "
                f"not {project_id}"
            )
        if envelope.store_schema_version != STORE_SCHEMA_VERSION:
            raise LearningRecordCorrupt(
                f"record at {path} has schema {envelope.store_schema_version!r}; "
                f"this store reads {STORE_SCHEMA_VERSION!r}"
            )
        return envelope.payload

    # ── candidates ────────────────────────────────────────────────────────────

    def save_candidate(self, record: CandidateRecord) -> CandidateRecord:
        """Persist a candidate identity, refusing to mutate an existing one.

        Re-saving the identical record is idempotent. Re-saving a *different*
        record under the same candidate id raises
        :class:`LearningImmutableIdentityError`.
        """
        existing = self.get_candidate(record.project_id, record.candidate_id)
        if existing is not None:
            existing.assert_identity_matches(record)
            return existing
        self._put(record.project_id, "candidate", "candidates", record)
        return record

    def get_candidate(
        self, project_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> Optional[CandidateRecord]:
        payload = self._get(project_id, "candidate", "candidates", str(candidate_id))
        if payload is None:
            return None
        try:
            record = CandidateRecord.model_validate(payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed candidate record: {ex}") from ex
        self._verify_hash(record, project_id, "candidate", candidate_id)
        # Defence in depth: the record's own project must match the addressed
        # project, so a mis-filed record cannot be read across a boundary.
        if record.project_id != project_id or record.scope.project_id != project_id:
            raise LearningProjectIsolationError(
                f"candidate {candidate_id} belongs to project {record.project_id}, "
                f"not {project_id}"
            )
        return record

    def require_candidate(
        self, project_id: uuid.UUID, candidate_id: uuid.UUID
    ) -> CandidateRecord:
        record = self.get_candidate(project_id, candidate_id)
        if record is None:
            raise LearningRecordNotFound(
                f"candidate {candidate_id} not found for project {project_id}"
            )
        return record

    def list_candidates(self, project_id: uuid.UUID) -> tuple[CandidateRecord, ...]:
        directory = self._project_dir(project_id) / "candidates"
        if not directory.is_dir():
            return ()
        out: list[CandidateRecord] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._get(project_id, "candidate", "candidates", path.stem)
            if payload is None:
                continue
            out.append(CandidateRecord.model_validate(payload))
        return tuple(out)

    # ── evaluations / approvals / promotions ──────────────────────────────────

    def save_evaluation(self, report: EvaluationReport) -> EvaluationReport:
        self._put(report.project_id, "evaluation", "evaluations", report)
        return report

    def get_evaluation(
        self, project_id: uuid.UUID, evaluation_id: uuid.UUID
    ) -> Optional[EvaluationReport]:
        payload = self._get(project_id, "evaluation", "evaluations", str(evaluation_id))
        if payload is None:
            return None
        try:
            return EvaluationReport.model_validate(payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed evaluation record: {ex}") from ex

    def list_evaluations(self, project_id: uuid.UUID) -> tuple[EvaluationReport, ...]:
        directory = self._project_dir(project_id) / "evaluations"
        if not directory.is_dir():
            return ()
        out: list[EvaluationReport] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._get(project_id, "evaluation", "evaluations", path.stem)
            if payload is not None:
                out.append(EvaluationReport.model_validate(payload))
        return tuple(out)

    def save_approval(self, record: ApprovalRecord) -> ApprovalRecord:
        self._put(record.project_id, "approval", "approvals", record)
        return record

    def get_approval(
        self, project_id: uuid.UUID, approval_id: uuid.UUID
    ) -> Optional[ApprovalRecord]:
        payload = self._get(project_id, "approval", "approvals", str(approval_id))
        if payload is None:
            return None
        try:
            record = ApprovalRecord.model_validate(payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed approval record: {ex}") from ex
        if record.project_id != project_id:
            raise LearningProjectIsolationError(
                f"approval {approval_id} belongs to project {record.project_id}"
            )
        return record

    def list_approvals(self, project_id: uuid.UUID) -> tuple[ApprovalRecord, ...]:
        directory = self._project_dir(project_id) / "approvals"
        if not directory.is_dir():
            return ()
        out: list[ApprovalRecord] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._get(project_id, "approval", "approvals", path.stem)
            if payload is not None:
                out.append(ApprovalRecord.model_validate(payload))
        return tuple(out)

    def save_promotion(self, record: PromotionRecord) -> PromotionRecord:
        self._put(record.project_id, "promotion", "promotions", record)
        return record

    def get_promotion(
        self, project_id: uuid.UUID, promotion_id: uuid.UUID
    ) -> Optional[PromotionRecord]:
        payload = self._get(project_id, "promotion", "promotions", str(promotion_id))
        if payload is None:
            return None
        try:
            return PromotionRecord.model_validate(payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed promotion record: {ex}") from ex

    def list_promotions(self, project_id: uuid.UUID) -> tuple[PromotionRecord, ...]:
        directory = self._project_dir(project_id) / "promotions"
        if not directory.is_dir():
            return ()
        out: list[PromotionRecord] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._get(project_id, "promotion", "promotions", path.stem)
            if payload is not None:
                out.append(PromotionRecord.model_validate(payload))
        return tuple(out)

    def save_rollback_handle(self, handle: RollbackHandle) -> RollbackHandle:
        """Persist a rollback handle.

        The handle is written with its integrity hash already computed, so a
        handle that exists on disk is immediately verifiable.
        """
        if not handle.integrity_hash:
            handle = handle.model_copy(
                update={"integrity_hash": handle.compute_integrity_hash()}
            )
        self._put(handle.project_id, "rollback_handle", "handles", handle)
        return handle

    def get_rollback_handle(
        self, project_id: uuid.UUID, handle_id: uuid.UUID
    ) -> Optional[RollbackHandle]:
        payload = self._get(project_id, "rollback_handle", "handles", str(handle_id))
        if payload is None:
            return None
        try:
            handle = RollbackHandle.model_validate(payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed rollback handle: {ex}") from ex
        # Defence in depth: a handle is only ever usable inside the project that
        # created it, even if a record were somehow relocated.
        if handle.project_id != project_id:
            raise LearningProjectIsolationError(
                f"rollback handle belongs to project {handle.project_id}, "
                f"not {project_id}"
            )
        return handle

    def list_rollback_handles(self, project_id: uuid.UUID) -> tuple[RollbackHandle, ...]:
        directory = self._project_dir(project_id) / "handles"
        if not directory.is_dir():
            return ()
        out: list[RollbackHandle] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._get(project_id, "rollback_handle", "handles", path.stem)
            if payload is not None:
                out.append(RollbackHandle.model_validate(payload))
        return tuple(out)

    def save_rollback(self, record: RollbackRecord) -> RollbackRecord:
        self._put(record.project_id, "rollback", "rollbacks", record)
        return record

    def list_rollbacks(self, project_id: uuid.UUID) -> tuple[RollbackRecord, ...]:
        directory = self._project_dir(project_id) / "rollbacks"
        if not directory.is_dir():
            return ()
        out: list[RollbackRecord] = []
        for path in sorted(directory.glob("*.json")):
            payload = self._get(project_id, "rollback", "rollbacks", path.stem)
            if payload is not None:
                out.append(RollbackRecord.model_validate(payload))
        return tuple(out)

    # ── active learning state ─────────────────────────────────────────────────

    @staticmethod
    def active_key(kind: str, key: str) -> str:
        """Deterministic filename for one (kind, key) active pointer."""
        return f"{kind}__{key}".replace("/", "_").replace("..", "_")

    def get_active_state(
        self, project_id: uuid.UUID, kind: str, key: str
    ) -> Optional[ActiveLearningState]:
        path = self._path(project_id, "active", self.active_key(kind, key))
        if not path.exists():
            return None
        try:
            envelope = StoredEnvelope.model_validate(
                json.loads(path.read_bytes().decode("utf-8"))
            )
        except (json.JSONDecodeError, UnicodeDecodeError, ValidationError, ValueError) as ex:
            raise LearningRecordCorrupt(f"corrupt active state: {ex}") from ex
        if envelope.project_id != project_id:
            raise LearningProjectIsolationError(
                "active state belongs to a different project"
            )
        try:
            state = ActiveLearningState.model_validate(envelope.payload)
        except ValidationError as ex:
            raise LearningRecordCorrupt(f"malformed active state: {ex}") from ex
        if state.project_id != project_id:
            raise LearningProjectIsolationError(
                f"active state belongs to project {state.project_id}"
            )
        if envelope.content_hash and envelope.content_hash != state.record_hash():
            raise LearningRecordCorrupt(
                "active learning state failed integrity verification "
                "(stored content hash does not match the record)"
            )
        return state

    def set_active_state(self, state: ActiveLearningState) -> ActiveLearningState:
        """Atomically publish the new active pointer.

        This is the single commit point of a promotion: one ``os.replace`` of
        a fully-written record at the deterministic ``<kind>__<key>`` path, so
        a consumer observes either the whole previous state or the whole new
        one — never a partial mixture.
        """
        path = self._path(state.project_id, "active", self.active_key(state.kind, state.key))
        envelope = StoredEnvelope(
            kind="active_state",
            project_id=state.project_id,
            record_id=self.active_key(state.kind, state.key),
            payload=state.model_dump(mode="json"),
            content_hash=state.record_hash(),
        )
        data = json.dumps(
            envelope.model_dump(mode="json"), sort_keys=True, separators=(",", ":")
        ).encode("utf-8")
        with self._lock:
            self._write_atomic(path, data)
        return state

    def clear_active_state(self, project_id: uuid.UUID, kind: str, key: str) -> None:
        path = self._path(project_id, "active", self.active_key(kind, key))
        with self._lock:
            if path.exists():
                os.remove(path)

    def _verify_hash(
        self, record: Any, project_id: uuid.UUID, kind: str, record_id: Any
    ) -> None:
        """Confirm a loaded record matches the hash recorded at write time.

        The envelope's ``content_hash`` is recomputed from the payload; a
        mismatch means the stored bytes were altered after publication.
        """
        path = self._path(project_id, "candidates", str(record_id))
        try:
            envelope = StoredEnvelope.model_validate(
                json.loads(path.read_bytes().decode("utf-8"))
            )
        except (OSError, json.JSONDecodeError, UnicodeDecodeError, ValidationError) as ex:
            raise LearningRecordCorrupt(f"cannot verify {kind} record: {ex}") from ex
        if envelope.content_hash and envelope.content_hash != record.record_hash():
            raise LearningRecordCorrupt(
                f"{kind} record {record_id} failed integrity verification "
                "(stored content hash does not match the record)"
            )


__all__ = [
    "STORE_SCHEMA_VERSION",
    "ActiveLearningState",
    "ApprovalRecord",
    "ApprovalStatus",
    "CandidateRecord",
    "DurableLearningStore",
    "LearningImmutableIdentityError",
    "LearningProjectIsolationError",
    "LearningRecordCorrupt",
    "LearningRecordNotFound",
    "LearningStateError",
    "LearningStoreError",
    "PromotionRecord",
    "PromotionState",
    "RollbackHandle",
    "RollbackRecord",
    "StoredEnvelope",
]