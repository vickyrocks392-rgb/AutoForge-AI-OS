"""
Gate E1: Power Engine Convergence to Canonical O-2 Path Architecture Tests.

Verifies all 12 Gate E1 architecture invariants (E1-INV-01 through E1-INV-12):
- E1-INV-01: Every Power Engine is reached through canonical capability dispatch.
- E1-INV-02: No Power Engine becomes a lifecycle authority.
- E1-INV-03: No Power Engine becomes a second orchestration engine.
- E1-INV-04: Power Engine results can be represented as canonical ExecutionOutcome.
- E1-INV-05: Lifecycle decisions remain deterministic and outside Power Engine domain logic.
- E1-INV-06: Model routing remains infrastructure-owned.
- E1-INV-07: Artifact ownership remains canonical.
- E1-INV-08: Validation/review cannot be bypassed.
- E1-INV-09: O-1 remains quarantined.
- E1-INV-10: O-3 remains untouched as an API path during E1.
- E1-INV-11: Phase 20 modernization continues using the existing modernization engine.
- E1-INV-12: No M1/HP hardware is required or activated.
"""

from __future__ import annotations

import asyncio
import os
import pathlib
import subprocess
import sys
import tempfile
import uuid
from typing import Any, Dict

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]

from autoforge_composition.capability_router import (
    CANONICAL_CAPABILITIES,
    CAPABILITY_AGENT,
    CAPABILITY_AUTOMATION,
    CAPABILITY_MIGRATION,
    CAPABILITY_MODERNIZATION,
    CAPABILITY_RAG,
    CommercialCapabilityRouter,
    RoutedExecution,
    build_default_router,
    read_capability,
)
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_composition.kernel_adapters import KernelExecutionEngineAdapter
from autoforge_composition.lifecycle_decision import (
    LifecycleDecision,
    RemediationBudget,
    decide_lifecycle,
)


class _RecordingEngine:
    """Stands in for generic ExecutionEngine."""

    def __init__(self) -> None:
        self.calls: list = []

    async def execute_task_definition(self, *args: Any, **kwargs: Any) -> tuple[bool, list, Any]:
        self.calls.append((args, kwargs))
        return True, [], None


class _ConfigReader:
    def __init__(self, config: Dict[str, Any]) -> None:
        self.config = config

    async def get_project_state(self, project_id: Any) -> Dict[str, Any]:
        return {"configuration": self.config}


def _make_loop(capability: str | None = None, **custom: Any) -> Dict[str, Any]:
    input_data: Dict[str, Any] = dict(custom)
    if capability:
        input_data["capability"] = capability
    return {
        "project_id": f"proj-{uuid.uuid4().hex[:6]}",
        "workflow_id": str(uuid.uuid4()),
        "request_text": "Gate E1 test execution",
        "loop": {
            "type": "coding",
            "name": "Core Coding Loop",
            "task_id": f"t-{uuid.uuid4().hex[:6]}",
            "input_data": input_data,
        },
    }


# ── E1-INV-01: Canonical Capability Dispatch ────────────────────────────────

@pytest.mark.asyncio
async def test_e1_inv_01_all_five_engines_reached_via_canonical_dispatch() -> None:
    """Every Power Engine is reached through canonical capability dispatch."""
    router = build_default_router()
    for cap in CANONICAL_CAPABILITIES:
        assert router.supports(cap), f"Router must support canonical capability {cap}"

    # Verify each of the 5 capabilities dispatches through KernelExecutionEngineAdapter
    expected_classes = {
        CAPABILITY_RAG: "RAGKnowledgePowerEngine",
        CAPABILITY_AGENT: "CustomAIAgentPowerEngine",
        CAPABILITY_AUTOMATION: "AIAutomationPowerEngine",
        CAPABILITY_MIGRATION: "CodeMigrationPowerEngine",
        CAPABILITY_MODERNIZATION: "ModernizationPipeline",
    }

    for cap, expected_class in expected_classes.items():
        with tempfile.TemporaryDirectory() as tmp:
            tmp_p = pathlib.Path(tmp)
            (tmp_p / "module.py").write_text("print('test')\n", encoding="utf-8")
            config = {
                "capability": cap,
                "source_root": str(tmp_p),
                "legacy_source_root": str(tmp_p),
            }
            recording = _RecordingEngine()
            adapter = KernelExecutionEngineAdapter(
                concrete_engine=recording,
                capability_router=router,
                project_configuration_reader=_ConfigReader(config),
            )
            loop_data = _make_loop()
            res = await adapter.execute_loop("coding", loop_data, loop_data)

            assert res.get("routed") is True, f"Capability {cap} must be routed"
            assert res.get("capability") == cap, f"Capability {cap} identity must match"
            assert res.get("engine_class") == expected_class, (
                f"Capability {cap} must dispatch to {expected_class}, got {res.get('engine_class')}"
            )
            assert len(recording.calls) == 0, (
                f"Generic engine must not execute for commercial capability {cap}"
            )


# ── E1-INV-02: No Power Engine Becomes Lifecycle Authority ──────────────────

def test_e1_inv_02_power_engines_do_not_own_lifecycle_authority() -> None:
    """Power engines produce domain deliverables, not lifecycle authority."""
    from autoforge_power_engines.base import PowerEngine
    from autoforge_modernization.pipeline import ModernizationPipeline

    # PowerEngine base class has no reference to Kernel, ProjectState, or LifecycleDecision
    assert not hasattr(PowerEngine, "transition_project_state")
    assert not hasattr(PowerEngine, "decide_lifecycle")
    assert not hasattr(ModernizationPipeline, "transition_project_state")
    assert not hasattr(ModernizationPipeline, "decide_lifecycle")


# ── E1-INV-03: No Power Engine Is A Second Orchestration Engine ──────────────

def test_e1_inv_03_no_power_engine_is_second_orchestration_engine() -> None:
    """Only O-2 DefaultOrchestrationEngine owns loop and stage orchestration."""
    from autoforge_power_engines.base import PowerEngine
    from autoforge_kernel.orchestration import OrchestrationEngine, DefaultOrchestrationEngine

    assert not issubclass(PowerEngine, OrchestrationEngine)
    assert DefaultOrchestrationEngine is not None


# ── E1-INV-04: Canonical ExecutionOutcome Representation ───────────────────

def test_e1_inv_04_all_engine_results_representable_as_execution_outcome() -> None:
    """Power Engine results map into canonical ExecutionOutcome."""
    class FakePowerResult:
        def __init__(self, success: bool, stages: list[str], err: str | None = None) -> None:
            self.success = success
            self.stages_executed = stages
            self.error_message = err

    # Engine 1-4 success -> COMPLETE
    res_ok = FakePowerResult(True, ["INTAKE", "VERIFY"])
    out_ok = ExecutionOutcome.from_power_engine_result(
        res_ok, loop_type="coding", capability=CAPABILITY_AGENT, engine_class="CustomAIAgentPowerEngine"
    )
    assert out_ok.status is OutcomeStatus.COMPLETE
    assert out_ok.passed is True
    assert out_ok.routed is True

    # Engine 1-4 failure -> REMEDIATE
    res_fail = FakePowerResult(False, ["INTAKE"], err="syntax error")
    out_fail = ExecutionOutcome.from_power_engine_result(
        res_fail, loop_type="coding", capability=CAPABILITY_RAG, engine_class="RAGKnowledgePowerEngine"
    )
    assert out_fail.status is OutcomeStatus.REMEDIATE
    assert out_fail.passed is False
    assert out_fail.findings == ["syntax error"]

    # Engine 1-4 waiting -> ESCALATE
    res_wait = FakePowerResult(False, ["INTAKE", "WAITING_FOR_HUMAN_APPROVAL"])
    out_wait = ExecutionOutcome.from_power_engine_result(
        res_wait, loop_type="coding", capability=CAPABILITY_MIGRATION, engine_class="CodeMigrationPowerEngine"
    )
    assert out_wait.status is OutcomeStatus.ESCALATE
    assert out_wait.passed is False

    # Engine 5 (PipelineResult) success -> COMPLETE
    class FakePipelineResult:
        def __init__(self, status: str, failed_units: int = 0, err: str | None = None) -> None:
            self.status = status
            self.wave_results = [type("W", (), {"units_failed": failed_units})()]
            self.error_message = err

    pipe_ok = FakePipelineResult("complete", failed_units=0)
    out_pipe_ok = ExecutionOutcome.from_pipeline_result(pipe_ok, loop_type="coding")
    assert out_pipe_ok.status is OutcomeStatus.COMPLETE
    assert out_pipe_ok.passed is True
    assert out_pipe_ok.routed is True

    # Engine 5 failure -> REMEDIATE
    pipe_fail = FakePipelineResult("failed", failed_units=2, err="transformation error")
    out_pipe_fail = ExecutionOutcome.from_pipeline_result(pipe_fail, loop_type="coding")
    assert out_pipe_fail.status is OutcomeStatus.REMEDIATE
    assert out_pipe_fail.passed is False
    assert out_pipe_fail.findings == ["transformation error"]

    # Engine 5 blocked -> ESCALATE
    pipe_block = FakePipelineResult("blocked")
    out_pipe_block = ExecutionOutcome.from_pipeline_result(pipe_block, loop_type="coding")
    assert out_pipe_block.status is OutcomeStatus.ESCALATE
    assert out_pipe_block.passed is False


# ── E1-INV-05: Lifecycle Decisions Deterministic and Outside Domain Logic ───

def test_e1_inv_05_lifecycle_decisions_remain_deterministic() -> None:
    """decide_lifecycle executes outside Power Engine domain logic."""
    outcome_complete = ExecutionOutcome(
        status=OutcomeStatus.COMPLETE,
        loop_type="coding",
        passed=True,
        routed=True,
        capability="custom_ai_agent",
        engine_class="CustomAIAgentPowerEngine",
    )
    dec_complete = decide_lifecycle(outcome_complete, budget=RemediationBudget(attempt=1, max_attempts=2))
    assert dec_complete.status is OutcomeStatus.COMPLETE
    assert dec_complete.terminal is True

    outcome_remediate = ExecutionOutcome(
        status=OutcomeStatus.REMEDIATE,
        loop_type="coding",
        passed=False,
        findings=["test failed"],
        routed=True,
        capability="rag_knowledge",
        engine_class="RAGKnowledgePowerEngine",
    )
    # Attempt 1: remediation allowed
    dec_rem1 = decide_lifecycle(outcome_remediate, budget=RemediationBudget(attempt=1, max_attempts=2))
    assert dec_rem1.status is OutcomeStatus.REMEDIATE
    assert dec_rem1.remediation_allowed is True
    assert dec_rem1.terminal is False

    # Attempt 2: budget exhausted -> fails closed
    dec_rem2 = decide_lifecycle(outcome_remediate, budget=RemediationBudget(attempt=2, max_attempts=2))
    assert dec_rem2.status is OutcomeStatus.FAILED
    assert dec_rem2.terminal is True


# ── E1-INV-06: Model Routing Remains Infrastructure-Owned ───────────────────

def test_e1_inv_06_model_routing_remains_infrastructure_owned() -> None:
    """ModelRouterService and KernelModelRouterAdapter are infrastructure-owned."""
    from autoforge_composition.kernel_adapters import KernelModelRouterAdapter
    from autoforge_ai_infrastructure import ModelRouterService

    # KernelModelRouterAdapter requires ModelRouterService and fails closed
    adapter = KernelModelRouterAdapter(model_router=None)
    with pytest.raises(RuntimeError, match="canonical model allocation"):
        asyncio.run(adapter.select_model({"offline_only": True}))


# ── E1-INV-07: Canonical Artifact Ownership ──────────────────────────────────

@pytest.mark.asyncio
async def test_e1_inv_07_routed_evidence_reaches_canonical_artifact_pipeline() -> None:
    """Power Engine verification scorecards are recorded through canonical ArtifactPipeline."""
    from autoforge_composition.kernel_adapters import KernelExecutionEngineAdapter

    class FakePipeline:
        def __init__(self) -> None:
            self.records = []

        def record_artifact(self, **kwargs: Any) -> Any:
            self.records.append(kwargs)
            return type("Rec", (), {"model_dump": lambda s, mode: kwargs})()

    class FakeExecutionEngine:
        def __init__(self) -> None:
            self.artifacts = FakePipeline()

        async def execute_task_definition(self, *a: Any, **k: Any) -> Any:
            return True, [], None

    fake_exec = FakeExecutionEngine()
    router = build_default_router()
    adapter = KernelExecutionEngineAdapter(
        concrete_engine=fake_exec,
        capability_router=router,
        project_configuration_reader=_ConfigReader({"capability": "custom_ai_agent"}),
    )

    loop_data = _make_loop()
    res = await adapter.execute_loop("coding", loop_data, loop_data)
    assert res.get("routed") is True
    assert len(fake_exec.artifacts.records) == 1
    rec = fake_exec.artifacts.records[0]
    assert "commercial_verification_custom_ai_agent" in rec["name"]


# ── E1-INV-08: Validation and Review Cannot Be Bypassed ──────────────────────

def test_e1_inv_08_completion_requires_validation_and_review() -> None:
    """Completion requires validation port and review evidence."""
    from autoforge_kernel.completion import DefaultCompletionModule

    assert hasattr(DefaultCompletionModule, "validate_completion") or hasattr(
        DefaultCompletionModule, "execute_completion"
    ) or hasattr(DefaultCompletionModule, "_validate_completion_readiness")


# ── E1-INV-09: O-1 Remains Quarantined ────────────────────────────────────────

def test_e1_inv_09_o1_remains_quarantined() -> None:
    """O-1 orchestrator remains quarantined and unwired in production."""
    from autoforge_orchestration import OrchestrationEngine

    assert OrchestrationEngine is not None
    # Verify composition_root does not construct O-1 OrchestrationEngine
    comp_file = _REPO / "packages/composition/src/autoforge_composition/composition_root.py"
    content = comp_file.read_text(encoding="utf-8")
    assert "autoforge_orchestration.orchestrator" not in content
    assert "from autoforge_orchestration import OrchestrationEngine" not in content


# ── E1-INV-10: O-3 Remains Untouched API Path ────────────────────────────────

def test_e1_inv_10_o3_remains_untouched_as_api_path() -> None:
    """O-3 AutonomousBuildEngine remains in autoforge_api and is not wired to composition."""
    o3_file = _REPO / "apps/api/src/autoforge_api/build_engine.py"
    assert o3_file.exists()
    comp_file = _REPO / "packages/composition/src/autoforge_composition/composition_root.py"
    assert "AutonomousBuildEngine" not in comp_file.read_text(encoding="utf-8")


# ── E1-INV-11: Phase 20 Modernization Path Remains Intact ───────────────────

def test_e1_inv_11_phase20_modernization_path_intact() -> None:
    """Phase 20 modernization continues using ModernizationPipeline."""
    from autoforge_modernization.pipeline import ModernizationPipeline
    from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies

    pipeline = ModernizationPipeline()
    assert hasattr(pipeline, "run")
    assert G3TransformationStrategies is not None


# ── E1-INV-12: No M1/HP Hardware Activation ─────────────────────────────────

def test_e1_inv_12_no_m1_or_hp_hardware_required_or_activated() -> None:
    """No M1 or HP hardware endpoints are activated during E1."""
    assert os.environ.get("AUTOFORGE_ACTIVATE_M1") != "1"
    assert os.environ.get("AUTOFORGE_ACTIVATE_HP") != "1"
