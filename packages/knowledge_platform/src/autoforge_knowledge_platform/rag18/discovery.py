"""Phase 18-D — safe, deterministic, repository-aware source discovery.

Excludes secrets/build/venv/generated/binary content by default and indexes
only engineering knowledge sources: source code, Markdown, README, plain-text
and technical documentation.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)

DEFAULT_EXCLUDED_DIRS: frozenset[str] = frozenset({
    ".git",
    ".hg",
    ".svn",
    "node_modules",
    ".venv",
    "venv",
    "env",
    "ENV",
    "__pycache__",
    "build",
    "dist",
    "coverage",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    ".tox",
    ".nox",
    ".eggs",
    "*.egg-info",
    "site-packages",
    "node_modules",
    "out",
    "target",
    ".autoforge",
    ".DS_Store",
    "logs",
    "tmp",
    "temp",
    ".docusaurus",
    "htmlcov",
})

SECRET_FILE_MARKERS: tuple[str, ...] = (
    ".env",
    ".pem",
    ".key",
    ".p12",
    ".p8",
    "credentials",
    "secret",
    "token",
    "id_rsa",
    "id_ed25519",
    "keystore",
    "htpasswd",
)

ALLOWED_SOURCE_EXTENSIONS: frozenset[str] = frozenset({
    # Source code
    ".py", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs",
    ".go", ".rs", ".java", ".rb", ".php", ".c", ".h", ".cpp",
    ".hpp", ".cs", ".swift", ".kt", ".kts", ".sh", ".sql",
    ".scala", ".ex", ".exs",
    # Documentation / markdown / plain text
    ".md", ".markdown", ".mdx", ".txt", ".rst", ".adoc", ".text",
})


@dataclass(frozen=True)
class SourceCandidate:
    """A discovered, validated source file."""

    relative_path: str
    absolute_path: str
    size_bytes: int


class SourceDiscovery:
    """Deterministic walker over a repository root."""

    def __init__(
        self,
        *,
        excluded_dirs: frozenset[str] = DEFAULT_EXCLUDED_DIRS,
        allowed_extensions: frozenset[str] = ALLOWED_SOURCE_EXTENSIONS,
        max_file_bytes: int = 512_000,
    ) -> None:
        self._excluded_dirs = excluded_dirs
        self._allowed_extensions = allowed_extensions
        self._max_file_bytes = max_file_bytes

    @property
    def allowed_extensions(self) -> frozenset[str]:
        return self._allowed_extensions

    @property
    def excluded_dirs(self) -> frozenset[str]:
        return self._excluded_dirs

    @property
    def max_file_bytes(self) -> int:
        return self._max_file_bytes

    def _is_excluded_dir(self, name: str) -> bool:
        if name in self._excluded_dirs:
            return True
        if name.endswith(".egg-info"):
            return True
        if name in {".", ".."}:
            return False
        return name.startswith(".")

    def _looks_like_secret(self, filename: str) -> bool:
        lowered = filename.lower()
        return any(marker in lowered for marker in SECRET_FILE_MARKERS)

    def discover(self, root: str | Path) -> list[SourceCandidate]:
        """Discover validated candidates, deterministic (sorted by path)."""
        root_path = Path(root).resolve()
        candidates: list[SourceCandidate] = []

        for dirpath, dirnames, filenames in root_path.walk():
            # Prune excluded directories in place (deterministic).
            kept_dirs: list[str] = []
            for d in sorted(dirnames):
                if not self._is_excluded_dir(d):
                    kept_dirs.append(d)
            dirnames[:] = kept_dirs

            for filename in sorted(filenames):
                if self._looks_like_secret(filename):
                    continue
                suffix = Path(filename).suffix.lower()
                if suffix not in self._allowed_extensions:
                    continue
                full = Path(dirpath) / filename
                try:
                    size = full.stat().st_size
                    if size > self._max_file_bytes:
                        logger.debug("Skipping oversized source: %s (%d bytes)", full, size)
                        continue
                    if size == 0:
                        continue
                    if self._is_binary(full):
                        logger.debug("Skipping binary-looking source: %s", full)
                        continue
                except OSError:
                    continue
                rel = full.relative_to(root_path).as_posix()
                candidates.append(
                    SourceCandidate(
                        relative_path=rel,
                        absolute_path=str(full),
                        size_bytes=size,
                    )
                )

        return candidates

    @staticmethod
    def _is_binary(path: Path) -> bool:
        try:
            with open(path, "rb") as handle:
                head = handle.read(1024)
        except OSError:
            return True
        return b"\x00" in head