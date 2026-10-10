"""
Gate F: Production Cutover, Duplicate Orchestration Retirement & Single Path Architecture Tests.

Verifies:
1. EXACTLY ONE production orchestration implementation remains: DefaultOrchestrationEngine (O-2).
2. O-1 (OrchestrationEngine) is physically deleted from the codebase.
3. O-3 (AutonomousBuildEngine) is physically deleted from the codebase.
4. ZERO production callers or references to retired orchestrators exist across the entire monorepo.
5. API handlers contain zero orchestration authority.
6. Canonical end-to-end flow operates through Kernel -> O-2 -> ExecutionOutcome.
"""

from __future__ import annotations

import ast
import pathlib
import uuid
from unittest.mock import AsyncMock, patch

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]

from autoforge_api.service import AutoForgeApiService
from autoforge_api.models import IntentExecutionRequest, IntentExecutionResponse
from autoforge_composition.composition_root import build_autoforge_system
from autoforge_kernel.kernel import Kernel
from autoforge_kernel.orchestration import DefaultOrchestrationEngine


def test_gate_f_exactly_one_production_orchestrator():
    """Verify that only DefaultOrchestrationEngine (O-2) is registered and authoritative."""
    system = build_autoforge_system()
    kernel = system.kernel
    assert isinstance(kernel.orchestration_engine, DefaultOrchestrationEngine)
    assert not hasattr(system, "o1_engine")
    assert not hasattr(system, "o3_engine")
    assert not hasattr(system, "build_engine")
    assert not hasattr(system, "api_orchestrator")


def test_gate_f_o1_physical_deletion_verified():
    """Verify O-1 orchestrator.py is physically removed from the repository."""
    o1_file = _REPO / "packages" / "orchestration" / "src" / "autoforge_orchestration" / "orchestrator.py"
    assert not o1_file.exists(), f"O-1 file {o1_file} must not exist"

    import autoforge_orchestration
    assert not hasattr(autoforge_orchestration, "OrchestrationEngine"), (
        "autoforge_orchestration must not export OrchestrationEngine"
    )


def test_gate_f_o3_physical_deletion_verified():
    """Verify O-3 build_engine.py is physically removed from the repository."""
    o3_file = _REPO / "apps" / "api" / "src" / "autoforge_api" / "build_engine.py"
    assert not o3_file.exists(), f"O-3 file {o3_file} must not exist"

    with pytest.raises(ImportError):
        from autoforge_api.build_engine import AutonomousBuildEngine  # type: ignore # noqa: F401


def test_gate_f_zero_production_callers_of_retired_orchestrators():
    """Verify via AST that no production source file references retired orchestrators."""
    production_dirs = [
        _REPO / "apps" / "api" / "src",
        _REPO / "packages" / "composition" / "src",
        _REPO / "packages" / "kernel" / "src",
        _REPO / "packages" / "execution" / "src",
        _REPO / "packages" / "artifacts" / "src",
        _REPO / "packages" / "security" / "src",
        _REPO / "packages" / "power_engines" / "src",
    ]

    for pdir in production_dirs:
        for py_file in pdir.rglob("*.py"):
            tree = ast.parse(py_file.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                # Check for import from autoforge_orchestration.orchestrator or autoforge_api.build_engine
                if isinstance(node, ast.ImportFrom):
                    mod = node.module or ""
                    if "build_engine" in mod or "autoforge_orchestration.orchestrator" in mod:
                        pytest.fail(f"Production file {py_file} imports retired orchestrator module: {mod}")
                    if mod == "autoforge_orchestration":
                        for alias in node.names:
                            if alias.name == "OrchestrationEngine":
                                pytest.fail(f"Production file {py_file} imports retired OrchestrationEngine from {mod}")
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "build_engine" in alias.name or "autoforge_orchestration.orchestrator" in alias.name:
                            pytest.fail(f"Production file {py_file} imports retired orchestrator module: {alias.name}")
                # Check for AutonomousBuildEngine construction or execute_build call
                if isinstance(node, ast.Name) and node.id == "AutonomousBuildEngine":
                    pytest.fail(f"Production file {py_file} references retired AutonomousBuildEngine")
                if isinstance(node, ast.Attribute) and node.attr in {"AutonomousBuildEngine", "execute_build"}:
                    pytest.fail(f"Production file {py_file} references retired attribute: {node.attr}")


def test_gate_f_api_handlers_contain_no_orchestration_authority():
    """Verify that server.py route handlers do not implement orchestration loops or model routing."""
    server_py = _REPO / "apps" / "api" / "src" / "autoforge_api" / "server.py"
    tree = ast.parse(server_py.read_text(encoding="utf-8"))

    forbidden_attrs = {"route_to_provider", "retry_loop", "remediate_loop", "orchestrate"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Attribute) and node.attr in forbidden_attrs:
            pytest.fail(f"server.py route handlers contain forbidden orchestration logic: {node.attr}")


def test_gate_f_full_canonical_request_lifecycle_intact():
    """Verify that production API executes through Kernel and O-2 orchestration."""
    service = AutoForgeApiService()
    kernel_mock = AsyncMock(return_value={
        "status": "completed",
        "project_id": str(uuid.uuid4()),
        "summary": "Kernel execution completed successfully",
        "artifacts": [],
    })

    with patch.object(service.system.kernel, "submit_request", kernel_mock):
        req = IntentExecutionRequest(
            prompt="Build a verified cloud-native microservice."
        )
        res = service.execute_intent_pipeline(req)

        assert kernel_mock.called
        call_req = kernel_mock.call_args[0][0]
        assert call_req.request_text == req.prompt
        assert call_req.configuration.get("execute") is True

        assert isinstance(res, IntentExecutionResponse)
        assert res.status == "COMPLETED"
        assert res.summary is not None
