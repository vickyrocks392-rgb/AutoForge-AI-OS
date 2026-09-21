"""
Canonical Durable Artifacts Integration Tests — Phase 18-K Remediation (Part 4).

Proves that build_autoforge_system wires:
  Runtime Persistence -> Durable Artifact Catalog -> Physical Artifact Store
  -> Durable Artifact Store Bridge -> Artifact Pipeline -> Execution Engine
  and Artifact Platform.
"""

from __future__ import annotations

import sys
import uuid
from pathlib import Path
import pytest

from autoforge_composition import build_autoforge_system
from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore
from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge
from autoforge_workflows.models import TaskDefinition, WorkflowDefinition


@pytest.mark.asyncio
async def test_canonical_durable_artifact_wiring(tmp_path: Path):
    # 1. Construct canonical system via build_autoforge_system
    system = build_autoforge_system(workspace_root=str(tmp_path))

    # Regression assertion: MUST fail if composition root reverts to in-memory defaults
    assert system.durable_catalog is not None, "durable_catalog missing from AutoForgeSystem"
    assert isinstance(system.durable_catalog, DurableArtifactCatalog)
    assert system.physical_store is not None, "physical_store missing from AutoForgeSystem"
    assert isinstance(system.physical_store, PhysicalArtifactStore)
    assert system.artifact_bridge is not None, "artifact_bridge missing from AutoForgeSystem"
    assert isinstance(system.artifact_bridge, DurableArtifactStoreBridge)

    # Prove ExecutionEngine pipeline has durable dependencies attached
    pipeline = system.execution_engine._artifacts
    assert pipeline._durable_catalog is system.durable_catalog
    assert pipeline._physical_store is system.physical_store

    # Prove ArtifactPlatform is wired to the DurableArtifactStoreBridge
    assert system.artifact_platform.store is system.artifact_bridge

    # 2. Execute a task that produces an artifact
    task_def = TaskDefinition(
        task_id="t-artifact-durable",
        name="Generate File",
        task_type="coding",
        input_data={
            "files": [{"path": "hello.py", "content": "print('hello durable world')\n"}],
            "commands": [[sys.executable, "hello.py"]],
        },
    )
    workflow_def = WorkflowDefinition(
        name="Artifact Verification Workflow",
        tasks=[task_def],
    )
    handle = system.workflow_engine.submit(workflow_def)

    completed = await system.execution_engine.run_workflow_to_completion(handle)
    status_str = str(getattr(completed.status, "value", completed.status))
    assert status_str in {"completed", "passed", "finished"}

    # 3. Verify artifact produced
    task_artifacts = pipeline.get_artifacts_for_task("t-artifact-durable")
    assert len(task_artifacts) > 0
    art = task_artifacts[0]
    art_id = art.artifact_id

    # 4. Prove DurableArtifactCatalog contains the artifact metadata
    catalog_state = system.durable_catalog.get_artifact(art_id)
    assert catalog_state is not None
    assert catalog_state.artifact_id == art_id
    assert catalog_state.content_hash == art.checksum
    assert catalog_state.size_bytes == art.size_bytes
    assert catalog_state.status.value == "committed"

    # 5. Prove PhysicalArtifactStore contains the physical file
    assert catalog_state.storage_path is not None
    physical_path = Path(catalog_state.storage_path)
    assert physical_path.exists()
    assert physical_path.is_file()

    # 6. Verify physical hash and size match metadata
    actual_hash, actual_size = system.physical_store.inspect_file(physical_path)
    assert actual_hash == art.checksum
    assert actual_size == art.size_bytes

    # 7. Prove ArtifactPlatform resolves the exact same durable artifact identity
    platform_art = system.artifact_platform.manager.get_artifact(art_id)
    assert platform_art is not None
    assert platform_art.artifact_id == art_id

    # 8. Prove fresh pipeline (surviving beyond in-memory object) retrieves from catalog
    fresh_pipeline = system.execution_engine._artifacts.__class__(
        durable_catalog=system.durable_catalog,
        physical_store=system.physical_store,
    )
    recovered_record = fresh_pipeline.get_artifact(art_id)
    assert recovered_record is not None
    assert recovered_record.artifact_id == art_id
    assert recovered_record.checksum == art.checksum
    assert recovered_record.content == art.content
