"""Git connector — controlled repository operations over subprocess.

Version-control capabilities for engineering workers WITHOUT embedding any
engineering workflow: inspection (status, diff, log, branch, head) and
mutation (stage, commit, branches, checkout, guarded reset).

Safety architecture:

- NO shell — every invocation is an ``argv`` list; user-controlled strings
  are validated before reaching git.
- Ref names pass :func:`validation.validate_ref_name` (no leading dashes ⇒
  no option injection; no ``..``).
- Hard wall-clock budget per command enforced by subprocess itself; expiry
  maps to :class:`ConnectorTimeoutError`.
- ``GIT_TERMINAL_PROMPT=0`` forbids interactive credential prompts.
- Non-zero exits are normalised into the connector error taxonomy via
  deterministic stderr classification — raw git failures never escape.
"""

from __future__ import annotations

import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from autoforge_connectors.errors import (
    ConnectorAuthenticationError,
    ConnectorAuthorizationError,
    ConnectorConflictError,
    ConnectorNotFoundError,
    ConnectorOperationFailedError,
    ConnectorTimeoutError,
    ConnectorUnavailableError,
    ConnectorValidationError,
)
from autoforge_connectors.events import ConnectorEvents
from autoforge_connectors.instrumentation import observe_connector_operation
from autoforge_connectors.validation import (
    validate_pathspec,
    validate_ref_name,
)


@dataclass(frozen=True)
class CommitInfo:
    """One entry of repository history."""

    hash: str
    short_hash: str
    author_name: str
    author_email: str
    committed_at: str  # ISO-8601 offset timestamp
    subject: str


@dataclass(frozen=True)
class GitStatus:
    """Parsed porcelain status of the working tree."""

    branch: str | None  # None ⇒ detached HEAD
    staged: tuple[str, ...]
    modified: tuple[str, ...]
    untracked: tuple[str, ...]
    conflicts: tuple[str, ...]


#: Porcelain state pairs indicating an unresolved merge conflict.
_CONFLICT_PAIRS = frozenset({"DD", "AU", "UD", "UA", "DU", "AA", "UU"})

#: NUL-separated log format — robust against subjects containing newlines or
#: pipes (field separator: NUL; record terminator: \x01).
_LOG_FIELD_FORMAT = "%H%x00%h%x00%an%x00%ae%x00%aI%x00%s"


def _parse_log(output: str, limit: int) -> list[CommitInfo]:
    records = [r for r in output.split("\x01") if r.strip()]
    commits: list[CommitInfo] = []
    for record in records[:limit]:
        fields = record.strip("\n").split("\x00")
        if len(fields) < 6:
            continue
        commits.append(
            CommitInfo(
                hash=fields[0],
                short_hash=fields[1],
                author_name=fields[2],
                author_email=fields[3],
                committed_at=fields[4],
                subject=fields[5],
            )
        )
    return commits


class GitConnector:
    """Git operations bound to one repository working tree."""

    def __init__(
        self,
        repository: Path | str,
        *,
        binary: str = "git",
        default_timeout_seconds: float = 30.0,
        events: ConnectorEvents | None = None,
    ) -> None:
        if default_timeout_seconds <= 0:
            raise ConnectorValidationError("default_timeout_seconds must be positive")
        repo = Path(repository).expanduser()
        if not repo.exists():
            raise ConnectorNotFoundError(
                f"repository path does not exist: {repo}",
                details={"repository": str(repo)},
            )
        if not repo.is_dir():
            raise ConnectorValidationError(
                f"repository path is not a directory: {repo}"
            )
        self._repository = repo.resolve(strict=True)
        self._binary = binary
        self._timeout = float(default_timeout_seconds)
        self._events = events
        #: Most recent OperationObservation on this connector.
        self.last_operation: Any = None

    @classmethod
    def discover(cls, start: Path | str, *, max_parents: int = 32, **kwargs: Any):
        """Locate the nearest repository at/above ``start`` and bind to it."""
        cursor = Path(start).expanduser().resolve(strict=True)
        for _ in range(max_parents + 1):
            if (cursor / ".git").exists():
                return cls(cursor, **kwargs)
            parent = cursor.parent
            if parent == cursor:
                break
            cursor = parent
        raise ConnectorNotFoundError(
            "no git repository found above the given location",
            details={"start": str(start)},
        )

    @property
    def connector_name(self) -> str:
        return "git"

    @property
    def repository(self) -> Path:
        """The bound repository working tree."""
        return self._repository

    # ------------------------------------------------------------------
    # Subprocess core
    # ------------------------------------------------------------------

    def _run(self, arguments: Sequence[str], *, timeout_seconds: float | None = None):
        """Execute one git argv inside the repo; classify every failure."""
        budget = timeout_seconds if timeout_seconds is not None else self._timeout
        command = [self._binary, *arguments]
        env = dict(os.environ)
        env["GIT_TERMINAL_PROMPT"] = "0"
        try:
            completed = subprocess.run(
                command,
                cwd=self._repository,
                capture_output=True,
                text=True,
                timeout=budget,
                check=False,
                env=env,
            )
        except FileNotFoundError as exc:
            if self._events is not None:
                self._events.connector_unavailable(
                    connector="git",
                    reason=f"executable '{self._binary}' is not installed",
                )
            raise ConnectorUnavailableError(
                f"git executable '{self._binary}' is not available",
                details={"binary": self._binary},
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise ConnectorTimeoutError(
                f"git {arguments[0]} exceeded {budget:.3f}s time budget",
                details={"operation": arguments[0], "timeout_seconds": budget},
            ) from exc
        if completed.returncode != 0:
            self._raise_for_failure(arguments[0], completed)
        return completed

    @staticmethod
    def _raise_for_failure(operation: str, completed) -> None:
        """Deterministically map a failed git invocation onto the taxonomy."""
        stderr = (completed.stderr or "").strip()
        detail = {
            "operation": operation,
            "exit_code": completed.returncode,
            "stderr_tail": stderr[-800:],
        }
        haystack = stderr.lower()
        if "authentication failed" in haystack or "could not read username" in haystack:
            raise ConnectorAuthenticationError(
                "git rejected credentials", details=detail
            )
        if "permission denied" in haystack or "denied to" in haystack:
            raise ConnectorAuthorizationError(
                "git reports insufficient permissions", details=detail
            )
        if any(
            token in haystack
            for token in (
                "already exists",
                "would be overwritten",
                "non-fast-forward",
                "rejected",
            )
        ):
            raise ConnectorConflictError(
                f"git {operation} conflicts with existing state", details=detail
            )
        if any(
            token in haystack
            for token in (
                "does not exist",
                "not found",
                "bad revision",
                "ambiguous argument",
                "did not match",
                "does not have any commits",
                "unborn branch",
                "unable to read tree",
                "reference is not a tree",
            )
        ):
            raise ConnectorNotFoundError(
                f"git {operation} referenced a missing entity", details=detail
            )
        if "usage:" in haystack or "not a valid" in haystack:
            raise ConnectorValidationError(
                f"git {operation} received invalid input", details=detail
            )
        raise ConnectorOperationFailedError(
            f"git {operation} failed with exit code {completed.returncode}",
            details=detail,
        )

    # ------------------------------------------------------------------
    # Inspection
    # ------------------------------------------------------------------

    def is_repository(self) -> bool:
        """Whether the bound directory is (inside) a git work tree."""
        completed = self._run(["rev-parse", "--is-inside-work-tree"])
        return completed.stdout.strip() == "true"

    def current_branch(self) -> str | None:
        """Current branch name; ``None`` when HEAD is detached."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="current_branch",
        ):
            completed = self._run(["rev-parse", "--abbrev-ref", "HEAD"])
            name = completed.stdout.strip()
            return None if name == "HEAD" else name

    def head_commit(self) -> CommitInfo | None:
        """The HEAD commit, or ``None`` when the repository is empty."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="head_commit",
        ):
            try:
                completed = self._run(
                    ["log", "-1", f"--format={_LOG_FIELD_FORMAT}\x01"]
                )
            except ConnectorNotFoundError:
                return None
            commits = _parse_log(completed.stdout, 1)
            return commits[0] if commits else None

    def status(self) -> GitStatus:
        """Parsed working-tree status (porcelain v1, renames disabled)."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="status",
        ):
            completed = self._run(["status", "--porcelain=v1", "-b", "--no-renames"])
            lines = completed.stdout.splitlines()
            branch: str | None = None
            staged: list[str] = []
            modified: list[str] = []
            untracked: list[str] = []
            conflicts: list[str] = []
            for line in lines:
                if line.startswith("## "):
                    header = line[3:].strip()
                    if header.startswith("HEAD") or header.startswith("(no branch"):
                        branch = None
                    else:
                        first = header.split(",", 1)[0]
                        branch = first.split("...", 1)[0].strip() or None
                    continue
                if len(line) < 4:
                    continue
                xy, path = line[:2], line[3:]
                index_state, work_state = xy[0], xy[1]
                if xy in _CONFLICT_PAIRS:
                    conflicts.append(path)
                    continue
                if index_state == "?" and work_state == "?":
                    untracked.append(path)
                    continue
                if index_state != " " and index_state != "?":
                    staged.append(path)
                if work_state not in (" ", "?"):
                    modified.append(path)
            return GitStatus(
                branch=branch,
                staged=tuple(staged),
                modified=tuple(modified),
                untracked=tuple(untracked),
                conflicts=tuple(conflicts),
            )

    def diff(self, *, staged: bool = False) -> str:
        """Unified diff of unstaged (default) or staged changes."""
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="diff",
        ):
            args = ["diff", "--no-color"]
            if staged:
                args.append("--staged")
            completed = self._run(args)
            return completed.stdout

    def log(self, *, limit: int = 20) -> list[CommitInfo]:
        """Most recent commits on HEAD (bounded by ``limit`` ≤ 1000)."""
        if limit < 1 or limit > 1000:
            raise ConnectorValidationError(
                "log limit must be between 1 and 1000", details={"limit": limit}
            )
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="log",
        ):
            try:
                completed = self._run(
                    [
                        "log",
                        f"--max-count={int(limit)}",
                        f"--format={_LOG_FIELD_FORMAT}\x01",
                    ]
                )
            except ConnectorNotFoundError:
                return []  # unborn HEAD — no history yet
            return _parse_log(completed.stdout, limit)

    # ------------------------------------------------------------------
    # Mutation
    # ------------------------------------------------------------------

    def stage(self, paths: Sequence[str]) -> int:
        """Stage the given workspace-relative paths; returns count staged."""
        if not paths:
            raise ConnectorValidationError("paths must contain at least one entry")
        clean_paths = [validate_pathspec(p) for p in paths]
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="stage",
        ):
            self._run(["add", "--", *clean_paths])
            return len(clean_paths)

    def commit(
        self,
        message: str,
        *,
        stage_all: bool = False,
        allow_empty: bool = False,
    ) -> str:
        """Commit staged (or all tracked when ``stage_all``) changes.

        Returns the full commit hash. Uses ``--no-gpg-sign`` so autonomous
        runs never block on passphrase prompts.
        """
        cleaned = message.strip() if isinstance(message, str) else ""
        if not cleaned:
            raise ConnectorValidationError("commit message must be non-empty")
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="commit",
        ):
            args = ["commit", "--no-gpg-sign"]
            if stage_all:
                args.append("-a")
            if allow_empty:
                args.append("--allow-empty")
            args += ["-m", cleaned]
            self._run(args)
            return self._run(["rev-parse", "HEAD"]).stdout.strip()

    def create_branch(self, name: str, *, start_point: str | None = None) -> str:
        """Create a branch at ``start_point`` (default HEAD); returns name."""
        safe_name = validate_ref_name(name, what="branch")
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="create_branch",
        ):
            args = ["branch", safe_name]
            if start_point is not None:
                args.append(validate_ref_name(start_point, what="start point"))
            self._run(args)
            return safe_name

    def checkout(self, ref: str, *, create: bool = False) -> str:
        """Check out an existing ref; with ``create=True`` create-then-switch
        (``git checkout -b``)."""
        safe_ref = validate_ref_name(ref, what="ref")
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="checkout",
        ):
            if create:
                self._run(["checkout", "-b", safe_ref])
            else:
                self._run(["checkout", safe_ref])
            return safe_ref

    def delete_branch(self, name: str, *, force: bool = False) -> None:
        """Delete a local branch (merged-only unless ``force``)."""
        safe_name = validate_ref_name(name, what="branch")
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="delete_branch",
        ):
            self._run(["branch", "-D" if force else "-d", safe_name])

    def reset(self, mode: str = "mixed", *, ref: str | None = None) -> None:
        """Reset HEAD to ``ref`` (soft / mixed / hard).

        ``hard`` discards working-tree changes; it exists for controlled
        rollback use by later recovery paths, never blind execution.
        """
        allowed = {"soft": "--soft", "mixed": "--mixed", "hard": "--hard"}
        if mode not in allowed:
            raise ConnectorValidationError(
                f"reset mode must be one of {sorted(allowed)}",
                details={"mode": mode},
            )
        with observe_connector_operation(
            events=self._events, record_into=self.__dict__,
            connector=self.connector_name, operation="reset",
        ):
            args = ["reset", allowed[mode]]
            if ref is not None:
                args.append(validate_ref_name(ref, what="ref"))
            self._run(args)


__all__ = ["CommitInfo", "GitConnector", "GitStatus"]

