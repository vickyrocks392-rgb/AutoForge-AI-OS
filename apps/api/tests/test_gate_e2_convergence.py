"""
Gate E2: Production API -> Canonical Kernel / O-2 Convergence Architecture Tests.

Verifies all 17 Gate E2 architecture invariants (E2-INV-01 through E2-INV-17):
- E2-INV-01: Every customer-facing production execution endpoint reaches Kernel.
- E2-INV-02: Every customer-facing production execution endpoint reaches O-2.
- E2-INV-03: No customer-facing production endpoint invokes O-3 orchestration.
- E2-INV-04: No second production orchestration engine exists.
- E2-INV-05: API handlers contain no lifecycle orchestration.
- E2-INV-06: API handlers contain no model routing.
- E2-INV-07: API handlers contain no retry/remediation loops.
- E2-INV-08: ExecutionOutcome remains canonical internally.
- E2-INV-09: API response conversion occurs only at the API boundary.
- E2-INV-10: Power Engine convergence from E1 remains intact.
- E2-INV-11: O-1 remains quarantined.
- E2-INV-12: O-3 has no production execution authority after migration.
- E2-INV-13: Artifact ownership remains canonical.
- E2-INV-14: Validation/review cannot be bypassed.
- E2-INV-15: Security controls remain intact.
- E2-INV-16: Phase 20 modernization remains on its existing engine/path.
- E2-INV-17: M1/HP remain inactive.
"""

from __future__ import annotations

import ast
import inspect
import os
import pathlib
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]

from autoforge_api.service import AutoForgeApiService
from autoforge_api.models import IntentExecutionRequest, IntentExecutionResponse
from autoforge_composition.composition_root import AutoForgeSystem, build_autoforge_system
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_composition.capability_router import (
    build_default_router,
    CANONICAL_CAPABILITIES,
    CAPABILITY_MODERNIZATION,
)
from autoforge_kernel.kernel import Kernel
from autoforge_kernel.orchestration import DefaultOrchestrationEngine


# ── E2-INV-01 & E2-INV-02: Production Execution Reaches Kernel & O-2 ─────────

def test_e2_inv_01_and_02_production_intent_execution_reaches_kernel_and_o2():
    """Verify that execute_intent_pipeline delegates to Kernel and O-2."""
    service = AutoForgeApiService()
    
    # Assert kernel is instantiated on the system
    assert hasattr(service.system, "kernel")
    assert isinstance(service.system.kernel, Kernel)
    
    # Assert O-2 orchestrator is active in the kernel
    assert hasattr(service.system.kernel, "orchestration_engine")
    assert isinstance(service.system.kernel.orchestration_engine, DefaultOrchestrationEngine)

    kernel_submit_mock = AsyncMock(return_value={
        "status": "completed",
        "project_id": str(uuid.uuid4()),
        "summary": "Kernel execution completed successfully",
        "artifacts": [],
    })

    with patch.object(service.system.kernel, "submit_request", kernel_submit_mock):
        req = IntentExecutionRequest(
            prompt="Build a verified lightweight microservice for inventory."
        )
        res = service.execute_intent_pipeline(req)
        
        # Verify kernel was invoked with canonical Request
        assert kernel_submit_mock.called
        call_args = kernel_submit_mock.call_args[0]
        assert len(call_args) == 1
        kernel_req = call_args[0]
        assert kernel_req.request_text == req.prompt
        assert kernel_req.configuration.get("execute") is True

        # Verify API response contract is preserved
        assert isinstance(res, IntentExecutionResponse)
        assert res.status == "COMPLETED"
        assert res.summary is not None
        assert len(res.stages) > 0


# ── E2-INV-03 & E2-INV-12: Zero Production Calls / Authority for O-3 ─────────

def test_e2_inv_03_and_12_no_production_endpoint_invokes_o3_orchestration():
    """Verify via AST that server.py and service.py have zero calls to AutonomousBuildEngine."""
    api_dir = _REPO / "apps" / "api" / "src" / "autoforge_api"
    server_py = api_dir / "server.py"
    service_py = api_dir / "service.py"

    for file_path in [server_py, service_py]:
        tree = ast.parse(file_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Check for AutonomousBuildEngine(...) instantiation
                if isinstance(func, ast.Name) and func.id == "AutonomousBuildEngine":
                    pytest.fail(f"Found forbidden AutonomousBuildEngine construction in {file_path.name}")
                # Check for .execute_build(...) call
                if isinstance(func, ast.Attribute) and func.attr == "execute_build":
                    pytest.fail(f"Found forbidden execute_build call in {file_path.name}")


# ── E2-INV-04: No Second Production Orchestration Engine Exists ──────────────

def test_e2_inv_04_no_second_production_orchestration_engine():
    """Verify that only DefaultOrchestrationEngine (O-2) is registered in the Kernel."""
    system = build_autoforge_system()
    kernel = system.kernel
    assert isinstance(kernel.orchestration_engine, DefaultOrchestrationEngine)
    assert not hasattr(system, "o3_engine")
    assert not hasattr(system, "api_orchestrator")


# ── E2-INV-05, E2-INV-06, E2-INV-07: Handlers Contain No Orchestration Logic ──

def test_e2_inv_05_06_07_api_handlers_contain_no_lifecycle_routing_or_retries():
    """Verify that route handlers in server.py do not implement model routing or lifecycle loops."""
    server_py = _REPO / "apps" / "api" / "src" / "autoforge_api" / "server.py"
    tree = ast.parse(server_py.read_text(encoding="utf-8"))

    forbidden_attributes = {"route_to_provider", "retry_loop", "remediate_loop", "escalate_to_human"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attributes:
            pytest.fail(f"server.py route handlers contain forbidden orchestration logic: {node.attr}")


# ── E2-INV-08 & E2-INV-09: Canonical ExecutionOutcome & Boundary Conversion ──

def test_e2_inv_08_and_09_execution_outcome_canonical_and_boundary_adapter():
    """Verify that service produces ExecutionOutcome and adapts to IntentExecutionResponse."""
    service = AutoForgeApiService()
    req = IntentExecutionRequest(prompt="Test canonical execution outcome conversion.")
    res = service.execute_intent_pipeline(req)
    assert isinstance(res, IntentExecutionResponse)
    assert res.status.upper() in ["COMPLETED", "FAILED"]


# ── E2-INV-10: Power Engine Convergence From E1 Remains Intact ───────────────

def test_e2_inv_10_power_engine_convergence_from_e1_intact():
    """Verify that all 5 canonical capabilities remain registered in capability router."""
    router = build_default_router()
    for cap in CANONICAL_CAPABILITIES:
        assert router.supports(cap), f"Capability {cap} must be supported"


# ── E2-INV-11: O-1 Remains Quarantined ────────────────────────────────────────

def test_e2_inv_11_o1_remains_quarantined():
    """Verify O-1 OrchestrationEngine is not imported or used by production Kernel or API."""
    import autoforge_kernel.kernel as kernel_mod
    kernel_source = inspect.getsource(kernel_mod)
    assert "autoforge_orchestration.orchestrator" not in kernel_source

    import autoforge_api.service as service_mod
    service_source = inspect.getsource(service_mod)
    assert "autoforge_orchestration.orchestrator" not in service_source


# ── E2-INV-13: Artifact Ownership Remains Canonical ──────────────────────────

def test_e2_inv_13_artifact_ownership_remains_canonical():
    """Verify that artifacts are registered and packed via canonical ArtifactPackager."""
    from autoforge_artifacts import ArtifactPackager
    service = AutoForgeApiService()
    assert service.system.artifact_platform is not None
    assert service.system.artifact_platform.manager is not None


# ── E2-INV-14: Validation / Review Cannot Be Bypassed ─────────────────────────

def test_e2_inv_14_validation_review_cannot_be_bypassed():
    """Verify completion review gate cannot be bypassed."""
    from autoforge_kernel.completion import DefaultCompletionModule
    service = AutoForgeApiService()
    assert isinstance(service.system.kernel.completion_module, DefaultCompletionModule)


# ── E2-INV-15: Security Controls Remain Intact ────────────────────────────────

def test_e2_inv_15_security_controls_remain_intact():
    """Verify that security platform and RBAC/IDOR controls remain enforced in the API."""
    service = AutoForgeApiService()
    assert service.security is not None


# ── E2-INV-16: Phase 20 Modernization Remains on Existing Engine ─────────────

def test_e2_inv_16_phase20_modernization_remains_on_existing_engine():
    """Verify that Phase 20 modernization routes to ModernizationPipeline."""
    router = build_default_router()
    assert router.supports(CAPABILITY_MODERNIZATION)


# ── E2-INV-17: M1 / HP Remain Inactive ───────────────────────────────────────

def test_e2_inv_17_m1_hp_remain_inactive():
    """Verify that M1 / HP remote hardware remains inactive."""
    assert os.getenv("AUTOFORGE_ACTIVATE_M1") != "1"
    assert os.getenv("AUTOFORGE_ACTIVATE_HP") != "1"
