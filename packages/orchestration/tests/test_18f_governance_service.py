"""Phase 18-F GovernanceReportService tests."""
from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from autoforge_orchestration.governance_service import (
    AuditEvidence,
    GovernanceDecision,
    GovernanceEvidence,
    GovernanceReport,
    GovernanceReportService,
    HITLEvidence,
    ReviewEvidence,
    StageEvidence,
)

def _make_state(**kw):
    defaults = dict(
        project_id="proj-1",
        workflow_id="wf-1",
        execution_id="exec-1",
        workflow_name="Test WF",
        objective="Build something",
        stages=None,
    )
    defaults.update(kw)
    if defaults["stages"] is None:
        defaults["stages"] = [
            SimpleNamespace(
                stage_id="s1",
                status="SUCCEEDED",
                started_at="2026-01-01T00:00:00",
                finished_at="2026-01-01T01:00:00",
                attempt_number=1,
                output={},
                definition={"kind": "implement"},
                worker_type="coder",
            ),
            SimpleNamespace(
                stage_id="s2",
                status="FAILED",
                started_at="2026-01-01T01:00:00",
                finished_at="2026-01-01T02:00:00",
                attempt_number=2,
                output={"evaluation": {"status": "failed", "passed": False, "failures": ["test_x"]}},
                definition={"kind": "evaluate"},
                worker_type="evaluator",
            ),
        ]
    stage_map = {s.stage_id: s for s in defaults["stages"]}
    stage_order = [s.stage_id for s in defaults["stages"]]
    return SimpleNamespace(
        project_id=defaults["project_id"],
        workflow_id=defaults["workflow_id"],
        execution_id=defaults["execution_id"],
        workflow_name=defaults["workflow_name"],
        objective=defaults["objective"],
        stage_order=stage_order,
        stages=stage_map,
        metrics=None,
        artifact_inventory=[],
    )


# ── 1. Dataclass serialization ─────────────────────────────────────────────

def test_stage_evidence_to_dict():
    se = StageEvidence(
        stage_id="s1", stage_kind="implement", status="SUCCEEDED",
        started_at="t0", finished_at="t1", attempt_number=1, artifact_ids=["a1"],
    )
    d = se.to_dict()
    assert d["stage_id"] == "s1"
    assert d["status"] == "SUCCEEDED"
    assert d["artifact_ids"] == ["a1"]


def test_review_evidence_to_dict():
    re = ReviewEvidence(
        stage_id="s1", review_id="r1", decision="APPROVED",
        findings_count=2, blocking_findings=0,
    )
    d = re.to_dict()
    assert d["decision"] == "APPROVED"
    assert d["findings_count"] == 2


def test_hitl_evidence_to_dict():
    he = HITLEvidence(
        gate_id="g1", stage_id="s1", status="APPROVED",
        risk_level="medium", requested_at="t0", decided_at="t1",
        decided_by="alice", decision="APPROVED", reason_text="ok",
    )
    d = he.to_dict()
    assert d["gate_id"] == "g1"
    assert d["status"] == "APPROVED"


def test_audit_evidence_to_dict():
    ae = AuditEvidence(
        record_id="rec1", action="authorize", decision="allow",
        reason="actor ok", outcome="ok", actor_id="alice",
        actor_type="human", project_id="p1", workflow_id="w1",
        task_id="t1", recorded_at="t0",
    )
    d = ae.to_dict()
    assert d["record_id"] == "rec1"
    assert d["actor_id"] == "alice"


def test_governance_evidence_json_roundtrip():
    ev = GovernanceEvidence(
        project_id="p1", workflow_id="w1", execution_id="e1",
        chain_summary={"total_stages": 1, "succeeded_stages": 1, "failed_stages": 0},
        stage_evidence=[
            StageEvidence(stage_id="s1", stage_kind="implement",
                          status="SUCCEEDED", started_at="t0", finished_at="t1",
                          attempt_number=1),
        ],
        review_evidence=[], hitl_evidence=[], audit_evidence=[],
        execution_metrics={}, assembled_at="t0",
    )
    d = ev.to_dict()
    assert d["chain_summary"]["total_stages"] == 1
    j = json.dumps(d)
    assert "s1" in j


def test_governance_report_json_includes_chain_identity():
    dec = GovernanceDecision(outcome="APPROVED", reason="all ok")
    ev = GovernanceEvidence(
        project_id="p1", workflow_id="w1", execution_id="e1",
        chain_summary={"total_stages": 1, "succeeded_stages": 1, "failed_stages": 0},
        stage_evidence=[], review_evidence=[], hitl_evidence=[],
        audit_evidence=[], execution_metrics={}, assembled_at="t0",
    )
    rep = GovernanceReport(
        report_id="r1", project_id="p1", workflow_id="w1", execution_id="e1",
        workflow_name="W", objective="O", outcome="APPROVED",
        governance_decision=dec, evidence=ev,
        artifact_inventory=[], final_stage="s1",
        total_stages=1, succeeded_stages=1, failed_stages=0, skipped_stages=0,
        generated_at="t0", chain_identity="deadbeef",
    )
    j = rep.to_json()
    assert "APPROVED" in j
    assert "deadbeef" in j
    assert "chain_identity" in j



# ── 2. assemble_execution_chain ────────────────────────────────────────────

def test_assemble_execution_chain_real_state():
    state = _make_state()
    svc = GovernanceReportService()
    ev = svc.assemble_execution_chain(
        state,
        artifact_records=[
            {"artifact_id": "a1", "name": "src.py", "artifact_type": "CODE",
             "metadata": {"stage_id": "s1"}},
        ],
    )
    assert ev.project_id == "proj-1"
    assert ev.workflow_id == "wf-1"
    assert ev.execution_id == "exec-1"
    assert ev.chain_summary["total_stages"] == 2
    assert ev.chain_summary["succeeded_stages"] == 1
    assert ev.chain_summary["failed_stages"] == 1
    assert len(ev.stage_evidence) == 2
    s2 = ev.stage_evidence[1]
    assert s2.evaluation_passed is False
    assert "test_x" in s2.evaluation_failures


def test_assemble_execution_chain_empty_stages():
    state = SimpleNamespace(
        project_id="p1", workflow_id="w1", execution_id="e1",
        workflow_name="", objective="",
        stage_order=[], stages={}, metrics=None, artifact_inventory=[],
    )
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    assert ev.chain_summary["total_stages"] == 0
    assert ev.stage_evidence == []


def test_assemble_execution_chain_with_metrics_dict():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    state.metrics = {"llm_tokens": 100, "duration_ms": 5000}
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    assert ev.execution_metrics["llm_tokens"] == 100


def test_assemble_execution_chain_with_metrics_object():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    state.metrics = SimpleNamespace(to_dict=lambda: {"k": "v"})
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    assert ev.execution_metrics == {"k": "v"}




def test_stage_evidence_extracts_diagnosis_and_repair():
    state = SimpleNamespace(
        project_id="p", workflow_id=None, execution_id="e",
        workflow_name="W", objective="O", stage_order=["s1"],
        stages={
            "s1": SimpleNamespace(
                stage_id="s1", status="FAILED",
                started_at="t0", finished_at="t1", attempt_number=2,
                output={
                    "diagnosis": {"root_cause": "null ptr", "confidence_score": 0.9},
                    "repair_result": {
                        "final_status": "failed", "retry_exhausted": True,
                        "attempts": [{}, {}],
                    },
                    "changed_files": ["a.py", "b.py"],
                },
                definition={"kind": "implement"}, worker_type="coder",
            ),
        },
        metrics=None, artifact_inventory=[],
    )
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    s1 = ev.stage_evidence[0]
    assert s1.diagnosis_root_cause == "null ptr"
    assert s1.diagnosis_confidence == 0.9
    assert s1.repair_attempts == 2
    assert s1.repair_retry_exhausted is True
    assert s1.changed_files == ["a.py", "b.py"]


# ── 3. make_governance_decision ────────────────────────────────────────────

def test_decision_rejected_on_failed_stage():
    state = _make_state()
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    dec = GovernanceReportService().make_governance_decision(ev)
    assert dec.outcome == "REJECTED"


def test_decision_approved_on_all_succeeded():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    dec = GovernanceReportService().make_governance_decision(ev)
    assert dec.outcome == "APPROVED"


def test_decision_pending_hitl_when_pending_gate():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])


def test_decision_rejected_on_hitl_rejection():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    ev = GovernanceReportService().assemble_governance_evidence(
        ev, hitl_gates={
            "g1": SimpleNamespace(
                gate_id="g1", stage_id="s1",
                status="REJECTED", risk_level="low",
                requested_at="t0", decided_at="t1",
                actor="bob", decision="reject", reason_text="no",
            ),
        },
    )
    dec = GovernanceReportService().make_governance_decision(ev)
    assert dec.outcome == "REJECTED"


def test_decision_blocked_on_blocking_findings():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    ev = GovernanceReportService().assemble_execution_chain(state, [])
    ev = GovernanceReportService().assemble_governance_evidence(
        ev, review_results=[
            SimpleNamespace(
                review_id="r1", task_id="s1",
                findings=[{"id": "f1"}], blocking_findings=1,
                deterministic_findings=1, ai_findings=0,
                categories_run=["security"],
                gate=SimpleNamespace(status="FAIL"),
            ),
        ],
    )
    dec = GovernanceReportService().make_governance_decision(ev)
    assert dec.outcome == "BLOCKED"


# ── 4. produce_governance_report ───────────────────────────────────────────

def test_produce_governance_report_has_chain_identity():
    state = _make_state()
    svc = GovernanceReportService()
    ev = svc.assemble_execution_chain(state, [])
    dec = svc.make_governance_decision(ev)
    rep = svc.produce_governance_report(state, ev, dec, artifact_records=[])
    assert rep.report_id
    assert rep.project_id == "proj-1"
    assert rep.outcome == dec.outcome
    assert rep.total_stages == 2
    assert rep.failed_stages == 1
    assert len(rep.chain_identity) == 64
    assert rep.evidence is ev
    j = rep.to_json()
    assert "chain_identity" in j


def test_produce_governance_report_chain_identity_changes():
    state_a = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    state_b = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="FAILED",
            started_at="t0", finished_at="t1", attempt_number=2,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    svc = GovernanceReportService()
    rep_a = svc.produce_governance_report(
        state_a,
        svc.assemble_execution_chain(state_a, []),
        svc.make_governance_decision(svc.assemble_execution_chain(state_a, [])),
    )
    rep_b = svc.produce_governance_report(
        state_b,
        svc.assemble_execution_chain(state_b, []),
        svc.make_governance_decision(svc.assemble_execution_chain(state_b, [])),
    )
    assert rep_a.chain_identity != rep_b.chain_identity


# ── 5. register methods ────────────────────────────────────────────────────

def test_register_governance_report_calls_artifact_manager():
    state = _make_state()
    svc = GovernanceReportService()
    ev = svc.assemble_execution_chain(state, [])
    dec = svc.make_governance_decision(ev)
    rep = svc.produce_governance_report(state, ev, dec)
    am = MagicMock()
    svc.register_governance_report(rep, am)
    assert am.create_artifact.called
    call_kwargs = am.create_artifact.call_args.kwargs
    assert call_kwargs["artifact_type"].name == "GOVERNANCE_REPORT"
    assert call_kwargs["metadata"]["report_id"] == rep.report_id
    assert call_kwargs["metadata"]["chain_identity"] == rep.chain_identity
    # Real ArtifactManager: content goes via create_version, not create_artifact
    assert "content" not in call_kwargs
    # Verify create_version was called with the report body
    assert am.create_version.called
    version_call = am.create_version.call_args
    version_content = json.loads(version_call.args[1])
    assert version_content["report_id"] == rep.report_id


def test_register_governance_report_none_artifact_manager():
    state = _make_state()
    svc = GovernanceReportService()
    ev = svc.assemble_execution_chain(state, [])
    dec = svc.make_governance_decision(ev)
    rep = svc.produce_governance_report(state, ev, dec)
    assert svc.register_governance_report(rep, None) is None


def test_register_review_artifact_calls_artifact_manager():
    review_result = SimpleNamespace(
        review_id="r1", decision="APPROVED",
        findings=[], blocking_findings=0,
        gate=SimpleNamespace(status="PASS"),
    )
    am = MagicMock()
    GovernanceReportService().register_review_artifact(
        review_result=review_result,
        stage_id="s1",
        artifact_manager=am,
    )
    assert am.create_artifact.called
    call_kwargs = am.create_artifact.call_args.kwargs
    assert call_kwargs["artifact_type"].name == "REVIEW_ARTIFACT"
    assert call_kwargs["metadata"]["stage_id"] == "s1"


def test_register_review_artifact_handles_model_dump():
    class FakeResult:
        def __init__(self):
            self.review_id = "r2"
            self.decision = SimpleNamespace(value="REJECTED")
            self.findings = []
            self.blocking_findings = 0
            self.gate = SimpleNamespace(status="FAIL")
        def model_dump(self):
            return {"review_id": self.review_id, "decision": "REJECTED"}

    am = MagicMock()
    GovernanceReportService().register_review_artifact(
        review_result=FakeResult(),
        stage_id="s2",
        artifact_manager=am,
    )
    call_kwargs = am.create_artifact.call_args.kwargs
    assert call_kwargs["metadata"]["decision"] == "REJECTED"


def test_register_review_artifact_none_artifact_manager():
    review_result = SimpleNamespace(
        review_id="r1", decision="APPROVED",
        findings=[], blocking_findings=0,
    )
    assert GovernanceReportService().register_review_artifact(
        review_result=review_result, stage_id="s1", artifact_manager=None,
    ) is None




# ── 6. OrchestrationEngine integration ────────────────────────────────────

def test_orchestrator_emits_governance_report_via_artifact_manager(tmp_path):
    from autoforge_orchestration.orchestrator import OrchestrationEngine, OrchestrationConfig

    config = OrchestrationConfig(
        workspace_root=str(tmp_path),
        state_dir=str(tmp_path / "state"),
    )
    am = MagicMock()
    engine = OrchestrationEngine(config, artifact_manager=am)
    assert hasattr(engine, "_emit_governance_report")
    state = _make_state()
    state.metrics = SimpleNamespace(
        started_at="t0", duration_seconds=1.0, finalize=lambda: None,
    )
    state.status = "COMPLETED"
    engine._emit_governance_report(state)
    assert am.create_artifact.called
    call_kwargs = am.create_artifact.call_args.kwargs
    assert call_kwargs["artifact_type"].name == "GOVERNANCE_REPORT"


def test_orchestrator_emit_handles_audit_records(tmp_path):
    from autoforge_orchestration.orchestrator import OrchestrationEngine, OrchestrationConfig

    config = OrchestrationConfig(
        workspace_root=str(tmp_path),
        state_dir=str(tmp_path / "state"),
    )

    class FakeAuditRecord:
        record_id = "rec-1"
        action = "authorize"
        decision = SimpleNamespace(value="allow")
        reason = "actor ok"
        outcome = "ok"
        actor_id = "alice"
        actor_type = "human"
        project_id = "proj-1"
        workflow_id = "wf-1"
        task_id = None
        recorded_at = SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00Z")

    class FakeAuditEngine:
        def __init__(self):
            self.records = [FakeAuditRecord()]

    am = MagicMock()
    engine = OrchestrationEngine(
        config, artifact_manager=am, audit_engine=FakeAuditEngine(),
    )
    state = _make_state()
    state.metrics = SimpleNamespace(
        started_at="t0", duration_seconds=1.0, finalize=lambda: None,
    )
    state.status = "COMPLETED"
    engine._emit_governance_report(state)
    assert am.create_artifact.called
    # Real ArtifactManager API: report body is stored via create_version
    assert am.create_version.called
    version_call = am.create_version.call_args
    content = json.loads(version_call.args[1])
    assert content["evidence"]["audit_evidence"][0]["record_id"] == "rec-1"


def test_orchestrator_emit_handles_hitl_gates(tmp_path):
    from autoforge_orchestration.orchestrator import OrchestrationEngine, OrchestrationConfig

    config = OrchestrationConfig(
        workspace_root=str(tmp_path),
        state_dir=str(tmp_path / "state"),
    )
    am = MagicMock()
    engine = OrchestrationEngine(config, artifact_manager=am)
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
            hitl_gate=SimpleNamespace(
                gate_id="g1", stage_id="s1",
                status=SimpleNamespace(value="APPROVED"),
                risk_level="low", requested_at="t0", decided_at="t1",
                actor="alice", decision="approve", reason_text="ok",
            ),
        ),
    ])
    state.metrics = SimpleNamespace(
        started_at="t0", duration_seconds=1.0, finalize=lambda: None,
    )
    state.status = "COMPLETED"
    engine._emit_governance_report(state)
    assert am.create_artifact.called
    # Real ArtifactManager API: report body is stored via create_version
    assert am.create_version.called
    version_call = am.create_version.call_args
    content = json.loads(version_call.args[1])
    assert len(content["evidence"]["hitl_evidence"]) == 1
    assert content["evidence"]["hitl_evidence"][0]["gate_id"] == "g1"


def test_orchestrator_emit_no_artifact_manager_is_noop(tmp_path):
    from autoforge_orchestration.orchestrator import OrchestrationEngine, OrchestrationConfig
    config = OrchestrationConfig(
        workspace_root=str(tmp_path),
        state_dir=str(tmp_path / "state"),
    )
    engine = OrchestrationEngine(config, artifact_manager=None)
    state = _make_state()
    state.metrics = SimpleNamespace(
        started_at="t0", duration_seconds=1.0, finalize=lambda: None,
    )
    state.status = "COMPLETED"
    engine._emit_governance_report(state)  # must not raise


# ── 7. assemble_governance_evidence with audit & review ────────────────────

def test_assemble_governance_evidence_with_audit_records():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    svc = GovernanceReportService()
    ev = svc.assemble_execution_chain(state, [])
    rec = SimpleNamespace(
        record_id="rec-1", action="approve",
        decision=SimpleNamespace(value="allow"),
        reason="ok", outcome="success",
        actor_id="bob", actor_type="human",
        project_id="proj-1", workflow_id="wf-1", task_id="t1",
        recorded_at=SimpleNamespace(isoformat=lambda: "2026-01-01T00:00:00Z"),
    )
    ev2 = svc.assemble_governance_evidence(ev, audit_records=[rec])
    assert len(ev2.audit_evidence) == 1
    assert ev2.audit_evidence[0].record_id == "rec-1"


def test_assemble_governance_evidence_with_review_results():
    state = _make_state(stages=[
        SimpleNamespace(
            stage_id="s1", status="SUCCEEDED",
            started_at="t0", finished_at="t1", attempt_number=1,
            output={}, definition={"kind": "implement"}, worker_type="coder",
        ),
    ])
    svc = GovernanceReportService()
    ev = svc.assemble_execution_chain(state, [])
    review = SimpleNamespace(
        review_id="r1", task_id="s1",
        findings=[{"id": "f1"}, {"id": "f2"}],
        blocking_findings=0, deterministic_findings=2, ai_findings=0,
        categories_run=["security", "quality"],
        gate=SimpleNamespace(status="PASS"),
    )
    ev2 = svc.assemble_governance_evidence(ev, review_results=[review])
    assert len(ev2.review_evidence) == 1
    assert ev2.review_evidence[0].findings_count == 2
    assert ev2.review_evidence[0].gate_status == "PASS"

