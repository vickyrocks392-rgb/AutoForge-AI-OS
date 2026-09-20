"""
Workload Sandbox Manager for AutoForge AI (Phase 18-I).

Coordinates sandbox provider selection, policy enforcement, deterministic
lifecycle progression, canonical event emission, and guaranteed reaper cleanup.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Any

from autoforge_execution.events import EventSinkProtocol
from autoforge_execution.sandbox.lifecycle import SandboxLifecycleManager
from autoforge_execution.sandbox.models import (
    CleanupPolicy,
    CleanupReport,
    CleanupStatus,
    PreparedWorkload,
    ResourceUsage,
    TerminationReason,
    VerificationState,
    WorkloadLifecycleState,
    WorkloadResult,
    WorkloadSpec,
)
from autoforge_execution.sandbox.policies import PolicyValidator, PolicyViolationError
from autoforge_execution.sandbox.provider import (
    ContainerSandboxProvider,
    DockerSandboxProvider,
    LocalRestrictedSandboxProvider,
    PodmanSandboxProvider,
    SandboxProvider,
    SandboxRuntimeUnavailableError,
)
from autoforge_execution.sandbox.reaper import WorkloadReaper


class WorkloadSandboxManager:
    """
    Central coordinator for safe, isolated execution of generated workloads.
    """

    def __init__(
        self,
        event_sink: EventSinkProtocol | None = None,
        default_provider: str = "local_restricted",
        base_sandboxes_dir: Path | None = None,
    ) -> None:
        self._reaper = WorkloadReaper()
        self._lifecycle = SandboxLifecycleManager(event_sink)
        self._default_provider_name = default_provider
        self._base_sandboxes_dir = base_sandboxes_dir

        # Instantiate providers
        self._local_provider = LocalRestrictedSandboxProvider(
            base_sandboxes_dir=self._base_sandboxes_dir,
            reaper=self._reaper,
        )
        self._podman_provider = PodmanSandboxProvider(
            reaper=self._reaper,
            base_sandboxes_dir=self._base_sandboxes_dir,
        )
        self._docker_provider = DockerSandboxProvider(
            reaper=self._reaper,
            base_sandboxes_dir=self._base_sandboxes_dir,
        )

    @property
    def reaper(self) -> WorkloadReaper:
        return self._reaper

    @property
    def lifecycle(self) -> SandboxLifecycleManager:
        return self._lifecycle

    def get_provider(self, provider_type: str | None = None) -> SandboxProvider:
        """Resolve the requested or best available sandbox provider."""
        ptype = provider_type or self._default_provider_name

        if ptype == "podman":
            return self._podman_provider
        if ptype == "docker":
            return self._docker_provider
        if ptype == "container":
            if self._podman_provider.is_available():
                return self._podman_provider
            return self._docker_provider

        return self._local_provider

    async def execute_workload(
        self,
        spec: WorkloadSpec,
        *,
        preferred_provider: str | None = None,
    ) -> WorkloadResult:
        """
        Execute a workload through the complete deterministic sandbox lifecycle.
        """
        provider = self.get_provider(preferred_provider)
        start_time = time.perf_counter()

        # 1. CREATE & VALIDATE POLICY
        self._lifecycle.transition(spec.workload_id, WorkloadLifecycleState.CREATED)

        try:
            self._lifecycle.transition(spec.workload_id, WorkloadLifecycleState.VALIDATING_POLICY)
            PolicyValidator.validate_spec(spec)
        except PolicyViolationError as err:
            self._lifecycle.emit_policy_rejected(spec.workload_id, err.violation_type, str(err))
            duration = time.perf_counter() - start_time
            return WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=126,
                stdout="",
                stderr=f"Security Policy Rejected: {err}",
                duration_seconds=duration,
                termination_reason=TerminationReason.SECURITY_VIOLATION,
                security_violations=[str(err)],
                verification_state=VerificationState.FAILED,
                cleanup_status=CleanupStatus.CLEANED,
            )

        # 2. PREPARE
        self._lifecycle.transition(spec.workload_id, WorkloadLifecycleState.PREPARING)
        try:
            prepared = provider.prepare(spec)
        except Exception as exc:
            self._lifecycle.emit_workload_failed(spec.workload_id, 1, f"Preparation failed: {exc}", 0.0)
            duration = time.perf_counter() - start_time
            return WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=1,
                stdout="",
                stderr=f"Sandbox preparation failed: {exc}",
                duration_seconds=duration,
                termination_reason=TerminationReason.ERROR,
                verification_state=VerificationState.FAILED,
                cleanup_status=CleanupStatus.CLEANED,
            )

        self._lifecycle.emit_workload_created(spec, provider.provider_type, str(prepared.sandbox_workspace))

        # 3. START & EXECUTE
        timeout = spec.timeout_seconds or spec.resource_limits.timeout_seconds
        self._lifecycle.emit_workload_started(spec.workload_id, spec.command, timeout)

        result: WorkloadResult
        try:
            result = await provider.execute(prepared)
        except Exception as exc:
            duration = time.perf_counter() - start_time
            self._lifecycle.emit_workload_failed(spec.workload_id, 1, str(exc), duration)
            result = WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=1,
                stdout="",
                stderr=f"Execution error: {exc}",
                duration_seconds=duration,
                termination_reason=TerminationReason.ERROR,
                verification_state=VerificationState.FAILED,
            )

        # 4. OBSERVE & EMIT MILESTONES
        if result.timed_out:
            self._lifecycle.emit_workload_timeout(spec.workload_id, timeout, result.duration_seconds)
        elif result.success:
            self._lifecycle.emit_workload_completed(
                spec.workload_id,
                result.exit_code,
                result.duration_seconds,
                artifact_count=len(result.artifact_paths),
            )
        else:
            self._lifecycle.emit_workload_failed(
                spec.workload_id,
                result.exit_code,
                result.stderr[:200] if result.stderr else "Non-zero exit",
                result.duration_seconds,
            )

        # 5. CLEANUP & DESTROY
        self._lifecycle.transition(spec.workload_id, WorkloadLifecycleState.CLEANING_UP)
        cleanup_report = await provider.cleanup(spec.workload_id)
        self._lifecycle.emit_cleanup_completed(
            spec.workload_id,
            str(prepared.sandbox_workspace),
            cleanup_report.duration_seconds,
            orphans_reaped=cleanup_report.orphans_reaped,
        )

        return result

    async def terminate_workload(self, workload_id: str, reason: str = "ABORTED") -> CleanupReport:
        """Terminate a running workload and clean up resources."""
        self._lifecycle.emit_workload_terminated(workload_id, reason)
        return await self._local_provider.cleanup(workload_id)

    async def reap_orphans(self) -> int:
        """Reap all lingering or expired workloads."""
        return await self._reaper.reap_orphans()
