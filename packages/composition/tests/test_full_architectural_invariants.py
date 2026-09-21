"""
Composition Regression Tests: Full Architectural Invariant Test (Part 16).

Verifies the canonical system graph:
Canonical Composition Root
    |
    +--> Kernel
    |
    +--> Strategic Engine
    |
    +--> Planning Coordinator
    |
    +--> Workflow Engine
    |
    +--> Execution Engine
    |       |
    |       +--> EngineeringContextBuilder
    |       |
    |       +--> Durable Artifact Pipeline
    |               |
    |               +--> DurableArtifactCatalog
    |               +--> PhysicalArtifactStore
    |
    +--> Review Engine
    |
    +--> Memory Engine
    |
    +--> Knowledge Engine
    |
    +--> EngineeringLearningEngine
    |
    +--> Model Router
    |
    +--> Artifact Platform
            |
            +--> DurableArtifactStoreBridge

Verifies actual object relationships, identity references, and observable behaviors,
not solely class names.
"""

from __future__ import annotations

from pathlib import Path
import uuid
import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_kernel.kernel import Kernel
from autoforge_kernel.learning_engine import EngineeringLearningEngine
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore
from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge


@pytest.mark.asyncio
async def test_full_canonical_system_graph_invariants(tmp_path: Path):
    system = build_autoforge_system(workspace_root=str(tmp_path))

    # 1. Canonical Root & Kernel
    assert system.kernel is not None
    assert isinstance(system.kernel, Kernel)

    # 2. Kernel Engine Dependencies (Injected, not disconnected)
    assert system.kernel.strategic_engine is system.strategic_engine
    assert system.kernel.workflow_engine is not None
    assert system.kernel.execution_engine is not None
    assert system.kernel.review_engine is not None
    assert system.kernel.model_router is not None
    assert system.kernel.planning_coordinator is system.planning_coordinator

    # 3. Memory & Knowledge Engine Invariants
    assert system.kernel.memory_engine is not None
    assert system.kernel.knowledge_engine is not None

    # 4. Learning Engine Invariant
    assert system.learning_engine is not None
    assert isinstance(system.learning_engine, EngineeringLearningEngine)
    assert system.kernel.learning_engine is system.learning_engine
    assert system.learning_engine.memory_engine is system.kernel.memory_engine
    assert system.learning_engine.knowledge_engine is system.kernel.knowledge_engine

    # 5. Execution Engine Graph & Context Builder
    assert system.execution_engine is not None
    assert system.context_builder is not None
    assert isinstance(system.context_builder, EngineeringContextBuilder)
    assert system.execution_engine._dispatcher._context_builder is system.context_builder

    # 6. Durable Artifact Infrastructure Invariants
    assert system.durable_catalog is not None
    assert isinstance(system.durable_catalog, DurableArtifactCatalog)
    assert system.physical_store is not None
    assert isinstance(system.physical_store, PhysicalArtifactStore)
    assert system.artifact_bridge is not None
    assert isinstance(system.artifact_bridge, DurableArtifactStoreBridge)

    # Durable catalog is wired to the runtime persistence layer and the physical store
    assert system.durable_catalog.physical_store is system.physical_store
    assert system.durable_catalog._persistence is system.runtime.persistence

    # Bridge is wired to the same durable catalog and physical store
    assert system.artifact_bridge.catalog is system.durable_catalog
    assert system.artifact_bridge.physical_store is system.physical_store

    # Execution Engine's Artifact Pipeline uses the durable catalog & physical store
    execution_pipeline = system.execution_engine._artifacts
    assert execution_pipeline._durable_catalog is system.durable_catalog
    assert execution_pipeline._physical_store is system.physical_store

    # Artifact Platform uses the DurableArtifactStoreBridge
    assert system.artifact_platform.store is system.artifact_bridge

    # 7. Functional verification: Shared artifact identity across subsystems
    # Create an artifact in bridge and store version
    from autoforge_artifacts.models import Artifact, ArtifactVersion, CanonicalArtifactType

    proj_id = uuid.uuid4()
    art = Artifact(
        project_id=proj_id,
        name="graph_invariant.txt",
        artifact_type=CanonicalArtifactType.DOCUMENTATION,
    )
    created_art = system.artifact_bridge.create(art)
    version = ArtifactVersion.create(
        artifact_id=created_art.artifact_id,
        version_number=1,
        content="System Graph Invariant Proof",
        created_by="system_test",
    )
    stored_ver = system.artifact_bridge.store_version(version)
    artifact_id = created_art.artifact_id

    # Catalog contains the durable state
    catalog_state = system.durable_catalog.get_artifact(stored_ver.version_id)
    assert catalog_state is not None
    assert catalog_state.storage_path is not None
    assert Path(catalog_state.storage_path).is_file()

    # Artifact Platform resolves the exact same artifact
    platform_art = system.artifact_platform.manager.get_artifact(artifact_id)
    assert platform_art is not None
    assert platform_art.artifact_id == artifact_id

    # Pipeline resolves the durable version from the catalog
    pipeline_art = execution_pipeline.get_artifact(stored_ver.version_id)
    assert pipeline_art is not None
    assert pipeline_art.artifact_id == stored_ver.version_id
    assert pipeline_art.content == "System Graph Invariant Proof"
