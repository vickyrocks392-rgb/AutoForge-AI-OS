"""The canonical learning promotion lifecycle — Phase 19B-2 (Gate 21).

This module is the *assembly point* for the whole gate. It wires the
already-built pieces into the exact order Gate 19A-6 specifies and nothing
more:

    propose → validate/evaluate (9 invariants) → HITL
             → rollback handle → atomic promotion → audit
             → deterministic rollback

What it deliberately does **not** do:

* It does not connect promoted learning into any execution engine. The
  active-state pointer is written, and nothing reads it yet. Gate 13 is
  explicit that this gate builds the promotion *infrastructure*; wiring it
  into production behaviour is a separate, separately-approved step.
* It does not evaluate autonomously, experiment, or optimise.
* It has no path to Level 5 and no authority to grant anything.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional, Sequence

from autoforge_learning.approval import ApprovalCoordinator
from autoforge_learning.audit import LearningAuditAction, LearningAuditor
from autoforge_learning.evaluation import (
    EvaluationOutcome,
    EvaluationReport,
    RegressionEvaluator,
)
from autoforge_learning.gateway import ProposalGateway
from autoforge_learning.invariants import InvariantMetrics
from autoforge_learning.models import EvidenceRef, LearningCandidate
from autoforge_learning.promotion import PromotionService, RollbackError
from autoforge_learning.store import (
    ActiveLearningState,
    ApprovalRecord,
    CandidateRecord,
    DurableLearningStore,
    PromotionRecord,
    RollbackRecord,
)
from autoforge_learning.telemetry import LearningTelemetry, TelemetryCollector
from autoforge_security.models import DecisionType, Subject

logger = logging.getLogger("autoforge.learning.lifecycle")

__test__ = False  # declares no pytest-collectable classes


class LearningLifecycleService:
    """One call per lifecycle stage, each independently testable.

    Every stage is explicit. There is no ``run_everything`` shortcut that
    could skip a gate, and no stage proceeds on a failure of the previous
    one — a caller cannot accidentally promote something that was never
    evaluated or approved.
    """

    def __init__(
        self,
        *,
        store: DurableLearningStore,
        gateway: ProposalGateway,
        evaluator: RegressionEvaluator,
        approvals: ApprovalCoordinator,
        promotion: PromotionService,
        auditor: LearningAuditor,
    ) -> None:
        self._store = store
        self._gateway = gateway
        self._evaluator = evaluator
        self._approvals = approvals
        self._promotion = promotion
        self._auditor = auditor
        self._telemetry = TelemetryCollector(store=store, auditor=auditor)

    @classmethod
    def build(
        cls,
        *,
        store_root: str | Path,
        security_platform: Any | None,
        proposal_gateway: Optional[ProposalGateway] = None,
        evaluator: Optional[RegressionEvaluator] = None,
        ttl_seconds: Optional[int] = None,
    ) -> "LearningLifecycleService":
        """Assemble the lifecycle from the certified security platform.

        ``security_platform`` supplies the *existing* guardrails, HITL
        manager, governance engine and audit engine. Learning creates no
        security component of its own.
        """
        guardrails = getattr(security_platform, "guardrails", None)
        audit_engine = getattr(security_platform, "audit", None)

        gateway = proposal_gateway or ProposalGateway(guardrails)
        store = DurableLearningStore(store_root)
        auditor = LearningAuditor(audit_engine)

        approvals_kwargs: dict[str, Any] = {
            "security_platform": security_platform,
            "store": store,
            "auditor": auditor,
        }
        if ttl_seconds is not None:
            approvals_kwargs["ttl_seconds"] = ttl_seconds
        approvals = ApprovalCoordinator(**approvals_kwargs)

        promotion = PromotionService(
            store=store,
            approvals=approvals,
            auditor=auditor,
            proposal_gateway=gateway,
        )
        return cls(
            store=store,
            gateway=gateway,
            evaluator=evaluator or RegressionEvaluator(),
            approvals=approvals,
            promotion=promotion,
            auditor=auditor,
        )

    # ── accessors ────────────────────────────────────────────────────────────

    @property
    def store(self) -> DurableLearningStore:
        return self._store

    @property
    def gateway(self) -> ProposalGateway:
        return self._gateway

    @property
    def approvals(self) -> ApprovalCoordinator:
        return self._approvals

    @property
    def promotion(self) -> PromotionService:
        return self._promotion

    @property
    def auditor(self) -> LearningAuditor:
        return self._auditor

    def telemetry(self, project_id: uuid.UUID) -> LearningTelemetry:
        return self._telemetry.collect(project_id)

    # ── stage 1: durable candidate ───────────────────────────────────────────

    def create_candidate(self, candidate: LearningCandidate) -> CandidateRecord:
        """Persist a candidate that the security boundary permitted.

        A denied candidate is *retained* (LC-07 keeps rejections auditable)
        but raises, so no caller can mistake a denial for a stored,
        promotable candidate.
        """
        decision = self._gateway.evaluate(candidate)
        project_id = candidate.scope.project_id

        record = CandidateRecord(
            candidate=candidate,
            project_id=project_id,
            stored_at=datetime.now(timezone.utc),
        )
        self._store.save_candidate(record)

        self._auditor.emit(
            LearningAuditAction.CANDIDATE_CREATED,
            project_id=project_id,
            candidate_id=candidate.candidate_id,
            outcome="success" if decision.permitted_to_proceed else "denied",
            reason=(
                "proposal permitted by the security boundary"
                if decision.permitted_to_proceed
                else f"proposal denied: {decision.denial_reason}"
            ),
            details={
                "kind": candidate.kind,
                "permitted_to_proceed": decision.permitted_to_proceed,
                "boundary_decision": str(getattr(decision, "boundary_decision", "")),
                "boundary_reason": decision.boundary_reason,
            },
            record_id=candidate.candidate_id,
            strict=False,
        )

        if not decision.permitted_to_proceed:
            raise PermissionError(
                f"security boundary denied candidate {candidate.candidate_id}: "
                f"{decision.denial_reason}"
            )
        return record

    # ── stage 2: evidence ────────────────────────────────────────────────────

    def record_evidence(
        self, record: CandidateRecord, evidence: Sequence[EvidenceRef]
    ) -> CandidateRecord:
        """Attach authoritative evidence references to a stored candidate.

        Absent evidence is recorded as absent. It is never dropped silently,
        and it is never replaced with a placeholder that would later read as
        a passing measurement.
        """
        if not evidence:
            self._auditor.emit(
                LearningAuditAction.EVIDENCE_COLLECTED,
                project_id=record.project_id,
                candidate_id=record.candidate_id,
                decision=DecisionType.DENY,
                outcome="absent",
                reason="no evidence supplied; recorded as absent, not as a pass",
                strict=False,
            )
            return record

        with_evidence = record.candidate.model_copy(update={"evidence": tuple(evidence)})
        updated = record.model_copy(update={"candidate": with_evidence})
        self._store.save_candidate(updated)
        self._auditor.emit(
            LearningAuditAction.EVIDENCE_COLLECTED,
            project_id=record.project_id,
            candidate_id=record.candidate_id,
            outcome="success",
            reason=f"{len(evidence)} evidence reference(s) recorded",
            details={
                "evidence_ids": [str(e.evidence_id) for e in evidence],
                "evidence_count": len(evidence),
            },
            strict=False,
        )
        return updated

    # ── stage 3: evaluation ─────────────────────────────────────────────────

    def evaluate(
        self,
        *,
        record: CandidateRecord,
        baseline: InvariantMetrics,
        candidate_metrics: InvariantMetrics,
        correlation_id: Optional[str] = None,
    ) -> EvaluationReport:
        """Evaluate all nine protected invariants and persist the report."""
        self._auditor.emit(
            LearningAuditAction.EVALUATION_STARTED,
            project_id=record.project_id,
            candidate_id=record.candidate_id,
            outcome="started",
            correlation_id=correlation_id,
            strict=False,
        )
        report = self._evaluator.evaluate(
            candidate_id=record.candidate_id,
            project_id=record.project_id,
            scope_kind=record.scope.kind.value,
            baseline=baseline,
            candidate=candidate_metrics,
            evidence=record.candidate.evidence,
            correlation_id=correlation_id,
        )
        self._store.save_evaluation(report)

        passed = report.outcome is EvaluationOutcome.PASSED
        self._auditor.emit(
            LearningAuditAction.EVALUATION_COMPLETED
            if passed
            else LearningAuditAction.EVALUATION_FAILED,
            project_id=record.project_id,
            candidate_id=record.candidate_id,
            outcome="success" if passed else "failed",
            reason=(
                "all required invariants passed"
                if passed
                else f"blocking invariants: {list(report.blocking_invariants)}"
            ),
            correlation_id=correlation_id,
            details={
                "evaluation_id": str(report.evaluation_id),
                "blocking_invariants": list(report.blocking_invariants),
                "baseline_hash": report.baseline_hash,
            },
            record_id=report.evaluation_id,
            strict=False,
        )
        return report

    # ── stage 4: approval ────────────────────────────────────────────────────

    def request_approval(
        self,
        *,
        record: CandidateRecord,
        evaluation: EvaluationReport,
        kind: str,
        key: str,
        proposed_effect: str,
        requested_by: Subject,
        correlation_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> ApprovalRecord:
        kwargs: dict[str, Any] = {}
        if ttl_seconds is not None:
            kwargs["ttl_seconds"] = ttl_seconds
        return self._approvals.request_approval(
            candidate_id=record.candidate_id,
            project_id=record.project_id,
            evaluation=evaluation,
            requested_scope=f"{kind}:{key}",
            proposed_effect=proposed_effect,
            requested_by=requested_by,
            correlation_id=correlation_id,
            **kwargs,
        )

    # ── stage 5 + 6: promotion and rollback ──────────────────────────────────

    def promote(
        self,
        *,
        record: CandidateRecord,
        evaluation: EvaluationReport,
        approval: ApprovalRecord,
        kind: str,
        key: str,
        proposed_effect: str,
        requested_by: Subject,
        resume_token: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> PromotionRecord:
        return self._promotion.promote(
            project_id=record.project_id,
            candidate_id=record.candidate_id,
            evaluation=evaluation,
            approval=approval,
            kind=kind,
            key=key,
            proposed_effect=proposed_effect,
            requested_by=requested_by,
            resume_token=resume_token,
            correlation_id=correlation_id,
        )

    def rollback(
        self,
        *,
        project_id: uuid.UUID,
        handle_id: uuid.UUID,
        reason: str = "",
        correlation_id: Optional[str] = None,
    ) -> RollbackRecord:
        return self._promotion.rollback(
            project_id=project_id,
            handle_id=handle_id,
            reason=reason,
            correlation_id=correlation_id,
        )

    def active_state(
        self, project_id: uuid.UUID, kind: str, key: str
    ) -> Optional[ActiveLearningState]:
        """The currently active learning state, if any.

        Exposed so a consumer can *read* promoted learning. Nothing in the
        platform calls this yet — Gate 13 keeps that wiring out of this gate.
        """
        return self._store.get_active_state(project_id, kind, key)


__all__ = ["LearningLifecycleService", "RollbackError"]
