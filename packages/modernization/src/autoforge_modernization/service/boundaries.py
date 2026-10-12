"""Phase 20 customer-output boundary and project isolation.

This module is the *mechanical* form of the Phase 20 hard architectural
invariant:

    No customer legacy code and no customer modernized code may ever mix with
    AutoForge's own source code.

A code review cannot enforce that, so it is enforced here as an importable,
testable guard. Every path that customer material touches -- intake staging,
transformation output, validation scratch space, delivery packaging, artifact
resolution -- is resolved through :class:`CustomerBoundary`.

Design rules
------------
1. **Fail closed.** Every check raises :class:`BoundaryViolation`. There is no
   permissive mode that silently downgrades a violation to a warning.
2. **Resolve before compare.** Every containment test runs on
   ``Path.resolve()`` results, so ``..`` segments, absolute paths and symlink
   escapes cannot step outside a boundary.
3. **Exact directory name.** The boundary is ``Modernization Output`` (single
   space, capital M, capital O). The name is a constant, never caller-supplied.
4. **One project, one guard.** :class:`ProjectAccessGuard` binds a caller to a
   single ``project_id`` and refuses every access naming another project.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

__all__ = [
    "AUTOFORGE_OWNED_SOURCE_DIRS",
    "CUSTOMER_OUTPUT_DIRNAME",
    "LEGACY_SOURCE_DIRNAME",
    "MODERNIZED_APP_DIRNAME",
    "PROJECT_ID_RE",
    "BoundaryViolation",
    "CustomerBoundary",
    "ProjectAccessGuard",
    "discover_project_ids",
    "is_within",
    "iter_boundary_files",
]

#: The customer delivery boundary. Exact capitalization is part of the contract.
CUSTOMER_OUTPUT_DIRNAME = "Modernization Output"

#: Directory names inside a customer project (Phase 20 section 12).
LEGACY_SOURCE_DIRNAME = "legacy-source"
MODERNIZED_APP_DIRNAME = "modernized-application"

#: AutoForge-owned top-level directories that must never contain customer code.
#: These are Domain A. ``Modernization Output`` is Domain B and is deliberately
#: absent from this tuple.
AUTOFORGE_OWNED_SOURCE_DIRS: tuple[str, ...] = (
    "packages",
    "apps",
    "services",
    "src",
    "tests",
    "docs",
    "scripts",
    "examples",
    "fixtures",
    "tools",
    "build",
    "docker",
)

#: A project id is a conservative, path-safe token: it becomes a directory name
#: and is embedded in delivery manifests, so it must not escape the boundary.
PROJECT_ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")

#: A single path segment inside the customer project.
_SEGMENT_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}$")

#: Names that must never appear as a path segment inside the boundary: classic
#: traversal spellings plus Windows device names. Rejecting device names keeps
#: the boundary portable and stops a payload staged on one OS from being
#: reinterpreted on another.
_FORBIDDEN_SEGMENTS = frozenset(
    {"..", ".", ""} | {f"com{i}" for i in range(1, 10)} | {f"lpt{i}" for i in range(1, 10)}
    | {"con", "prn", "aux", "nul"}
)


class BoundaryViolation(RuntimeError):
    """Raised when a path or access would breach the Domain A / Domain B split.

    This is the enforcement mechanism for a Phase 20 certification invariant.
    Callers must not catch it and continue.
    """


def is_within(child: Path, parent: Path) -> bool:
    """True when ``child`` resolves to ``parent`` or something beneath it."""
    try:
        resolved_child = Path(child).resolve()
        resolved_parent = Path(parent).resolve()
    except OSError as exc:  # pragma: no cover - defensive
        raise BoundaryViolation(f"Cannot resolve {child!r}: {exc}") from exc
    return resolved_child == resolved_parent or resolved_parent in resolved_child.parents


def _validate_segment(segment: str, *, what: str) -> str:
    if segment.lower() in _FORBIDDEN_SEGMENTS:
        raise BoundaryViolation(
            f"Refusing {what} path segment {segment!r}: reserved or traversal name."
        )
    if not _SEGMENT_RE.match(segment):
        raise BoundaryViolation(
            f"Refusing {what} path segment {segment!r}: must match {_SEGMENT_RE.pattern!r}."
        )
    return segment


def discover_project_ids(boundary_root: Path) -> tuple[str, ...]:
    """List the project ids present under a ``Modernization Output`` directory."""
    boundary_root = Path(boundary_root)
    if not boundary_root.is_dir():
        return ()
    return tuple(
        entry.name
        for entry in sorted(boundary_root.iterdir())
        if entry.is_dir() and PROJECT_ID_RE.match(entry.name)
    )


def iter_boundary_files(project_root: Path) -> Iterator[Path]:
    """Yield every file under a customer project root, deterministically."""
    project_root = Path(project_root)
    if not project_root.is_dir():
        return
    for path in sorted(project_root.rglob("*")):
        if path.is_file():
            yield path
@dataclass(frozen=True)
class CustomerBoundary:
    """Resolves and enforces the customer delivery boundary for one project.

    Parameters
    ----------
    repo_root
        The AutoForge repository root (Domain A root).
    project_id
        The customer project identifier; must match :data:`PROJECT_ID_RE`.
    """

    repo_root: Path
    project_id: str

    def __post_init__(self) -> None:
        if not PROJECT_ID_RE.match(self.project_id):
            raise BoundaryViolation(
                f"Invalid customer project id {self.project_id!r}; "
                f"must match {PROJECT_ID_RE.pattern!r}."
            )
        object.__setattr__(self, "repo_root", Path(self.repo_root))

    # ── Locations ───────────────────────────────────────────────────────────

    @property
    def output_root(self) -> Path:
        """The ``Modernization Output`` delivery boundary."""
        return self.repo_root / CUSTOMER_OUTPUT_DIRNAME

    @property
    def project_root(self) -> Path:
        """The root of this customer's isolated project area."""
        return self.output_root / self.project_id

    def section(self, *segments: str) -> Path:
        """Return ``project_root/<segments…>`` with every segment validated.

        This is the ONLY supported way to build a customer path. Validation
        lives here so no caller can assemble one by hand and bypass it.
        """
        if not segments:
            raise BoundaryViolation("section() requires at least one path segment.")
        for segment in segments:
            _validate_segment(segment, what="customer")
        return self.project_root.joinpath(*segments)

    def ensure_section(self, *segments: str) -> Path:
        """Like :meth:`section`, but creates the directory."""
        path = self.section(*segments)
        path.mkdir(parents=True, exist_ok=True)
        return path
# ── Guards ──────────────────────────────────────────────────────────────

    def assert_inside_boundary(self, path: Path | str) -> Path:
        """Assert ``path`` is inside this project; return it resolved."""
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (self.repo_root / candidate).resolve()
        if not is_within(candidate, self.project_root):
            raise BoundaryViolation(
                f"Path {candidate} is outside the customer boundary {self.project_root}."
            )
        return candidate

    def assert_not_autoforge_source(self, path: Path | str) -> Path:
        """Assert ``path`` is not inside AutoForge-owned source (Domain A).

        A path cannot be simultaneously inside the customer boundary and inside
        Domain A -- the boundary is a top-level directory that is not Domain A
        -- so this is an independent check rather than a tautology.
        """
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (self.repo_root / candidate).resolve()
        for owned in AUTOFORGE_OWNED_SOURCE_DIRS:
            owned_root = self.repo_root / owned
            if owned_root.exists() and is_within(candidate, owned_root):
                raise BoundaryViolation(
                    f"Path {candidate} is inside AutoForge-owned source directory "
                    f"{owned!r}; customer material may never be written there."
                )
        return candidate

    def assert_writable_customer_path(self, path: Path | str) -> Path:
        """Combined guard applied to every customer-material write.

        The path must be inside this project's boundary *and* outside Domain A.
        """
        resolved = self.assert_inside_boundary(path)
        return self.assert_not_autoforge_source(resolved)

    def guard_all(self, paths: Iterable[Path | str]) -> list[Path]:
        """Apply :meth:`assert_writable_customer_path` to many paths."""
        return [self.assert_writable_customer_path(p) for p in paths]


@dataclass(frozen=True)
class ProjectAccessGuard:
    """Fail-closed isolation between logical customer projects.

    One guard is bound to exactly one ``project_id``. Any access naming a
    different project -- a read, a write, an artifact, a delivery or a learning
    record -- is refused *before* the underlying operation runs.
    """

    owner_project_id: str
    known_project_ids: tuple[str, ...] = field(default=())

    def __post_init__(self) -> None:
        if not PROJECT_ID_RE.match(self.owner_project_id):
            raise BoundaryViolation(f"Invalid owner project id {self.owner_project_id!r}.")
        for pid in self.known_project_ids:
            if not PROJECT_ID_RE.match(pid):
                raise BoundaryViolation(f"Invalid known project id {pid!r}.")
        object.__setattr__(
            self, "known_project_ids", tuple(sorted(set(self.known_project_ids)))
        )

    def assert_owner(self, requested_project_id: str) -> str:
        """Return the project id when it is the owner's, else refuse."""
        if requested_project_id != self.owner_project_id:
            raise BoundaryViolation(
                f"Project isolation violation: {self.owner_project_id!r} may not access "
                f"{requested_project_id!r}."
            )
        return requested_project_id

    def assert_owner_in_paths(self, paths: Iterable[Path | str]) -> None:
        """Refuse any path containing a foreign project id segment."""
        for raw in paths:
            parts = Path(raw).parts
            for other in self.known_project_ids:
                if other == self.owner_project_id:
                    continue
                if other in parts:
                    raise BoundaryViolation(
                        f"Project isolation violation: path {raw!r} references "
                        f"foreign project {other!r}."
                    )

    def owned(self, requested_project_id: str) -> "ProjectAccessGuard":
        """Return a guard bound to ``requested_project_id`` if it is ours."""
        self.assert_owner(requested_project_id)
        return self
        """Combined guard applied to every customer-material write.

        The path must be inside this project's boundary *and* outside Domain A.
        """
        resolved = self.assert_inside_boundary(path)
        return self.assert_not_autoforge_source(resolved)

    def guard_all(self, paths: Iterable[Path | str]) -> list[Path]:
        """Apply :meth:`assert_writable_customer_path` to many paths."""
        return [self.assert_writable_customer_path(p) for p in paths]
        return path