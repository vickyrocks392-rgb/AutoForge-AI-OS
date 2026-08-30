"""
Scenario 4: Stage Failure → Workflow Failure.

When a stage fails, the workflow transitions to FAILED and
subsequent stages are not executed.
"""
from __future__ import annotations

from typing import Any

import pytest

from autoforge_orchestration.orchestrator import OrchestrationConfig, OrchestrationEngine
from autoforge_orchestration.models import StageStatus, WorkflowStatus
from test_helpers import SimpleEventSink


class FailingAIProvider:
    """AI provider that always generates code that fails verification."""

    def __init__(self) -> None:
        self.plans: list[str] = []

    async def generate_plan(self, context: Any) -> str:
        plan = f"Failing plan for {context.task_name}"
        self.plans.append(plan)
        return plan

    async def generate_implementation(self, context: Any, plan: str) -> list[dict]:
        return [
            {
                "path": "failing_code.py",
                "content": "def solve():\n    return 1 / 0  # Deliberate error\n",
            }
        ]

    async def diagnose_failure(self, context: Any, failure_evidence: Any) -> Any:
        from autoforge_execution.models import DiagnosisReport
        return DiagnosisReport(
            root_cause="Division by zero",
            failure_mechanism="return 1/0 causes ZeroDivisionError",
            affected_files=["failing_code.py"],
            suggested_fix="Fix the division",
            confidence_score=1.0,
        )

    async def generate_repair(self, context: Any, diagnosis: Any) -> list[dict]:
        return []


class FailingOrchestrator(OrchestrationEngine):
    def __init__(self, config: OrchestrationConfig, *, event_sink: SimpleEventSink | None = None) -> None:
        super().__init__(config, event_sink=event_sink)
        self._ai_providers: list[FailingAIProvider] = []

    def _get_ai_provider(self, stage: Any) -> FailingAIProvider:
        provider = FailingAIProvider()
        self._ai_providers.append(provider)
        return provider

    def _get_verification_commands(self, stage: Any) -> list[Any] | None:
        """Return a verification that expects failing_code.py to exist and be importable."""
        from autoforge_execution.models import CommandSpec
        return [
            CommandSpec(
                argv=[
                    "python3",
                    "-c",
                    "import importlib.util, pathlib; "
                    "p = pathlib.Path('failing_code.py'); "
                    "assert p.exists(), 'File not found'; "
                    "spec = importlib.util.spec_from_file_location('mod', p); "
                    "mod = importlib.util.module_from_spec(spec); "
                    "spec.loader.exec_module(mod); "
                    "assert mod.solve() is True",
                ]
            )
        ]


@pytest.mark.asyncio
async def test_stage_failure_propagates_to_workflow_failure(workspace_root: Any, simple_event_sink: SimpleEventSink) -> None:
    config = OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=0,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=False,
        enable_persistence=True,
        security_guard_enabled=False,
    )

    orchestrator = FailingOrchestrator(config, event_sink=simple_event_sink)

    state = await orchestrator.create_project(
        objective="Test failure propagation",
        workflow_id="greenfield",
    )

    result = await orchestrator.run_project(state.execution_id)

    assert result.status == WorkflowStatus.FAILED, (
        f"Expected FAILED, got {result.status}"
    )

    failed_stages = [
        sid for sid, s in result.stages.items()
        if s.status == StageStatus.FAILED
    ]
    assert len(failed_stages) >= 1, "Expected at least one FAILED stage"

    assert simple_event_sink.has_event_type("STAGE_FAILED")
    assert simple_event_sink.has_event_type("WORKFLOW_FAILED")

    assert result.metrics.total_failures >= 1
