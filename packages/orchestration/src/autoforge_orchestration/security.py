"""Security boundary guard for Phase 18 orchestration (section 20).

Enforces least-privilege isolation for verification commands executed
during stage evaluation. Generated code/artifacts never modify the
AutoForge control plane. Worker-generated verification commands must
never execute unrestricted on the host — they run inside the existing
``WorkspaceEnvironment`` sandbox with explicit argv lists only (no shell).
"""

from __future__ import annotations

import re
from typing import Any

from autoforge_orchestration.errors import SecurityBoundaryError


_FORBIDDEN_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"\brm\s+-rf\s+/(?:usr|bin|etc|proc|sys|var)\b", re.IGNORECASE),
    re.compile(r"\bsudo\b", re.IGNORECASE),
    re.compile(r"\bsu\b", re.IGNORECASE),
    re.compile(r"\bchmod\b.*\bR\b", re.IGNORECASE),
    re.compile(r"\bchown\b.*-R", re.IGNORECASE),
    re.compile(r"\bmkfs\b", re.IGNORECASE),
    re.compile(r"\bdd\b.*of=/dev/", re.IGNORECASE),
    re.compile(r"\bshutdown\b|\breboot\b|\bpoweroff\b|\bhalt\b", re.IGNORECASE),
    re.compile(r"\bkill\b.*-9.*\b1\b", re.IGNORECASE),
    re.compile(r"\bgit\b.*\bpush\b", re.IGNORECASE),
    re.compile(r"\bgit\b.*\bremote\b.*\badd\b", re.IGNORECASE),
]

_PATH_TRAVERSAL_TOKENS = {"..", "~", "$HOME", "$USER", "/etc", "/root", "/home",
                          "/proc", "/sys", "/usr/local", "/var"}


class VerificationCommandError(SecurityBoundaryError):
    """Raised when a verification command violates security policy."""


class SecurityBoundaryGuard:
    """Validates workspace-scoped command execution requests.

    Invoked before any verification command or worker-generated command is
    executed by the OrchestrationEngine. Enforces:

    1. No path traversal outside the workspace root.
    2. No forbidden host-mutating commands (sudo, rm -rf /usr, etc.).
    3. No shell execution — argv lists only, no ``shell=True``.
    4. No arbitrary filesystem writes outside the workspace.
    """

    def __init__(self, workspace_root: str) -> None:
        from pathlib import Path
        self._workspace_root: Path = Path(workspace_root).resolve()

    @property
    def workspace_root(self):
        return self._workspace_root

    def validate_command(self, argv: list[str], cwd: str | None = None) -> list[str]:
        """Validate an argv command list for safe workspace-scoped execution.

        Args:
            argv: Command and arguments as a list (no shell).
            cwd: Optional working directory (must be within workspace).

        Returns:
            The validated argv list.

        Raises:
            VerificationCommandError: If the command violates security policy.
        """
        if not isinstance(argv, list) or len(argv) == 0:
            raise VerificationCommandError(
                "Command must be a non-empty argv list (no shell execution permitted)"
            )

        shell_chars = set(";|&$`<>(){}\n\r")
        for arg in argv:
            if not isinstance(arg, str):
                raise VerificationCommandError(
                    f"Command arguments must be strings, got {type(arg).__name__}"
                )
            for ch in arg:
                if ch in shell_chars:
                    raise VerificationCommandError(
                        f"Shell metacharacter '{ch}' is forbidden in command arguments",
                        details={"argument": arg, "char": ch},
                    )

        cmd_str = " ".join(argv)
        for pattern in _FORBIDDEN_PATTERNS:
            match = pattern.search(cmd_str)
            if match:
                raise VerificationCommandError(
                    f"Command matches forbidden pattern: {match.pattern}",
                    details={"command": cmd_str, "pattern": match.pattern},
                )

        for arg in argv:
            for token in _PATH_TRAVERSAL_TOKENS:
                if token in arg:
                    raise VerificationCommandError(
                        f"Path traversal token '{token}' is forbidden in workspace",
                        details={"argument": arg, "token": token},
                    )
            if ".." in arg.split("/"):
                raise VerificationCommandError(
                    "Path traversal via '..' is forbidden in workspace commands",
                    details={"argument": arg},
                )

        if cwd is not None:
            from pathlib import Path
            cwd_path = Path(cwd).resolve()
            try:
                cwd_path.relative_to(self._workspace_root)
            except ValueError:
                raise VerificationCommandError(
                    "Working directory must be within the workspace root",
                    details={"cwd": str(cwd_path),
                             "workspace_root": str(self._workspace_root)},
                )
        return argv

    def validate_path(self, relative_path: str) -> Any:
        """Validate that a relative path stays within the workspace root.

        Returns the resolved absolute Path.
        Raises VerificationCommandError if the path escapes the workspace.
        """
        from pathlib import Path
        if not relative_path or relative_path in {".", "./"}:
            return self._workspace_root
        clean = relative_path.replace("\\", "/").strip("/")
        parts = clean.split("/")
        if any(p == ".." for p in parts):
            raise VerificationCommandError(
                "Path traversal via '..' is forbidden",
                details={"path": relative_path},
            )
        resolved = (self._workspace_root / clean).resolve()
        try:
            resolved.relative_to(self._workspace_root)
        except ValueError:
            raise VerificationCommandError(
                "Path escapes workspace root",
                details={"path": str(resolved),
                         "workspace_root": str(self._workspace_root)},
            )
        return resolved
