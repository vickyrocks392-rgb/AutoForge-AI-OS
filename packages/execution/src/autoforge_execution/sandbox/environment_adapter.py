"""
Sandboxed Workspace Environment Adapter for Execution Platform (Phase 18-I).

Wraps WorkloadSandboxManager to provide a drop-in, 100% backward-compatible
interface matching WorkspaceEnvironment.
"""

from __future__ import annotations

import asyncio
import os
import time
from pathlib import Path
from typing import Any

from autoforge_connectors.filesystem import WorkspaceFilesystem
from autoforge_connectors.git import GitConnector
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution.models import CommandResult, CommandSpec
from autoforge_execution.sandbox.manager import WorkloadSandboxManager
from autoforge_execution.sandbox.models import (
    CleanupPolicy,
    ResourceLimits,
    SecurityProfile,
    WorkloadSpec,
)


class SandboxedWorkspaceEnvironment(WorkspaceEnvironment):
    """
    Drop-in alternative to WorkspaceEnvironment that routes command executions
    through the Workload Sandbox subsystem.
    """

    def __init__(
        self,
        workspace_root: str | Path,
        *,
        sandbox_manager: WorkloadSandboxManager | None = None,
        filesystem: WorkspaceFilesystem | None = None,
        git: GitConnector | None = None,
        security_profile: SecurityProfile = SecurityProfile.UNTRUSTED,
        preferred_provider: str = "local_restricted",
    ) -> None:
        super().__init__(workspace_root, filesystem=filesystem, git=git)
        self._sandbox_manager = sandbox_manager or WorkloadSandboxManager(default_provider=preferred_provider)
        self._security_profile = security_profile
        self._preferred_provider = preferred_provider

    @property
    def sandbox_manager(self) -> WorkloadSandboxManager:
        return self._sandbox_manager

    async def execute_command(
        self,
        spec: CommandSpec | list[str],
        *,
        timeout_seconds: float | None = None,
    ) -> CommandResult:
        """
        Execute a command via the WorkloadSandboxManager.
        Translates CommandSpec to WorkloadSpec and maps WorkloadResult to CommandResult.
        """
        if isinstance(spec, list):
            cmd_spec = CommandSpec(argv=spec)
        else:
            cmd_spec = spec

        timeout = timeout_seconds if timeout_seconds is not None else cmd_spec.timeout_seconds

        # Build WorkloadSpec
        workload_spec = WorkloadSpec(
            project_id="workspace-env",
            command=cmd_spec.argv,
            cwd=cmd_spec.cwd,
            env=cmd_spec.env,
            resource_limits=ResourceLimits(timeout_seconds=timeout),
            security_profile=self._security_profile,
            cleanup_policy=CleanupPolicy.DESTROY_ALWAYS,
            timeout_seconds=timeout,
        )

        # Execute through Workload Sandbox
        res = await self._sandbox_manager.execute_workload(
            workload_spec,
            preferred_provider=self._preferred_provider,
        )

        return CommandResult(
            command=cmd_spec.argv,
            exit_code=res.exit_code,
            stdout=res.stdout,
            stderr=res.stderr,
            duration_seconds=res.duration_seconds,
            timed_out=res.timed_out,
        )
