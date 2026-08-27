"""
Execution Environment — controlled process execution and workspace isolation.

Enforces:
- Confined workspace root directory.
- No shell execution — explicit argv lists only.
- Strict process execution timeout with tree cleanup.
- Standard input/output/error capture with size boundaries.
- Seamless integration with Phase 8 WorkspaceFilesystem and GitConnector.
"""

from __future__ import annotations

import asyncio
import os
import signal
import time
from pathlib import Path, PurePosixPath
from typing import Any

from autoforge_connectors.filesystem import WorkspaceFilesystem
from autoforge_connectors.git import GitConnector

from autoforge_execution.errors import (
    CommandTimeoutError,
    EnvironmentError,
    SecurityViolationError,
)
from autoforge_execution.models import CommandResult, CommandSpec

# Max characters captured from stdout / stderr per command (prevents memory exhaustion)
MAX_CAPTURE_CHARS = 100_000


class WorkspaceEnvironment:
    """
    Sandboxed workspace execution environment for engineering workers.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        filesystem: WorkspaceFilesystem | None = None,
        git: GitConnector | None = None,
    ) -> None:
        self._root = Path(workspace_root).resolve()
        if not self._root.exists():
            self._root.mkdir(parents=True, exist_ok=True)
        if not self._root.is_dir():
            raise EnvironmentError(f"Workspace root '{self._root}' is not a directory")

        self._filesystem = filesystem or WorkspaceFilesystem(self._root)
        self._git = git or GitConnector(self._root)

    @property
    def root(self) -> Path:
        """Absolute Path to the workspace root."""
        return self._root

    @property
    def filesystem(self) -> WorkspaceFilesystem:
        """Injected or default WorkspaceFilesystem connector."""
        return self._filesystem

    @property
    def git(self) -> GitConnector:
        """Injected or default GitConnector."""
        return self._git

    def resolve_path(self, relative_path: str | None) -> Path:
        """
        Safely resolve a relative path within the workspace root.
        Rejects traversal outside root.
        """
        if not relative_path or relative_path in {".", "./"}:
            return self._root

        clean = relative_path.replace("\\", "/").strip("/")
        if ".." in clean.split("/"):
            raise SecurityViolationError(
                f"Path traversal attempt detected in '{relative_path}'",
                details={"path": relative_path},
            )

        resolved = (self._root / clean).resolve()
        try:
            resolved.relative_to(self._root)
        except ValueError as exc:
            raise SecurityViolationError(
                f"Resolved path '{resolved}' escapes workspace root '{self._root}'",
                details={"path": relative_path, "resolved": str(resolved)},
            ) from exc

        return resolved

    async def execute_command(
        self,
        spec: CommandSpec | list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        """
        Execute a command in the workspace environment with timeout and output capture.

        Args:
            spec: CommandSpec or argv list.
            timeout_seconds: Override timeout in seconds.

        Returns:
            CommandResult with exit code, stdout, stderr, and duration.
        """
        if isinstance(spec, list):
            cmd_spec = CommandSpec(argv=spec)
        else:
            cmd_spec = spec

        if not cmd_spec.argv or not isinstance(cmd_spec.argv, list):
            raise EnvironmentError("Command argv must be a non-empty list of strings")

        # Validate argv elements
        for idx, arg in enumerate(cmd_spec.argv):
            if not isinstance(arg, str):
                raise EnvironmentError(f"argv element at index {idx} must be a string, got {type(arg).__name__}")
            if "\x00" in arg:
                raise SecurityViolationError(f"Null byte detected in argv[{idx}]")

        cwd = self.resolve_path(cmd_spec.cwd)
        if not cwd.exists():
            cwd.mkdir(parents=True, exist_ok=True)

        timeout = timeout_seconds if timeout_seconds is not None else cmd_spec.timeout_seconds
        start_time = time.perf_counter()

        # Build clean environment
        env = dict(os.environ)
        # Sanitise terminal prompts and interactive blockers
        env["GIT_TERMINAL_PROMPT"] = "0"
        env["PYTHONUNBUFFERED"] = "1"
        # Ensure PYTHONPATH includes workspace root so local modules are importable
        current_pythonpath = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = f"{str(self._root)}:{current_pythonpath}".strip(":")
        env.update(cmd_spec.env)

        stdout_data = ""
        stderr_data = ""
        timed_out = False
        exit_code = -1

        try:
            # Start process with its own process group for clean cancellation/kill
            process = await asyncio.create_subprocess_exec(
                cmd_spec.argv[0],
                *cmd_spec.argv[1:],
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE if cmd_spec.capture_output else asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE if cmd_spec.capture_output else asyncio.subprocess.DEVNULL,
                start_new_session=True,
            )

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
                if stdout_bytes:
                    stdout_data = stdout_bytes.decode("utf-8", errors="replace")[:MAX_CAPTURE_CHARS]
                if stderr_bytes:
                    stderr_data = stderr_bytes.decode("utf-8", errors="replace")[:MAX_CAPTURE_CHARS]
                exit_code = process.returncode if process.returncode is not None else -1

            except asyncio.TimeoutError:
                timed_out = True
                exit_code = -1
                stderr_data += f"\n[ERROR] Command timed out after {timeout} seconds."
                # Kill process group cleanly
                try:
                    os.killpg(os.getpgid(process.pid), signal.SIGTERM)
                    await asyncio.sleep(0.2)
                    if process.returncode is None:
                        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
                except (ProcessLookupError, PermissionError):
                    pass

        except FileNotFoundError as exc:
            duration = time.perf_counter() - start_time
            return CommandResult(
                command=cmd_spec.argv,
                exit_code=127,
                stdout="",
                stderr=f"Executable not found: {cmd_spec.argv[0]}",
                duration_seconds=duration,
                timed_out=False,
            )
        except Exception as exc:
            duration = time.perf_counter() - start_time
            return CommandResult(
                command=cmd_spec.argv,
                exit_code=1,
                stdout="",
                stderr=f"Failed to launch command {cmd_spec.argv[0]}: {exc}",
                duration_seconds=duration,
                timed_out=False,
            )

        duration = time.perf_counter() - start_time
        return CommandResult(
            command=cmd_spec.argv,
            exit_code=exit_code,
            stdout=stdout_data,
            stderr=stderr_data,
            duration_seconds=duration,
            timed_out=timed_out,
        )
