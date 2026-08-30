"""
Scenario 1: Greenfield E2E Happy Path.
"""
from __future__ import annotations

from typing import Any

import pytest

from autoforge_orchestration.orchestrator import OrchestrationConfig, OrchestrationEngine
from autoforge_orchestration.models import StageStatus, WorkflowStatus
from test_helpers import SimpleEventSink, DeterministicStageAIProvider, default_verification_command


class DeterministicOrchestrator(OrchestrationEngine):
    """Test orchestrator that uses a deterministic (no-real-LLM) AI provider."""

    def __init__(
        self,
        config: OrchestrationConfig,
        *,
        event_sink: SimpleEventSink | None = None,
    ) -> None:
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
async def test_greenfield_e2e_happy_path(workspace_root: Any, simple_event_sink: SimpleEventSink) -> None:
    config = OrchestrationConfig(
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

    orchestrator = DeterministicOrchestrator(config, event_sink=simple_event_sink)

    state = await orchestrator.create_project(
        objective="E2E test: build a simple calculator module",
        workflow_id="greenfield",
    )

    assert state.project_id is not None
    assert state.workflow_id == "greenfield"
    assert state.status == WorkflowStatus.CREATED

    result = await orchestrator.run_project(state.execution_id)

    assert result.status == WorkflowStatus.COMPLETED, (
        f"Expected COMPLETED, got {result.status}. "
        f"Failed stages: {[s for s in result.stages.values() if s.status == StageStatus.FAILED]}"
    )

    for stage_id, stage in result.stages.items():
        assert stage.status in (StageStatus.SUCCEEDED, StageStatus.SKIPPED), (
            f"Stage '{stage_id}' status is {stage.status}"
        )

    assert simple_event_sink.has_event_type("WORKFLOW_STARTED")
    assert simple_event_sink.has_event_type("WORKFLOW_COMPLETED")
    assert len(orchestrator._ai_providers) >= 1

    # At least one AI provider should have generated plans (indicating real AI interaction).
    # Note: specialized loops (ResearchLoop, PlanningLoop, ArchitectureLoop) don't call
    # generate_plan - only EngineeringLoop stages do. So we check "any" not "all".
    assert any(len(p.plans_generated) >= 1 for p in orchestrator._ai_providers), (
        "At least one AI provider should have generated plans"
    )
