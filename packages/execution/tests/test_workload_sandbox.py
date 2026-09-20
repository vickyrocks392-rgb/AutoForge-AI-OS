"""
Unit and lifecycle tests for Workload Sandboxing subsystem (Phase 18-I).

Verifies:
- Deterministic lifecycle state transitions
- Canonical event emission to event sink
- Process group execution and stdout/stderr capture
- Resource usage measurement
- Artifact collection from isolated sandbox workspace
- Non-zero failure and timeout handling
- WorkloadReaper cleanup and workspace disposal
- SandboxedWorkspaceEnvironment adapter compatibility
- DockerSandboxProvider contract, security flag generation, and unavailable error reporting
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path
from typing import Any

import pytest

from autoforge_events.event_types import EventCategory, EventType
from autoforge_events.workload_events import (
    WorkloadCleanupCompleted,
    WorkloadCompleted,
    WorkloadCreated,
    WorkloadFailed,
    WorkloadStarted,
    WorkloadTimeout,
)
from autoforge_execution.models import CommandSpec
from autoforge_execution.sandbox import (
    CleanupPolicy,
    DockerSandboxProvider,
    LocalRestrictedSandboxProvider,
    NetworkMode,
    ResourceLimits,
    SandboxLifecycleManager,
    SandboxRuntimeUnavailableError,
    SandboxedWorkspaceEnvironment,
    SecurityProfile,
    TerminationReason,
    WorkloadLifecycleState,
    WorkloadReaper,
    WorkloadSandboxManager,
    WorkloadSpec,
)


class MockEventSink:
    """Mock sink capturing published canonical events for testing."""

    def __init__(self) -> None:
        self.events: list[Any] = []

    def publish(self, event: Any) -> None:
        self.events.append(event)


@pytest.fixture
def temp_sandbox_root(tmp_path: Path) -> Path:
    sbx_root = tmp_path / "sandboxes"
    sbx_root.mkdir(parents=True, exist_ok=True)
    return sbx_root


@pytest.fixture
def mock_sink() -> MockEventSink:
    return MockEventSink()


@pytest.fixture
def sandbox_manager(temp_sandbox_root: Path, mock_sink: MockEventSink) -> WorkloadSandboxManager:
    return WorkloadSandboxManager(
        event_sink=mock_sink,
        default_provider="local_restricted",
        base_sandboxes_dir=temp_sandbox_root,
    )


# ── Lifecycle & Execution Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_successful_workload_execution(
    sandbox_manager: WorkloadSandboxManager,
    mock_sink: MockEventSink,
) -> None:
    """Test normal successful workload execution and event emission."""
    spec = WorkloadSpec(
        workload_id="sbx-success-001",
        project_id="proj-101",
        command=[sys.executable, "-c", "print('Hello from AutoForge Sandbox!')"],
        security_profile=SecurityProfile.UNTRUSTED,
    )

    result = await sandbox_manager.execute_workload(spec)

    assert result.success is True
    assert result.exit_code == 0
    assert "Hello from AutoForge Sandbox!" in result.stdout
    assert result.timed_out is False
    assert result.termination_reason == TerminationReason.NORMAL
    assert result.duration_seconds > 0.0
    assert result.resource_usage.process_count == 1

    # Verify canonical event progression
    event_types = [type(e) for e in mock_sink.events]
    assert WorkloadCreated in event_types
    assert WorkloadStarted in event_types
    assert WorkloadCompleted in event_types
    assert WorkloadCleanupCompleted in event_types

    # Check payload on WorkloadCompleted
    completed_event = next(e for e in mock_sink.events if isinstance(e, WorkloadCompleted))
    assert completed_event.workload_id == "sbx-success-001"
    assert completed_event.exit_code == 0


@pytest.mark.asyncio
async def test_artifact_collection_from_sandbox(
    sandbox_manager: WorkloadSandboxManager,
) -> None:
    """Verify that artifacts produced inside the sandbox are safely tracked and collected."""
    script = (
        "import os\n"
        "with open('output_metric.json', 'w') as f:\n"
        "    f.write('{\"status\": \"certified\"}')\n"
    )

    spec = WorkloadSpec(
        workload_id="sbx-artifact-002",
        command=[sys.executable, "-c", script],
        artifact_paths=["output_metric.json"],
    )

    result = await sandbox_manager.execute_workload(spec)

    assert result.success is True
    assert len(result.artifact_paths) == 1
    assert Path(result.artifact_paths[0]).name == "output_metric.json"


@pytest.mark.asyncio
async def test_failed_workload_execution(
    sandbox_manager: WorkloadSandboxManager,
    mock_sink: MockEventSink,
) -> None:
    """Verify non-zero return codes are captured as structured failures."""
    spec = WorkloadSpec(
        workload_id="sbx-failure-003",
        command=[sys.executable, "-c", "import sys; sys.stderr.write('Fatal Crash\\n'); sys.exit(42)"],
    )

    result = await sandbox_manager.execute_workload(spec)

    assert result.success is False
    assert result.exit_code == 42
    assert "Fatal Crash" in result.stderr
    assert result.termination_reason == TerminationReason.ERROR

    event_types = [type(e) for e in mock_sink.events]
    assert WorkloadFailed in event_types
    failed_event = next(e for e in mock_sink.events if isinstance(e, WorkloadFailed))
    assert failed_event.exit_code == 42


@pytest.mark.asyncio
async def test_workload_timeout_enforcement(
    sandbox_manager: WorkloadSandboxManager,
    mock_sink: MockEventSink,
) -> None:
    """Verify runaway workloads are forcefully terminated upon reaching timeout budget."""
    spec = WorkloadSpec(
        workload_id="sbx-timeout-004",
        command=[sys.executable, "-c", "import time; time.sleep(10.0)"],
        timeout_seconds=0.6,
        resource_limits=ResourceLimits(timeout_seconds=0.6),
    )

    result = await sandbox_manager.execute_workload(spec)

    assert result.success is False
    assert result.timed_out is True
    assert result.termination_reason == TerminationReason.TIMEOUT
    assert "timed out" in result.stderr.lower()

    event_types = [type(e) for e in mock_sink.events]
    assert WorkloadTimeout in event_types


@pytest.mark.asyncio
async def test_workspace_reaper_disposal(
    temp_sandbox_root: Path,
    mock_sink: MockEventSink,
) -> None:
    """Verify that sandbox workspace is completely deleted after execution when DESTROY_ALWAYS is set."""
    mgr = WorkloadSandboxManager(
        event_sink=mock_sink,
        default_provider="local_restricted",
        base_sandboxes_dir=temp_sandbox_root,
    )

    workload_id = "sbx-reaper-005"
    spec = WorkloadSpec(
        workload_id=workload_id,
        command=[sys.executable, "-c", "print('done')"],
        cleanup_policy=CleanupPolicy.DESTROY_ALWAYS,
    )

    result = await mgr.execute_workload(spec)
    assert result.success is True

    # Check that the sandbox workspace directory was destroyed
    workspace_path = temp_sandbox_root / workload_id
    assert not workspace_path.exists()
    assert mgr.reaper.active_count == 0


@pytest.mark.asyncio
async def test_sandboxed_workspace_environment_adapter(tmp_path: Path) -> None:
    """Verify SandboxedWorkspaceEnvironment functions as drop-in WorkspaceEnvironment replacement."""
    env = SandboxedWorkspaceEnvironment(
        workspace_root=tmp_path,
        preferred_provider="local_restricted",
    )

    cmd_spec = CommandSpec(
        argv=[sys.executable, "-c", "print('adapter test passed')"],
        timeout_seconds=5.0,
    )

    cmd_result = await env.execute_command(cmd_spec)

    assert cmd_result.passed is True
    assert cmd_result.exit_code == 0
    assert "adapter test passed" in cmd_result.stdout
    assert cmd_result.timed_out is False


# ── Docker Provider Contract Tests ────────────────────────────────────────


def test_docker_sandbox_provider_contract() -> None:
    """
    Test DockerSandboxProvider flag generation, security parameters,
    and unavailable runtime error reporting.
    """
    docker_provider = DockerSandboxProvider()

    spec = WorkloadSpec(
        workload_id="sbx-docker-006",
        command=["python3", "main.py"],
        resource_limits=ResourceLimits(
            max_memory_bytes=256 * 1024 * 1024,
            max_cpu_seconds=1.5,
            max_processes=16,
        ),
    )

    prepared = docker_provider.prepare(spec)
    args = docker_provider.build_docker_run_args(prepared)

    # Verify OCI security hardening arguments
    assert "docker" == args[0]
    assert "run" == args[1]
    assert "--rm" in args
    assert "--security-opt" in args
    assert "no-new-privileges:true" in args
    assert "--cap-drop" in args
    assert "ALL" in args
    assert "--user" in args
    assert "1000:1000" in args
    assert "--read-only" in args
    assert "--network" in args
    assert "none" in args
    assert "--memory" in args
    assert "256m" in args
    assert "--pids-limit" in args
    assert "16" in args


@pytest.mark.asyncio
async def test_docker_unavailable_error_reporting() -> None:
    """
    When Docker is unavailable on the host, attempting execution must raise
    SandboxRuntimeUnavailableError with 'DOCKER RUNTIME NOT AVAILABLE — INTEGRATION TEST DEFERRED'.
    """
    docker_provider = DockerSandboxProvider()

    if not docker_provider.is_available():
        spec = WorkloadSpec(
            workload_id="sbx-docker-unavail",
            command=["python3", "app.py"],
        )
        prepared = docker_provider.prepare(spec)

        with pytest.raises(SandboxRuntimeUnavailableError) as exc_info:
            await docker_provider.execute(prepared)

        assert "DOCKER RUNTIME NOT AVAILABLE — INTEGRATION TEST DEFERRED" in str(exc_info.value)
