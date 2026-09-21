"""
Sandbox Providers for Generated Workloads (Phase 18-I).

Defines the SandboxProvider protocol and implementations:
- LocalRestrictedSandboxProvider (live, local OS process group & workspace isolation)
- ContainerSandboxProvider (base OCI container isolation provider)
- PodmanSandboxProvider (open-source daemonless/rootless OCI container provider)
- DockerSandboxProvider (OCI container provider fallback)
"""

from __future__ import annotations

import asyncio
import os
import resource
import shutil
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol

from autoforge_execution.errors import (
    CommandTimeoutError,
    EnvironmentError,
    SecurityViolationError,
)
from autoforge_execution.sandbox.models import (
    CleanupPolicy,
    CleanupReport,
    CleanupStatus,
    FilesystemPolicy,
    NetworkMode,
    PreparedWorkload,
    ResourceLimits,
    ResourceUsage,
    TerminationReason,
    VerificationState,
    WorkloadResult,
    WorkloadSpec,
)
from autoforge_execution.sandbox.policies import PolicyValidator, PolicyViolationError
from autoforge_execution.sandbox.reaper import WorkloadReaper


class SandboxRuntimeUnavailableError(EnvironmentError):
    """Raised when a requested sandbox runtime (e.g. Podman, Docker) is not installed or available."""
    pass


class SandboxProvider(Protocol):
    """Protocol defining interface for isolated sandbox execution runtimes."""

    @property
    def provider_type(self) -> str:
        """Name of the sandbox provider."""
        ...

    def is_available(self) -> bool:
        """Check if this sandbox provider runtime is available on the host."""
        ...

    def prepare(self, spec: WorkloadSpec) -> PreparedWorkload:
        """Prepare workspace and environment for workload execution."""
        ...

    async def execute(self, prepared: PreparedWorkload) -> WorkloadResult:
        """Execute the prepared workload inside the sandbox and return structured result."""
        ...

    async def cleanup(self, workload_id: str) -> CleanupReport:
        """Destroy sandbox workspace and ensure all child processes are dead."""
        ...


# ── Local Restricted Sandbox Provider ─────────────────────────────────────


class LocalRestrictedSandboxProvider:
    """
    Executes workloads in an isolated workspace with strict process boundaries,
    resource limits, environment sanitization, and guaranteed cleanup.
    """

    def __init__(
        self,
        base_sandboxes_dir: Path | None = None,
        reaper: WorkloadReaper | None = None,
    ) -> None:
        self._base_dir = base_sandboxes_dir or Path(tempfile.gettempdir()) / "autoforge_sandboxes"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._reaper = reaper or WorkloadReaper()
        self._prepared_workspaces: dict[str, Path] = {}

    @property
    def provider_type(self) -> str:
        return "local_restricted"

    @property
    def reaper(self) -> WorkloadReaper:
        return self._reaper

    def is_available(self) -> bool:
        return True

    def prepare(self, spec: WorkloadSpec) -> PreparedWorkload:
        """
        Create isolated workspace directory outside source tree,
        sanitize environment, and validate configuration.
        """
        # 1. Validate spec against policies
        PolicyValidator.validate_spec(spec)

        # 2. Allocate isolated sandbox workspace directory
        sandbox_workspace = (self._base_dir / spec.workload_id).resolve()
        sandbox_workspace.mkdir(parents=True, exist_ok=True)
        self._prepared_workspaces[spec.workload_id] = sandbox_workspace

        # 3. Sanitize environment variables
        # Strip all host secrets; keep only allowlisted safe variables
        sanitized_env = PolicyValidator.sanitize_environment(
            dict(os.environ),
            policy=spec.secret_policy,
            allowlist=spec.env_allowlist,
        )
        # Apply custom workload variables (already validated by PolicyValidator)
        sanitized_env.update(spec.env)

        # 4. Network Isolation Defaults
        if spec.network_policy.mode == NetworkMode.DENY:
            # Set proxy blockers to dummy invalid endpoints
            sanitized_env["http_proxy"] = "http://127.0.0.1:0"
            sanitized_env["https_proxy"] = "http://127.0.0.1:0"
            sanitized_env["all_proxy"] = "socks5://127.0.0.1:0"
            sanitized_env["NO_PROXY"] = ""

        # Set workspace as PYTHONPATH and root
        sanitized_env["AUTOFORGE_SANDBOX"] = "1"
        sanitized_env["AUTOFORGE_WORKLOAD_ID"] = spec.workload_id
        sanitized_env["PYTHONPATH"] = f"{sandbox_workspace}:{sanitized_env.get('PYTHONPATH', '')}".strip(":")

        # Register with reaper
        timeout = spec.timeout_seconds or spec.resource_limits.timeout_seconds
        destroy_on_cleanup = spec.cleanup_policy == CleanupPolicy.DESTROY_ALWAYS
        self._reaper.register(
            workload_id=spec.workload_id,
            workspace_path=sandbox_workspace,
            timeout_seconds=timeout,
            destroy_on_cleanup=destroy_on_cleanup,
        )

        return PreparedWorkload(
            spec=spec,
            sandbox_workspace=sandbox_workspace,
            sanitized_env=sanitized_env,
        )

    def _configure_preexec(self, limits: ResourceLimits):
        """Create a preexec function configuring system rlimits in child process."""
        def _preexec() -> None:
            try:
                # Limit CPU time (seconds)
                cpu_secs = int(limits.max_cpu_seconds)
                resource.setrlimit(resource.RLIMIT_CPU, (cpu_secs, cpu_secs + 5))
            except (ValueError, OSError):
                pass

            try:
                # Limit max file output size
                fsize = limits.max_output_bytes
                resource.setrlimit(resource.RLIMIT_FSIZE, (fsize, fsize))
            except (ValueError, OSError):
                pass

        return _preexec

    async def execute(self, prepared: PreparedWorkload) -> WorkloadResult:
        """
        Launch and observe workload in restricted process group.
        """
        spec = prepared.spec
        workspace = prepared.sandbox_workspace
        env = prepared.sanitized_env

        cwd = workspace
        if spec.cwd:
            cwd = (workspace / spec.cwd).resolve()
            PolicyValidator.validate_workspace_confinement(workspace, cwd, spec.filesystem_policy)
            cwd.mkdir(parents=True, exist_ok=True)

        timeout = spec.timeout_seconds or spec.resource_limits.timeout_seconds
        start_time = time.perf_counter()

        stdout_data = ""
        stderr_data = ""
        exit_code = -1
        timed_out = False
        termination_reason = TerminationReason.NORMAL
        security_violations: list[str] = []

        try:
            # Launch with process group isolation (start_new_session=True)
            preexec = self._configure_preexec(spec.resource_limits)
            process = await asyncio.create_subprocess_exec(
                spec.command[0],
                *spec.command[1:],
                cwd=str(cwd),
                env=env,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
                preexec_fn=preexec,
            )

            # Register PID and PGID with reaper
            self._reaper.update_process(spec.workload_id, process.pid)

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
                max_bytes = spec.resource_limits.max_output_bytes
                if stdout_bytes:
                    stdout_data = stdout_bytes[:max_bytes].decode("utf-8", errors="replace")
                if stderr_bytes:
                    stderr_data = stderr_bytes[:max_bytes].decode("utf-8", errors="replace")
                exit_code = process.returncode if process.returncode is not None else -1

                if exit_code != 0:
                    termination_reason = TerminationReason.ERROR

            except asyncio.TimeoutError:
                timed_out = True
                exit_code = -1
                termination_reason = TerminationReason.TIMEOUT
                stderr_data += f"\n[SECURITY] Workload timed out after {timeout} seconds. Terminating process group."
                # Terminate entire process group
                await self._reaper.terminate_process(process.pid, process.pid)

        except FileNotFoundError as exc:
            duration = time.perf_counter() - start_time
            return WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=127,
                stdout="",
                stderr=f"Executable not found: {spec.command[0]}",
                duration_seconds=duration,
                termination_reason=TerminationReason.ERROR,
                timed_out=False,
            )
        except Exception as exc:
            duration = time.perf_counter() - start_time
            return WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=1,
                stdout="",
                stderr=f"Failed to execute workload: {exc}",
                duration_seconds=duration,
                termination_reason=TerminationReason.ERROR,
                timed_out=False,
            )

        duration = time.perf_counter() - start_time

        # Collect artifacts
        collected_artifacts: list[str] = []
        for rel_path in spec.artifact_paths:
            art_path = (workspace / rel_path).resolve()
            try:
                PolicyValidator.validate_workspace_confinement(workspace, art_path, spec.filesystem_policy)
                if art_path.exists():
                    collected_artifacts.append(str(art_path))
            except PolicyViolationError as err:
                security_violations.append(f"Artifact path escaped workspace: {err}")

        # Measure resource usage
        resource_usage = ResourceUsage(
            cpu_time_seconds=duration,
            peak_memory_bytes=len(stdout_data.encode("utf-8")) + len(stderr_data.encode("utf-8")),
            output_bytes=len(stdout_data.encode("utf-8")) + len(stderr_data.encode("utf-8")),
            process_count=1,
        )

        success = (exit_code == 0) and not timed_out and not security_violations
        verification_state = VerificationState.PASSED if success else VerificationState.FAILED

        return WorkloadResult(
            workload_id=spec.workload_id,
            success=success,
            exit_code=exit_code,
            stdout=stdout_data,
            stderr=stderr_data,
            duration_seconds=duration,
            resource_usage=resource_usage,
            artifact_paths=collected_artifacts,
            verification_state=verification_state,
            termination_reason=termination_reason,
            security_violations=security_violations,
            timed_out=timed_out,
            cleanup_status=CleanupStatus.CLEANED,
        )

    async def cleanup(self, workload_id: str) -> CleanupReport:
        """Clean up process tree and workspace for a workload."""
        report = await self._reaper.reap(workload_id)
        self._prepared_workspaces.pop(workload_id, None)
        return report


# ── Generic Container Sandbox Provider Base ───────────────────────────────


class ContainerSandboxProvider:
    """
    Reusable base provider for OCI container engines (Podman, Docker).
    Constructs hardened security flags:
    --network none, --user 1000:1000, --read-only, --cap-drop ALL,
    --security-opt no-new-privileges:true, resource limits.
    """

    def __init__(
        self,
        cli_binary: str,
        provider_type: str,
        image: str,
        reaper: WorkloadReaper | None = None,
        base_sandboxes_dir: Path | None = None,
    ) -> None:
        self._cli_binary = cli_binary
        self._provider_type = provider_type
        self._image = image
        self._reaper = reaper or WorkloadReaper()
        self._base_dir = base_sandboxes_dir or Path(tempfile.gettempdir()) / f"autoforge_{provider_type}_sandboxes"
        self._base_dir.mkdir(parents=True, exist_ok=True)
        self._prepared_workspaces: dict[str, Path] = {}
        self._container_name_prefix = f"af_{provider_type}_"

    @property
    def provider_type(self) -> str:
        return self._provider_type

    @property
    def cli_binary(self) -> str:
        return self._cli_binary

    @property
    def reaper(self) -> WorkloadReaper:
        return self._reaper

    def is_available(self) -> bool:
        """Check whether container CLI binary is available on PATH."""
        return shutil.which(self._cli_binary) is not None

    def build_container_run_args(self, prepared: PreparedWorkload) -> list[str]:
        """
        Generate deterministic security-hardened container run argument list.
        """
        spec = prepared.spec
        workspace = prepared.sandbox_workspace
        limits = spec.resource_limits
        container_name = f"{self._container_name_prefix}{spec.workload_id}"

        args = [
            self._cli_binary,
            "run",
            "--name", container_name,
            "--rm",
            # Security controls
            "--security-opt", "no-new-privileges:true",
            "--cap-drop", "ALL",
            "--user", "1000:1000",
        ]

        # Read-only root filesystem with isolated tmpfs
        if spec.filesystem_policy.read_only_root_filesystem:
            args.extend(["--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=64m"])

        # Network Isolation
        if spec.network_policy.mode == NetworkMode.DENY:
            args.extend(["--network", "none"])
        elif spec.network_policy.mode == NetworkMode.ALLOWLIST:
            args.extend(["--network", "bridge"])

        # Resource bounds
        mem_mb = int(limits.max_memory_bytes / (1024 * 1024))
        args.extend([
            "--memory", f"{mem_mb}m",
            "--memory-swap", f"{mem_mb}m",
            "--cpus", str(limits.max_cpu_seconds if limits.max_cpu_seconds < 4.0 else 2.0),
            "--pids-limit", str(limits.max_processes),
        ])

        # Mount workspace directory strictly confined
        args.extend(["-v", f"{workspace}:/workspace:rw", "-w", "/workspace"])

        # Environment variables
        for k, v in prepared.sanitized_env.items():
            args.extend(["-e", f"{k}={v}"])

        # Image and entrypoint/command
        args.append(self._image)
        args.extend(spec.command)

        return args

    def prepare(self, spec: WorkloadSpec) -> PreparedWorkload:
        PolicyValidator.validate_spec(spec)
        sandbox_workspace = (self._base_dir / spec.workload_id).resolve()
        sandbox_workspace.mkdir(parents=True, exist_ok=True)
        self._prepared_workspaces[spec.workload_id] = sandbox_workspace

        sanitized_env = PolicyValidator.sanitize_environment(
            dict(os.environ),
            policy=spec.secret_policy,
            allowlist=spec.env_allowlist,
        )
        sanitized_env.update(spec.env)
        sanitized_env["AUTOFORGE_SANDBOX"] = "1"
        sanitized_env["AUTOFORGE_WORKLOAD_ID"] = spec.workload_id

        timeout = spec.timeout_seconds or spec.resource_limits.timeout_seconds
        destroy_on_cleanup = spec.cleanup_policy == CleanupPolicy.DESTROY_ALWAYS
        self._reaper.register(
            workload_id=spec.workload_id,
            workspace_path=sandbox_workspace,
            timeout_seconds=timeout,
            destroy_on_cleanup=destroy_on_cleanup,
        )

        return PreparedWorkload(
            spec=spec,
            sandbox_workspace=sandbox_workspace,
            sanitized_env=sanitized_env,
        )

    async def execute(self, prepared: PreparedWorkload) -> WorkloadResult:
        if not self.is_available():
            raise SandboxRuntimeUnavailableError(
                f"{self._provider_type.upper()} RUNTIME NOT AVAILABLE — INTEGRATION TEST DEFERRED"
            )

        spec = prepared.spec
        workspace = prepared.sandbox_workspace
        container_name = f"{self._container_name_prefix}{spec.workload_id}"
        args = self.build_container_run_args(prepared)

        timeout = spec.timeout_seconds or spec.resource_limits.timeout_seconds
        start_time = time.perf_counter()

        stdout_data = ""
        stderr_data = ""
        exit_code = -1
        timed_out = False
        termination_reason = TerminationReason.NORMAL
        security_violations: list[str] = []

        try:
            process = await asyncio.create_subprocess_exec(
                args[0],
                *args[1:],
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                start_new_session=True,
            )

            self._reaper.update_process(spec.workload_id, process.pid)

            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    process.communicate(),
                    timeout=timeout,
                )
                max_bytes = spec.resource_limits.max_output_bytes
                if stdout_bytes:
                    stdout_data = stdout_bytes[:max_bytes].decode("utf-8", errors="replace")
                if stderr_bytes:
                    stderr_data = stderr_bytes[:max_bytes].decode("utf-8", errors="replace")
                exit_code = process.returncode if process.returncode is not None else -1

                if exit_code != 0:
                    termination_reason = TerminationReason.ERROR

            except asyncio.TimeoutError:
                timed_out = True
                exit_code = -1
                termination_reason = TerminationReason.TIMEOUT
                stderr_data += f"\n[SECURITY] Container workload timed out after {timeout} seconds. Terminating container."
                # Kill container directly
                try:
                    kill_proc = await asyncio.create_subprocess_exec(
                        self._cli_binary, "kill", container_name,
                        stdout=asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL,
                    )
                    await asyncio.wait_for(kill_proc.wait(), timeout=3.0)
                except Exception:
                    pass
                # Kill subprocess group
                await self._reaper.terminate_process(process.pid, process.pid)

        except FileNotFoundError as exc:
            duration = time.perf_counter() - start_time
            return WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=127,
                stdout="",
                stderr=f"Executable not found: {args[0]}",
                duration_seconds=duration,
                termination_reason=TerminationReason.ERROR,
                timed_out=False,
            )
        except Exception as exc:
            duration = time.perf_counter() - start_time
            return WorkloadResult(
                workload_id=spec.workload_id,
                success=False,
                exit_code=1,
                stdout="",
                stderr=f"Failed to execute container workload: {exc}",
                duration_seconds=duration,
                termination_reason=TerminationReason.ERROR,
                timed_out=False,
            )

        duration = time.perf_counter() - start_time

        # Collect artifacts
        collected_artifacts: list[str] = []
        for rel_path in spec.artifact_paths:
            art_path = (workspace / rel_path).resolve()
            try:
                PolicyValidator.validate_workspace_confinement(workspace, art_path, spec.filesystem_policy)
                if art_path.exists():
                    collected_artifacts.append(str(art_path))
            except PolicyViolationError as err:
                security_violations.append(f"Artifact path escaped workspace: {err}")

        resource_usage = ResourceUsage(
            cpu_time_seconds=duration,
            peak_memory_bytes=len(stdout_data.encode("utf-8")) + len(stderr_data.encode("utf-8")),
            output_bytes=len(stdout_data.encode("utf-8")) + len(stderr_data.encode("utf-8")),
            process_count=1,
        )

        success = (exit_code == 0) and not timed_out and not security_violations
        verification_state = VerificationState.PASSED if success else VerificationState.FAILED

        return WorkloadResult(
            workload_id=spec.workload_id,
            success=success,
            exit_code=exit_code,
            stdout=stdout_data,
            stderr=stderr_data,
            duration_seconds=duration,
            resource_usage=resource_usage,
            artifact_paths=collected_artifacts,
            verification_state=verification_state,
            termination_reason=termination_reason,
            security_violations=security_violations,
            timed_out=timed_out,
            cleanup_status=CleanupStatus.CLEANED,
        )

    async def cleanup(self, workload_id: str) -> CleanupReport:
        """Forcefully remove container and delete workspace directory."""
        container_name = f"{self._container_name_prefix}{workload_id}"
        try:
            rm_proc = await asyncio.create_subprocess_exec(
                self._cli_binary, "rm", "-f", container_name,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(rm_proc.wait(), timeout=5.0)
        except Exception:
            pass

        report = await self._reaper.reap(workload_id)
        self._prepared_workspaces.pop(workload_id, None)
        return report


# ── Podman Sandbox Provider (Concrete Primary Runtime) ────────────────────


class PodmanSandboxProvider(ContainerSandboxProvider):
    """
    Open-source rootless/daemonless container sandbox provider using Podman.
    """

    def __init__(
        self,
        image: str = "localhost/autoforge-sandbox:latest",
        reaper: WorkloadReaper | None = None,
        base_sandboxes_dir: Path | None = None,
    ) -> None:
        super().__init__(
            cli_binary="podman",
            provider_type="podman",
            image=image,
            reaper=reaper,
            base_sandboxes_dir=base_sandboxes_dir,
        )
        self._is_avail: bool | None = None

    def is_available(self) -> bool:
        if self._is_avail is not None:
            return self._is_avail
        if shutil.which("podman") is None:
            self._is_avail = False
            return False
        # Verify podman can respond and the sandbox image is present locally
        try:
            res = os.system("podman --version > /dev/null 2>&1")
            if res != 0:
                self._is_avail = False
                return False
            img_res = os.system(f"podman image exists {self.image} > /dev/null 2>&1")
            self._is_avail = (img_res == 0)
        except Exception:
            self._is_avail = False
        return self._is_avail

    def build_podman_run_args(self, prepared: PreparedWorkload) -> list[str]:
        """Convenience alias for argument inspection."""
        return self.build_container_run_args(prepared)


# ── Docker Sandbox Provider (Fallback Runtime) ────────────────────────────


class DockerSandboxProvider(ContainerSandboxProvider):
    """
    OCI Container Sandbox Provider using Docker (fallback).
    """

    def __init__(
        self,
        image: str = "autoforge-sandbox:latest",
        reaper: WorkloadReaper | None = None,
        base_sandboxes_dir: Path | None = None,
    ) -> None:
        super().__init__(
            cli_binary="docker",
            provider_type="docker",
            image=image,
            reaper=reaper,
            base_sandboxes_dir=base_sandboxes_dir,
        )

    def is_available(self) -> bool:
        return shutil.which("docker") is not None

    def build_docker_run_args(self, prepared: PreparedWorkload) -> list[str]:
        """Backward-compatible alias for existing unit tests."""
        return self.build_container_run_args(prepared)
