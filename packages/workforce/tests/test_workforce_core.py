"""
Behavioral tests for Worker Core, Greenfield Workers, and Registry.
"""

from __future__ import annotations
import pytest
import uuid
from pathlib import Path

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
    """
    env = WorkspaceEnvironment(tmp_path)
    
    # 1. Instantiate specialized worker
    worker = ResearchEngineer(
        worker_id="test-researcher-01",
        environment=env,
        ai_provider=None,
    )
    
    assert worker.specialized_type == "research_engineer"
    assert worker.base_type == BaseWorkerType.RESEARCH
    assert worker.status == WorkerStatus.CREATED

    # 2. Run execution
    task_def = TaskDefinition(
        task_id="task-research-xyz",
        name="Research New Idea",
        task_type="research",
        input_data={"idea": "Vibrant Dark Mode Theme"},
    )
    
    worker_inst = WORKER_REGISTRY.lookup("research_engineer")(
        worker_id="test-researcher-01",
        environment=env,
        ai_provider=None,
    )
    passed, artifacts, eval_res = await worker_inst.execute_task(
        context=pytest.importorskip("autoforge_execution.context").ExecutionContext.from_task_definition(task_def, env.root)
    )

    assert passed is True
    assert len(artifacts) == 1
    assert artifacts[0].name == "research_brief.md"
    assert "Research Brief" in artifacts[0].content
    assert eval_res.status.value == "passed"
