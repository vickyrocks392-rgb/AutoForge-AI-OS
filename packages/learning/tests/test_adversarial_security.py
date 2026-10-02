"""Adversarial matrix F — security and authority (Gate 14 F, Gates 10 & 12).

Two properties are under test:

* **F:** the learning system cannot reach any security/authority capability,
  and attempting to is a hard DENY (a disqualifier, not a negative signal).
* **Gate 12:** Level 5 remains unreachable and the model may only propose.
"""

from __future__ import annotations

import pytest

from autoforge_learning.invariants import PROTECTED_INVARIANTS
from autoforge_learning.models import (
    LearningAuthority,
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
)
from autoforge_security.ai_guardrails import (
    LEARNABLE_PROPOSAL_KINDS,
    LEARNING_FORBIDDEN_CAPABILITIES,
    AIGuardrailsEngine,
    Capability,
)

#: Every capability named in the anti-self-elevation contract. Each one must
#: be denied when a learning candidate requests it.
FORBIDDEN_CAPABILITY_NAMES = sorted(c.value for c in LEARNING_FORBIDDEN_CAPABILITIES)


def _candidate(project_id, capabilities=(), kind="pattern_template", authority=None):
    kwargs = {}
    if authority is not None:
        kwargs["authority"] = authority
    return LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=kind,
        summary="a candidate",
        requested_capabilities=tuple(capabilities),
        **kwargs,
    )


# ── F.1 FORBIDDEN CAPABILITY PROPOSALS ───────────────────────────────────────


@pytest.mark.parametrize("capability", FORBIDDEN_CAPABILITY_NAMES)
def test_every_forbidden_capability_is_denied(service, project_id, capability):
    """F.1 — each escalation path is refused at proposal time."""
    with pytest.raises(PermissionError):
        service.create_candidate(_candidate(project_id, capabilities=[capability]))


def test_an_unknown_capability_is_treated_as_an_escalation_attempt(service, project_id):
    """F.1 — an unrecognised capability is never silently dropped."""
    with pytest.raises(PermissionError):
        service.create_candidate(
            _candidate(project_id, capabilities=["totally_invented_capability"])
        )


# ── F.2 LEVEL 5 ───────────────────────────────────────────────────────────────


def test_level_5_cannot_be_represented_on_a_candidate(project_id):
    """F.2 — L5 is unrepresentable, not merely discouraged."""
    with pytest.raises(Exception):
        _candidate(project_id, authority=LearningAuthority.L5_SECURITY_POLICY)


def test_the_learning_package_contains_no_level_5_assignment():
    """F.2 — static proof: no module *assigns* L5 authority.

    Naming the level in order to refuse it is required (that is what
    ``gateway.py`` does); what must not exist is an assignment.
    """
    import ast
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "autoforge_learning"
    for path in src.glob("*.py"):
        text = path.read_text()
        assert "authority=LearningAuthority.L5" not in text, path.name
        tree = ast.parse(text)
        for node in ast.walk(tree):
            if not isinstance(node, ast.keyword):
                continue
            if node.arg == "authority":
                assert "L5" not in ast.unparse(node.value), (
                    f"{path.name} assigns L5 authority: {ast.unparse(node.value)}"
                )


def test_only_the_five_certified_proposal_kinds_exist():
    """F.7 — the allow-list is used as-is, never widened by learning."""
    assert LEARNABLE_PROPOSAL_KINDS == frozenset(
        {
            "workflow_definition",
            "routing_rule",
            "optimization_hint",
            "pattern_template",
            "documentation_pattern",
        }
    )


@pytest.mark.parametrize(
    "kind",
    ["guardrail_policy", "hitl_bypass", "credential_scope", "role_definition"],
)
def test_unknown_proposal_kinds_are_denied(service, project_id, kind):
    """F.7 — a sixth kind cannot be invented."""
    with pytest.raises(PermissionError):
        service.create_candidate(_candidate(project_id, kind=kind))


# ── F.3/F.4/F.5/F.6 GUARDRAIL, AUTHORIZATION, CREDENTIAL, HITL ───────────────


@pytest.mark.parametrize(
    "capability",
    [
        Capability.SECURITY_MODIFY,
        Capability.CREDENTIAL_USE,
        Capability.CREDENTIAL_ADMINISTER,
        Capability.CREDENTIAL_REQUEST,
    ],
)
def test_security_authorization_and_credential_mutation_are_unreachable(
    service, project_id, capability
):
    """F.3/F.4/F.5 — the boundary is the single authority and it denies."""
    with pytest.raises(PermissionError) as exc:
        service.create_candidate(_candidate(project_id, capabilities=[capability.value]))
    assert "denied" in str(exc.value)


def test_the_guardrail_engine_exposes_no_policy_mutation_surface():
    """F.3 — learning adds no mutation API and the engine has none either."""
    engine = AIGuardrailsEngine()
    for method in ("set_policy", "mutate", "reload", "update_policy"):
        assert not hasattr(engine, method)


def test_the_learning_package_never_writes_guardrails_policy():
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "src" / "autoforge_learning"
    for path in src.glob("*.py"):
        text = path.read_text()
        for forbidden in ("set_policy(", ".mutate(", "_allowed_proposal_kinds ="):
            assert forbidden not in text, f"{path.name} contains {forbidden}"


@pytest.mark.parametrize(
    "capability", ["hitl_bypass", "validation_bypass", "audit_bypass"]
)
def test_hitl_validation_and_audit_bypass_are_unreachable(service, project_id, capability):
    """F.6 — a HITL/validation/audit bypass is not a learnable capability."""
    with pytest.raises(PermissionError):
        service.create_candidate(_candidate(project_id, capabilities=[capability]))


def test_the_nine_invariants_cannot_be_reduced():
    """F.8 — the invariant set is fixed; learning cannot shrink the gate."""
    assert len(PROTECTED_INVARIANTS) == 9
    assert [i.value for i in PROTECTED_INVARIANTS] == [f"PI-{n}" for n in range(1, 10)]


# ── GATE 12: MODEL AUTHORITY ─────────────────────────────────────────────────


def test_the_model_may_only_propose_never_promote():
    """Gate 12 — nothing model-facing can auto-promote, approve or roll back."""
    from autoforge_learning.lifecycle import LearningLifecycleService

    for forbidden in ("auto_promote", "auto_approve", "auto_rollback"):
        assert not hasattr(LearningLifecycleService, forbidden)


def test_promotion_records_a_human_approver_not_the_requester(
    service, stored_candidate, passing_report, service_requester, human_approver
):
    """Gate 12 — the approver on the record is human, and that is enforced."""
    approval = service.approvals.record_decision(
        approval=service.request_approval(
            record=stored_candidate,
            evaluation=passing_report,
            kind="pattern_template",
            key="template-alpha",
            proposed_effect="effect",
            requested_by=service_requester,
        ),
        approver=human_approver,
        approve=True,
        reason="ok",
    )
    assert approval.approver_subject_type == "human"
    assert approval.approver_id == human_approver.subject_id
    assert approval.approver_id != service_requester.subject_id