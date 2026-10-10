"""Regression tests for ArtifactPackager — Gate D O-3 extraction (Category B).

Pins the extraction contract:
* real ``.tar.gz`` bytes on disk with the project's top-level members,
* single canonical registration via ``ArtifactManager`` (BUILD_OUTPUT),
* workspace-relative registered path (canonical store traversal guard),
* SHA-256 of the archive recorded in metadata,
* pure query for a project's packaged artifacts,
* no orchestration authority (missing dir -> FileNotFoundError, and the
  class exposes no lifecycle/dispatch/completion/retry surface).
"""

from __future__ import annotations

import tarfile
import uuid

import pytest

from autoforge_artifacts import (
    ArtifactPackager,
    CanonicalArtifactType,
    build_artifact_platform,
)


@pytest.fixture()
def packager() -> ArtifactPackager:
    platform = build_artifact_platform()
    return ArtifactPackager(platform.manager)


@pytest.fixture()
def project_dir(tmp_path):
    proj = tmp_path / "demo-proj"
    proj.mkdir()
    (proj / "app.py").write_text("print('hi')\n")
    (proj / "README.md").write_text("# demo\n")
    return proj


def test_pack_project_creates_tarball_and_registers_canonically(
    packager: ArtifactPackager, project_dir
) -> None:
    pid = uuid.uuid4()
    artifact, archive = packager.pack_project(project_dir, project_id=pid)

    assert archive.exists()
    assert archive.suffixes == [".tar", ".gz"]
    assert artifact.artifact_type == CanonicalArtifactType.BUILD_OUTPUT
    assert artifact.project_id == pid
    assert artifact.metadata["packaging"] == "tar.gz"
    assert artifact.metadata["content_sha256"]
    # Canonical store policy: workspace-relative path, never absolute.
    assert artifact.path == archive.name
    assert not artifact.path.startswith("/")

    with tarfile.open(archive, "r:gz") as tar:
        assert sorted(tar.getnames()) == ["README.md", "app.py"]


def test_pack_project_registers_archive_sha256(
    packager: ArtifactPackager, project_dir
) -> None:
    import hashlib

    artifact, archive = packager.pack_project(project_dir)

    assert artifact.metadata["content_sha256"] == hashlib.sha256(
        archive.read_bytes()
    ).hexdigest()


def test_get_packaged_artifacts_filters_build_output(
    packager: ArtifactPackager, project_dir
) -> None:
    pid = uuid.uuid4()
    packager.pack_project(project_dir, project_id=pid)

    found = packager.get_packaged_artifacts(pid)

    assert len(found) == 1
    assert found[0].artifact_type == CanonicalArtifactType.BUILD_OUTPUT
    assert packager.get_packaged_artifacts(uuid.uuid4()) == []


def test_pack_project_missing_directory_raises(
    packager: ArtifactPackager, tmp_path
) -> None:
    with pytest.raises(FileNotFoundError):
        packager.pack_project(tmp_path / "does-not-exist")


def test_packager_exposes_no_orchestration_authority(
    packager: ArtifactPackager,
) -> None:
    forbidden = {
        "execute", "dispatch", "complete", "progress", "retry",
        "remediate", "escalate", "route", "approve", "lifecycle",
        "transition", "validate_review",
    }
    surface = {m for m in dir(packager) if not m.startswith("_")}
    assert surface == {"pack_project", "get_packaged_artifacts"}
    assert not (surface & forbidden)
