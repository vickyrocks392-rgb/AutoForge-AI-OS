"""Probe: does the same defect class affect the durable_bridge store_version path?"""

from __future__ import annotations

import sys
import tempfile
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _pkg in (
    "execution/src", "composition/src", "workflows/src", "ai_infrastructure/src",
    "runtime/src", "events/src", "event_platform/src", "kernel/src",
    "artifacts/src", "security/src", "models/src", "connectors/src",
    "memory/src", "knowledge_platform/src", "observability/src",
):
    _p = REPO / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from autoforge_artifacts.durable_bridge import DurableArtifactStoreBridge
from autoforge_artifacts.models import (
    Artifact,
    ArtifactVersion,
    CanonicalArtifactType,
)
from autoforge_runtime.artifact_catalog import DurableArtifactCatalog
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.physical_artifact_store import PhysicalArtifactStore


def main() -> int:
    tmp = Path(tempfile.mkdtemp(prefix="af_18j_bridge_"))
    store = PhysicalArtifactStore(
        artifact_root=tmp / "artifacts",
        staging_root=tmp / "artifacts" / ".staging",
        quarantine_root=tmp / "artifacts" / ".quarantine",
    )
    catalog = DurableArtifactCatalog(persistence=PersistenceLayer(), physical_store=store)
    bridge = DurableArtifactStoreBridge(catalog, store)

    art = bridge.create(
        Artifact(
            artifact_id=uuid.uuid4(),
            project_id=uuid.uuid4(),
            name="report.txt",
            artifact_type=CanonicalArtifactType.SOURCE,
        )
    )
    print("created artifact:", art.artifact_id)

    v1 = bridge.store_version(
        ArtifactVersion(artifact_id=art.artifact_id, version_number=1, content="hello")
    )
    print("v1 stored ->", catalog.get_artifact(v1.version_id).status.value)

    # Idempotent replay of the SAME logical version.
    try:
        v1_again = bridge.store_version(
            ArtifactVersion(artifact_id=art.artifact_id, version_number=1, content="hello")
        )
        print("v1 replay ->", catalog.get_artifact(v1_again.version_id).status.value)
        print("RESULT: no error")
    except Exception as exc:
        print("RESULT:", type(exc).__name__, "-", exc)

    # A genuinely new version (version 2).
    try:
        v2 = bridge.store_version(
            ArtifactVersion(artifact_id=art.artifact_id, version_number=2, content="hello v2")
        )
        print("v2 stored ->", catalog.get_artifact(v2.version_id).status.value)
    except Exception as exc:
        print("v2 RESULT:", type(exc).__name__, "-", exc)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
