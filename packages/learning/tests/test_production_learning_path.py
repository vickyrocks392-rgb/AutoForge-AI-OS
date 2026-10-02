"""Production-path integration tests — Gate 10.

Proves the REAL production path invokes the security boundary:

    experience -> learning candidate -> ProposalGateway
               -> evaluate_learning_proposal() -> decision

These are not unit tests of the gateway in isolation. They build the actual
canonical AutoForge system from the composition root.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_kernel.learning_engine import (
    EngineeringLearningEngine,
    _confidence_from_review_findings,
)
from autoforge_learning.evidence import EvidenceCollector
from autoforge_learning.gateway import ProposalGateway
from autoforge_security.ai_guardrails import (
    AIGuardrailsEngine,
    GuardrailDecisionType,
    LearningProposal,
    LearningProposalDecision,
)

APPROVED_KINDS = (
    "workflow_definition",
    "routing_rule",
    "optimization_hint",
    "pattern_template",
    "documentation_pattern",
)


@pytest.fixture()
async def system(tmp_path):
    sys_ = build_autoforge_system(workspace_root=str(tmp_path))
    await sys_.initialize()
    try:
        yield sys_
    finally:
        await sys_.shutdown()


class _DenyAll:
    def evaluate_learning_proposal(self, proposal):
        return LearningProposalDecision(
            is_permitted=False,
            decision=GuardrailDecisionType.DENY,
            reason="denied by test",
        )


class _KnowledgeSpy:
    def __init__(self):
        self.promoted: list = []

    async def promote(self, learning):
        self.promoted.append(learning)


FAILING_EVIDENCE = [
    {
        "kind": "deterministic_validation",
        "required": True,
        "passed": False,
        "reason": "tests failed",
    }
]


# ── WIRING ───────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_production_system_wires_a_real_proposal_gateway(system):
    engine = system.learning_engine
    assert isinstance(engine, EngineeringLearningEngine)
    assert engine.proposal_gateway is not None
    assert isinstance(engine.evidence_collector, EvidenceCollector)
    # The gateway is bound to the REAL certified engine, not a stub.
    assert isinstance(engine.proposal_gateway._boundary, AIGuardrailsEngine)


@pytest.mark.asyncio
async def test_gateway_is_shared_with_the_kernel(system):
    """One gateway, one boundary -- no bypass path."""
    assert system.kernel.learning_engine is system.learning_engine
    assert system.kernel.learning_engine.proposal_gateway is not None


@pytest.mark.asyncio
async def test_denied_candidates_are_not_promoted(system):
    """A denial must stop the candidate from continuing."""
    engine = system.learning_engine
    engine.proposal_gateway = ProposalGateway(_DenyAll())
    knowledge = _KnowledgeSpy()
    engine.knowledge_engine = knowledge
    engine._promoted_candidate_ids.clear()

    await engine.reflect_and_learn(
        project_id=uuid.uuid4(),
        execution_summary={"success": True, "final_review": {"approved": True}},
        review_findings=FAILING_EVIDENCE,
    )

    assert knowledge.promoted == [], "a denied candidate must never be promoted"
    assert engine._promoted_candidate_ids == []


@pytest.mark.asyncio
async def test_absent_gateway_denies_everything(system):
    """No gateway configured => no candidate may be proposed (fail closed)."""
    engine = system.learning_engine
    engine.proposal_gateway = None
    knowledge = _KnowledgeSpy()
    engine.knowledge_engine = knowledge
    engine._promoted_candidate_ids.clear()

    await engine.reflect_and_learn(
        project_id=uuid.uuid4(),
        execution_summary={"success": True},
        review_findings=FAILING_EVIDENCE,
    )
    assert knowledge.promoted == []


@pytest.mark.asyncio
async def test_promoted_count_matches_boundary_permits(system):
    """Telemetry counts real boundary permits, nothing else."""
    engine = system.learning_engine
    engine._promoted_candidate_ids.clear()
    await engine.reflect_and_learn(
        project_id=uuid.uuid4(),
        execution_summary={"success": True, "final_review": {"approved": True}},
        review_findings=FAILING_EVIDENCE,
    )
    # Each extracted lesson is proposed; permitted ones are recorded.
    assert len(engine._promoted_candidate_ids) == 2


# ── GATE 4: THE DEAD EXTRACTION BRANCH IS REPAIRED ───────────────────────────


def test_kernel_extracts_real_review_evidence():
    """kernel.py no longer reads a "findings" key that never existed.

    The Kernel supplies the genuine final-review verdict and deterministic
    validation truth, so the defect-prevention branch receives real evidence.
    """
    from autoforge_kernel.kernel import _authoritative_review_findings

    findings = _authoritative_review_findings(
        {
            "success": True,
            "final_review": {
                "approved": False,
                "reason": "rejected",
                "evidence_files": 1,
                "validation": {"required": True, "passed": False, "reason": "boom"},
            },
        }
    )
    assert [f["kind"] for f in findings] == ["deterministic_validation", "final_review"]
    assert findings[0]["passed"] is False
    assert findings[1]["approved"] is False
    assert all(f["authoritative"] for f in findings)


def test_authoritative_findings_helper_handles_failure_shape():
    from autoforge_kernel.kernel import _authoritative_review_findings

    findings = _authoritative_review_findings(
        {
            "success": False,
            "validation": {"required": True, "passed": False, "reason": "bad"},
            "review_gate": {"approved": False, "reason": "nope", "evidence_files": 0},
        }
    )
    assert [f["kind"] for f in findings] == ["deterministic_validation", "final_review"]


def test_authoritative_findings_helper_handles_absent_data():
    from autoforge_kernel.kernel import _authoritative_review_findings

    assert _authoritative_review_findings(None) == []
    assert _authoritative_review_findings({}) == []
    assert _authoritative_review_findings({"final_review": {}}) == []


# ── CONFIDENCE IS DERIVED, NOT CONSTANT (Gate 19A GAP-06) ───────────────────


def test_confidence_is_zero_without_evidence():
    assert _confidence_from_review_findings([]) == 0.0


def test_confidence_differs_by_evidence_strength():
    deterministic = _confidence_from_review_findings(
        [
            {"kind": "deterministic_validation", "required": True, "passed": False},
            {"kind": "final_review", "approved": False},
        ]
    )
    review_only = _confidence_from_review_findings([{"kind": "final_review", "approved": False}])
    assert deterministic > review_only
    assert review_only > 0.0


def test_confidence_is_not_the_old_flat_constant():
    """The old code assigned exactly 0.90 to every finding."""
    values = {
        _confidence_from_review_findings([{"kind": "final_review", "approved": False}]),
        _confidence_from_review_findings(
            [{"kind": "deterministic_validation", "required": True, "passed": False},
             {"kind": "final_review", "approved": False}]
        ),
    }
    assert 0.90 not in values


# ── GATE 9: TELEMETRY REFLECTS REAL STATE ────────────────────────────────────


@pytest.fixture()
def api_service():
    """The Product Experience service, which owns the telemetry surface."""
    from autoforge_api.service import AutoForgeApiService

    svc = AutoForgeApiService.__new__(AutoForgeApiService)
    svc.kernel = None
    return svc


def test_telemetry_reports_zero_when_nothing_learned(api_service):
    center = api_service.get_self_improvement_center()
    assert center.learned_heuristics_count == 0
    assert center.candidate_improvements_count == 0
    assert center.last_regression_status == "UNAVAILABLE"
    assert center.learned_heuristics == []
    assert center.is_autonomous_active is False


def test_telemetry_never_reports_the_old_fabricated_values(api_service):
    """GAP-12: 14 heuristics / "ALL_PASSING (1119/1119)" must be gone."""
    center = api_service.get_self_improvement_center()
    assert center.learned_heuristics_count != 14
    assert "1119" not in center.last_regression_status
    assert "1135" not in center.last_regression_status
    assert center.regression_results == []
    assert "green" not in str(center.last_regression_status).lower()


@pytest.mark.asyncio
async def test_telemetry_counts_real_boundary_permits(api_service, system):
    """After a real, permitted proposal the count is real -- not fabricated."""
    engine = system.learning_engine
    engine._promoted_candidate_ids.clear()

    await engine.reflect_and_learn(
        project_id=uuid.uuid4(),
        execution_summary={"success": True, "final_review": {"approved": True}},
        review_findings=FAILING_EVIDENCE,
    )

    api_service.kernel = system.kernel
    center = api_service.get_self_improvement_center()
    assert center.learned_heuristics_count == len(engine._promoted_candidate_ids)
    assert center.candidate_improvements_count == len(engine._promoted_candidate_ids)
    assert center.learned_heuristics_count > 0


def test_telemetry_response_model_defaults_are_truthful():
    """Even an unset response must not carry fabricated defaults."""
    from autoforge_api.models import SelfImprovementResponse

    empty = SelfImprovementResponse()
    assert empty.learned_heuristics_count == 0
    assert empty.last_regression_status == "UNAVAILABLE"
    assert empty.data_available is False


# ── THE PRODUCTION PATH INVOKES THE BOUNDARY ─────────────────────────────────


@pytest.mark.asyncio
async def test_production_path_invokes_evaluate_learning_proposal(system):
    """The decisive proof: the certified boundary is actually reached."""
    engine = system.learning_engine
    boundary = engine.proposal_gateway._boundary
    seen: list[LearningProposal] = []
    original = boundary.evaluate_learning_proposal

    def spy(proposal):
        seen.append(proposal)
        return original(proposal)

    boundary.evaluate_learning_proposal = spy

    await engine.reflect_and_learn(
        project_id=uuid.uuid4(),
        execution_summary={"success": True, "final_review": {"approved": True}},
        review_findings=FAILING_EVIDENCE,
    )

    assert seen, "evaluate_learning_proposal must be called on the production path"
    assert all(isinstance(p, LearningProposal) for p in seen)
    assert all(p.proposal_kind in APPROVED_KINDS for p in seen)