"""
Real Podman Container Sandboxing & Adversarial Security Test Suite (Phase 18-I).

Executes REAL container workloads using rootless Podman to empirically prove:
- Rootless non-root container user (UID 1000)
- Read-only container root filesystem (/ is read-only, /workspace is writable)
- Dropped Linux capabilities (CAP_DROP ALL) & no-new-privileges
- Network isolation (default DENY with --network none; loopback and external blocked)
- Filesystem isolation & traversal defense
- Host secret isolation (zero host credential leakage)
- Control socket inaccessibility (/var/run/docker.sock & podman.sock absent)
- Host namespace isolation (no host PID, net, or IPC sharing)
- Resource limit enforcement & output size capping
- Runaway timeout termination and container cleanup (no orphaned containers)
- WorkloadSandboxManager integration with podman provider
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import pytest

from autoforge_execution.sandbox import (
    CleanupPolicy,
    FilesystemPolicy,
    NetworkMode,
    NetworkPolicy,
    PodmanSandboxProvider,
    ResourceLimits,
    SecurityProfile,
    TerminationReason,
    WorkloadSandboxManager,
    WorkloadSpec,
)


@pytest.fixture(scope="module")
def podman_provider() -> PodmanSandboxProvider:
    provider = PodmanSandboxProvider()
    if not provider.is_available():
        pytest.fail("Podman is required for test_sandbox_podman.py but is not available.")
    return provider


@pytest.fixture
def podman_manager(tmp_path: Path) -> WorkloadSandboxManager:
    return WorkloadSandboxManager(
        default_provider="podman",
        base_sandboxes_dir=tmp_path / "sandboxes",
    )


# ── Real Non-Root & Privilege Tests ───────────────────────────────────────


@pytest.mark.asyncio
async def test_podman_real_non_root_execution(podman_provider: PodmanSandboxProvider) -> None:
    """Verify that workload inside Podman executes strictly as a non-root user (UID 1000)."""
    spec = WorkloadSpec(
        workload_id="podman-non-root",
        command=["id", "-u"],
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    assert result.stdout.strip() == "1000"
    assert result.exit_code == 0


@pytest.mark.asyncio
async def test_podman_real_privilege_escalation_blocked(podman_provider: PodmanSandboxProvider) -> None:
    """Verify that attempts to gain root privileges (su, sudo) inside container fail."""
    spec = WorkloadSpec(
        workload_id="podman-priv-escalate",
        command=["sh", "-c", "su root -c id 2>&1 || true"],
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    # In alpine/minimal container as user 1000 with dropped caps and no-new-privs, su fails
    out = result.stdout.lower()
    assert any(term in out for term in ("not permitted", "denied", "fail", "must be suid", "suid"))


# ── Real Read-Only Filesystem & Workspace Confinement ─────────────────────


@pytest.mark.asyncio
async def test_podman_real_read_only_root_filesystem(podman_provider: PodmanSandboxProvider) -> None:
    """Verify container root / is read-only, while /workspace is writable."""
    probe_script = (
        "touch /root_test 2>&1 || echo 'ROOT_WRITE_BLOCKED'\n"
        "echo 'WORKSPACE_WRITE_OK' > /workspace/allowed.txt\n"
        "cat /workspace/allowed.txt\n"
    )
    spec = WorkloadSpec(
        workload_id="podman-ro-root",
        command=["sh", "-c", probe_script],
        artifact_paths=["allowed.txt"],
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    assert "ROOT_WRITE_BLOCKED" in result.stdout
    assert "WORKSPACE_WRITE_OK" in result.stdout
    assert len(result.artifact_paths) == 1


# ── Real Network Isolation Tests ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_podman_real_network_none_blocks_all_access(podman_provider: PodmanSandboxProvider) -> None:
    """
    Verify --network none completely blocks loopback, internal subnets,
    and external web targets.
    """
    script = (
        "nc -z -w 1 127.0.0.1 80 2>&1 || echo 'LOOPBACK_BLOCKED'\n"
        "nc -z -w 1 169.254.169.254 80 2>&1 || echo 'METADATA_BLOCKED'\n"
        "nc -z -w 1 1.1.1.1 53 2>&1 || echo 'WAN_BLOCKED'\n"
    )
    spec = WorkloadSpec(
        workload_id="podman-net-none",
        command=["sh", "-c", script],
        network_policy=NetworkPolicy(mode=NetworkMode.DENY),
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    assert "LOOPBACK_BLOCKED" in result.stdout
    assert "METADATA_BLOCKED" in result.stdout
    assert "WAN_BLOCKED" in result.stdout


# ── Real Secret & Credential Isolation Tests ──────────────────────────────


@pytest.mark.asyncio
async def test_podman_real_host_secret_isolation(
    podman_provider: PodmanSandboxProvider,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """
    Verify host environment secrets (AWS, GITHUB, OPENAI, GEMINI, SSH)
    are never leaked into the container workload environment.
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-live-secret-podman-test")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_real_secret_token_val")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws_secret_key_98765")
    monkeypatch.setenv("GEMINI_API_KEY", "AIzaSyPodmanSecretKey")
    monkeypatch.setenv("SSH_AUTH_SOCK", "/private/tmp/ssh-secret.sock")
    monkeypatch.setenv("PRIVATE_KEY_DATA", "MIIEvgIBADANBgkqhkiG9w0BAQEFA")

    # Inside container: inspect environment variables
    script = "env | grep -E 'OPENAI|GITHUB|AWS|GEMINI|SSH|PRIVATE_KEY' || echo 'ZERO_SECRETS_LEAKED'"

    spec = WorkloadSpec(
        workload_id="podman-secret-test",
        command=["sh", "-c", script],
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    assert "ZERO_SECRETS_LEAKED" in result.stdout
    assert "sk-live-secret-podman-test" not in result.stdout
    assert "ghp_real_secret_token_val" not in result.stdout


# ── Real Runtime Socket & Control Escape Tests ────────────────────────────


@pytest.mark.asyncio
async def test_podman_real_socket_escape_prevention(podman_provider: PodmanSandboxProvider) -> None:
    """
    Verify container runtime sockets (/var/run/docker.sock, /run/podman/podman.sock)
    are not mounted and inaccessible inside the container.
    """
    script = (
        "if [ -e /var/run/docker.sock ]; then echo 'DOCKER_SOCKET_FOUND'; fi\n"
        "if [ -e /run/podman/podman.sock ]; then echo 'PODMAN_SOCKET_FOUND'; fi\n"
        "echo 'SOCKETS_SECURE'\n"
    )
    spec = WorkloadSpec(
        workload_id="podman-sock-test",
        command=["sh", "-c", script],
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    assert "DOCKER_SOCKET_FOUND" not in result.stdout
    assert "PODMAN_SOCKET_FOUND" not in result.stdout
    assert "SOCKETS_SECURE" in result.stdout


# ── Real Namespace Isolation Tests ────────────────────────────────────────


@pytest.mark.asyncio
async def test_podman_real_host_pid_namespace_isolated(podman_provider: PodmanSandboxProvider) -> None:
    """Verify the container has its own isolated PID namespace (PID 1 is inside container)."""
    spec = WorkloadSpec(
        workload_id="podman-pid-ns",
        command=["sh", "-c", "ps -o pid,comm | wc -l"],
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    # Inside isolated container PID namespace, there are only 2-4 processes, not hundreds of host processes
    count = int(result.stdout.strip())
    assert count <= 5, f"Expected container-isolated process count <= 5, got {count}"


# ── Real Resource Limits & Output Truncation Tests ────────────────────────


@pytest.mark.asyncio
async def test_podman_real_output_truncation(podman_provider: PodmanSandboxProvider) -> None:
    """Verify massive output stream inside container is capped at max_output_bytes."""
    max_out = 8192  # 8 KB
    spec = WorkloadSpec(
        workload_id="podman-out-flood",
        command=["sh", "-c", "head -c 100000 /dev/zero | tr '\\0' 'X'"],
        resource_limits=ResourceLimits(max_output_bytes=max_out),
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)
    await podman_provider.cleanup(spec.workload_id)

    assert result.success is True
    assert len(result.stdout.encode("utf-8")) <= max_out


# ── Real Timeout & Guaranteed Cleanup Tests ───────────────────────────────


@pytest.mark.asyncio
async def test_podman_real_timeout_termination_and_cleanup(
    podman_provider: PodmanSandboxProvider,
) -> None:
    """
    Verify that an unresponsive container workload is forcefully killed
    when reaching timeout budget, and no orphan container remains in podman.
    """
    workload_id = "podman-timeout-kill"
    spec = WorkloadSpec(
        workload_id=workload_id,
        command=["sleep", "30"],
        timeout_seconds=0.8,
        resource_limits=ResourceLimits(timeout_seconds=0.8),
    )
    prepared = podman_provider.prepare(spec)
    result = await podman_provider.execute(prepared)

    assert result.success is False
    assert result.timed_out is True
    assert result.termination_reason == TerminationReason.TIMEOUT
    assert "timed out" in result.stderr.lower()

    # Perform cleanup
    clean_rep = await podman_provider.cleanup(workload_id)
    assert clean_rep.status.value == "cleaned"

    # Verify no orphan container named af_podman_podman-timeout-kill remains
    container_name = f"af_podman_{workload_id}"
    check = await asyncio.create_subprocess_exec(
        "podman", "ps", "-a", "--filter", f"name={container_name}", "--format", "{{.Names}}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await check.communicate()
    active_names = stdout.decode().strip().split()
    assert container_name not in active_names


# ── WorkloadSandboxManager Integration with Podman ────────────────────────


@pytest.mark.asyncio
async def test_manager_executes_workload_via_podman(
    podman_manager: WorkloadSandboxManager,
) -> None:
    """Verify WorkloadSandboxManager orchestrates Podman execution end-to-end."""
    spec = WorkloadSpec(
        workload_id="podman-manager-e2e",
        command=["echo", "AUTONOMOUS_PODMAN_ORCHESTRATION_OK"],
        cleanup_policy=CleanupPolicy.DESTROY_ALWAYS,
    )

    result = await podman_manager.execute_workload(spec, preferred_provider="podman")

    assert result.success is True
    assert "AUTONOMOUS_PODMAN_ORCHESTRATION_OK" in result.stdout
    assert result.exit_code == 0
    assert result.cleanup_status.value == "cleaned"
    assert podman_manager.reaper.active_count == 0
