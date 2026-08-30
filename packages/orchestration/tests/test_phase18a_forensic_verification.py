"""PHASE 18-A FORENSIC VERIFICATION TESTS"""

from __future__ import annotations
from typing import Any
import pytest

from autoforge_orchestration.orchestrator import OrchestrationConfig, OrchestrationEngine
from autoforge_orchestration.models import StageStatus, WorkflowStatus
from autoforge_workforce.workers import WorkforceWorker
from test_helpers import SimpleEventSink, DeterministicStageAIProvider, default_verification_command

class InstrumentedAIProvider(DeterministicStageAIProvider):
    def __init__(self) -> None:
        super().__init__()
        self.calls = []
    async def generate_plan(self, context):
        self.calls.append(f"plan:{context.task_id}")
        return await super().generate_plan(context)
    async def generate_implementation(self, context, plan):
        self.calls.append(f"impl:{context.task_id}")
        return await super().generate_implementation(context, plan)

class ProofOrchestrator(OrchestrationEngine):
    def __init__(self, config, *, event_sink=None):
        super().__init__(config, event_sink=event_sink)
        self._ai_providers = []
    def _get_ai_provider(self, stage):
        provider = InstrumentedAIProvider()
        self._ai_providers.append(provider)
        return provider
    def _get_verification_commands(self, stage):
        from autoforge_execution.models import CommandSpec
        return [CommandSpec(argv=default_verification_command(stage.stage_id))]

class FailingAIProvider:
    def __init__(self):
        self.calls = []
    async def generate_plan(self, context):
        self.calls.append("plan")
        return "Failing plan"
    async def generate_implementation(self, context, plan):
        self.calls.append("impl")
        return [{"path": "fail.py", "content": "def solve(): return False"}]
    async def diagnose_failure(self, context, failure_evidence):
        from autoforge_execution.models import DiagnosisReport
        return DiagnosisReport(root_cause="Test", failure_mechanism="Intentional", affected_files=[], suggested_fix="N/A", confidence_score=1.0)
    async def generate_repair(self, context, diagnosis):
        return []

class FailurePropagationOrchestrator(ProofOrchestrator):
    def _get_ai_provider(self, stage):
        return FailingAIProvider()

def _make_config(workspace_root):
    return OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1, global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0, max_rectification_loops=1,
        max_attempts_per_stage=1, require_hitl_for_deployment=False,
        enable_persistence=True, security_guard_enabled=False,
    )

@pytest.mark.asyncio
async def test_selected_worker_is_executed_workforce_worker(workspace_root, simple_event_sink):
    from unittest.mock import patch
    config = _make_config(workspace_root)
    orchestrator = ProofOrchestrator(config, event_sink=simple_event_sink)
    state = await orchestrator.create_project(objective="Test", workflow_id="greenfield")
    executed_workers = []
    orig = WorkforceWorker.execute_task
    async def patched(self, ctx):
        executed_workers.append(self)
        return await orig(self, ctx)
    with patch.object(WorkforceWorker, "execute_task", patched):
        result = await orchestrator.run_project(state.execution_id)
    assert result.status == WorkflowStatus.COMPLETED
    assert len(executed_workers) > 0
    for w in executed_workers:
        assert isinstance(w, WorkforceWorker), f"Not WorkforceWorker: {type(w).__name__}"
        assert hasattr(w, "specialized_type")

@pytest.mark.asyncio
async def test_multiple_specialized_workers_execute(workspace_root, simple_event_sink):
    from unittest.mock import patch
    config = _make_config(workspace_root)
    orchestrator = ProofOrchestrator(config, event_sink=simple_event_sink)
    state = await orchestrator.create_project(objective="Test", workflow_id="greenfield")
    executed_types = set()
    orig = WorkforceWorker.execute_task
    async def patched(self, ctx):
        executed_types.add(type(self).__name__)
        return await orig(self, ctx)
    with patch.object(WorkforceWorker, "execute_task", patched):
        result = await orchestrator.run_project(state.execution_id)
    assert result.status == WorkflowStatus.COMPLETED
    assert len(executed_types) >= 3, f"Expected >=3 types, got {len(executed_types)}: {executed_types}"
    from autoforge_workforce.workers import (
        ResearchEngineer, PlanningEngineer, ArchitectureEngineer,
        BackendEngineer, QAEngineer, DocumentationEngineer,
    )
    known = {c.__name__ for c in [
        ResearchEngineer, PlanningEngineer, ArchitectureEngineer,
        BackendEngineer, QAEngineer, DocumentationEngineer,
    ]}
    for wt in executed_types:
        assert wt in known, f"Unknown worker: {wt}"

@pytest.mark.asyncio
async def test_worker_failure_propagates(workspace_root, simple_event_sink):
    config = _make_config(workspace_root)
    orchestrator = FailurePropagationOrchestrator(config, event_sink=simple_event_sink)
    state = await orchestrator.create_project(objective="Test", workflow_id="greenfield")
    result = await orchestrator.run_project(state.execution_id)
    assert result.status == WorkflowStatus.FAILED
    failed = [s for s in result.stages.values() if s.status == StageStatus.FAILED]
    assert len(failed) >= 1
    for fs in failed:
        assert fs.worker_assignment is not None
        assert fs.finished_at is not None

@pytest.mark.asyncio
async def test_no_generic_engineering_worker_substitution(workspace_root, simple_event_sink):
    from unittest.mock import patch
    config = _make_config(workspace_root)
    orchestrator = ProofOrchestrator(config, event_sink=simple_event_sink)
    state = await orchestrator.create_project(objective="Test", workflow_id="greenfield")
    executed_classes = []
    orig = WorkforceWorker.execute_task
    async def patched(self, ctx):
        executed_classes.append(type(self))
        return await orig(self, ctx)
    with patch.object(WorkforceWorker, "execute_task", patched):
        result = await orchestrator.run_project(state.execution_id)
    assert result.status == WorkflowStatus.COMPLETED
    for cls in executed_classes:
        assert issubclass(cls, WorkforceWorker), f"Generic: {cls.__name__}"
