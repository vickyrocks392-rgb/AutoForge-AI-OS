"""Phase 18-F Governance Report Service."""
from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from autoforge_artifacts.models import CanonicalArtifactType


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(content: str) -> str:
    return hashlib.sha256(content.encode("utf-8")).hexdigest()



@dataclass
class StageEvidence:
    stage_id: str
    stage_kind: str
    status: str
    started_at: str | None
    finished_at: str | None
    attempt_number: int
    artifact_ids: list[str] = field(default_factory=list)
    evaluation_passed: bool | None = None
    evaluation_status: str | None = None
    evaluation_failures: list[str] = field(default_factory=list)
    test_summary: dict[str, Any] | None = None
    diagnosis_root_cause: str | None = None
    diagnosis_confidence: float | None = None
    repair_attempts: int = 0
    repair_final_status: str | None = None
    repair_retry_exhausted: bool = False
    changed_files: list[str] = field(default_factory=list)
    rag_hit_count: int = 0
    rag_max_score: float | None = None
    worker_type: str = ""
    model_id: str | None = None
    provider_id: str | None = None
    provenance_refs: dict[str, str] = field(default_factory=dict)
    unavailable: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "stage_kind": self.stage_kind,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "attempt_number": self.attempt_number,
            "artifact_ids": list(self.artifact_ids),
            "evaluation_passed": self.evaluation_passed,
            "evaluation_status": self.evaluation_status,
            "evaluation_failures": list(self.evaluation_failures),
            "test_summary": dict(self.test_summary) if self.test_summary else None,
            "diagnosis_root_cause": self.diagnosis_root_cause,
            "diagnosis_confidence": self.diagnosis_confidence,
            "repair_attempts": self.repair_attempts,
            "repair_final_status": self.repair_final_status,
            "repair_retry_exhausted": self.repair_retry_exhausted,
            "changed_files": list(self.changed_files),
            "rag_hit_count": self.rag_hit_count,
            "rag_max_score": self.rag_max_score,
            "worker_type": self.worker_type,
            "model_id": self.model_id,
            "provider_id": self.provider_id,
            "provenance_refs": dict(self.provenance_refs),
            "unavailable": list(self.unavailable),
        }



@dataclass
class ReviewEvidence:
    stage_id: str
    review_id: str
    decision: str
    findings_count: int = 0
    blocking_findings: int = 0
    deterministic_findings: int = 0
    ai_findings: int = 0
    categories_run: list[str] = field(default_factory=list)
    gate_status: str = ""
    review_artifact_id: str | None = None
    review_requested: bool = False
    review_result_recorded: bool = False
    unavailable_reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "stage_id": self.stage_id,
            "review_id": self.review_id,
            "decision": self.decision,
            "findings_count": self.findings_count,
            "blocking_findings": self.blocking_findings,
            "deterministic_findings": self.deterministic_findings,
            "ai_findings": self.ai_findings,
            "categories_run": list(self.categories_run),
            "gate_status": self.gate_status,
            "review_artifact_id": self.review_artifact_id,
            "review_requested": self.review_requested,
            "review_result_recorded": self.review_result_recorded,
            "unavailable_reason": self.unavailable_reason,
        }


@dataclass
class HITLEvidence:
    gate_id: str
    stage_id: str
    status: str
    risk_level: str
    requested_at: str
    decided_at: str | None
    decided_by: str | None
    decision: str | None
    reason_text: str | None
    approved: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "gate_id": self.gate_id,
            "stage_id": self.stage_id,
            "status": self.status,
            "risk_level": self.risk_level,
            "requested_at": self.requested_at,
            "decided_at": self.decided_at,
            "decided_by": self.decided_by,
            "decision": self.decision,
            "reason_text": self.reason_text,
            "approved": self.approved,
        }


@dataclass
class AuditEvidence:
    record_id: str
    action: str
    decision: str
    reason: str
    outcome: str
    actor_id: str
    actor_type: str
    project_id: str | None
    workflow_id: str | None
    task_id: str | None
    recorded_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_id": self.record_id,
            "action": self.action,
            "decision": self.decision,
            "reason": self.reason,
            "outcome": self.outcome,
            "actor_id": self.actor_id,
            "actor_type": self.actor_type,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "recorded_at": self.recorded_at,
        }



@dataclass
class GovernanceEvidence:
    project_id: str
    workflow_id: str | None
    execution_id: str
    chain_summary: dict[str, Any]
    stage_evidence: list[StageEvidence]
    review_evidence: list[ReviewEvidence]
    hitl_evidence: list[HITLEvidence]
    audit_evidence: list[AuditEvidence]
    execution_metrics: dict[str, Any]
    assembled_at: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "chain_summary": dict(self.chain_summary),
            "stage_evidence": [s.to_dict() for s in self.stage_evidence],
            "review_evidence": [r.to_dict() for r in self.review_evidence],
            "hitl_evidence": [h.to_dict() for h in self.hitl_evidence],
            "audit_evidence": [a.to_dict() for a in self.audit_evidence],
            "execution_metrics": dict(self.execution_metrics),
            "assembled_at": self.assembled_at,
        }


@dataclass
class GovernanceDecision:
    outcome: str
    reason: str
    evidence_refs: list[str] = field(default_factory=list)
    policy_version: str = ""
    decided_at: str = field(default_factory=lambda: _utc_now())
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "outcome": self.outcome,
            "reason": self.reason,
            "evidence_refs": list(self.evidence_refs),
            "policy_version": self.policy_version,
            "decided_at": self.decided_at,
            "blockers": list(self.blockers),
        }


@dataclass
class GovernanceReport:
    report_id: str
    project_id: str
    workflow_id: str | None
    execution_id: str
    workflow_name: str
    objective: str
    outcome: str
    governance_decision: GovernanceDecision
    evidence: GovernanceEvidence
    artifact_inventory: list[dict[str, Any]]
    final_stage: str | None
    total_stages: int
    succeeded_stages: int
    failed_stages: int
    skipped_stages: int
    generated_at: str
    chain_identity: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_id": self.report_id,
            "project_id": self.project_id,
            "workflow_id": self.workflow_id,
            "execution_id": self.execution_id,
            "workflow_name": self.workflow_name,
            "objective": self.objective,
            "outcome": self.outcome,
            "governance_decision": self.governance_decision.to_dict(),
            "evidence": self.evidence.to_dict(),
            "artifact_inventory": list(self.artifact_inventory),
            "final_stage": self.final_stage,
            "total_stages": self.total_stages,
            "succeeded_stages": self.succeeded_stages,
            "failed_stages": self.failed_stages,
            "skipped_stages": self.skipped_stages,
            "generated_at": self.generated_at,
            "chain_identity": self.chain_identity,
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, default=str)


class GovernanceReportService:
    """Assembles governance reports from real execution state."""

    def assemble_execution_chain(
        self,
        state: Any,
        artifact_records: list[dict[str, Any]] | None = None,
    ) -> GovernanceEvidence:
        artifacts = artifact_records or []
        project_id = state.project_id or "unknown"
        workflow_id = getattr(state, "workflow_id", None)
        execution_id = state.execution_id or "unknown"

        by_stage: dict[str, list[dict]] = {}
        for art in artifacts:
            meta = art.get("metadata") or {}
            sid = meta.get("stage_id")
            if sid:
                by_stage.setdefault(sid, []).append(art)

        stages = getattr(state, "stages", {}) or {}
        stage_order = getattr(state, "stage_order", list(stages.keys()))
        metrics = getattr(state, "metrics", None)

        stage_evidence: list[StageEvidence] = []
        succeeded = failed = skipped = 0

        for sid in stage_order:
            ss = stages.get(sid)
            if ss is None:
                continue
            sev = self._build_stage_evidence(sid, ss, by_stage.get(sid, []))
            stage_evidence.append(sev)
            if sev.status == "SUCCEEDED" or sev.status == "succeeded":
                succeeded += 1
            elif sev.status in ("FAILED", "BLOCKED", "failed", "blocked"):
                failed += 1
            else:
                skipped += 1

        metrics_dict: dict[str, Any] = {}
        if metrics and hasattr(metrics, "to_dict"):
            try:
                metrics_dict = metrics.to_dict()
            except Exception:
                pass
        elif isinstance(metrics, dict):
            metrics_dict = dict(metrics)

        return GovernanceEvidence(
            project_id=project_id,
            workflow_id=str(workflow_id) if workflow_id else None,
            execution_id=execution_id,
            chain_summary={
                "total_stages": len(stage_evidence),
                "succeeded_stages": succeeded,
                "failed_stages": failed,
                "skipped_stages": skipped,
                "has_failures": failed > 0,
            },
            stage_evidence=stage_evidence,
            review_evidence=[],
            hitl_evidence=[],
            audit_evidence=[],
            execution_metrics=metrics_dict,
            assembled_at=_utc_now(),
        )

    def _build_stage_evidence(
        self,
        stage_id: str,
        stage_state: Any,
        artifacts: list[dict[str, Any]],
    ) -> StageEvidence:
        status = getattr(stage_state, "status", None)
        status_val = status.value if hasattr(status, "value") else str(status) if status else "UNKNOWN"
        artifact_ids = [str(art.get("artifact_id") or art.get("name", "")) for art in artifacts]
        output = getattr(stage_state, "output", {}) or {}
        eval_passed: bool | None = None
        eval_status: str | None = None
        eval_failures: list[str] = []
        test_summary: dict[str, Any] | None = None
        diag_root_cause: str | None = None
        diag_confidence: float | None = None
        repair_attempts = 0
        repair_final_status: str | None = None
        repair_retry_exhausted = False
        changed_files: list[str] = []
        rag_hit_count = 0

        if isinstance(output, dict):
            eval_data = output.get("evaluation")
            if eval_data and isinstance(eval_data, dict):
                eval_status = eval_data.get("status")
                eval_passed = eval_data.get("passed")
                eval_failures = list(eval_data.get("failures") or [])
                ts = eval_data.get("test_results")
                if ts and isinstance(ts, dict):
                    test_summary = dict(ts)

            diag_data = output.get("diagnosis")
            if diag_data and isinstance(diag_data, dict):
                diag_root_cause = diag_data.get("root_cause")
                diag_confidence = diag_data.get("confidence_score")

            repair_data = output.get("repair_result")
            if repair_data and isinstance(repair_data, dict):
                repair_final_status = repair_data.get("final_status")
                repair_retry_exhausted = repair_data.get("retry_exhausted", False)
                attempts_data = repair_data.get("attempts")
                if attempts_data and isinstance(attempts_data, list):
                    repair_attempts = len(attempts_data)

            changed = output.get("changed_files")
            if changed and isinstance(changed, list):
                changed_files = list(changed)

        for art in artifacts:
            art_type = art.get("artifact_type", "")
            if "diagnosis" in art_type.lower() or "evaluation" in art_type.lower():
                meta = art.get("metadata") or {}
                rk_count = meta.get("retrieved_knowledge_count", 0)
                if rk_count and isinstance(rk_count, int) and rk_count > 0:
                    rag_hit_count = max(rag_hit_count, rk_count)

        stage_kind = stage_id
        definition = getattr(stage_state, "definition", None)
        if isinstance(definition, dict):
            stage_kind = definition.get("kind", stage_id)
        elif hasattr(definition, "kind"):
            k = getattr(definition, "kind")
            stage_kind = k.value if hasattr(k, "value") else str(k)

        return StageEvidence(
            stage_id=stage_id,
            stage_kind=str(stage_kind),
            status=status_val,
            started_at=getattr(stage_state, "started_at", None),
            finished_at=getattr(stage_state, "finished_at", None),
            attempt_number=getattr(stage_state, "attempt_number", 1),
            artifact_ids=artifact_ids,
            evaluation_passed=eval_passed,
            evaluation_status=eval_status,
            evaluation_failures=eval_failures,
            test_summary=test_summary,
            diagnosis_root_cause=diag_root_cause,
            diagnosis_confidence=diag_confidence,
            repair_attempts=repair_attempts,
            repair_final_status=repair_final_status,
            repair_retry_exhausted=repair_retry_exhausted,
            changed_files=changed_files,
            rag_hit_count=rag_hit_count,
            worker_type=getattr(stage_state, "worker_type", "") or "",
        )

    def assemble_governance_evidence(
        self,
        evidence: GovernanceEvidence,
        audit_records: list[Any] | None = None,
        hitl_gates: dict[str, Any] | None = None,
        review_results: list[Any] | None = None,
    ) -> GovernanceEvidence:
        """Augment execution chain evidence with audit, HITL, and review evidence."""
        hitl_evidence: list[HITLEvidence] = []
        if hitl_gates:
            for gate_id, gate in hitl_gates.items():
                status = getattr(gate, "status", "pending") or "pending"
                status_val = status.value if hasattr(status, "value") else str(status)
                hitl_evidence.append(HITLEvidence(
                    gate_id=getattr(gate, "gate_id", gate_id),
                    stage_id=getattr(gate, "stage_id", ""),
                    status=status_val.upper() if isinstance(status_val, str) else str(status_val),
                    risk_level=str(getattr(gate, "risk_level", "medium") or "medium"),
                    requested_at=getattr(gate, "requested_at", "") or "",
                    decided_at=getattr(gate, "decided_at", None),
                    decided_by=getattr(gate, "actor", None),
                    decision=getattr(gate, "decision", None),
                    reason_text=getattr(gate, "reason_text", None),
                    approved=status_val.upper() == "APPROVED" if isinstance(status_val, str) else None,
                ))

        audit_evidence: list[AuditEvidence] = []
        if audit_records:
            for rec in audit_records:
                decision = getattr(rec, "decision", "") or ""
                decision_val = decision.value if hasattr(decision, "value") else str(decision)
                rec_at = getattr(rec, "recorded_at", None)
                if rec_at:
                    recorded = rec_at.isoformat() if hasattr(rec_at, "isoformat") else str(rec_at)
                else:
                    recorded = _utc_now()
                audit_evidence.append(AuditEvidence(
                    record_id=str(getattr(rec, "audit_id", "") or getattr(rec, "record_id", "") or str(uuid.uuid4())),
                    action=getattr(rec, "action", "") or "",
                    decision=str(decision_val),
                    reason=getattr(rec, "reason", "") or "",
                    outcome=getattr(rec, "outcome", "") or "",
                    actor_id=getattr(rec, "actor_id", "") or "",
                    actor_type=str(getattr(rec, "actor_type", "")),
                    project_id=getattr(rec, "project_id", None),
                    workflow_id=getattr(rec, "workflow_id", None),
                    task_id=getattr(rec, "task_id", None),
                    recorded_at=recorded,
                ))

        review_evidence: list[ReviewEvidence] = []
        if review_results:
            for result in review_results:
                review_id = getattr(result, "review_id", "") or ""
                if hasattr(result, "to_dict"):
                    rd = result.to_dict()
                elif isinstance(result, dict):
                    rd = dict(result)
                else:
                    # SimpleNamespace or any attr-based object
                    rd = {k: v for k, v in vars(result).items()} if hasattr(result, "__dict__") else {}
                categories_run = rd.get("categories_run", []) or []
                gate_data = rd.get("gate", {})
                gate_status = ""
                if isinstance(gate_data, dict):
                    gate_status = gate_data.get("status", "")
                elif hasattr(gate_data, "status"):
                    gate_status = str(gate_data.status)
                review_evidence.append(ReviewEvidence(
                    stage_id=rd.get("task_id") or rd.get("stage_id", ""),
                    review_id=review_id,
                    decision=str(rd.get("decision", "")).upper() if rd.get("decision") else "UNKNOWN",
                    findings_count=len(rd.get("findings", [])),
                    blocking_findings=rd.get("blocking_findings", 0),
                    deterministic_findings=rd.get("deterministic_findings", 0),
                    ai_findings=rd.get("ai_findings", 0),
                    categories_run=categories_run,
                    gate_status=gate_status,
                    review_requested=True,
                    review_result_recorded=True,
                ))

        return GovernanceEvidence(
            project_id=evidence.project_id,
            workflow_id=evidence.workflow_id,
            execution_id=evidence.execution_id,
            chain_summary=evidence.chain_summary,
            stage_evidence=evidence.stage_evidence,
            review_evidence=review_evidence or evidence.review_evidence,
            hitl_evidence=hitl_evidence or evidence.hitl_evidence,
            audit_evidence=audit_evidence or evidence.audit_evidence,
            execution_metrics=evidence.execution_metrics,
            assembled_at=_utc_now(),
        )

    def make_governance_decision(
        self,
        evidence: GovernanceEvidence,
    ) -> GovernanceDecision:
        """Derive a governance decision from assembled evidence.

        Deterministic derivation from real subsystem outputs — not a policy engine.
        """
        blockers: list[str] = []

        for rev in evidence.review_evidence:
            if rev.blocking_findings > 0:
                blockers.append(f"BLOCKING_FINDINGS:{rev.blocking_findings}")

        pending_hitl = rejected_hitl = False
        for hitl in evidence.hitl_evidence:
            if hitl.status == "PENDING":
                pending_hitl = True
            elif hitl.status == "REJECTED":
                rejected_hitl = True
                blockers.append(f"HITL_REJECTED:{hitl.gate_id}")

        if pending_hitl:
            return GovernanceDecision(
                outcome="PENDING_HITL",
                reason="One or more HITL gates are awaiting human approval.",
                evidence_refs=[h.gate_id for h in evidence.hitl_evidence],
                blockers=blockers,
            )

        if rejected_hitl:
            return GovernanceDecision(
                outcome="REJECTED",
                reason="An HITL gate was rejected.",
                evidence_refs=[h.gate_id for h in evidence.hitl_evidence],
                blockers=blockers,
            )

        if blockers:
            return GovernanceDecision(
                outcome="BLOCKED",
                reason="One or more blocking conditions detected.",
                evidence_refs=blockers,
                blockers=blockers,
            )

        failed = evidence.chain_summary.get("failed_stages", 0)
        succeeded = evidence.chain_summary.get("succeeded_stages", 0)
        total = evidence.chain_summary.get("total_stages", 0)

        if failed > 0:
            return GovernanceDecision(
                outcome="REJECTED",
                reason=f"{failed} stage(s) failed during execution.",
                evidence_refs=[s.stage_id for s in evidence.stage_evidence if s.status == "FAILED"],
                blockers=[f"FAILED:{s.stage_id}" for s in evidence.stage_evidence if s.status == "FAILED"],
            )

        if succeeded == total and total > 0:
            return GovernanceDecision(
                outcome="APPROVED",
                reason=f"All {total} stage(s) completed successfully.",
                evidence_refs=[s.stage_id for s in evidence.stage_evidence],
            )

        return GovernanceDecision(
            outcome="UNKNOWN",
            reason="Insufficient evidence to determine governance outcome.",
            evidence_refs=[],
            blockers=[],
        )

    def produce_governance_report(
        self,
        state: Any,
        evidence: GovernanceEvidence,
        decision: GovernanceDecision,
        artifact_records: list[dict[str, Any]] | None = None,
    ) -> GovernanceReport:
        """Produce a formal GovernanceReport artifact from assembled evidence."""
        report_id = str(uuid.uuid4())
        artifacts = artifact_records or []

        stages = getattr(state, "stages", {}) or {}
        stage_order = getattr(state, "stage_order", list(stages.keys()))
        final_stage = stage_order[-1] if stage_order else None

        total = len(evidence.stage_evidence)
        succeeded_n = sum(1 for s in evidence.stage_evidence if s.status in ("SUCCEEDED", "succeeded"))
        failed_n = sum(1 for s in evidence.stage_evidence if s.status in ("FAILED", "failed"))
        skipped_n = sum(1 for s in evidence.stage_evidence if s.status in ("PENDING", "RUNNING", "BLOCKED", "pending", "running", "blocked"))

        artifact_inventory = [
            {
                "artifact_id": str(art.get("artifact_id", "")),
                "name": art.get("name", ""),
                "type": art.get("artifact_type", ""),
                "stage_id": (art.get("metadata") or {}).get("stage_id", ""),
                "content_hash": art.get("checksum") or art.get("content_hash", ""),
            }
            for art in artifacts
        ]

        report = GovernanceReport(
            report_id=report_id,
            project_id=evidence.project_id,
            workflow_id=evidence.workflow_id,
            execution_id=evidence.execution_id,
            workflow_name=getattr(state, "workflow_name", "") or "",
            objective=getattr(state, "objective", "") or "",
            outcome=decision.outcome,
            governance_decision=decision,
            evidence=evidence,
            artifact_inventory=artifact_inventory,
            final_stage=final_stage,
            total_stages=total,
            succeeded_stages=succeeded_n,
            failed_stages=failed_n,
            skipped_stages=skipped_n,
            generated_at=_utc_now(),
            chain_identity="",
        )

        report_dict = report.to_dict()
        report_dict.pop("chain_identity", None)
        report.chain_identity = _sha256(json.dumps(report_dict, sort_keys=True, default=str))

        return report

    def register_governance_report(
        self,
        report: GovernanceReport,
        artifact_manager: Any,
        *,
        created_by: str = "governance_service",
        provenance: dict[str, Any] | None = None,
    ) -> Any:
        """Register a governance report as an artifact with the ArtifactManager.

        Uses the real ArtifactManager contract:
            1. create_artifact(...) — registers identity, type, metadata
            2. create_version(artifact_id, content, ...) — stores the body
        """
        if artifact_manager is None:
            return None
        report_content = report.to_json()
        prov_dict = provenance or {}
        artifact = artifact_manager.create_artifact(
            name=f"governance_report_{report.execution_id}.json",
            artifact_type=CanonicalArtifactType.GOVERNANCE_REPORT,
            project_id=None,
            workflow_id=None,
            created_by=created_by,
            metadata={
                "report_id": report.report_id,
                "execution_id": report.execution_id,
                "outcome": report.outcome,
                "total_stages": report.total_stages,
                "succeeded_stages": report.succeeded_stages,
                "failed_stages": report.failed_stages,
                "chain_identity": report.chain_identity,
                "generated_at": report.generated_at,
                "governance_decision": report.governance_decision.outcome,
                **prov_dict,
            },
        )
        # Store the body as a real, hashable, content-addressed version.
        if hasattr(artifact_manager, "create_version") and artifact is not None:
            try:
                artifact_manager.create_version(
                    artifact.artifact_id,
                    report_content,
                    created_by=created_by,
                )
            except Exception:
                # Versioning failure must not block artifact registration.
                pass
        return artifact

    def register_review_artifact(
        self,
        review_result: Any,
        stage_id: str,
        artifact_manager: Any,
        project_id: str | None = None,
        workflow_id: str | None = None,
        created_by: str = "review_engine",
    ) -> Any:
        """Register a ReviewEngine result as a REVIEW_ARTIFACT."""
        if artifact_manager is None:
            return None
        if hasattr(review_result, "model_dump"):
            content = json.dumps(review_result.model_dump(), indent=2, default=str)
        elif isinstance(review_result, dict):
            content = json.dumps(review_result, indent=2, default=str)
        else:
            # SimpleNamespace or any attr-based object — use vars()
            try:
                payload = {k: v for k, v in vars(review_result).items()}
            except TypeError:
                payload = {}
            content = json.dumps(payload, indent=2, default=str)
        review_id = getattr(review_result, "review_id", "unknown")
        decision = getattr(review_result, "decision", "UNKNOWN")
        decision_val = decision.value if hasattr(decision, "value") else str(decision)
        gate = getattr(review_result, "gate", None)
        gate_status = str(getattr(gate, "status", "") if gate else "")
        artifact = artifact_manager.create_artifact(
            name=f"review_{stage_id}_{review_id}.json",
            artifact_type=CanonicalArtifactType.REVIEW_ARTIFACT,
            project_id=None,
            workflow_id=None,
            created_by=created_by,
            metadata={
                "stage_id": stage_id,
                "review_id": review_id,
                "decision": decision_val,
                "findings_count": len(getattr(review_result, "findings", [])),
                "blocking_findings": getattr(review_result, "blocking_findings", 0),
                "gate_status": gate_status,
            },
        )
        # Persist the body as a content-addressed version when the real
        # ArtifactManager is connected.
        if hasattr(artifact_manager, "create_version") and artifact is not None:
            try:
                artifact_manager.create_version(
                    artifact.artifact_id,
                    content,
                    created_by=created_by,
                )
            except Exception:
                pass
        return artifact


__all__ = [
    "StageEvidence",
    "ReviewEvidence",
    "HITLEvidence",
    "AuditEvidence",
    "GovernanceEvidence",
    "GovernanceDecision",
    "GovernanceReport",
    "GovernanceReportService",
]
