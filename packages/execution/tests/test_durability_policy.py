"""
Tests for Execution Durability Policy and Artifact Persistence Error Disambiguation.
Phase 18-K Remediation: Parts 9 & 10.
"""

from __future__ import annotations

import uuid
from pathlib import Path
from unittest.mock import MagicMock
import pytest

from autoforge_workflows.models import TaskDefinition
from autoforge_execution.engine import (
    ExecutionEngine,
    ExecutionEngineConfig,
    DurabilityPolicy,
    DurabilityPersistenceError,
)
from autoforge_execution.artifacts import (
    ArtifactPipeline,
    ArtifactRetrievalError,
    ArtifactPersistenceError,
)
from autoforge_execution.environment import WorkspaceEnvironment


@pytest.mark.asyncio
async def test_durability_policy_fail_closed(tmp_path: Path):
    # Setup mock recorder that fails
    mock_recorder = MagicMock()
    mock_recorder.begin_execution.side_effect = RuntimeError("Disk full / DB connection failed")

    config = ExecutionEngineConfig(
        durable_recorder=mock_recorder,
        durability_policy=DurabilityPolicy.FAIL_CLOSED,
    )
    env = WorkspaceEnvironment(tmp_path)
    engine = ExecutionEngine(environment=env, config=config)

    task_def = TaskDefinition(
        task_id="task-fail-closed",
        name="test-fail-closed",
        description="Testing fail-closed durability policy",
        task_type="coding",
    )

    with pytest.raises(DurabilityPersistenceError) as exc_info:
        await engine.execute_task_definition(task_def, workflow_id=uuid.uuid4())

    assert "Durable execution recording failed" in str(exc_info.value)


@pytest.mark.asyncio
async def test_durability_policy_degraded_observable(tmp_path: Path):
    # Setup mock recorder that fails
    mock_recorder = MagicMock()
    mock_recorder.begin_execution.side_effect = RuntimeError("Transient network issue")

    config = ExecutionEngineConfig(
        durable_recorder=mock_recorder,
        durability_policy=DurabilityPolicy.DEGRADED,
    )
    env = WorkspaceEnvironment(tmp_path)
    engine = ExecutionEngine(environment=env, config=config)

    task_def = TaskDefinition(
        task_id="task-degraded",
        name="test-degraded",
        description="Testing degraded durability policy",
        task_type="coding",
    )

    result = await engine.execute_task_definition(task_def, workflow_id=uuid.uuid4())
    # Should observe DEGRADED status in metadata, not silent success
    assert task_def.metadata.get("durability_status") == "DEGRADED"
    assert "Transient network issue" in task_def.metadata.get("durability_error", "")


def test_artifact_disambiguation_not_found_vs_persistence_error():
    # 1. Genuine Not Found: catalog returns None -> get_artifact returns None
    mock_catalog_empty = MagicMock()
    mock_catalog_empty.get_artifact.return_value = None
    pipeline1 = ArtifactPipeline(durable_catalog=mock_catalog_empty)

    missing_id = uuid.uuid4()
    assert pipeline1.get_artifact(missing_id) is None

    # 2. Persistence Failure: catalog raises exception -> get_artifact raises ArtifactPersistenceError
    mock_catalog_broken = MagicMock()
    mock_catalog_broken.get_artifact.side_effect = RuntimeError("SQLite database is locked")
    pipeline2 = ArtifactPipeline(durable_catalog=mock_catalog_broken)

    with pytest.raises(ArtifactPersistenceError) as exc_info:
        pipeline2.get_artifact(missing_id)

    assert "Durable catalog error" in str(exc_info.value)
    assert "SQLite database is locked" in str(exc_info.value)
