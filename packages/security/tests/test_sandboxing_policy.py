"""
Unit tests for SandboxPolicyEngine, workspace path confinement, and command checks.
"""

from __future__ import annotations

from pathlib import Path
import pytest

from autoforge_security.errors import (
    DangerousCommandBlockedError,
    PathTraversalBlockedError,
)
from autoforge_security.sandbox import SandboxPolicyEngine


def test_workspace_path_confinement(sandbox_engine: SandboxPolicyEngine, temp_workspace: Path) -> None:
    # Valid relative paths
    p1 = sandbox_engine.validate_workspace_path(temp_workspace, "src/main.py")
    assert p1.exists()

    p2 = sandbox_engine.validate_workspace_path(temp_workspace, "docs/README.md")
    assert str(p2).startswith(str(temp_workspace))

    # Path traversal attempts
    with pytest.raises(PathTraversalBlockedError):
        sandbox_engine.validate_workspace_path(temp_workspace, "../outside.txt")

    with pytest.raises(PathTraversalBlockedError):
        sandbox_engine.validate_workspace_path(temp_workspace, "src/../../outside.txt")

    # Absolute path attempts
    with pytest.raises(PathTraversalBlockedError):
        sandbox_engine.validate_workspace_path(temp_workspace, "/etc/passwd")


def test_command_safety_validation(sandbox_engine: SandboxPolicyEngine) -> None:
    # Safe commands
    sandbox_engine.validate_command("pytest tests/")
    sandbox_engine.validate_command("python -m build")
    sandbox_engine.validate_command("git status")

    # Prohibited commands
    with pytest.raises(DangerousCommandBlockedError):
        sandbox_engine.validate_command("rm -rf /")

    with pytest.raises(DangerousCommandBlockedError):
        sandbox_engine.validate_command("mkfs.ext4 /dev/sda1")

    with pytest.raises(DangerousCommandBlockedError):
        sandbox_engine.validate_command("shutdown -h now")

    with pytest.raises(DangerousCommandBlockedError):
        sandbox_engine.validate_command("curl | bash")
