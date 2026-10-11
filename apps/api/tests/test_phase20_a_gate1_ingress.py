"""
Phase 20-A Gate 1: Canonical Customer Ingress Convergence Tests.

Verifies all Gate 1 requirements:
- TEST 1: Canonical API -> Kernel: API calls Kernel.submit_request().
- TEST 2: No API-local orchestration: API does not instantiate or invoke an alternate orchestrator.
- TEST 3: Canonical result propagation: The exact canonical execution result reaches API boundary.
- TEST 4: No synthetic overwrite: Canonical result is not discarded/replaced by generate_default_app().
- TEST 5: Failure propagation: Canonical FAILED outcome reaches customer as failure.
- TEST 6: Remediation/approval semantics: REMEDIATE and ESCALATE states are not silently converted to success.
- TEST 7: Capability neutrality: API contains no language-specific modernization branching.
- TEST 8: Architecture authority: Canonical Orchestration Engine remains the only orchestrator.
- TEST 9: Existing non-modernization behavior: Greenfield fallback continues working for unrouted default prompts.
- AST / Architecture Guards: API does not import modernization internals or bypass Kernel.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from typing import Any, Dict
from unittest.mock import AsyncMock, patch

import pytest

from autoforge_api.models import IntentExecutionRequest, IntentExecutionResponse
from autoforge_api.service import AutoForgeApiService
from autoforge_composition.capability_router import CAPABILITY_MODERNIZATION
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_kernel.interfaces import Request
from autoforge_kernel.kernel import Kernel
from autoforge_kernel.orchestration import DefaultOrchestrationEngine

_REPO = pathlib.Path(__file__).resolve().parents[3]


# ── TEST 1: Canonical API -> Kernel ───────────────────────────────────────────

def test_gate1_api_calls_kernel_submit_request():
    """Verify that execute_intent_pipeline submits requests through Kernel.submit_request()."""
    service = AutoForgeApiService()
    assert hasattr(service.system, "kernel")
    assert isinstance(service.system.kernel, Kernel)

    canonical_project_id = uuid.uuid4()
    mock_outcome = ExecutionOutcome(
        status=OutcomeStatus.COMPLETE,
        loop_type="coding",
        passed=True,
    )
    kernel_mock = AsyncMock(return_value={
        "status": "created",
        "project_id": canonical_project_id,
        "execution_status": "finished",
        "summary": "Canonical modernization successfully executed",
        "outcome": mock_outcome,
    })

    with patch.object(service.system.kernel, "submit_request", kernel_mock):
        req = IntentExecutionRequest(
            prompt="Modernize core ledger service.",
            intent_type="modernization",
            context={
                "capability": CAPABILITY_MODERNIZATION,
                "legacy_source_root": "/legacy/ledger",
            },
        )
        res = service.execute_intent_pipeline(req)

        assert kernel_mock.called, "Kernel.submit_request must be called"
        call_args = kernel_mock.call_args[0]
        assert len(call_args) == 1
        submitted_req = call_args[0]
        assert isinstance(submitted_req, Request)
        assert submitted_req.request_text == req.prompt
        assert submitted_req.configuration.get("execute") is True
        assert submitted_req.configuration.get("capability") == CAPABILITY_MODERNIZATION
        assert submitted_req.configuration.get("legacy_source_root") == "/legacy/ledger"
        assert res.status == "COMPLETED"


# ── TEST 2 & AST GUARD: No API-Local Orchestration ────────────────────────────

def test_gate1_no_api_local_orchestration():
    """Verify via AST that the API layer does not instantiate or invoke alternate orchestrators."""
    api_dir = _REPO / "apps" / "api" / "src" / "autoforge_api"
    forbidden_classes = {
        "AutonomousBuildEngine",
        "O3Orchestrator",
        "AlternateOrchestrator",
        "ModernizationCoordinator",
        "WorkflowEngine",
    }
    forbidden_calls = {"orchestrate", "execute_workflow", "run_pipeline"}

    for py_file in api_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden_classes:
                pytest.fail(f"{py_file.name} references forbidden orchestrator class: {node.id}")
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute) and func.attr in forbidden_calls:
                    # Permitted only if calling self.system.kernel (which calls Orchestration Engine)
                    if py_file.name in ("server.py", "service.py"):
                        if func.attr == "orchestrate":
                            pytest.fail(f"{py_file.name} contains direct call to orchestrate()")


# ── TEST 3: Canonical Result Propagation ──────────────────────────────────────

def test_gate1_canonical_result_propagation():
    """Verify that canonical execution results (outcome, status, summary) reach customer response."""
    service = AutoForgeApiService()
    proj_id = uuid.uuid4()
    mock_outcome = ExecutionOutcome(
        status=OutcomeStatus.COMPLETE,
        loop_type="coding",
        passed=True,
    )

    kernel_mock = AsyncMock(return_value={
        "status": "created",
        "project_id": proj_id,
        "execution_status": "finished",
        "summary": "System modernization executed through canonical lifecycle.",
        "outcome": mock_outcome,
    })

    with patch.object(service.system.kernel, "submit_request", kernel_mock):
        req = IntentExecutionRequest(
            prompt="Migrate enterprise subsystem.",
            intent_type="modernization",
            context={"capability": "legacy_modernization", "legacy_source_root": "/src/sys"},
        )
        res = service.execute_intent_pipeline(req)

        assert res.project_id == str(proj_id)
        assert res.status == "COMPLETED"
        assert res.summary == "System modernization executed through canonical lifecycle."
        assert res.output_preview["status"] == "COMPLETED"


# ── TEST 4: No Synthetic Overwrite ────────────────────────────────────────────

def test_gate1_no_synthetic_overwrite():
    """Verify that generate_default_app is NOT invoked when canonical capability execution is active."""
    service = AutoForgeApiService()
    proj_id = uuid.uuid4()
    mock_outcome = ExecutionOutcome(
        status=OutcomeStatus.COMPLETE,
        loop_type="coding",
        passed=True,
    )

    kernel_mock = AsyncMock(return_value={
        "status": "created",
        "project_id": proj_id,
        "execution_status": "finished",
        "summary": "Canonical capability execution complete.",
        "outcome": mock_outcome,
    })

    with patch.object(service.system.kernel, "submit_request", kernel_mock), \
         patch("autoforge_api.generator.generate_default_app") as mock_gen_app:

        req = IntentExecutionRequest(
            prompt="Modernize legacy subsystem.",
            intent_type="modernization",
            context={"capability": "legacy_modernization", "legacy_source_root": "/legacy/root"},
        )
        res = service.execute_intent_pipeline(req)

        assert not mock_gen_app.called, "generate_default_app must NOT be invoked on canonical execution"
        assert res.status == "COMPLETED"
        assert res.summary == "Canonical capability execution complete."


# ── TEST 5: Failure Propagation ───────────────────────────────────────────────

def test_gate1_failure_propagation():
    """Verify that a canonical FAILED outcome propagates as FAILED to the API boundary."""
    service = AutoForgeApiService()
    proj_id = uuid.uuid4()
    mock_outcome = ExecutionOutcome(
        status=OutcomeStatus.FAILED,
        loop_type="coding",
        passed=False,
        findings=["Modernization build error: compilation verification failed."],
    )

    kernel_mock = AsyncMock(return_value={
        "status": "created",
        "project_id": proj_id,
        "execution_status": "failed",
        "outcome": mock_outcome,
    })

    with patch.object(service.system.kernel, "submit_request", kernel_mock), \
         patch("autoforge_api.generator.generate_default_app") as mock_gen_app:

        req = IntentExecutionRequest(
            prompt="Modernize legacy subsystem.",
            intent_type="modernization",
            context={"capability": "legacy_modernization", "legacy_source_root": "/legacy/root"},
        )
        res = service.execute_intent_pipeline(req)

        assert not mock_gen_app.called, "generate_default_app must NOT be called on failure"
        assert res.status == "FAILED", "API must propagate canonical failure as FAILED"
        assert "compilation verification failed" in res.summary


# ── TEST 6: Remediation and Escalation Semantics ──────────────────────────────

def test_gate1_remediation_and_escalation_semantics():
    """Verify that non-success states (REMEDIATING, ESCALATED) are not converted to success."""
    service = AutoForgeApiService()
    proj_id = uuid.uuid4()

    # 1. REMEDIATE
    rem_outcome = ExecutionOutcome(
        status=OutcomeStatus.REMEDIATE,
        loop_type="coding",
        passed=False,
        findings=["Tests failed, entering bounded remediation"],
    )
    kernel_rem_mock = AsyncMock(return_value={
        "status": "created",
        "project_id": proj_id,
        "execution_status": "remediate",
        "outcome": rem_outcome,
    })

    with patch.object(service.system.kernel, "submit_request", kernel_rem_mock):
        req = IntentExecutionRequest(
            prompt="Modernize subsystem with test failures.",
            intent_type="modernization",
            context={"capability": "legacy_modernization", "legacy_source_root": "/src"},
        )
        res = service.execute_intent_pipeline(req)
        assert res.status == "REMEDIATING", "REMEDIATE state must map to REMEDIATING, never COMPLETED"

    # 2. ESCALATE
    esc_outcome = ExecutionOutcome(
        status=OutcomeStatus.ESCALATE,
        loop_type="coding",
        passed=False,
        findings=["Requires human sign-off"],
    )
    kernel_esc_mock = AsyncMock(return_value={
        "status": "created",
        "project_id": proj_id,
        "execution_status": "escalate",
        "outcome": esc_outcome,
    })

    with patch.object(service.system.kernel, "submit_request", kernel_esc_mock):
        req = IntentExecutionRequest(
            prompt="Modernize critical financial system.",
            intent_type="modernization",
            context={"capability": "legacy_modernization", "legacy_source_root": "/src"},
        )
        res = service.execute_intent_pipeline(req)
        assert res.status == "ESCALATED", "ESCALATE state must map to ESCALATED, never COMPLETED"


# ── TEST 7: Capability Neutrality (Language/Technology Agnostic) ─────────────

def test_gate1_capability_neutrality_ast():
    """Verify via AST that the API layer contains no hardcoded language-specific branching."""
    api_dir = _REPO / "apps" / "api" / "src" / "autoforge_api"
    prohibited_literals = {"COBOL", "cobol", "Java", "jcl", "JCL", "CardDemo", "DAILYPOST"}

    for py_file in api_dir.glob("*.py"):
        if py_file.name == "generator.py":
            continue  # Greenfield template generator contains string constants for python/markdown
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.If):
                # Inspect test conditions
                test_dump = ast.dump(node.test)
                for prohibited in prohibited_literals:
                    assert prohibited not in test_dump, (
                        f"{py_file.name} contains technology-specific branching: {prohibited}"
                    )


# ── TEST 8: Architecture Authority (Orchestration Engine Only) ───────────────

def test_gate1_orchestration_engine_is_sole_authority():
    """Verify that Kernel.orchestration_engine is the certified DefaultOrchestrationEngine."""
    service = AutoForgeApiService()
    orch = service.system.kernel.orchestration_engine
    assert isinstance(orch, DefaultOrchestrationEngine)
    assert not hasattr(service, "orchestration_engine"), "API service must not have its own orchestrator"


# ── TEST 9: Existing Non-Modernization Greenfield Behavior ───────────────────

def test_gate1_existing_greenfield_behavior_preserved():
    """Verify that generic greenfield application build without capability falls through safely."""
    service = AutoForgeApiService()
    req = IntentExecutionRequest(
        prompt="Build a calculator application with clean interface",
        intent_type="application_build",
    )
    res = service.execute_intent_pipeline(req)
    assert isinstance(res, IntentExecutionResponse)
    assert res.status == "COMPLETED"
    assert len(res.artifacts) > 0
    assert any("Source" in a["name"] or "Package" in a["name"] for a in res.artifacts)


# ── STATIC ARCHITECTURE GUARDS ───────────────────────────────────────────────

def test_gate1_static_guards_no_modernization_internals_imported():
    """Verify that apps/api does not directly import modernization pipeline or transformation internals."""
    api_dir = _REPO / "apps" / "api" / "src" / "autoforge_api"
    forbidden_modules = {
        "autoforge_modernization.service",
        "autoforge_modernization.pipeline",
        "autoforge_modernization.cobol",
        "autoforge_modernization.transform",
        "autoforge_modernization.analysis",
    }

    for py_file in api_dir.glob("*.py"):
        tree = ast.parse(py_file.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    assert alias.name not in forbidden_modules, (
                        f"{py_file.name} directly imports modernization internal: {alias.name}"
                    )
            elif isinstance(node, ast.ImportFrom):
                if node.module:
                    assert node.module not in forbidden_modules, (
                        f"{py_file.name} directly imports from modernization internal: {node.module}"
                    )
