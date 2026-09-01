"""
Phase 18-F Adversarial Certification Test Suite.
"""
from __future__ import annotations
import asyncio
import json
import uuid
from pathlib import Path
from typing import Any

import pytest
import sys

_ROOT = Path(__file__).resolve().parents[2]
for _pkg in ["orchestration", "workforce", "execution", "ai_infrastructure",
             "events", "artifacts", "security", "review", "knowledge",
             "connectors", "workflows"]:
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
from autoforge_review.models import (
    ReviewRequest, ReviewResult, ReviewDecision, QualityGateResult, GateStatus,
    ReviewFinding, ReviewCategory, Severity,
)
from test_helpers import DeterministicStageAIProvider, SimpleEventSink, default_verification_command


class _BaseOrchestrator(OrchestrationEngine):
    def __init__(self, config, review_engine, event_sink=None):
        self._mock_review_engine = review_engine
        super().__init__(config, event_sink=event_sink, review_engine=review_engine)
        self._ai_providers: list = []

    def _get_ai_provider(self, stage):
        provider = DeterministicStageAIProvider()
        self._ai_providers.append(provider)
        return provider

    def _get_verification_commands(self, stage):
        from autoforge_execution.models import CommandSpec
        return [CommandSpec(argv=default_verification_command(stage.stage_id))]


class MockReviewEngine:
    """Async review engine wrapper — review() must be async since orchestrator awaits it."""
    def __init__(self, scripted: ReviewResult):
        self._scripted = scripted

    async def review(self, request: ReviewRequest) -> ReviewResult:
        return self._scripted


def _make_approved() -> ReviewResult:
    return ReviewResult(
        review_id=f"rev-{uuid.uuid4().hex[:8]}",
        categories_run=["style", "correctness", "security"],
        findings=[],
        count_by_category={"style": 0, "correctness": 0, "security": 0},
        count_by_severity={},
        blocking_findings=0,
        gate=QualityGateResult(
            status=GateStatus.PASS,
            satisfied_gates=["style", "correctness", "security"],
            violated_gates=[],
        ),
        decision=ReviewDecision.APPROVED,
    )


def _make_rejected() -> ReviewResult:
    blocking_finding = ReviewFinding(
        category=ReviewCategory.CODE,
        severity=Severity.HIGH,
        title="Critical correctness violation detected",
        description="Code has a critical bug",
        blocking=True,
    )
    return ReviewResult(
        review_id=f"rev-{uuid.uuid4().hex[:8]}",
        categories_run=["correctness"],
        findings=[blocking_finding],
        count_by_category={"correctness": 1},
        count_by_severity={"HIGH": 1},
        blocking_findings=1,
        gate=QualityGateResult(
            status=GateStatus.FAIL,
            satisfied_gates=[],
            violated_gates=["correctness"],
        ),
        decision=ReviewDecision.REJECTED,
    )


def _make_changes_requested() -> ReviewResult:
    cr_finding = ReviewFinding(
        category=ReviewCategory.CODE,
        severity=Severity.HIGH,
        title="Code needs revision: correctness issue found",
        description="Code requires changes before approval",
        blocking=True,
    )
    return ReviewResult(
        review_id=f"rev-{uuid.uuid4().hex[:8]}",
        categories_run=["correctness"],
        findings=[cr_finding],
        count_by_category={"correctness": 1},
        count_by_severity={"HIGH": 1},
        blocking_findings=1,
        gate=QualityGateResult(
            status=GateStatus.FAIL,
            satisfied_gates=[],
            violated_gates=["correctness"],
        ),
        decision=ReviewDecision.CHANGES_REQUESTED,
    )


def _record_audit(engine: AuditEngine, actor_id: str, action: str,
                  resource: str, outcome: str = "success") -> AuditRecord:
    request = AuthorizationRequest(
        subject=Subject(subject_id=actor_id, display_name=actor_id,
                       subject_type=SubjectType.WORKER, roles=frozenset()),
        action=action, resource=resource,
    )
    decision = AuthorizationDecision(
        decision=DecisionType.ALLOW, is_allowed=True,
        reason=f"test event for {action}",
    )
    return engine.record_decision(request, decision, outcome=outcome)


def _extract_gov(plat):
    store = plat.store
    arts = [a for a in store.list_artifacts()
            if a.artifact_type == CanonicalArtifactType.GOVERNANCE_REPORT]
    if not arts:
        return None
    # Return the most recent one (latest `generated_at` timestamp).
    def _sort_key(a):
        return a.metadata.get("generated_at", "") or ""
    return max(arts, key=_sort_key)


def _load_gov(plat, gov):
    versions = plat.versioning.get_history(gov.artifact_id)
    assert versions, "GOVERNANCE_REPORT has no versions"
    latest = versions[-1]
    content = plat.versioning.get_version(gov.artifact_id, latest.version_id)
    return json.loads(content.content)


async def _run_greenfield(orch, objective="Build a simple calculator"):
    state = await orch.create_project(objective=objective, workflow_id="greenfield")
    return await orch.run_project(state.execution_id)


def _base_config(workspace_root: Path, **overrides) -> OrchestrationConfig:
    cfg = dict(
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
    cfg.update(overrides)
    return OrchestrationConfig(**cfg)


@pytest.fixture
def workspace_root(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def plat():
    return build_artifact_platform()


@pytest.fixture
def audit_engine() -> AuditEngine:
    return AuditEngine()


# ── Test: HITL APPROVED → governance APPROVED ──────────────────────────────────


@pytest.mark.asyncio
async def test_18f_hitl_approved_governance_approved(workspace_root, audit_engine):
    """
    [S5] HITL APPROVED path: human approves deployment gate → governance APPROVED.
    """
    plat = build_artifact_platform()
    cfg = _base_config(workspace_root, require_hitl_for_deployment=True)
    _record_audit(audit_engine, 'actor', 'stage_execute', 'stage-0', 'success')
    orch = _BaseOrchestrator(cfg, MockReviewEngine(_make_approved()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine

    state = await orch.create_project(objective="Build a calculator", workflow_id="greenfield")
    result = await orch.run_project(state.execution_id)
    assert result.status == WorkflowStatus.WAITING_FOR_HITL

    gate_id = next(iter(result.hitl_gates.keys()))
    resumed = await orch.resume_from_hitl(
        state.execution_id, gate_id, approved=True, reason="Approved by human",
    )
    assert resumed.status in (WorkflowStatus.COMPLETED, WorkflowStatus.RUNNING)

    gov = _extract_gov(plat)
    assert gov is not None, "GOVERNANCE_REPORT not found after HITL approval"
    report = _load_gov(plat, gov)
    outcome = report["governance_decision"]["outcome"]
    assert outcome == "APPROVED", f"HITL-approval path must yield APPROVED, got {outcome}"

    hitl_ev = report.get("evidence", {}).get("hitl_evidence", [])
    approved_gates = [h for h in hitl_ev if h.get("status") == "APPROVED"]
    assert approved_gates, "No APPROVED HITL gates in governance evidence"


# ── Test: HITL REJECTED → governance REJECTED ──────────────────────────────────


@pytest.mark.asyncio
async def test_18f_hitl_rejected_governance_rejected(workspace_root, audit_engine):
    """
    [S6] HITL REJECTED path: human rejects deployment gate → governance MUST NOT be APPROVED.
    """
    plat = build_artifact_platform()
    cfg = _base_config(workspace_root, require_hitl_for_deployment=True)
    _record_audit(audit_engine, 'actor', 'stage_execute', 'stage-0', 'success')
    orch = _BaseOrchestrator(cfg, MockReviewEngine(_make_approved()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine

    state = await orch.create_project(objective="Build a calculator", workflow_id="greenfield")
    result = await orch.run_project(state.execution_id)
    assert result.status == WorkflowStatus.WAITING_FOR_HITL

    gate_id = next(iter(result.hitl_gates.keys()))
    resumed = await orch.resume_from_hitl(
        state.execution_id, gate_id, approved=False, reason="Security concern",
    )
    assert resumed.status == WorkflowStatus.FAILED, (
        f"Expected FAILED after HITL rejection, got {resumed.status}"
    )

    gov = _extract_gov(plat)
    assert gov is not None
    report = _load_gov(plat, gov)
    outcome = report["governance_decision"]["outcome"]
    assert outcome != "APPROVED", (
        f"HITL-rejected path MUST NOT yield APPROVED, got {outcome}"
    )
    assert outcome in ("REJECTED", "BLOCKED"), (
        f"Expected REJECTED or BLOCKED after HITL rejection, got {outcome}"
    )

    hitl_ev = report.get("evidence", {}).get("hitl_evidence", [])
    rejected_gates = [h for h in hitl_ev if h.get("status") == "REJECTED"]
    assert rejected_gates, "No REJECTED HITL gates in governance evidence"


# Test: CHANGES_REQUESTED not approved

@pytest.mark.asyncio
async def test_18f_changes_requested_not_approved(workspace_root, audit_engine):
    plat = build_artifact_platform()
    _record_audit(audit_engine, 'actor', 'stage_execute', 'stage-0', 'success')
    orch = _BaseOrchestrator(_base_config(workspace_root), MockReviewEngine(_make_changes_requested()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine
    await _run_greenfield(orch)
    gov = _extract_gov(plat)
    assert gov is not None, 'GOVERNANCE_REPORT not found'
    report = _load_gov(plat, gov)
    outcome = report['governance_decision']['outcome']
    assert outcome != 'APPROVED', f'CHANGES_REQUESTED MUST NOT yield APPROVED, got {outcome}'
    assert outcome in ('REJECTED', 'BLOCKED', 'UNKNOWN'), f'Expected REJECTED/BLOCKED/UNKNOWN, got {outcome}'


# Test: blocking_findings surface in governance

@pytest.mark.asyncio
async def test_18f_blocking_findings_in_governance(workspace_root, audit_engine):
    plat = build_artifact_platform()
    _record_audit(audit_engine, 'actor', 'stage_execute', 'stage-0', 'success')
    orch = _BaseOrchestrator(_base_config(workspace_root), MockReviewEngine(_make_rejected()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine
    await _run_greenfield(orch)
    gov = _extract_gov(plat)
    assert gov is not None
    report = _load_gov(plat, gov)
    review_ev = report.get('evidence', {}).get('review_evidence', [])
    assert review_ev, 'review_evidence must be populated in GOVERNANCE_REPORT'
    blocking = [r for r in review_ev if r.get('blocking_findings', 0) > 0]
    assert blocking, f'No review_evidence with blocking_findings > 0: {review_ev}'
    outcome = report['governance_decision']['outcome']
    blockers = report['governance_decision'].get('blockers', [])
    assert outcome in ('REJECTED', 'BLOCKED'), f'Expected REJECTED/BLOCKED, got {outcome}'
    assert any('BLOCKING_FINDINGS' in b for b in blockers), f'BLOCKING_FINDINGS missing: {blockers}'


# Test: review_evidence populated on happy path

@pytest.mark.asyncio
async def test_18f_review_evidence_populated_on_approved(workspace_root, audit_engine):
    plat = build_artifact_platform()
    for i in range(3):
        _record_audit(audit_engine, f'actor-{i}', f'action-{i}', f'res-{i}', 'success')
    orch = _BaseOrchestrator(_base_config(workspace_root), MockReviewEngine(_make_approved()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine
    await _run_greenfield(orch)
    gov = _extract_gov(plat)
    assert gov is not None
    report = _load_gov(plat, gov)
    review_ev = report.get('evidence', {}).get('review_evidence', [])
    assert review_ev, 'review_evidence is empty - the review-governance pipeline is not wired.'
    for rev in review_ev:
        assert 'review_id' in rev, f'review_id missing: {rev}'
        assert 'decision' in rev, f'decision missing: {rev}'
        assert 'stage_id' in rev, f'stage_id missing: {rev}'
    assert report['governance_decision']['outcome'] == 'APPROVED'


# Test: audit record_id equals real AuditRecord.audit_id

@pytest.mark.asyncio
async def test_18f_audit_identity_never_fabricated(workspace_root, audit_engine):
    plat = build_artifact_platform()
    audit_records = [
        _record_audit(audit_engine, 'alice', 'deploy', 'prod-app', 'success'),
        _record_audit(audit_engine, 'bob', 'stage_execute', 'build-stage', 'success'),
    ]
    orch = _BaseOrchestrator(_base_config(workspace_root), MockReviewEngine(_make_approved()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine
    await _run_greenfield(orch)
    gov = _extract_gov(plat)
    assert gov is not None
    report = _load_gov(plat, gov)
    audit_ev = report.get('evidence', {}).get('audit_evidence', [])
    assert audit_ev, 'audit_evidence must not be empty'
    real_ids = {rec.audit_id for rec in audit_records}
    for aud in audit_ev:
        rid = aud.get('record_id', '')
        assert rid in real_ids, f'audit record_id does not match any AuditRecord.audit_id. Expected one of {real_ids}'


# Test: failed execution -> governance REJECTED

@pytest.mark.asyncio
async def test_18f_failed_execution_governance_rejected(workspace_root, audit_engine):
    plat = build_artifact_platform()
    _record_audit(audit_engine, 'actor', 'stage_execute', 'stage-0', 'success')
    orch = _BaseOrchestrator(_base_config(workspace_root), MockReviewEngine(_make_rejected()), SimpleEventSink())
    orch._artifact_manager = plat.manager
    orch._audit_engine = audit_engine
    result = await _run_greenfield(orch)
    assert result.status == WorkflowStatus.FAILED
    gov = _extract_gov(plat)
    assert gov is not None
    report = _load_gov(plat, gov)
    outcome = report['governance_decision']['outcome']
    assert outcome != 'APPROVED', f'Failed execution MUST NOT yield APPROVED, got {outcome}'
    assert outcome in ('REJECTED', 'BLOCKED'), f'Expected REJECTED/BLOCKED, got {outcome}'


# Test: chain_identity differs by outcome

@pytest.mark.asyncio
async def test_18f_chain_identity_differs_by_outcome(workspace_root, audit_engine):
    plat_a = build_artifact_platform()
    _record_audit(audit_engine, 'actor', 'stage_execute', 'stage-0', 'success')
    orch_a = _BaseOrchestrator(_base_config(workspace_root / 'run_a'), MockReviewEngine(_make_approved()), SimpleEventSink())
    orch_a._artifact_manager = plat_a.manager
    orch_a._audit_engine = audit_engine
    await _run_greenfield(orch_a)
    gov_a = _extract_gov(plat_a)
    assert gov_a is not None
    chain_a = gov_a.metadata['chain_identity']

    plat_b = build_artifact_platform()
    audit_b = AuditEngine()
    _record_audit(audit_b, 'actor', 'stage_execute', 'stage-0', 'success')
    orch_b = _BaseOrchestrator(_base_config(workspace_root / 'run_b'), MockReviewEngine(_make_rejected()), SimpleEventSink())
    orch_b._artifact_manager = plat_b.manager
    orch_b._audit_engine = audit_b
    await _run_greenfield(orch_b)
    gov_b = _extract_gov(plat_b)
    assert gov_b is not None
    chain_b = gov_b.metadata['chain_identity']

    assert chain_a != chain_b, f'chain_identity must differ. Both: {chain_a}'
