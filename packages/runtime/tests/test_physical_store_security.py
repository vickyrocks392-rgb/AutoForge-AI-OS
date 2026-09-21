"""
Physical Artifact Store Security and Invariant Tests — Phase 18-K Remediation.
Proves root confinement, symlink escape rejection, quarantine confinement,
and integrity validation.
"""

from __future__ import annotations

import os
import tempfile
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
def store_env(tmp_path: Path):
    artifact_root = tmp_path / "artifacts"
    staging_root = tmp_path / "staging"
    quarantine_root = tmp_path / "quarantine"
    store = PhysicalArtifactStore(
        artifact_root=artifact_root,
        staging_root=staging_root,
        quarantine_root=quarantine_root,
    )
    return store, artifact_root, staging_root, quarantine_root, tmp_path


def test_path_traversal_double_dot(store_env):
    store, artifact_root, _, _, _ = store_env
    with pytest.raises(ArtifactPathViolationError):
        store.resolve_artifact_path("../../etc/passwd")

    with pytest.raises(ArtifactPathViolationError):
        store.resolve_staging_path("../outside.tmp")


def test_absolute_path_escape(store_env):
    store, _, _, _, tmp_path = store_env
    outside_file = tmp_path / "outside.txt"
    outside_file.write_text("external content")

    with pytest.raises(ArtifactPathViolationError):
        store.resolve_artifact_path(outside_file)

    with pytest.raises(ArtifactPathViolationError):
        store.resolve_staging_path(outside_file)


def test_symlink_escape(store_env):
    store, artifact_root, _, _, tmp_path = store_env
    outside_target = tmp_path / "secret.txt"
    outside_target.write_text("confidential")

    symlink_path = artifact_root / "symlink_escape.txt"
    try:
        os.symlink(outside_target, symlink_path)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    # Accessing symlink path via inspect_file should raise InvalidArtifactTypeError
    with pytest.raises(InvalidArtifactTypeError):
        store.inspect_file(symlink_path)


def test_atomic_publish_existing_symlink_rejected(store_env):
    store, artifact_root, staging_root, _, tmp_path = store_env
    outside_target = tmp_path / "overwrite_target.txt"
    outside_target.write_text("do not overwrite")

    symlink_path = artifact_root / "attack_link.txt"
    try:
        os.symlink(outside_target, symlink_path)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    stage_file = store.create_staging_file("art_1")
    c_hash, s_bytes = store.write_staging_text(stage_file, "malicious data")

    with pytest.raises(ArtifactPathViolationError):
        store.atomic_publish(stage_file, "attack_link.txt", expected_hash=c_hash, expected_size=s_bytes)

    # Outside target file must remain unmodified
    assert outside_target.read_text() == "do not overwrite"


def test_quarantine_outside_file_rejected(store_env):
    store, _, _, quarantine_root, tmp_path = store_env
    outside_file = tmp_path / "external_critical.txt"
    outside_file.write_text("system critical file")

    with pytest.raises(ArtifactPathViolationError):
        store.quarantine(outside_file, reason="Should be rejected")

    # File must still be in place
    assert outside_file.exists()


def test_quarantine_symlink_rejected(store_env):
    store, artifact_root, _, _, tmp_path = store_env
    internal_file = artifact_root / "real_file.txt"
    internal_file.write_text("valid data")
    symlink_in_root = artifact_root / "link_to_real.txt"
    try:
        os.symlink(internal_file, symlink_in_root)
    except OSError:
        pytest.skip("Symlinks not supported on this platform")

    with pytest.raises(ArtifactPathViolationError):
        store.quarantine(symlink_in_root, reason="Symlink quarantine attempt")


def test_quarantine_valid_staging_and_artifact(store_env):
    store, artifact_root, staging_root, quarantine_root, _ = store_env
    stage_file = store.create_staging_file("corrupt_art")
    store.write_staging_text(stage_file, "corrupt content")

    q_path = store.quarantine(stage_file, reason="Corrupted staging")
    assert q_path.exists()
    assert not stage_file.exists()
    assert q_path.parent == quarantine_root


def test_integrity_hash_and_size_mismatch(store_env):
    store, _, _, _, _ = store_env
    stage_file = store.create_staging_file("mismatch_test")
    c_hash, s_bytes = store.write_staging_text(stage_file, "sample text payload")

    # Wrong hash
    wrong_hash = "0" * 64
    with pytest.raises(ArtifactIntegrityMismatchError):
        store.validate_integrity(stage_file, expected_hash=wrong_hash, expected_size=s_bytes)

    # Wrong size
    with pytest.raises(ArtifactIntegrityMismatchError):
        store.validate_integrity(stage_file, expected_hash=c_hash, expected_size=s_bytes + 10)
