"""
End-to-End Integration Tests for Greenfield and Legacy Modernization Pipelines.
"""

from __future__ import annotations
import pytest
import sys
import json
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_workflows.models import (
    DependencyEdge,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)
from autoforge_execution.models import ArtifactType


@pytest.mark.asyncio
async def test_greenfield_e2e_pipeline(tmp_path: Path):
    """
    Greenfield Pipeline:
    Idea -> Research -> Architecture -> Planning -> Backend -> QA.
    """
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
    except Exception:
        pytest.skip("Local live Ollama daemon (11434) not running")

    system = build_autoforge_system(workspace_root=str(tmp_path))
    await system.initialize()

    # Create task definitions
    t_research = TaskDefinition(
        task_id="t_res",
        name="Research Concept",
        task_type="research_engineer",
        input_data={"idea": "Distributed cache system"},
    )
    t_architecture = TaskDefinition(
        task_id="t_arch",
        name="Design System Architecture",
        task_type="architecture_engineer",
    )
    t_planning = TaskDefinition(
        task_id="t_plan",
        name="Plan Engineering Wave",
        task_type="planning_engineer",
    )
    t_backend = TaskDefinition(
        task_id="t_back",
        name="Implement Cache Store",
        task_type="backend_engineer",
        input_data={
            "files": [{"path": "store.py", "content": "class Store:\n    def get(self, k): return None"}],
            "commands": [[sys.executable, "-c", "import store"]],
        },
    )
    t_qa = TaskDefinition(
        task_id="t_qa",
        name="Verify Implementation",
        task_type="qa_engineer",
        input_data={
            "commands": [[sys.executable, "-c", "import store; s = store.Store(); assert s.get('k') is None"]],
        },
    )

    # Wire DAG dependencies
    edges = [
        DependencyEdge(upstream_task_id="t_res", downstream_task_id="t_arch"),
        DependencyEdge(upstream_task_id="t_arch", downstream_task_id="t_plan"),
        DependencyEdge(upstream_task_id="t_plan", downstream_task_id="t_back"),
        DependencyEdge(upstream_task_id="t_back", downstream_task_id="t_qa"),
    ]

    workflow_def = WorkflowDefinition(
        name="Greenfield Pipeline Workflow",
        tasks=[t_research, t_architecture, t_planning, t_backend, t_qa],
        dependencies=edges,
    )

    handle = system.workflow_engine.submit(workflow_def)
    completed_handle = await system.execution_engine.run_workflow_to_completion(handle)

    # Assert all tasks completed successfully
    assert completed_handle.is_complete
    for t_id in ["t_res", "t_arch", "t_plan", "t_back", "t_qa"]:
        assert completed_handle.task_statuses[t_id] == WorkflowTaskStatus.SUCCEEDED

    await system.shutdown()


@pytest.mark.asyncio
async def test_legacy_modernization_e2e_pipeline(tmp_path: Path):
    """
    Legacy Modernization Pipeline:
    Legacy Intake/Discovery -> Code Archaeology -> Business Rules -> Modernization Architect -> Migration.
    """
    import urllib.request
    try:
        urllib.request.urlopen("http://127.0.0.1:11434/api/tags", timeout=1)
    except Exception:
        pytest.skip("Local live Ollama daemon (11434) not running")

    system = build_autoforge_system(workspace_root=str(tmp_path))
    await system.initialize()

    # Pre-populate some legacy file context in the environment filesystem
    system.execution_engine.environment.filesystem.write_text(
        "legacy_module.cbl",
        "       IDENTIFICATION DIVISION.\n       PROCEDURE DIVISION.\n       CALC-INTEREST.\n           IF AMT > 1000 COMPUTE INT = AMT * 0.05.\n"
    )

    t_discovery = TaskDefinition(
        task_id="t_disc",
        name="Ingest and Discover Legacy Tech",
        task_type="legacy_systems_research_engineer",
    )
    t_archaeology = TaskDefinition(
        task_id="t_archaeo",
        name="Analyze Code Architecture",
        task_type="legacy_code_archaeologist",
    )
    t_rules = TaskDefinition(
        task_id="t_rules",
        name="Extract Business Rules",
        task_type="business_rules_analyst",
    )
    t_mod_architect = TaskDefinition(
        task_id="t_mod_arch",
        name="Formulate Modernization Proposal",
        task_type="modernization_architect",
    )
    t_migration = TaskDefinition(
        task_id="t_migr",
        name="Sequencing Migration Plan",
        task_type="migration_engineer",
    )

    edges = [
        DependencyEdge(upstream_task_id="t_disc", downstream_task_id="t_archaeo"),
        DependencyEdge(upstream_task_id="t_archaeo", downstream_task_id="t_rules"),
        DependencyEdge(upstream_task_id="t_rules", downstream_task_id="t_mod_arch"),
        DependencyEdge(upstream_task_id="t_mod_arch", downstream_task_id="t_migr"),
    ]

    workflow_def = WorkflowDefinition(
        name="Legacy Modernization Workflow",
        tasks=[t_discovery, t_archaeology, t_rules, t_mod_architect, t_migration],
        dependencies=edges,
    )

    handle = system.workflow_engine.submit(workflow_def)
    completed_handle = await system.execution_engine.run_workflow_to_completion(handle)

    # Assert tasks completed successfully
    assert completed_handle.is_complete
    for t_id in ["t_disc", "t_archaeo", "t_rules", "t_mod_arch", "t_migr"]:
        assert completed_handle.task_statuses[t_id] == WorkflowTaskStatus.SUCCEEDED

    await system.shutdown()
