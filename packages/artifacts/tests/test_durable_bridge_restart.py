"""
Tests for DurableArtifactStoreBridge Restart and Reconstruction (Phase 18-K Part 13).
Verifies that versions, artifacts, and physical integrity survive process restarts
and are successfully reconstructed from DurableArtifactCatalog and PhysicalArtifactStore.
"""

from __future__ import annotations

import tempfile
import uuid
from pathlib import Path
import pytest

from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore
from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge
from autoforge_artifacts.models import Artifact, ArtifactVersion, CanonicalArtifactType


@pytest.fixture
def bridge_env(tmp_path: Path):
    db_path = tmp_path / "runtime.db"
    persistence = PersistenceLayer(db_path=db_path)

    art_root = tmp_path / "artifacts"
    store = PhysicalArtifactStore(artifact_root=art_root)
    catalog = DurableArtifactCatalog(persistence=persistence, physical_store=store)
    bridge = DurableArtifactStoreBridge(catalog=catalog, physical_store=store)

    return bridge, catalog, store, persistence, art_root, db_path


def test_durable_bridge_restart_reconstruction(bridge_env):
    bridge1, catalog1, store1, persistence1, art_root, db_path = bridge_env

    # 1. Create artifact and store versions
    project_id = uuid.uuid4()
    art = Artifact(
        project_id=project_id,
        name="main.py",
        artifact_type=CanonicalArtifactType.SOURCE,
    )
    registered = bridge1.create(art)

    v1 = ArtifactVersion(
        artifact_id=registered.artifact_id,
        version_number=1,
        content="print('Hello v1')",
    )
    stored_v1 = bridge1.store_version(v1)

    v2 = ArtifactVersion(
        artifact_id=registered.artifact_id,
        version_number=2,
        content="print('Hello v2')",
        parent_version_id=stored_v1.version_id,
    )
    stored_v2 = bridge1.store_version(v2)

    # Verify initial integrity
    assert bridge1.verify_integrity(registered.artifact_id, stored_v1.version_id)
    assert bridge1.verify_integrity(registered.artifact_id, stored_v2.version_id)

    # 2. Simulate Process Restart: Instantiate completely fresh catalog & bridge from same DB and files
    persistence2 = PersistenceLayer(db_path=db_path)
    store2 = PhysicalArtifactStore(artifact_root=art_root)
    catalog2 = DurableArtifactCatalog(persistence=persistence2, physical_store=store2)
    bridge2 = DurableArtifactStoreBridge(catalog=catalog2, physical_store=store2)

    # In bridge2, memory caches are completely empty
    assert len(bridge2._artifacts) == 0
    assert len(bridge2._versions) == 0

    # 3. Reconstruct artifact from durable catalog
    reconstructed_art = bridge2.get(registered.artifact_id)
    assert reconstructed_art is not None
    assert reconstructed_art.name == "main.py"
    assert reconstructed_art.artifact_id == registered.artifact_id

    # 4. Reconstruct versions from durable catalog and disk
    versions = bridge2.list_versions(registered.artifact_id)
    assert len(versions) >= 2

    latest_v = bridge2.get_latest_version(registered.artifact_id)
    assert latest_v is not None
    assert latest_v.version_number == 2
    assert "Hello v2" in latest_v.content

    v1_reconstructed = bridge2.get_version(registered.artifact_id, stored_v1.version_id)
    assert v1_reconstructed is not None
    assert "Hello v1" in v1_reconstructed.content

    # 5. Verify physical integrity matches on the reconstructed bridge
    assert bridge2.verify_integrity(registered.artifact_id, stored_v1.version_id)
    assert bridge2.verify_integrity(registered.artifact_id, stored_v2.version_id)
