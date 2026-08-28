"""
Integration tests for SecurityPlatform and AutoForge AI OS composition root.
"""

from __future__ import annotations

import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_security.models import (
    ApprovalGateStatus,
    ConsequentialAction,
    CredentialType,
    DecisionType,
    SecretScope,
    Subject,
    SubjectType,
)
from autoforge_security.permissions import Permissions
from autoforge_security.roles import Roles


def test_composition_root_security_wiring() -> None:
    system = build_autoforge_system()
    assert system.security_platform is not None
    assert system.security_platform.authentication is not None
    assert system.security_platform.authorization is not None
    assert system.security_platform.governance is not None
    assert system.security_platform.hitl is not None
    assert system.security_platform.secrets is not None
    assert system.security_platform.credentials is not None
    assert system.security_platform.sandbox is not None
    assert system.security_platform.audit is not None


def test_end_to_end_security_pipeline(tmp_path) -> None:
    system = build_autoforge_system(workspace_root=str(tmp_path))
    sec = system.security_platform

    # 1. Register operator (alice)
    alice = sec.authentication.identity_provider.create_human_user(
        username="alice_dev",
        display_name="Alice Developer",
        roles={Roles.OPERATOR},
        password="MySecretPassword123!",
    )
    # Register reviewer
    reviewer = sec.authentication.identity_provider.create_human_user(
        username="carol_rev",
        display_name="Carol Reviewer",
        roles={Roles.REVIEWER},
        password="ReviewerSecret123!",
    )

    # 2. Login
    login_res = sec.login_password("user_alice_dev", "MySecretPassword123!")
    assert login_res.authenticated is True

    # 3. Authorize safe action (workspace.write)
    safe_dec = sec.authorize(
        action=Permissions.WORKSPACE_WRITE,
        resource="src/main.py",
        subject=alice,
    )
    assert safe_dec.is_allowed is True
    assert safe_dec.decision == DecisionType.ALLOW

    # 4. Attempt consequential action without gate (DEPLOYMENT)
    gated_dec = sec.authorize(
        action=ConsequentialAction.DEPLOYMENT.value,
        resource="prod_cluster",
        subject=alice,
    )
    assert gated_dec.is_allowed is False
    assert gated_dec.decision == DecisionType.REQUIRE_HITL

    # 5. Request HITL gate
    gate = sec.request_approval(
        action=ConsequentialAction.DEPLOYMENT,
        description="Deploying service v1.0",
        requested_by=alice,
        project_id="proj_001",
    )
    assert gate.status == ApprovalGateStatus.PENDING

    # 6. Reviewer decides approval
    approved_gate = sec.submit_approval_decision(
        gate_id=gate.gate_id,
        approver=reviewer,
        status=ApprovalGateStatus.APPROVED,
        reason="Validated and passed staging checks.",
    )
    assert approved_gate.status == ApprovalGateStatus.APPROVED

    # 7. Execute consequential action with resume token
    final_dec = sec.authorize(
        action=ConsequentialAction.DEPLOYMENT.value,
        resource="prod_cluster",
        subject=alice,
        gate_id=gate.gate_id,
        resume_token=approved_gate.resume_token,
    )
    assert final_dec.is_allowed is True

    # 8. Check audit records and status read model for Phase 16
    status = sec.get_security_status()
    assert status["audit_records_count"] >= 3
    assert status["pending_approvals_count"] == 0
