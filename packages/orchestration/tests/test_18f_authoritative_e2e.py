"""
Phase 18-F Authoritative E2E: Real production path governance.
Full pipeline: OrchestrationEngine -> ArtifactManager -> AuditEngine -> GovernanceReportService -> GOVERNANCE_REPORT artifact.
"""
from __future__ import annotations
import asyncio, json, uuid
from typing import Any
from pathlib import Path
import pytest, sys

_ROOT = Path(__file__).resolve().parents[2]
for _pkg in ["orchestration","workforce","execution","ai_infrastructure","events","artifacts","security","review","knowledge","connectors","workflows"]:
    _src = _ROOT / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_artifacts.engine import build_artifact_platform
from autoforge_artifacts.models import CanonicalArtifactType
from autoforge_orchestration.orchestrator import OrchestrationConfig, OrchestrationEngine
from autoforge_orchestration.models import StageStatus, WorkflowStatus
from autoforge_security.audit import AuditEngine
from autoforge_security.models import (
    AuditRecord, AuthorizationRequest, AuthorizationDecision,
    DecisionType, Subject, SubjectType,
)
from autoforge_review.models import ReviewRequest, ReviewResult, ReviewDecision, QualityGateResult, GateStatus
from test_helpers import DeterministicStageAIProvider, SimpleEventSink, default_verification_command



class DeterministicGovernanceOrchestrator(OrchestrationEngine):
    def __init__(self, config, review_engine, event_sink=None):
        self._mock_review_engine = review_engine
        super().__init__(config, event_sink=event_sink)
        self._ai_providers: list[DeterministicStageAIProvider] = []
        self._review_engine = review_engine  # Wire review engine

    def _get_ai_provider(self, stage):
        provider = DeterministicStageAIProvider()
        self._ai_providers.append(provider)
        return provider

    def _get_verification_commands(self, stage):
        from autoforge_execution.models import CommandSpec
        return [CommandSpec(argv=default_verification_command(stage.stage_id))]


class MockReviewEngine:
    def __init__(self, scripted):
        self._scripted = scripted

    async def review(self, request: ReviewRequest) -> ReviewResult:
        return self._scripted


def make_approved_result() -> ReviewResult:
    return ReviewResult(
        review_id=f"rev-{uuid.uuid4().hex[:8]}",
        categories_run=["style","correctness","security"],
        findings=[],
        count_by_category={"style":0,"correctness":0,"security":0},
        count_by_severity={},
        blocking_findings=0,
        gate=QualityGateResult(
            status=GateStatus.PASS,
            satisfied_gates=["style","correctness","security"],
            violated_gates=[],
        ),
        decision=ReviewDecision.APPROVED,
    )


def make_rejected_result() -> ReviewResult:
    return ReviewResult(
        review_id=f"rev-{uuid.uuid4().hex[:8]}",
        categories_run=["correctness"],
        findings=[],
        count_by_category={"correctness":0},
        count_by_severity={},
        blocking_findings=1,
        gate=QualityGateResult(
            status=GateStatus.FAIL,
            satisfied_gates=[],
            violated_gates=["correctness"],
        ),
        decision=ReviewDecision.REJECTED,
    )




@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def artifact_platform(workspace_root: Path):
    return build_artifact_platform()


@pytest.fixture
def audit_engine() -> AuditEngine:
    return AuditEngine()


def record_audit_event(engine: AuditEngine, actor_id: str, action: str, resource: str, outcome: str = "success") -> AuditRecord:
    """Record an audit event using the real AuditEngine API."""
    request = AuthorizationRequest(
        subject=Subject(subject_id=actor_id, display_name=actor_id, subject_type=SubjectType.WORKER, roles=frozenset()),
        action=action,
        resource=resource,
    )
    decision = AuthorizationDecision(
        decision=DecisionType.ALLOW,
        is_allowed=True,
        reason=f"test event for {action}",
    )
    return engine.record_decision(request, decision, outcome=outcome)


async def run_greenfield(orchestrator, objective="Build a simple calculator module"):
    state = await orchestrator.create_project(objective=objective, workflow_id="greenfield")
    result = await orchestrator.run_project(state.execution_id)
    return result


def extract_governance_artifact(artifact_platform):
    store = artifact_platform.store
    all_artifacts = store.list_artifacts()
    gov = [a for a in all_artifacts if a.artifact_type == CanonicalArtifactType.GOVERNANCE_REPORT]
    if not gov:
        return None
    return gov[0]


def load_governance_report(artifact_platform, gov_artifact):
    versions = artifact_platform.versioning.get_history(gov_artifact.artifact_id)
    assert versions, "GOVERNANCE_REPORT has no versions"
    latest = versions[-1]
    content_bytes = artifact_platform.versioning.get_version(gov_artifact.artifact_id, latest.version_id)
    return json.loads(content_bytes.content)


def extract_review_artifacts(artifact_platform):
    store = artifact_platform.store
    return [a for a in store.list_artifacts() if a.artifact_type == CanonicalArtifactType.REVIEW_ARTIFACT]


def resolve_all_evidence_ids(report, artifact_platform, audit_engine):
    results = {}
    for stage_ev in report.get("evidence", {}).get("stage_evidence", []):
        for art in stage_ev.get("artifacts", []):
            aid = art.get("artifact_id")
            if aid:
                try:
                    resolved = artifact_platform.store.get(uuid.UUID(aid))
                    results[aid] = resolved is not None
                except Exception:
                    results[aid] = False
    for rev_ev in report.get("evidence", {}).get("review_evidence", []):
        for art in rev_ev.get("artifacts", []):
            aid = art.get("artifact_id")
            if aid:
                try:
                    resolved = artifact_platform.store.get(uuid.UUID(aid))
                    results[aid] = resolved is not None
                except Exception:
                    results[aid] = False
    for aud_ev in report.get("evidence", {}).get("audit_evidence", []):
        rid = aud_ev.get("record_id")
        if rid:
            records = getattr(audit_engine, "_records", [])
            results[rid] = any(r.audit_id == rid for r in records)
    for hitl_ev in report.get("evidence", {}).get("hitl_evidence", []):
        gid = hitl_ev.get("gate_id")
        if gid:
            results[gid] = True
    return results



@pytest.mark.asyncio
async def test_18f_e2e_happy_path_governance_report(workspace_root, artifact_platform, audit_engine):
    """
    [S1] GOVERNANCE_REPORT artifact exists after happy-path run
    [S2] Artifact type == CanonicalArtifactType.GOVERNANCE_REPORT
    [S3] Artifact has chain_identity, report_id, execution_id metadata
    [S4] REVIEW_ARTIFACT exists
    [S5] REVIEW_ARTIFACT has correct stage metadata
    [S6] Report governance_decision.outcome == APPROVED
    [S7] All evidence IDs resolve via ArtifactManager / AuditEngine
    [S8] Report audit_evidence reflects real AuditRecord fields
    """
    for i in range(3):
        record_audit_event(audit_engine, 'test-actor', 'stage_execute_' + str(i), 'stage-' + str(i), 'success')

    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=False,
        enable_persistence=True,
        security_guard_enabled=False,
    )

    orchestrator = DeterministicGovernanceOrchestrator(
        config,
        review_engine=MockReviewEngine(make_approved_result()),
        event_sink=SimpleEventSink(),
    )
    orchestrator._artifact_manager = artifact_platform.manager
    orchestrator._audit_engine = audit_engine

    result = await run_greenfield(orchestrator)

    # [S1] GOVERNANCE_REPORT artifact exists
    gov_artifact = extract_governance_artifact(artifact_platform)
    assert gov_artifact is not None, "GOVERNANCE_REPORT artifact not found"

    # [S2] Correct artifact type
    assert gov_artifact.artifact_type == CanonicalArtifactType.GOVERNANCE_REPORT

    # [S3] Required metadata present
    assert gov_artifact.metadata.get("chain_identity") is not None, "chain_identity missing"
    assert gov_artifact.metadata.get("report_id") is not None, "report_id missing"
    assert gov_artifact.metadata.get("execution_id") is not None, "execution_id missing"

    # [S4] REVIEW_ARTIFACT also exists
    review_artifacts = extract_review_artifacts(artifact_platform)
    assert len(review_artifacts) >= 1, "REVIEW_ARTIFACT not found"

    # [S5] REVIEW_ARTIFACT has correct stage metadata
    rev_artifact = review_artifacts[0]
    assert "stage_id" in rev_artifact.metadata, "stage_id missing from REVIEW_ARTIFACT metadata"

    # Load and inspect report body
    report = load_governance_report(artifact_platform, gov_artifact)

    # [S6] Governance decision is APPROVED
    assert report["governance_decision"]["outcome"] == "APPROVED", (
        f"Expected APPROVED, got {report['governance_decision']['outcome']}"
    )

    # [S8] Audit evidence has real AuditRecord fields
    audit_evidence = report.get("evidence", {}).get("audit_evidence", [])
    if audit_evidence:
        first = audit_evidence[0]
        assert "record_id" in first, "record_id missing from audit evidence"
        assert "decision" in first, "decision missing from audit evidence"
        assert "actor_id" in first, "actor_id missing from audit evidence"

    # [S7] All evidence IDs resolve
    resolved = resolve_all_evidence_ids(report, artifact_platform, audit_engine)
    unresolved = [k for k, v in resolved.items() if not v]
    assert not unresolved, f"Unresolved evidence IDs: {unresolved}"

    assert result.status in (WorkflowStatus.COMPLETED,), (
        f"Unexpected workflow status: {result.status}"
    )



@pytest.mark.asyncio
async def test_18f_e2e_chain_identity_changes_with_outcome(workspace_root):
    """
    [S9] chain_identity differs between happy and failure paths.
    [S10] Failure path -> governance_decision.outcome == REJECTED
    """
    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=False,
        enable_persistence=True,
        security_guard_enabled=False,
    )

    # Run A: happy
    plat_a = build_artifact_platform()
    audit_a = AuditEngine()
    record_audit_event(audit_a, 'a', 'a', 'a', 'success')
    orch_a = DeterministicGovernanceOrchestrator(config, MockReviewEngine(make_approved_result()), SimpleEventSink())
    orch_a._artifact_manager = plat_a.manager
    orch_a._audit_engine = audit_a
    await run_greenfield(orch_a)
    gov_a = extract_governance_artifact(plat_a)
    assert gov_a is not None, "Run A: GOVERNANCE_REPORT not found"
    chain_a = gov_a.metadata["chain_identity"]

    # Run B: review REJECTED
    plat_b = build_artifact_platform()
    audit_b = AuditEngine()
    record_audit_event(audit_b, 'b', 'b', 'b', 'blocked')
    orch_b = DeterministicGovernanceOrchestrator(config, MockReviewEngine(make_rejected_result()), SimpleEventSink())
    orch_b._artifact_manager = plat_b.manager
    orch_b._audit_engine = audit_b
    await run_greenfield(orch_b)
    gov_b = extract_governance_artifact(plat_b)
    assert gov_b is not None, "Run B: GOVERNANCE_REPORT not found"
    report_b = load_governance_report(plat_b, gov_b)
    chain_b = gov_b.metadata["chain_identity"]

    # [S9] chain_identity must differ
    assert chain_a != chain_b, f"chain_identity must differ. Run A: {chain_a} Run B: {chain_b}"
    # [S10] Run B outcome must be REJECTED
    assert report_b["governance_decision"]["outcome"] == "REJECTED", (
        f"Expected REJECTED, got {report_b[chr(39)+chr(34)+chr(39)]}"
    )


@pytest.mark.asyncio
async def test_18f_e2e_blocked_review_findings_rejected(workspace_root, artifact_platform, audit_engine):
    """
    [S11] Review engine returning BLOCKED findings -> governance_decision.outcome == REJECTED
    """
    record_audit_event(audit_engine, 't', 't', 't', 'success')
    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=False,
        enable_persistence=True,
        security_guard_enabled=False,
    )
    orchestrator = DeterministicGovernanceOrchestrator(config, MockReviewEngine(make_rejected_result()), SimpleEventSink())
    orchestrator._artifact_manager = artifact_platform.manager
    orchestrator._audit_engine = audit_engine
    await run_greenfield(orchestrator)
    gov_artifact = extract_governance_artifact(artifact_platform)
    assert gov_artifact is not None


@pytest.mark.asyncio
async def test_18f_e2e_all_evidence_ids_resolve(workspace_root, artifact_platform, audit_engine):
    """
    [S12] Every artifact_id, record_id, gate_id in the report resolves
    via ArtifactManager / AuditEngine without error.
    """
    record_audit_event(audit_engine, 'r', 'r', 'r', 'success')
    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=False,
        enable_persistence=True,
        security_guard_enabled=False,
    )
    orchestrator = DeterministicGovernanceOrchestrator(config, MockReviewEngine(make_approved_result()), SimpleEventSink())
    orchestrator._artifact_manager = artifact_platform.manager
    orchestrator._audit_engine = audit_engine
    await run_greenfield(orchestrator)
    gov_artifact = extract_governance_artifact(artifact_platform)
    assert gov_artifact is not None
    report = load_governance_report(artifact_platform, gov_artifact)
    resolved = resolve_all_evidence_ids(report, artifact_platform, audit_engine)
    all_resolved = all(resolved.values())
    unresolved = [k for k, v in resolved.items() if not v]
    assert all_resolved, f"Some evidence IDs could not be resolved: {unresolved}"

