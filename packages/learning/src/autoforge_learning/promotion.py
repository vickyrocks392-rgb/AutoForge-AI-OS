"""Atomic promotion and deterministic rollback — Phase 19B-2 (Gates 6–8).

Architecture basis: ``phase19/LEARNING_LIFECYCLE.md`` (LC-05, LC-06) and
``phase19/ROLLBACK_AND_VERSIONING.md`` (RB-01..RB-08).

The order of operations is the whole design, and it is fixed:

1. Re-verify the evaluation (all nine invariants, fail closed).
2. Re-verify the human approval through the certified HITL lineage.
3. **Create the rollback handle** — durably, before anything changes.
4. Commit the new active state with a single atomic pointer write.
5. Emit the audit record.

Invariants this module guarantees:

* **Rollback handle precedes activation** (Gate 6). If handle creation
  fails, promotion does not happen. There is no code path that reaches the
  commit without a persisted, verifiable handle.
* **Atomicity** (Gate 7). The active pointer is replaced in one
  ``os.replace``. A reader sees the whole old state or the whole new one.
  A failure before the commit leaves the prior state valid and the candidate
  non-active.
* **Idempotency.** Promoting an already-promoted candidate returns the same
  record instead of promoting twice. A concurrent conflicting promotion is
  rejected deterministically.
* **Deterministic rollback** (Gate 8). Rollback restores the exact prior
  state recorded in the handle, requires no model, and is idempotent.
  Historical records are retained, never deleted (RB-04/RB-05).
"""

from __future__ import annotations

import logging
import threading
import uuid
from datetime import datetime, timezone
from typing import Optional

from autoforge_learning.approval import ApprovalCoordinator, ApprovalError
from autoforge_learning.audit import LearningAuditAction, LearningAuditError, LearningAuditor
from autoforge_learning.evaluation import EvaluationOutcome, EvaluationReport
from autoforge_learning.gateway import ProposalGateway
from autoforge_learning.store import (
    ActiveLearningState,
    ApprovalRecord,
    DurableLearningStore,
    PromotionRecord,
    PromotionState,
    RollbackHandle,
    RollbackRecord,
)
from autoforge_security.models import DecisionType, Subject

logger = logging.getLogger("autoforge.learning.promotion")

__test__ = False  # declares data models, not tests


class PromotionError(RuntimeError):
    """A promotion was refused or failed."""


class PromotionConflict(PromotionError):
    """A conflicting promotion was attempted against an already-promoted state."""


class RollbackError(RuntimeError):
    """A rollback was refused or failed."""


class PromotionAuditError(PromotionError):
    """The promotion committed, but its success could not be audited.

    This is a distinct outcome from "promotion failed". The state change
    really did happen, so the durable record says ``PROMOTED`` and carries the
    audit failure reason. What it must never become is a *clean* success:
    Gate 17 forbids converting an audit failure into a silent promotion.
    """


class PromotionService:
    """Executes the human-authorized promotion of one candidate.

    The service has no authority of its own. It refuses to promote unless
    the evaluation passed, a human approval is on record, the security
    boundary still permits the candidate, and a durable rollback handle has
    been written.
    """

    def __init__(
        self,
        *,
        store: DurableLearningStore,
        approvals: ApprovalCoordinator,
        auditor: LearningAuditor,
        proposal_gateway: Optional[ProposalGateway] = None,
    ) -> None:
        self._store = store
        self._approvals = approvals
        self._auditor = auditor
        self._gateway = proposal_gateway
        #: Serialises the check-then-act sequence of a promotion. Two threads
        #: racing the same candidate must produce one promotion, not two
        #: (Gate 18). This is a single in-process lock, matching the store's
        #: existing discipline — no distributed-locking framework is added.
        self._promotion_lock = threading.RLock()

    # ── promotion ─────────────────────────────────────────────────────────────

    def promote(
        self,
        *,
        project_id: uuid.UUID,
        candidate_id: uuid.UUID,
        evaluation: EvaluationReport,
        approval: ApprovalRecord,
        kind: str,
        key: str,
        proposed_effect: str,
        requested_by: Subject,
        resume_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> PromotionRecord:
        """Promote a validated, human-approved candidate.

        Returns a :class:`PromotionRecord` in every outcome — including
        refusals — so a failed attempt is retained rather than lost.
        """
        self._auditor.emit(
            LearningAuditAction.PROMOTION_ATTEMPTED,
            project_id=project_id,
            candidate_id=candidate_id,
            outcome="attempted",
            reason=proposed_effect,
            correlation_id=correlation_id,
            details={"kind": kind, "key": key, "requested_by": requested_by.subject_id},
            strict=False,
        )

        try:
            with self._promotion_lock:
                return self._promote_locked(
                    project_id=project_id,
                    candidate_id=candidate_id,
                    evaluation=evaluation,
                    approval=approval,
                    kind=kind,
                    key=key,
                    proposed_effect=proposed_effect,
                    requested_by=requested_by,
                    resume_token=resume_token,
                    correlation_id=correlation_id,
                )
        except PromotionAuditError:
            # The commit happened but the audit did not. Do not record a
            # second, contradictory FAILED promotion: the truth is that the
            # candidate IS active and the audit is degraded.
            raise
        except Exception as ex:  # noqa: BLE001 - fail closed, always recorded
            logger.info("Promotion refused for candidate %s: %s", candidate_id, ex)
            self._record_failure(
                project_id=project_id,
                candidate_id=candidate_id,
                evaluation=evaluation,
                approval=approval,
                kind=kind,
                key=key,
                proposed_effect=proposed_effect,
                requested_by=requested_by,
                correlation_id=correlation_id,
                reason=f"{type(ex).__name__}: {ex}",
            )
            # Every refusal surfaces as a PromotionError so a caller cannot
            # mistake an infrastructure failure for an ordinary success or
            # retry around a gate. The original cause is chained.
            if isinstance(ex, PromotionError):
                raise
            raise PromotionError(f"promotion failed: {ex}") from ex

    def _promote_locked(
        self,
        *,
        project_id: uuid.UUID,
        candidate_id: uuid.UUID,
        evaluation: EvaluationReport,
        approval: ApprovalRecord,
        kind: str,
        key: str,
        proposed_effect: str,
        requested_by: Subject,
        resume_token: Optional[str],
        correlation_id: Optional[str],
    ) -> PromotionRecord:
        # ── Gate A: evaluation must exist, belong here, and have passed ──────
        if evaluation.outcome is not EvaluationOutcome.PASSED or not evaluation.promotable:
            raise PromotionError(
                "promotion requires a passed evaluation; this candidate is "
                f"{evaluation.outcome.value}"
            )
        if evaluation.candidate_id != candidate_id or evaluation.project_id != project_id:
            raise PromotionError(
                "evaluation does not belong to this candidate/project pair"
            )

        # ── Gate B: candidate must exist in this project's store ─────────────
        candidate_record = self._store.get_candidate(project_id, candidate_id)
        if candidate_record is None:
            raise PromotionError(
                f"candidate {candidate_id} is not stored for project {project_id}"
            )

        # ── Gate C: security boundary must still permit the candidate ────────
        if self._gateway is not None:
            decision = self._gateway.evaluate(candidate_record.candidate)
            if not decision.permitted_to_proceed:
                raise PromotionError(
                    "the security boundary denied this candidate at promotion "
                    f"time: {decision.denial_reason}"
                )

        # ── Gate D: human approval, re-verified against the live gate ────────
        # An approval refusal is a promotion refusal: it is reported through
        # the same error type so a caller cannot accidentally treat one as a
        # transient problem and retry around the gate.
        try:
            self._approvals.verify(
                approval=approval,
                candidate_id=candidate_id,
                project_id=project_id,
                resume_token=resume_token,
            )
        except ApprovalError as ex:
            raise PromotionError(f"human approval did not verify: {ex}") from ex
        if approval.evaluation_id != evaluation.evaluation_id:
            raise PromotionError(
                "approval was granted against a different evaluation than the "
                "one being promoted"
            )

        # ── Gate E: the approval's scope/effect must match what is promoted ──
        if approval.requested_scope != f"{kind}:{key}":
            raise PromotionError(
                f"approval authorises scope {approval.requested_scope!r}, "
                f"not {f'{kind}:{key}'!r}"
            )

        # ── Idempotency / conflict (Gate 18) ─────────────────────────────────
        existing = self._existing_successful_promotion(
            project_id, candidate_id, kind, key
        )
        if existing is not None:
            active = self._store.get_active_state(project_id, kind, key)
            if active is not None and active.candidate_id == candidate_id:
                # Already promoted and still active: idempotent no-op.
                return existing
            raise PromotionConflict(
                f"candidate {candidate_id} was already promoted for {kind}:{key}; "
                "refusing a duplicate promotion"
            )

        active_before = self._store.get_active_state(project_id, kind, key)
        expected_version = (active_before.version_number + 1) if active_before else 1

        proposed_state = ActiveLearningState(
            project_id=project_id,
            kind=kind,
            key=key,
            version_id=uuid.uuid4(),
            version_number=expected_version,
            candidate_id=candidate_id,
            content_hash=candidate_record.candidate.record_hash(),
            activation_timestamp=datetime.now(timezone.utc),
            scope_kind=candidate_record.scope.kind.value,
            scope_workflow_id=candidate_record.scope.workflow_id,
            scope_task_type=candidate_record.scope.task_type,
        )

        # ── Gate F (HARD): rollback handle BEFORE any state change ───────────
        handle = RollbackHandle(
            project_id=project_id,
            candidate_id=candidate_id,
            kind=kind,
            key=key,
            previous_state=active_before,
            proposed_state=proposed_state,
            previous_version_number=active_before.version_number if active_before else None,
            proposed_version_number=expected_version,
            rollback_target_version_id=(
                active_before.version_id if active_before else None
            ),
            approval_id=approval.approval_id,
            evaluation_id=evaluation.evaluation_id,
        )
        handle = handle.model_copy(
            update={"integrity_hash": handle.compute_integrity_hash()}
        )
        self._store.save_rollback_handle(handle)

        # A handle that cannot be read back is not a handle. Promotion stops.
        stored_handle = self._store.get_rollback_handle(project_id, handle.handle_id)
        if stored_handle is None or not stored_handle.is_intact:
            raise PromotionError(
                "rollback handle could not be durably created; promotion aborted"
            )

        self._auditor.emit(
            LearningAuditAction.ROLLBACK_HANDLE_CREATED,
            project_id=project_id,
            candidate_id=candidate_id,
            outcome="success",
            reason="rollback handle created before activation",
            correlation_id=correlation_id,
            details={
                "handle_id": str(handle.handle_id),
                "kind": kind,
                "key": key,
                "proposed_version_number": expected_version,
            },
            record_id=handle.handle_id,
            strict=False,
        )

        # ── COMMIT: one atomic pointer write. Before this line nothing has
        #    changed; after it the new state is wholly active. ───────────────
        self._store.set_active_state(proposed_state)

        record = PromotionRecord(
            candidate_id=candidate_id,
            project_id=project_id,
            evaluation_id=evaluation.evaluation_id,
            approval_id=approval.approval_id,
            rollback_handle_id=handle.handle_id,
            state=PromotionState.PROMOTED,
            requested_scope=f"{kind}:{key}",
            proposed_effect=proposed_effect,
            attempted_by=requested_by.subject_id,
            completed_at=datetime.now(timezone.utc),
            previous_state=active_before,
            new_state=proposed_state,
            correlation_id=correlation_id,
        )
        self._store.save_promotion(record)

        try:
            self._auditor.emit(
                LearningAuditAction.PROMOTION_SUCCEEDED,
                project_id=project_id,
                candidate_id=candidate_id,
                outcome="success",
                reason=f"promoted {kind}:{key} to version {expected_version}",
                correlation_id=correlation_id,
                details={
                    "promotion_id": str(record.promotion_id),
                    "handle_id": str(handle.handle_id),
                    "version_number": expected_version,
                    "previous_version_number": (
                        active_before.version_number if active_before else None
                    ),
                    "approver_id": approval.approver_id,
                    "approved_by": approval.approver_subject_type,
                },
                record_id=record.promotion_id,
            )
        except LearningAuditError as ex:
            # The commit already happened and is real. Record that truthfully
            # on the durable record, then refuse to report a clean success.
            degraded = record.model_copy(update={"audit_failure_reason": str(ex)})
            self._store.save_promotion(degraded)
            raise PromotionAuditError(
                "promotion committed but its success could not be audited: "
                f"{ex}"
            ) from ex
        return record

    def _existing_successful_promotion(
        self,
        project_id: uuid.UUID,
        candidate_id: uuid.UUID,
        kind: str,
        key: str,
    ) -> Optional[PromotionRecord]:
        for record in self._store.list_promotions(project_id):
            if (
                record.candidate_id == candidate_id
                and record.requested_scope == f"{kind}:{key}"
                and record.state is PromotionState.PROMOTED
            ):
                return record
        return None

    def _record_failure(
        self,
        *,
        project_id: uuid.UUID,
        candidate_id: uuid.UUID,
        evaluation: EvaluationReport,
        approval: ApprovalRecord,
        kind: str,
        key: str,
        proposed_effect: str,
        requested_by: Subject,
        correlation_id: Optional[str],
        reason: str,
    ) -> None:
        """Persist and audit a refused promotion. Nothing was activated."""
        record = PromotionRecord(
            candidate_id=candidate_id,
            project_id=project_id,
            evaluation_id=evaluation.evaluation_id,
            approval_id=approval.approval_id,
            rollback_handle_id=uuid.UUID(int=0),
            state=PromotionState.FAILED,
            requested_scope=f"{kind}:{key}",
            proposed_effect=proposed_effect,
            attempted_by=requested_by.subject_id,
            completed_at=datetime.now(timezone.utc),
            failure_reason=reason,
            correlation_id=correlation_id,
        )
        self._store.save_promotion(record)
        self._auditor.emit(
            LearningAuditAction.PROMOTION_FAILED,
            project_id=project_id,
            candidate_id=candidate_id,
            decision=DecisionType.DENY,
            outcome="failed",
            reason=reason,
            correlation_id=correlation_id,
            details={
                "promotion_id": str(record.promotion_id),
                "kind": kind,
                "key": key,
            },
            record_id=record.promotion_id,
            strict=False,
        )

    # ── rollback (Gate 8) ────────────────────────────────────────────────────

    def rollback(
        self,
        *,
        project_id: uuid.UUID,
        handle_id: uuid.UUID,
        reason: str = "",
        performed_by: str = "autoforge.learning.rollback",
        correlation_id: Optional[str] = None,
    ) -> RollbackRecord:
        """Restore the exact prior state recorded in a rollback handle.

        Deterministic and model-free: the target is *recorded at promotion
        time*, never reasoned about now (RB-03). Rollback requires no human
        approval precisely because it removes authority rather than granting
        it (RB-08) — but it is always audited.

        Idempotent: rolling back an already-rolled-back handle restores the
        same prior state and reports success again, rather than failing or
        corrupting state.
        """
        self._auditor.emit(
            LearningAuditAction.ROLLBACK_ATTEMPTED,
            project_id=project_id,
            outcome="attempted",
            reason=reason,
            correlation_id=correlation_id,
            details={"handle_id": str(handle_id), "performed_by": performed_by},
            strict=False,
        )

        try:
            return self._rollback_locked(
                project_id=project_id,
                handle_id=handle_id,
                reason=reason,
                performed_by=performed_by,
                correlation_id=correlation_id,
            )
        except Exception as ex:  # noqa: BLE001 - fail closed
            self._auditor.emit(
                LearningAuditAction.ROLLBACK_FAILED,
                project_id=project_id,
                decision=DecisionType.DENY,
                outcome="failed",
                reason=f"{type(ex).__name__}: {ex}",
                correlation_id=correlation_id,
                details={"handle_id": str(handle_id)},
                strict=False,
            )
            raise

    def _rollback_locked(
        self,
        *,
        project_id: uuid.UUID,
        handle_id: uuid.UUID,
        reason: str,
        performed_by: str,
        correlation_id: Optional[str],
    ) -> RollbackRecord:
        handle = self._store.get_rollback_handle(project_id, handle_id)
        if handle is None:
            raise RollbackError(
                f"no rollback handle {handle_id} exists for project {project_id}"
            )
        if handle.project_id != project_id:
            raise RollbackError("rollback handle belongs to a different project")
        if not handle.is_intact:
            raise RollbackError(
                "rollback handle failed integrity verification; refusing to act "
                "on a tampered handle"
            )

        promotion = self._promotion_for_handle(project_id, handle)
        if promotion is None:
            raise RollbackError(
                f"no promotion record references handle {handle_id}"
            )

        current = self._store.get_active_state(project_id, handle.kind, handle.key)
        target = handle.previous_state

        # Idempotency: if the target state is already active (or already
        # cleared), the desired end-state holds. Report success without
        # performing a second, meaningless write.
        already_restored = self._is_restored(current, target)

        if not already_restored:
            if target is None:
                self._store.clear_active_state(project_id, handle.kind, handle.key)
            else:
                restored = target.model_copy(
                    update={
                        "deactivation_timestamp": None,
                        "version_id": target.version_id,
                        "activation_timestamp": target.activation_timestamp,
                    }
                )
                self._store.set_active_state(restored)

        record = RollbackRecord(
            handle_id=handle_id,
            promotion_id=promotion.promotion_id,
            candidate_id=handle.candidate_id,
            project_id=project_id,
            kind=handle.kind,
            key=handle.key,
            restored_state=target,
            superseded_version_id=handle.proposed_state.version_id,
            performed_at=datetime.now(timezone.utc),
            performed_by=performed_by,
            reason=reason,
            correlation_id=correlation_id,
        )
        self._store.save_rollback(record)

        self._auditor.emit(
            LearningAuditAction.ROLLBACK_SUCCEEDED,
            project_id=project_id,
            candidate_id=handle.candidate_id,
            outcome="success",
            reason=reason or "restored prior active state",
            correlation_id=correlation_id,
            details={
                "rollback_id": str(record.rollback_id),
                "handle_id": str(handle_id),
                "restored_version_id": str(target.version_id) if target else None,
                "superseded_version_id": str(handle.proposed_state.version_id),
                "idempotent_no_op": already_restored,
            },
            record_id=record.rollback_id,
        )
        return record

    @staticmethod
    def _is_restored(
        current: Optional[ActiveLearningState], target: Optional[ActiveLearningState]
    ) -> bool:
        if target is None:
            return current is None
        return current is not None and current.version_id == target.version_id

    def _promotion_for_handle(
        self, project_id: uuid.UUID, handle: RollbackHandle
    ) -> Optional[PromotionRecord]:
        for record in self._store.list_promotions(project_id):
            if record.rollback_handle_id == handle.handle_id:
                return record
        return None


__all__ = [
    "PromotionAuditError",
    "PromotionConflict",
    "PromotionError",
    "PromotionService",
    "RollbackError",
]