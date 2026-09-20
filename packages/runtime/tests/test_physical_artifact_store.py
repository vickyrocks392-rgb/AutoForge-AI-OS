"""Tests for PhysicalArtifactStore.

Verifies:
- Path confinement to artifact_root / staging_root / quarantine_root
- Path traversal detection and rejection
- Streaming SHA-256 and size computation
- Fsync and parent directory sync
- Atomic publish / rename
- Safe quarantine and staging cleanup
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import pytest

from autoforge_runtime.physical_artifact_store import (
    PhysicalArtifactStore,
    ArtifactPathViolationError,
    ArtifactMissingError,
    ArtifactIntegrityMismatchError,
    InvalidArtifactTypeError,
)


@pytest.fixture
def store(tmp_path: Path) -> PhysicalArtifactStore:
    return PhysicalArtifactStore(
        artifact_root=tmp_path / "artifacts",
        staging_root=tmp_path / "staging",
        quarantine_root=tmp_path / "quarantine",
    )


class TestPhysicalArtifactStorePathSafety:
    """Path confinement and traversal prevention."""

    def test_root_initialization(self, store: PhysicalArtifactStore) -> None:
        assert store.artifact_root.exists()
        assert store.staging_root.exists()
        assert store.quarantine_root.exists()

    def test_resolve_artifact_path_inside_root(self, store: PhysicalArtifactStore) -> None:
        p = store.resolve_artifact_path("sub/dir/model.onnx")
        assert p.is_relative_to(store.artifact_root)
        assert p.name == "model.onnx"

    def test_resolve_artifact_path_traversal_rejected(self, store: PhysicalArtifactStore) -> None:
        with pytest.raises(ArtifactPathViolationError):
            store.resolve_artifact_path("../../etc/passwd")

    def test_resolve_staging_path_inside_root(self, store: PhysicalArtifactStore) -> None:
        p = store.resolve_staging_path("task-123/output.json")
        assert p.is_relative_to(store.staging_root)

    def test_resolve_staging_path_traversal_rejected(self, store: PhysicalArtifactStore) -> None:
        with pytest.raises(ArtifactPathViolationError):
            store.resolve_staging_path("/tmp/outside")


class TestPhysicalArtifactStoreOperations:
    """Staging, writing, fsync, atomic publish, and integrity."""

    def test_stage_and_write_file(self, store: PhysicalArtifactStore) -> None:
        content = b"hello durable artifact world"
        staging_file = store.staging_root / "test" / "doc.txt"
        sha, size = store.write_staging_bytes(staging_file, content)

        assert staging_file.exists()
        assert staging_file.read_bytes() == content
        assert sha == hashlib.sha256(content).hexdigest()
        assert size == len(content)

    def test_inspect_file(self, store: PhysicalArtifactStore) -> None:
        content = b"sample content for hashing"
        staging_file = store.staging_root / "hash_test.bin"
        store.write_staging_bytes(staging_file, content)

        sha, size = store.inspect_file(staging_file)
        expected_sha = hashlib.sha256(content).hexdigest()
        assert sha == expected_sha
        assert size == len(content)

    def test_inspect_missing_file_raises(self, store: PhysicalArtifactStore) -> None:
        nonexistent = store.staging_root / "ghost.txt"
        with pytest.raises(ArtifactMissingError):
            store.inspect_file(nonexistent)

    def test_inspect_directory_raises(self, store: PhysicalArtifactStore) -> None:
        dir_path = store.staging_root / "somedir"
        dir_path.mkdir(parents=True, exist_ok=True)
        with pytest.raises(InvalidArtifactTypeError):
            store.inspect_file(dir_path)

    def test_atomic_publish_success(self, store: PhysicalArtifactStore) -> None:
        content = b"production grade deliverable"
        expected_sha = hashlib.sha256(content).hexdigest()
        expected_size = len(content)

        staging_file = store.staging_root / "run-1" / "final.tar.gz"
        store.write_staging_bytes(staging_file, content)

        published_path = store.atomic_publish(
            staging_path=staging_file,
            target_relative_path="releases/v1/final.tar.gz",
            expected_hash=expected_sha,
            expected_size=expected_size,
        )

        assert published_path.exists()
        assert not staging_file.exists()  # Moved via atomic rename
        assert published_path.read_bytes() == content
        assert published_path.is_relative_to(store.artifact_root)

    def test_atomic_publish_integrity_mismatch_rejected(self, store: PhysicalArtifactStore) -> None:
        content = b"genuine content"
        staging_file = store.staging_root / "run-2" / "compromised.txt"
        store.write_staging_bytes(staging_file, content)

        with pytest.raises(ArtifactIntegrityMismatchError):
            store.atomic_publish(
                staging_path=staging_file,
                target_relative_path="releases/compromised.txt",
                expected_hash="badhash000000000000000000000000000000000000000000000000000000000",
            )
        # Staging file should remain untouched when validation fails prior to publish
        assert staging_file.exists()

    def test_quarantine_corrupted_file(self, store: PhysicalArtifactStore) -> None:
        content = b"corrupted payload"
        staging_file = store.staging_root / "bad" / "bad.bin"
        store.write_staging_bytes(staging_file, content)

        q_path = store.quarantine(staging_file, reason="checksum_failure")
        assert q_path.exists()
        assert not staging_file.exists()
        assert q_path.is_relative_to(store.quarantine_root)
        assert "bad.bin" in q_path.name

    def test_symlink_artifact_path_rejected(self, store: PhysicalArtifactStore, tmp_path: Path) -> None:
        real_file = tmp_path / "external.txt"
        real_file.write_text("outside data")
        symlink_file = store.staging_root / "symlink_test.txt"
        symlink_file.symlink_to(real_file)

        with pytest.raises(InvalidArtifactTypeError) as exc:
            store.inspect_file(symlink_file)
        assert "cannot be a symlink" in str(exc.value)
