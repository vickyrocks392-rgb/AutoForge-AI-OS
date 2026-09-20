"""Physical Artifact Store — Phase 18-K Runtime Hardening.

Owns the physical filesystem boundary for AutoForge artifacts:
- Confined path derivation for artifact, staging, and quarantine directories
- Staging file creation, synchronous writes, flush and fsync
- Atomic rename / publish with parent-directory fsync
- Streaming SHA-256 and size verification
- Quarantine of invalid, corrupted, or orphaned artifacts
- Safe cleanup of staging files

The physical artifact store is purely a filesystem boundary manager:
all authoritative lifecycle state belongs exclusively to DurableArtifactCatalog.
"""

from __future__ import annotations

import hashlib
import logging
import os
import shutil
import uuid
from pathlib import Path
from typing import Any

from autoforge_runtime.exceptions import (
    PersistenceError,
)

logger = logging.getLogger("autoforge.runtime.physical_artifact_store")


# ── Exceptions ────────────────────────────────────────────────────────────


class ArtifactStorageException(PersistenceError):
    """Base exception for physical artifact storage operations."""


class ArtifactPathViolationError(ArtifactStorageException):
    """Raised when an artifact path escapes the allowed directory boundary."""


class ArtifactMissingError(ArtifactStorageException):
    """Raised when the expected physical artifact file does not exist."""


class ArtifactIntegrityMismatchError(ArtifactStorageException):
    """Raised when an artifact's physical hash or size does not match expectations."""


class InvalidArtifactTypeError(ArtifactStorageException):
    """Raised when an artifact is not a regular file (e.g., directory, socket, fifo)."""


# ── Physical Artifact Store ──────────────────────────────────────────────


class PhysicalArtifactStore:
    """Manages the physical filesystem boundary for artifacts.

    Enforces strict path confinement under ``artifact_root``, isolates
    in-progress writes to ``staging_root``, and safely moves corrupted or
    suspicious files to ``quarantine_root``.
    """

    CHUNK_SIZE = 64 * 1024  # 64 KB streaming buffer

    def __init__(
        self,
        artifact_root: str | Path,
        *,
        staging_root: str | Path | None = None,
        quarantine_root: str | Path | None = None,
    ) -> None:
        self._artifact_root = Path(artifact_root).resolve()
        self._staging_root = (
            Path(staging_root).resolve()
            if staging_root is not None
            else (self._artifact_root / ".staging").resolve()
        )
        self._quarantine_root = (
            Path(quarantine_root).resolve()
            if quarantine_root is not None
            else (self._artifact_root / ".quarantine").resolve()
        )

        # Ensure roots exist
        self._artifact_root.mkdir(parents=True, exist_ok=True)
        self._staging_root.mkdir(parents=True, exist_ok=True)
        self._quarantine_root.mkdir(parents=True, exist_ok=True)

    @property
    def artifact_root(self) -> Path:
        return self._artifact_root

    @property
    def staging_root(self) -> Path:
        return self._staging_root

    @property
    def quarantine_root(self) -> Path:
        return self._quarantine_root

    # ── Path Confinement ──────────────────────────────────────────────────

    def resolve_artifact_path(self, rel_or_abs_path: str | Path) -> Path:
        """Resolve and verify a path is safely confined within artifact_root.

        Raises:
            ArtifactPathViolationError: If the resolved path escapes artifact_root.
        """
        p = Path(rel_or_abs_path)
        target = p.resolve() if p.is_absolute() else (self._artifact_root / p).resolve()
        if not target.is_relative_to(self._artifact_root):
            raise ArtifactPathViolationError(
                f"Artifact path traversal detected: '{rel_or_abs_path}' escapes root '{self._artifact_root}'",
                details={
                    "requested_path": str(rel_or_abs_path),
                    "artifact_root": str(self._artifact_root),
                },
            )
        return target

    def resolve_staging_path(self, rel_or_abs_path: str | Path) -> Path:
        """Resolve and verify a path is safely confined within staging_root.

        Raises:
            ArtifactPathViolationError: If the resolved path escapes staging_root.
        """
        p = Path(rel_or_abs_path)
        target = p.resolve() if p.is_absolute() else (self._staging_root / p).resolve()
        if not target.is_relative_to(self._staging_root):
            raise ArtifactPathViolationError(
                f"Staging path traversal detected: '{rel_or_abs_path}' escapes staging root '{self._staging_root}'",
                details={
                    "requested_path": str(rel_or_abs_path),
                    "staging_root": str(self._staging_root),
                },
            )
        return target

    # ── Staging Operations ────────────────────────────────────────────────

    def create_staging_file(
        self,
        artifact_key: str,
        *,
        suffix: str = ".tmp",
    ) -> Path:
        """Create a new unique staging file path inside staging_root."""
        key_hash = hashlib.sha256(artifact_key.encode("utf-8")).hexdigest()[:16]
        filename = f"stage_{key_hash}_{uuid.uuid4().hex[:8]}{suffix}"
        staging_file = self._staging_root / filename
        return staging_file

    def write_staging_bytes(
        self,
        staging_path: Path | str,
        data: bytes,
    ) -> tuple[str, int]:
        """Write raw bytes to a staging file with flush and fsync.

        Returns:
            Tuple of (sha256_hex_digest, size_in_bytes).
        """
        resolved = self.resolve_staging_path(staging_path)
        resolved.parent.mkdir(parents=True, exist_ok=True)

        hasher = hashlib.sha256()
        with open(resolved, "wb") as f:
            f.write(data)
            f.flush()
            os.fsync(f.fileno())
            hasher.update(data)

        size = len(data)
        self._sync_directory(resolved.parent)
        return hasher.hexdigest(), size

    def write_staging_text(
        self,
        staging_path: Path | str,
        text: str,
        *,
        encoding: str = "utf-8",
    ) -> tuple[str, int]:
        """Write text to a staging file with flush and fsync."""
        return self.write_staging_bytes(staging_path, text.encode(encoding))

    # ── Inspection & Validation ───────────────────────────────────────────

    def inspect_file(self, path: Path | str) -> tuple[str, int]:
        """Verify file existence and regular file type, then compute SHA-256 and size.

        Returns:
            Tuple of (sha256_hex_digest, size_in_bytes).

        Raises:
            ArtifactMissingError: If file does not exist.
            InvalidArtifactTypeError: If path is not a regular file.
        """
        p = Path(path)
        if p.is_symlink():
            raise InvalidArtifactTypeError(
                f"Artifact path cannot be a symlink: {p}",
                details={"path": str(p)},
            )
        if not p.exists():
            raise ArtifactMissingError(
                f"Artifact file missing: {p}",
                details={"path": str(p)},
            )
        if not p.is_file():
            raise InvalidArtifactTypeError(
                f"Artifact path is not a regular file: {p}",
                details={"path": str(p)},
            )

        hasher = hashlib.sha256()
        size = 0
        with open(p, "rb") as f:
            while chunk := f.read(self.CHUNK_SIZE):
                hasher.update(chunk)
                size += len(chunk)
        return hasher.hexdigest(), size

    def validate_integrity(
        self,
        path: Path | str,
        *,
        expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> tuple[str, int]:
        """Inspect file and assert that hash and size match expectations.

        Raises:
            ArtifactMissingError: If file does not exist.
            InvalidArtifactTypeError: If not a regular file.
            ArtifactIntegrityMismatchError: If hash or size disagree.
        """
        actual_hash, actual_size = self.inspect_file(path)

        if expected_size is not None and actual_size != expected_size:
            raise ArtifactIntegrityMismatchError(
                f"Artifact size mismatch for {path}: expected {expected_size} bytes, got {actual_size}",
                details={
                    "path": str(path),
                    "expected_size": expected_size,
                    "actual_size": actual_size,
                },
            )

        if expected_hash and actual_hash.lower() != expected_hash.lower():
            raise ArtifactIntegrityMismatchError(
                f"Artifact hash mismatch for {path}: expected {expected_hash}, got {actual_hash}",
                details={
                    "path": str(path),
                    "expected_hash": expected_hash,
                    "actual_hash": actual_hash,
                },
            )

        return actual_hash, actual_size

    # ── Atomic Publish ────────────────────────────────────────────────────

    def atomic_publish(
        self,
        staging_path: Path | str,
        target_relative_path: Path | str,
        *,
        expected_hash: str | None = None,
        expected_size: int | None = None,
    ) -> Path:
        """Validate staging file, atomically publish to target under artifact_root, and fsync.

        Returns:
            The resolved target Path.

        Raises:
            ArtifactMissingError: If staging file missing.
            ArtifactIntegrityMismatchError: If content check fails.
            ArtifactPathViolationError: If target escapes artifact_root.
        """
        staged = self.resolve_staging_path(staging_path)
        actual_hash, actual_size = self.validate_integrity(
            staged,
            expected_hash=expected_hash,
            expected_size=expected_size,
        )

        target = self.resolve_artifact_path(target_relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)

        # Atomic replace on POSIX / Windows
        os.replace(staged, target)

        # Sync target parent directory to ensure directory entry is durable
        self._sync_directory(target.parent)
        logger.debug("Atomically published %s -> %s (hash=%s)", staged, target, actual_hash)
        return target

    # ── Quarantine & Cleanup ──────────────────────────────────────────────

    def quarantine(self, path: Path | str, reason: str = "") -> Path:
        """Safely move an invalid, corrupted, or orphaned artifact to quarantine_root."""
        src = Path(path)
        if not src.exists():
            raise ArtifactMissingError(f"Cannot quarantine nonexistent file: {src}")

        q_name = f"quarantine_{uuid.uuid4().hex[:12]}_{src.name}"
        q_target = self._quarantine_root / q_name
        shutil.move(src, q_target)
        self._sync_directory(self._quarantine_root)
        logger.warning("Quarantined artifact %s -> %s (reason: %s)", src, q_target, reason)
        return q_target

    def cleanup_staging(self, staging_path: Path | str) -> bool:
        """Remove a staging file safely if it exists."""
        try:
            p = self.resolve_staging_path(staging_path)
            if p.is_file():
                p.unlink()
                return True
        except Exception as e:
            logger.warning("Failed to cleanup staging file %s: %e", staging_path, e)
        return False

    # ── Helper ────────────────────────────────────────────────────────────

    @staticmethod
    def _sync_directory(dir_path: Path) -> None:
        """Flush directory entry changes to durable media where supported."""
        try:
            if hasattr(os, "O_DIRECTORY"):
                fd = os.open(dir_path, os.O_RDONLY | os.O_DIRECTORY)
            else:
                fd = os.open(dir_path, os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            # Some platforms / filesystems do not support fsync on directory fds
            pass
