"""
Scenario 2: Stage State Transitions.

Verify correct stage status transitions through the lifecycle:
  PENDING → RUNNING → SUCCEEDED
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
async def test_stage_state_transitions(workspace_root: Any, simple_event_sink: SimpleEventSink) -> None:
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
        objective="Test stage transitions",
        workflow_id="greenfield",
    )

    result = await orchestrator.run_project(state.execution_id)

    stage_events: dict[str, list[str]] = {sid: [] for sid in result.stage_order}
    for event in simple_event_sink.events:
        stage_id = getattr(event, "metadata", {}).get("stage_id")
        if stage_id and stage_id in stage_events:
            event_type = getattr(event, "event_type", None)
            if event_type is not None:
                # Store name for flexible string matching
                stage_events[stage_id].append(getattr(event_type, "name", str(event_type)))

    for stage_id, events in stage_events.items():
        stage = result.stages[stage_id]
        if stage.status in (StageStatus.SKIPPED, StageStatus.CANCELLED):
            continue

        assert "STAGE_STARTED" in events, (
            f"Stage '{stage_id}' never emitted STAGE_STARTED. Events: {events}"
        )
        assert "STAGE_SUCCEEDED" in events, (
            f"Stage '{stage_id}' never emitted STAGE_SUCCEEDED. Events: {events}"
        )
        assert "STAGE_FAILED" not in events, (
            f"Stage '{stage_id}' emitted STAGE_FAILED. Events: {events}"
        )

    assert simple_event_sink.has_event_type("INFERENCE_STARTED")
    assert simple_event_sink.has_event_type("INFERENCE_COMPLETED")
