"""
Unit and integration tests for WorkspaceEnvironment and safe subprocess execution.
"""

import sys
import tempfile
from pathlib import Path

import pytest

from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.errors import (
    EnvironmentError,
    SecurityViolationError,
)
from autoforge_execution.models import CommandSpec


@pytest.fixture
def temp_workspace(tmp_path):
    return WorkspaceEnvironment(tmp_path)


@pytest.mark.asyncio
async def test_workspace_resolve_path(temp_workspace):
    # Valid paths
    p1 = temp_workspace.resolve_path("src/main.py")
    assert p1 == temp_workspace.root / "src" / "main.py"

    p2 = temp_workspace.resolve_path(None)
    assert p2 == temp_workspace.root

    # Path traversal rejected
    with pytest.raises(SecurityViolationError):
        temp_workspace.resolve_path("../escape.py")

    with pytest.raises(SecurityViolationError):
        temp_workspace.resolve_path("foo/../../escape.py")


@pytest.mark.asyncio
async def test_execute_successful_command(temp_workspace):
    res = await temp_workspace.execute_command([sys.executable, "-c", "print('hello world')"])
    assert res.passed
    assert res.exit_code == 0
    assert "hello world" in res.stdout
    assert res.stderr == ""
    assert not res.timed_out
    assert res.duration_seconds > 0.0


@pytest.mark.asyncio
async def test_execute_failing_command(temp_workspace):
    res = await temp_workspace.execute_command([sys.executable, "-c", "import sys; sys.stderr.write('failed!'); sys.exit(2)"])
    assert not res.passed
    assert res.exit_code == 2
    assert "failed!" in res.stderr
    assert not res.timed_out


@pytest.mark.asyncio
async def test_execute_command_timeout(temp_workspace):
    spec = CommandSpec(
        argv=[sys.executable, "-c", "import time; time.sleep(10)"],
        timeout_seconds=0.5,
    )
    res = await temp_workspace.execute_command(spec)
    assert not res.passed
    assert res.timed_out
    assert "timed out" in res.stderr.lower()


@pytest.mark.asyncio
async def test_execute_nonexistent_executable(temp_workspace):
    res = await temp_workspace.execute_command(["non_existent_binary_xyz_123"])
    assert not res.passed
    assert res.exit_code == 127
    assert "not found" in res.stderr.lower()


@pytest.mark.asyncio
async def test_execute_security_null_byte(temp_workspace):
    with pytest.raises(SecurityViolationError):
        await temp_workspace.execute_command(["python\x00", "test.py"])


@pytest.mark.asyncio
async def test_workspace_filesystem_integration(temp_workspace):
    # Write file via filesystem connector
    temp_workspace.filesystem.write_text("calc.py", "def add(a, b): return a + b\n")
    temp_workspace.filesystem.write_text("test_calc.py", "from calc import add\nassert add(2, 3) == 5\nprint('TESTS PASSED')\n")

    res = await temp_workspace.execute_command([sys.executable, "test_calc.py"])
    assert res.passed
    assert "TESTS PASSED" in res.stdout
