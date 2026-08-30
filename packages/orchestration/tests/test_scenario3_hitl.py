"""
Scenario 3: HITL Gate Workflow Pause and Resumption.
"""
from __future__ import annotations

from typing import Any

import pytest

from autoforge_orchestration.orchestrator import OrchestrationConfig, OrchestrationEngine
from autoforge_orchestration.models import StageStatus, WorkflowStatus
from test_helpers import SimpleEventSink, DeterministicStageAIProvider, default_verification_command


class DeterministicOrchestrator(OrchestrationEngine):
    def __init__(self, config: OrchestrationConfig, *, event_sink: SimpleEventSink | None = None) -> None:
        super().__init__(config, event_sink=event_sink)
        self._ai_providers: list[DeterministicStageAIProvider] = []

    def _get_ai_provider(self, stage: Any) -> DeterministicStageAIProvider:
        provider = DeterministicStageAIProvider()
        self._ai_providers.append(provider)
        return provider

    def _get_verification_commands(self, stage: Any) -> list[Any] | None:
        """Override to provide real verification per stage."""
        from autoforge_execution.models import CommandSpec
        return [CommandSpec(argv=default_verification_command(stage.stage_id))]


@pytest.mark.asyncio
async def test_hitl_gate_pauses_and_resumes_workflow(workspace_root: Any, simple_event_sink: SimpleEventSink) -> None:
    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=True,
        enable_persistence=True,
        security_guard_enabled=False,
    )

    orchestrator = DeterministicOrchestrator(config, event_sink=simple_event_sink)

    state = await orchestrator.create_project(
        objective="Test HITL gate",
        workflow_id="greenfield",
    )

    result = await orchestrator.run_project(state.execution_id)

    assert result.status == WorkflowStatus.WAITING_FOR_HITL, (
        f"Expected WAITING_FOR_HITL, got {result.status}"
    )

    assert len(result.hitl_gates) >= 1, "No HITL gate was registered"

    gate_id = next(iter(result.hitl_gates.keys()))
    gate = result.hitl_gates[gate_id]

    assert gate.status == "PENDING"
    assert gate.stage_id == "deployment"

    assert simple_event_sink.has_event_type("APPROVAL_REQUIRED")

    resumed = await orchestrator.resume_from_hitl(
        execution_id=result.execution_id,
        gate_id=gate_id,
        approved=True,
        reason="E2E test approval",
    )

    assert resumed.status == WorkflowStatus.COMPLETED, (
        f"Expected COMPLETED after HITL approval, got {resumed.status}"
    )

    deploy_stage = resumed.stages.get("deployment")
    assert deploy_stage is not None
    assert deploy_stage.status == StageStatus.SUCCEEDED, (
        f"Deployment stage should be SUCCEEDED, got {deploy_stage.status}"
    )

    assert simple_event_sink.has_event_type("APPROVAL_DECIDED")

    updated_gate = resumed.hitl_gates[gate_id]
    assert updated_gate.status == "APPROVED"
    assert updated_gate.actor == "human_operator"
    assert updated_gate.reason_text == "E2E test approval"


@pytest.mark.asyncio
async def test_hitl_rejection_fails_workflow(workspace_root: Any, simple_event_sink: SimpleEventSink) -> None:
    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=True,
        enable_persistence=True,
        security_guard_enabled=False,
    )

    orchestrator = DeterministicOrchestrator(config, event_sink=simple_event_sink)

    state = await orchestrator.create_project(
        objective="Test HITL rejection",
        workflow_id="greenfield",
    )

    result = await orchestrator.run_project(state.execution_id)
    assert result.status == WorkflowStatus.WAITING_FOR_HITL

    gate_id = next(iter(result.hitl_gates.keys()))

    rejected = await orchestrator.resume_from_hitl(
        execution_id=result.execution_id,
        gate_id=gate_id,
        approved=False,
        reason="E2E test rejection",
    )

    assert rejected.status == WorkflowStatus.FAILED, (
        f"Expected FAILED after HITL rejection, got {rejected.status}"
    )
    assert simple_event_sink.has_event_type("APPROVAL_DECIDED")
