"""Human approval for learning promotion — Phase 19B-2 (Gate 5 / M-10).

Architecture basis: ``phase19/LEARNING_LIFECYCLE.md`` §5.6 and Gate 19A-5
§6, which require the L3 → L4 edge to be human-only and to bind the
*existing* ``HITLManager`` + ``GovernancePolicyEngine``.

**This module creates no second approval framework.** Every approval it
records is recorded through the certified ``SecurityPlatform``:

* the gate is created by ``SecurityPlatform.request_approval`` →
  ``HITLManager.create_gate`` (a gated ``ConsequentialAction``),
* the decision is submitted through ``HITLManager.submit_decision``, which
  already refuses non-human subjects and self-approval via
  ``GovernancePolicyEngine.validate_human_approver``,
* the authorizing resume token is verified with
  ``HITLManager.verify_resume_token`` before any promotion consumes it.

The single rule this module adds on top is the one the security package
cannot express for a learning artifact: **MODEL PROPOSAL ≠ HUMAN APPROVAL**.
A model cannot mint an approval record, and no field of a candidate can
widen itself into one.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

from autoforge_learning.audit import LearningAuditAction, LearningAuditor
from autoforge_learning.evaluation import EvaluationOutcome, EvaluationReport
from autoforge_learning.store import (
    ApprovalRecord,
    ApprovalStatus,
    DurableLearningStore,
)
from autoforge_security.errors import (
    ApprovalGateExpiredError,
    ApprovalGateNotFoundError,
    ConsequentialActionBlockedError,
    GovernanceError,
    SelfApprovalForbiddenError,
)
from autoforge_security.models import (
    ApprovalGateStatus,
    ConsequentialAction,
    Subject,
    SubjectType,
)

logger = logging.getLogger("autoforge.learning.approval")

__test__ = False  # this module declares data models, not tests

#: The promotion of a learning artifact is an artifact publication: it
#: changes what the platform will do. That is exactly the class of action
#: the certified governance policy gates, so the existing policy applies
#: unchanged rather than learning inventing its own notion of "consequential".
PROMOTION_ACTION = ConsequentialAction.ARTIFACT_PUBLICATION

#: Default approval lifetime. Expiry is durable: an expired approval cannot
#: be resurrected (Gate 5 ``EXPIRED`` fails closed).
DEFAULT_APPROVAL_TTL_SECONDS = 24 * 3600


class ApprovalError(RuntimeError):
    """A requested approval could not be created or recorded."""


class ApprovalRejected(RuntimeError):
    """A human explicitly rejected the promotion."""


class ApprovalCoordinator:
    """Drives the certified HITL gate for one learning candidate.

    The coordinator is deliberately incapable of approving anything itself.
    It opens gates, submits the human's decision, and mirrors the result into
    an immutable :class:`ApprovalRecord`. If the security platform is absent,
    every call fails closed — an unavailable boundary is not an approval.
    """

    def __init__(
        self,
        *,
        security_platform: object | None,
        store: DurableLearningStore,
        auditor: LearningAuditor,
        ttl_seconds: int = DEFAULT_APPROVAL_TTL_SECONDS,
    ) -> None:
        self._security = security_platform
        self._store = store
        self._auditor = auditor
        self._ttl = ttl_seconds

    @property
    def available(self) -> bool:
        return self._security is not None

    def _require_platform(self) -> object:
        if self._security is None:
            raise ApprovalError(
                "no SecurityPlatform is configured; a learning promotion cannot "
                "be approved without the certified HITL/governance boundary"
            )
        return self._security

    def request_approval(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        evaluation: EvaluationReport,
        requested_scope: str,
        proposed_effect: str,
        requested_by: Subject,
        correlation_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> ApprovalRecord:
        """Open an approval gate and persist a PENDING approval record.

        The gate is created through the certified HITL manager, so its
        expiry, required-approver count and notification behaviour are the
        platform's, not learning's.
        """
        platform = self._require_platform()

        if evaluation is None:
            raise ApprovalError(
                "an evaluation report is required before approval can be "
                "requested; promotion cannot proceed without one"
            )
        if evaluation.candidate_id != candidate_id or evaluation.project_id != project_id:
            raise ApprovalError(
                "evaluation does not belong to this candidate/project pair; "
                "refusing to open an approval gate for mismatched evidence"
            )
        if evaluation.outcome is not EvaluationOutcome.PASSED:
            raise ApprovalError(
                "only an evaluation that passed every required invariant may "
                f"be submitted for approval (outcome={evaluation.outcome.value})"
            )

        requested_at = datetime.now(timezone.utc)
        ttl = ttl_seconds if ttl_seconds is not None else self._ttl
        expires_at = requested_at + timedelta(seconds=ttl)

        gate = platform.request_approval(  # type: ignore[attr-defined]
            PROMOTION_ACTION,
            f"Promote learning candidate {candidate_id} ({proposed_effect})",
            requested_by=requested_by,
            project_id=str(project_id),
            required_approvers=1,
            ttl_seconds=ttl,
            metadata={
                "candidate_id": str(candidate_id),
                "project_id": str(project_id),
                "evaluation_id": str(evaluation.evaluation_id),
                "requested_scope": requested_scope,
                "proposed_effect": proposed_effect,
                "correlation_id": correlation_id or "",
            },
        )

        record = ApprovalRecord(
            candidate_id=candidate_id,
            project_id=project_id,
            evaluation_id=evaluation.evaluation_id,
            evaluation_outcome=evaluation.outcome.value,
            evaluation_blocking_invariants=evaluation.blocking_invariants,
            evidence_ids=evaluation.evidence_ids,
            requested_scope=requested_scope,
            proposed_effect=proposed_effect,
            status=ApprovalStatus.PENDING,
            requested_by=requested_by.subject_id,
            requested_at=requested_at,
            expires_at=expires_at,
            hitl_gate_id=gate.gate_id,
            correlation_id=correlation_id,
        )
        self._store.save_approval(record)

        self._auditor.emit(
            LearningAuditAction.APPROVAL_REQUESTED,
            project_id=project_id,
            candidate_id=candidate_id,
            reason=f"approval gate {gate.gate_id} opened for promotion",
            correlation_id=correlation_id,
            details={
                "gate_id": gate.gate_id,
                "approval_id": str(record.approval_id),
                "requested_scope": requested_scope,
                "evaluation_id": str(evaluation.evaluation_id),
                "requested_by": requested_by.subject_id,
            },
            record_id=record.approval_id,
            strict=False,
        )
        return record

    def record_decision(
        self,
        *,
        approval: ApprovalRecord,
        approver: Subject,
        approve: bool,
        reason: str = "",
        correlation_id: Optional[str] = None,
    ) -> ApprovalRecord:
        """Submit a human decision through the certified HITL manager.

        Three fail-closed properties come from the existing security
        package and are *not* re-implemented here:

        * a non-human subject is rejected (``SelfApprovalForbiddenError``),
        * an approver who is also the requester is rejected,
        * an already-resolved or expired gate is rejected.

        A model therefore cannot impersonate approval: the decision is
        recorded by the platform against a HUMAN ``Subject``, and the
        resulting record carries that subject's identity.
        """
        platform = self._require_platform()

        if approval.status is not ApprovalStatus.PENDING:
            raise ApprovalError(
                f"approval {approval.approval_id} is already {approval.status.value}"
            )

        status = ApprovalGateStatus.APPROVED if approve else ApprovalGateStatus.REJECTED

        try:
            gate = platform.submit_approval_decision(  # type: ignore[attr-defined]
                approval.hitl_gate_id,
                approver,
                status,
                reason=reason,
            )
        except (
            ApprovalGateExpiredError,
            ApprovalGateNotFoundError,
            ConsequentialActionBlockedError,
            SelfApprovalForbiddenError,
            GovernanceError,
        ) as ex:
            # An expired gate is a durable terminal state, not a transient
            # error: record it so the candidate can never be promoted on it.
            if isinstance(ex, ApprovalGateExpiredError):
                approval = self._mark(approval, ApprovalStatus.EXPIRED, reason=str(ex))
            self._store.save_approval(approval)
            raise

        final_status = {
            ApprovalGateStatus.APPROVED: ApprovalStatus.APPROVED,
            ApprovalGateStatus.REJECTED: ApprovalStatus.REJECTED,
            ApprovalGateStatus.EXPIRED: ApprovalStatus.EXPIRED,
        }.get(gate.status)

        if final_status is None:
            # The platform resolved the gate into a state the learning
            # contract does not recognise. Fail closed.
            approval = self._mark(
                approval, ApprovalStatus.REJECTED, reason="unrecognised gate outcome"
            )
            self._store.save_approval(approval)
            raise ApprovalError(
                f"approval gate resolved to unhandled status {gate.status!r}"
            )

        decided_at = datetime.now(timezone.utc)
        updated = approval.model_copy(
            update={
                "status": final_status,
                "approver_id": approver.subject_id,
                "approver_subject_type": approver.subject_type.value,
                "decided_at": decided_at,
                "reason": reason or f"decided {final_status.value} by gate",
                "resume_token_present": bool(gate.resume_token),
            }
        )
        self._store.save_approval(updated)

        self._auditor.emit(
            LearningAuditAction.APPROVAL_GRANTED
            if final_status is ApprovalStatus.APPROVED
            else LearningAuditAction.APPROVAL_REJECTED,
            project_id=updated.project_id,
            candidate_id=updated.candidate_id,
            actor=approver,
            outcome="success",
            reason=updated.reason,
            correlation_id=correlation_id or updated.correlation_id,
            details={
                "approval_id": str(updated.approval_id),
                "gate_id": updated.hitl_gate_id,
                "status": final_status.value,
                "approver_id": approver.subject_id,
                "approver_subject_type": approver.subject_type.value,
            },
            record_id=updated.approval_id,
            strict=False,
        )
        return updated

    @staticmethod
    def _mark(
        record: ApprovalRecord, status: ApprovalStatus, *, reason: str
    ) -> ApprovalRecord:
        return record.model_copy(
            update={
                "status": status,
                "reason": reason,
                "decided_at": datetime.now(timezone.utc),
            }
        )

    def revoke(
        self,
        *,
        approval: ApprovalRecord,
        revoked_by: Subject,
        reason: str,
        correlation_id: Optional[str] = None,
    ) -> ApprovalRecord:
        """Withdraw a granted approval before it is consumed.

        Revocation is a durable terminal state: a revoked approval is
        permanently un-promotable, exactly like a rejected one.
        """
        if revoked_by.subject_type is not SubjectType.HUMAN:
            raise ApprovalError("only a human subject may revoke an approval")
        if approval.status is not ApprovalStatus.APPROVED:
            raise ApprovalError(
                f"only an APPROVED approval can be revoked (was {approval.status.value})"
            )
        updated = approval.model_copy(
            update={
                "status": ApprovalStatus.REVOKED,
                "revoked_at": datetime.now(timezone.utc),
                "reason": reason,
            }
        )
        self._store.save_approval(updated)
        self._auditor.emit(
            LearningAuditAction.APPROVAL_REJECTED,
            project_id=updated.project_id,
            candidate_id=updated.candidate_id,
            actor=revoked_by,
            outcome="revoked",
            reason=reason,
            correlation_id=correlation_id,
            details={
                "approval_id": str(updated.approval_id),
                "status": ApprovalStatus.REVOKED.value,
                "revoked_by": revoked_by.subject_id,
            },
            record_id=updated.approval_id,
            strict=False,
        )
        return updated

    def verify(
        self,
        *,
        approval: ApprovalRecord,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        resume_token: Optional[str] = None,
    ) -> ApprovalRecord:
        """Re-verify an approval at promotion time. Fails closed on anything.

        Every check below must hold. Any failure means the candidate is not
        promotable — there is no partial credit and no override.
        """
        if approval.candidate_id != candidate_id:
            raise ApprovalError(
                f"approval {approval.approval_id} belongs to candidate "
                f"{approval.candidate_id}, not {candidate_id}"
            )
        if approval.project_id != project_id:
            raise ApprovalError(
                f"approval {approval.approval_id} belongs to project "
                f"{approval.project_id}, not {project_id}"
            )
        if approval.status is not ApprovalStatus.APPROVED:
            raise ApprovalError(
                f"approval is {approval.status.value}; only APPROVED authorizes promotion"
            )
        if not approval.is_human_approved:
            raise ApprovalError(
                "approval was not granted by an identifiable human subject"
            )
        if approval.expires_at is not None and datetime.now(timezone.utc) >= approval.expires_at:
            raise ApprovalError("approval has expired")
        if not approval.hitl_gate_id:
            raise ApprovalError("approval carries no HITL gate lineage")
        if resume_token is not None:
            # ``SecurityPlatform.hitl`` is a property returning the certified
            # HITLManager; the resume token is verified there, not locally.
            verified = bool(
                self._require_platform().hitl.verify_resume_token(  # type: ignore[attr-defined]
                    approval.hitl_gate_id, resume_token
                )
            )
            if not verified:
                raise ApprovalError("HITL resume token does not verify")
        return approval


__all__ = [
    "DEFAULT_APPROVAL_TTL_SECONDS",
    "PROMOTION_ACTION",
    "ApprovalCoordinator",
    "ApprovalError",
    "ApprovalRejected",
]