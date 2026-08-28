"""
Sandboxing Policies & Workspace Confinement for AutoForge Security (Phase 15).
"""

from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
from typing import Any

from autoforge_security.errors import (
    DangerousCommandBlockedError,
    PathTraversalBlockedError,
    SandboxViolationError,
)
from autoforge_security.models import SandboxPolicy


class SandboxPolicyEngine:
    """
    Evaluates filesystem operations and command execution for sandbox compliance.
    """

    def __init__(self, policy: SandboxPolicy | None = None) -> None:
        self._policy = policy or SandboxPolicy()

    @property
    def policy(self) -> SandboxPolicy:
        return self._policy

    def validate_workspace_path(self, workspace_root: str | Path, path: str) -> Path:
        """
        Validate that a relative path stays confined strictly within workspace_root.
        Rejects path traversal ('..'), absolute paths, or escaping symlinks.
        """
        if not path or not isinstance(path, str) or not path.strip():
            raise PathTraversalBlockedError("Path cannot be empty.")

        # Check for traversal patterns in raw string
        if ".." in path:
            raise PathTraversalBlockedError(
                f"Path traversal sequence '..' in '{path}' is strictly forbidden.",
                details={"path": path, "workspace_root": str(workspace_root)},
            )

        root = Path(workspace_root).resolve()
        posix = PurePosixPath(path.replace("\\", "/"))

        # Rejection of absolute paths
        if posix.is_absolute():
            raise PathTraversalBlockedError(
                f"Absolute path '{path}' is forbidden within workspace sandbox.",
                details={"path": path, "workspace_root": str(root)},
            )

        target = (root / posix).resolve()

        # Check resolved path is inside root
        try:
            target.relative_to(root)
        except ValueError:
            raise PathTraversalBlockedError(
                f"Resolved path '{target}' escapes workspace root '{root}'.",
                details={"path": path, "resolved": str(target), "workspace_root": str(root)},
            )

        return target

    def validate_command(self, command: str) -> None:
        """
        Scan a command line for forbidden destructive patterns.
        """
        if not command or not isinstance(command, str):
            raise DangerousCommandBlockedError("Command must be a non-empty string.")

        cmd_lower = command.lower().strip()

        for forbidden in self._policy.disallowed_commands:
            if forbidden.lower() in cmd_lower:
                raise DangerousCommandBlockedError(
                    f"Command execution blocked: contains prohibited sequence '{forbidden}'.",
                    details={"command": command, "forbidden_pattern": forbidden},
                )

        # Destructive rm heuristics
        if "rm -rf" in cmd_lower or "rm -f -r" in cmd_lower or "rm -r -f" in cmd_lower:
            if any(target in cmd_lower for target in (" /", " ~", " *", "/*")):
                raise DangerousCommandBlockedError(
                    "Destructive recursive deletion of system/root directory is forbidden.",
                    details={"command": command},
                )

        # Pipe to shell heuristics
        if "| bash" in cmd_lower or "| sh" in cmd_lower or "| zsh" in cmd_lower:
            raise DangerousCommandBlockedError(
                "Piping external downloads directly into shell is prohibited.",
                details={"command": command},
            )

    def sanitize_environment(self, env: dict[str, str], allowed_keys: set[str] | None = None) -> dict[str, str]:
        """
        Strip sensitive system environment variables before spawning external processes.
        """
        sanitized: dict[str, str] = {}
        disallowed_prefixes = ("AWS_", "GITHUB_TOKEN", "OPENAI_API_KEY", "ANTHROPIC_API_KEY", "GEMINI_API_KEY", "SECRET_")

        for k, v in env.items():
            if allowed_keys and k in allowed_keys:
                sanitized[k] = v
                continue
            if any(k.startswith(p) for p in disallowed_prefixes):
                continue
            sanitized[k] = v

        return sanitized
