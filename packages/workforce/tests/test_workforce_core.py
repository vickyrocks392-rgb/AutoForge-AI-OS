from __future__ import annotations
import sys
import uuid
from pathlib import Path
import pytest

# Ensure local source packages take precedence over installed packages.
_ROOT = Path(__file__).resolve().parents[3]
for _pkg in [
    "orchestration", "workforce", "ai_infrastructure", "execution", "events",
    "observability", "composition", "models", "persistence", "workflows",
    "artifacts", "kernel", "runtime", "review", "security", "event_platform",
    "connectors", "shared", "knowledge_platform",
]:
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

"""
Behavioral tests for Worker Core, Greenfield Workers, and Registry.
"""

from autoforge_workflows.models import TaskDefinition
from autoforge_execution import WorkspaceEnvironment
from autoforge_execution.models import WorkerType as BaseWorkerType, WorkerStatus

from autoforge_workforce.registry import WORKER_REGISTRY
from autoforge_workforce.workers import (
    WORKER_CLASSES,
    ResearchEngineer,
    BackendEngineer,
    LegacyCodeArchaeologist,
)
from autoforge_workforce.capabilities import Permission


def test_registry_registration_and_lookup():
    """
    Registry must register and lookup workers and their expertise deterministically.
    """
    assert "backend_engineer" in WORKER_REGISTRY.list_workers()
    assert "legacy_code_archaeologist" in WORKER_REGISTRY.list_workers()

    cls = WORKER_REGISTRY.lookup("backend_engineer")
    assert cls == BackendEngineer

    exp = WORKER_REGISTRY.get_expertise("backend_engineer")
    assert exp is not None
    assert exp.worker_type == "backend_engineer"
    assert "backend_coding" in exp.capabilities


def test_registry_capability_matching():
    """
    Registry must perform capability matching deterministically.
    """
    matches_res = WORKER_REGISTRY.match_capabilities(["research"])
    assert "research_engineer" in matches_res
    matches_arch = WORKER_REGISTRY.match_capabilities(["architecture_design"])
    assert "architecture_engineer" in matches_arch


def test_registry_task_compatibility():
    """
    Registry must check task compatibility.
    """
    assert WORKER_REGISTRY.check_task_compatibility("backend_engineer", "coding")
    assert not WORKER_REGISTRY.check_task_compatibility("backend_engineer", "research")


def test_registry_permission_validation():
    """
    Registry must enforce permissions.
    """
    assert WORKER_REGISTRY.validate_permission("backend_engineer", "read", "fs")
    assert WORKER_REGISTRY.validate_permission("backend_engineer", "write", "fs")
    
    # Legacy worker has read only filesystem access
    assert WORKER_REGISTRY.validate_permission("legacy_code_archaeologist", "read", "fs")
    assert not WORKER_REGISTRY.validate_permission("legacy_code_archaeologist", "write", "fs")


@pytest.mark.asyncio
async def test_specialized_worker_instantiation_and_lifecycle(tmp_path: Path):
    """
    Verify worker lifecycle and specialized loop execution.

    Phase 18-C: Specialized loops now call real AI infrastructure.
    Tests must provide a mock AI provider that returns substantive output,
    reflecting actual AI behavior. Short/deterministic output is correctly
    rejected as non-AI by the loops.
    """
    env = WorkspaceEnvironment(tmp_path)

    # Mock AI provider returning substantive output (reflects real AI behavior)
    class MockResearchAI:
        _last_execution_result = type("R", (), {"provider_id": "test", "model_id": "mock"})()

        async def generate_plan(self, ctx):
            return (
                "# Research Brief\n\n"
                "## Problem Understanding\n"
                "Building a vibrant dark mode theme requires designing color schemes, "
                "contrast ratios, accessibility considerations, and implementation strategies.\n\n"
                "## User Needs\n"
                "- Accessibility compliance\n"
                "- System preference detection\n"
                "- Smooth transition animations\n\n"
                "## Recommended Approach\n"
                "Use CSS custom properties with prefers-color-scheme media query."
            )

        async def generate_implementation(self, ctx, plan):
            return []

        async def diagnose_failure(self, ctx, evidence):
            return None

        async def generate_repair(self, ctx, diagnosis):
            return []

    # 1. Instantiate specialized worker
    worker = ResearchEngineer(
        worker_id="test-researcher-01",
        environment=env,
        ai_provider=MockResearchAI(),
    )

    assert worker.specialized_type == "research_engineer"
    assert worker.base_type == BaseWorkerType.RESEARCH
    assert worker.status == WorkerStatus.CREATED

    # 2. Run execution with mock AI provider
    task_def = TaskDefinition(
        task_id="task-research-xyz",
        name="Research New Idea",
        task_type="research",
        input_data={"idea": "Vibrant Dark Mode Theme"},
    )

    worker_inst = WORKER_REGISTRY.lookup("research_engineer")(
        worker_id="test-researcher-01",
        environment=env,
        ai_provider=MockResearchAI(),
    )
    passed, artifacts, eval_res = await worker_inst.execute_task(
        context=pytest.importorskip("autoforge_execution.context").ExecutionContext.from_task_definition(task_def, env.root)
    )

    # Phase 18-C: Real AI output from mock provider produces PASSED
    assert passed is True, f"Worker must pass with mock AI output. eval={eval_res}"
    assert len(artifacts) == 1
    assert artifacts[0].name == "research_brief.md"
    assert "Research Brief" in artifacts[0].content
    assert eval_res.status.value == "passed"
    assert "routed via" in eval_res.qualitative_findings
    assert "routed via" in eval_res.qualitative_findings


class _PassingLoop:
    """Minimal loop that always passes (H2 helper)."""
    async def run(self, context, worker_id, **kwargs):
        from autoforge_execution.models import (
            ArtifactRecord, ArtifactType, EvaluationResult, EvaluationStatus,
        )
        return (True,
                [ArtifactRecord(name="test.md", artifact_type=ArtifactType.SUMMARY,
                                content="passed", provenance=None)],
                EvaluationResult(status=EvaluationStatus.PASSED, qualitative_findings="ok"))


class _FailingLoop:
    """Minimal loop that always fails (H2 helper)."""
    async def run(self, context, worker_id, **kwargs):
        from autoforge_execution.models import EvaluationResult, EvaluationStatus
        return (False, [],
                EvaluationResult(status=EvaluationStatus.FAILED,
                                 qualitative_findings="intentional failure"))



@pytest.mark.asyncio
async def test_worker_retry_prepare_from_failed(tmp_path: Path):
    """H2 Tests 1-3: Worker can be prepared from FAILED state for retry.

    Before H2: EngineeringWorker.prepare() only allowed CREATED -> READY.
    When a worker was in FAILED state (from a previous attempt), calling
    prepare() raised WorkerError("cannot prepare from status 'failed'").

    After H2: prepare() allows CREATED | FAILED | CANCELLED | READY -> READY.
    """
    env = WorkspaceEnvironment(tmp_path)

    class _FailingAI:
        async def generate_plan(self, ctx):
            raise RuntimeError("intentional AI failure")

    worker = ResearchEngineer(
        worker_id="test-retry-worker",
        environment=env,
        ai_provider=_FailingAI(),
    )

    # H2 Test 1: normal CREATED -> READY
    assert worker.status == WorkerStatus.CREATED
    worker.prepare("task-1", workflow_id=uuid.uuid4(), attempt_number=1)
    assert worker.status == WorkerStatus.READY

    # Simulate failed execution (worker goes to FAILED state)
    worker._state.status = WorkerStatus.FAILED
    assert worker.status == WorkerStatus.FAILED

    # H2 Test 2: prepare() from FAILED -> READY (no WorkerError)
    worker.prepare("task-1-retry", workflow_id=uuid.uuid4(), attempt_number=2)
    assert worker.status == WorkerStatus.READY, (
        "Worker must transition to READY after prepare() from FAILED state"
    )
    assert worker._state.attempt_number == 2, (
        "Attempt number must be updated for the retry"
    )
    assert worker._state.task_id == "task-1-retry", (
        "Task ID must be updated for the retry"
    )


@pytest.mark.asyncio
async def test_worker_retry_second_attempt_reaches_execution(tmp_path: Path):
    """H2 Tests 3-5: Second attempt does NOT raise 'cannot prepare' and reaches execution."""
    from autoforge_execution.context import ExecutionContext
    env = WorkspaceEnvironment(tmp_path)
    execution_log: list[int] = []

    class _CountingLoop:
        async def run(self, context, worker_id, **kwargs):
            execution_log.append(context.attempt_number)
            from autoforge_execution.models import (
                ArtifactRecord, ArtifactType, EvaluationResult, EvaluationStatus,
                ArtifactProvenance,
            )
            provenance = ArtifactProvenance(
                task_id=context.task_id,
                worker_id=worker_id,
                attempt_number=context.attempt_number,
            )
            if context.attempt_number == 1:
                return (False, [],
                        EvaluationResult(status=EvaluationStatus.FAILED,
                                        qualitative_findings="first attempt fails"))
            return (True,
                    [ArtifactRecord(name="succeeded.md",
                                    artifact_type=ArtifactType.SUMMARY,
                                    content="retry succeeded", provenance=provenance)],
                    EvaluationResult(status=EvaluationStatus.PASSED,
                                    qualitative_findings="ok"))

    class _DummyAI:
        async def generate_plan(self, ctx):
            raise RuntimeError("not used")

    worker = ResearchEngineer(
        worker_id="test-retry-exec", environment=env, ai_provider=_DummyAI()
    )
    task_def = TaskDefinition(
        task_id="task-retry-exec", name="Retry Test Task", task_type="research"
    )

    import autoforge_workforce.loops as wf_loops
    original_fn = wf_loops.get_loop_class

    class _PatchedResearchLoop(original_fn("research")):
        def __init__(self, *args, **kwargs):
            pass  # Skip parent __init__

        async def run(self, *args, **kwargs):
            return await _CountingLoop().run(*args, **kwargs)

    wf_loops.get_loop_class = (
        lambda t: _PatchedResearchLoop if t == "research" else original_fn(t)
    )

    try:
        ctx1 = ExecutionContext.from_task_definition(task_def, tmp_path)
        ctx1._attempt_number = 1
        worker.prepare("task-retry-exec", workflow_id=uuid.uuid4(), attempt_number=1)
        passed1, _, _ = await worker.execute_task(ctx1)
        assert passed1 is False
        assert worker.status == WorkerStatus.FAILED

        # H2 Test 3: prepare() from FAILED must not raise
        ctx2 = ExecutionContext.from_task_definition(task_def, tmp_path, attempt_number=2)
        worker.prepare("task-retry-exec", workflow_id=uuid.uuid4(), attempt_number=2)
        assert worker.status == WorkerStatus.READY, (
            "H2: prepare() from FAILED must not raise"
        )

        # H2 Test 4: Second attempt reaches execution
        passed2, artifacts2, _ = await worker.execute_task(ctx2)
        assert passed2 is True, "Second attempt must succeed"
        assert len(artifacts2) == 1
        assert worker.status == WorkerStatus.COMPLETED

        # H2 Test 5: Attempt identity preserved
        assert 1 in execution_log and 2 in execution_log
    finally:
        wf_loops.get_loop_class = original_fn


def test_worker_prepare_from_cancelled(tmp_path: Path):
    """H2 Test 6: prepare() allowed from CANCELLED state."""
    env = WorkspaceEnvironment(tmp_path)
    worker = ResearchEngineer(
        worker_id="test-cancelled", environment=env, ai_provider=None
    )
    worker.prepare("task-x", workflow_id=uuid.uuid4(), attempt_number=1)
    worker._state.status = WorkerStatus.CANCELLED
    assert worker.status == WorkerStatus.CANCELLED
    worker.prepare("task-x-retry", workflow_id=uuid.uuid4(), attempt_number=2)
    assert worker.status == WorkerStatus.READY


def test_worker_prepare_from_ready_noop(tmp_path: Path):
    """H2 Test 6 variant: prepare() from READY is a safe no-op."""
    env = WorkspaceEnvironment(tmp_path)
    worker = ResearchEngineer(
        worker_id="test-ready", environment=env, ai_provider=None
    )
    worker.prepare("task-y", workflow_id=uuid.uuid4(), attempt_number=1)
    assert worker.status == WorkerStatus.READY
    worker.prepare("task-y-2", workflow_id=uuid.uuid4(), attempt_number=2)
    assert worker.status == WorkerStatus.READY
    assert worker._state.attempt_number == 2
