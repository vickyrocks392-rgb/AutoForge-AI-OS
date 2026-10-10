"""
Artifact Packager — O-3 capability extraction (Gate D, Category B: UNIQUE REUSABLE).

Extracts the one genuinely reusable O-3 behavior — creating ``.tar.gz``
distribution archives from a built project directory — into the canonical
Artifact Platform boundary (``packages/artifacts``).

Pure delegation capability: callers hand it a built project directory;
it produces tarball bytes on disk and registers the result with the
canonical ``ArtifactManager``. It never decides *which* project to
package, *when*, or *what happens next* (no lifecycle progression, no
dispatch, no completion, no retry). Registration goes through
``ArtifactManager.create_artifact`` — there is no second artifact
authority here. It never shapes HTTP/API contracts.

O-3 provenance: ``AutonomousBuildEngine.execute_build`` packaging block
(``apps/api/src/autoforge_api/build_engine.py``, "Physical Delivery
Package Generation"): sandbox creation, toolchain discovery, ``tarfile``
archive creation, ``art-dist``/``art-src`` entries, sizes, delivery
paths. Only the mechanical archive creation + canonical registration is
extracted. All orchestration around it stays quarantined in O-3.
"""

from __future__ import annotations

import hashlib
import logging
import shutil
import tarfile
import tempfile
import uuid
from pathlib import Path
from typing import Any

from autoforge_artifacts.engine import ArtifactManager
from autoforge_artifacts.models import (
    Artifact,
    CanonicalArtifactType,
)

logger = logging.getLogger(__name__)


class ArtifactPackager:
    """Create ``.tar.gz`` distribution archives and register them canonically.

    Pure capability — packaging decisions and routing belong to the
    canonical orchestration layer (Kernel, O-2).
    """

    def __init__(self, manager: ArtifactManager) -> None:
        self._manager = manager


    # ── Public capability ─────────────────────────────────────────────

    def pack_project(
        self,
        project_path: str | Path,
        *,
        archive_name: str | None = None,
        project_id: uuid.UUID | None = None,
        workflow_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        created_by: str = "artifact-packager",
        metadata: dict[str, Any] | None = None,
    ) -> tuple[Artifact, Path]:
        """Package a built project directory into a ``.tar.gz`` artifact.

        Returns ``(artifact, archive_path)`` — the canonical ``Artifact``
        registration and the ``.tar.gz`` written next to the project dir.
        Raises ``FileNotFoundError`` if ``project_path`` is not a dir;
        canonical validation errors propagate unchanged.
        """
        source = Path(project_path)
        if not source.is_dir():
            raise FileNotFoundError(
                f"Cannot package project: not a directory: {source}"
            )

        name = archive_name or f"{source.name}.tar.gz"
        if not name.endswith(".tar.gz"):
            name = f"{name}.tar.gz"
        archive_path = source.parent / name

        # Canonical store policy (_validate_path): workspace-relative paths
        # only — absolute paths are rejected as a traversal guard. Register
        # the archive relative to the project parent; the caller still gets
        # the absolute path back for filesystem use.
        try:
            registered_path = str(archive_path.relative_to(source.parent))
        except ValueError:
            registered_path = archive_path.name

        record_meta: dict[str, Any] = {
            "packaging": "tar.gz",
            "source_directory": str(source),
            # Created by _create_archive immediately below (metadata holds a
            # copy of the archive's own SHA-256 for offline verification).
            "content_sha256": self._create_archive(source, archive_path),
        }
        if metadata:
            record_meta.update(metadata)

        # Single registration authority: ArtifactManager.create_artifact.
        # No second registration, versioning, or state transition here.
        artifact = self._manager.create_artifact(
            name=name,
            artifact_type=CanonicalArtifactType.BUILD_OUTPUT,
            project_id=project_id,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            created_by=created_by,
            path=registered_path,
            metadata=record_meta,
        )

        logger.info(
            "Packaged project %s into %s (artifact %s)",
            source,
            archive_path,
            artifact.artifact_id,
        )
        return artifact, archive_path

    # ── Mechanical helpers (no authority) ─────────────────────────────

    @staticmethod
    def _create_archive(source: Path, archive_path: Path) -> str:
        """Write ``source/`` as ``archive_path`` (.tar.gz); return SHA-256."""
        import os

        tmp_fd, tmp_name = tempfile.mkstemp(
            prefix=f".{archive_path.name}.", suffix=".part"
        )
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)
        try:
            with tarfile.open(tmp_path, "w:gz") as tar:
                for child in sorted(source.iterdir()):
                    tar.add(child, arcname=child.name, recursive=True)
            content_hash = ArtifactPackager._sha256_file(tmp_path)
            shutil.move(str(tmp_path), str(archive_path))
        finally:
            if tmp_path.exists():
                tmp_path.unlink()
        return content_hash

    @staticmethod
    def _sha256_file(path: Path) -> str:
        """Compute SHA-256 checksum of a file."""
        sha256 = hashlib.sha256()
        with path.open("rb") as f:
            for chunk in iter(lambda: f.read(1024 * 64), b""):
                sha256.update(chunk)
        return sha256.hexdigest()

    def get_packaged_artifacts(
        self, project_id: uuid.UUID
    ) -> list[Artifact]:
        """List packaged (``BUILD_OUTPUT``) artifacts for a project."""
        return [
            a
            for a in self._manager.list_artifacts(project_id=project_id)
            if a.artifact_type == CanonicalArtifactType.BUILD_OUTPUT
        ]