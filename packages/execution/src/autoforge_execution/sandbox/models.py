"""
Domain models and policies for Generated Workload Containerization + Sandboxing (Phase 18-I).

Defines specifications, security policies, resource limits, lifecycle states,
and structured outputs for isolated workload execution.
"""

from __future__ import annotations

import os
import uuid
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid_str() -> str:
    return str(uuid.uuid4())


class SecurityProfile(str, Enum):
    """Classification of trust level for a generated workload."""
    UNTRUSTED = "untrusted"
    SEMI_TRUSTED = "semi_trusted"
    RESTRICTED = "restricted"


class NetworkMode(str, Enum):
    """Network accessibility policy for the sandbox."""
    DENY = "deny"
    ALLOWLIST = "allowlist"


class CleanupPolicy(str, Enum):
    """Policy for environment disposal upon workload completion or failure."""
    DESTROY_ALWAYS = "destroy_always"
    RETAIN_ON_FAILURE = "retain_on_failure"


class WorkloadLifecycleState(str, Enum):
    """Deterministic states for a sandboxed workload lifecycle."""
    CREATED = "created"
    PREPARING = "preparing"
    VALIDATING_POLICY = "validating_policy"
    STARTING = "starting"
    EXECUTING = "executing"
    OBSERVING = "observing"
    COLLECTING_RESULTS = "collecting_results"
    VERIFYING = "verifying"
    TERMINATING = "terminating"
    CLEANING_UP = "cleaning_up"
    DESTROYED = "destroyed"
    FAILED = "failed"


class TerminationReason(str, Enum):
    """Reason for workload completion or termination."""
    NORMAL = "normal"
    TIMEOUT = "timeout"
    RESOURCE_EXHAUSTED = "resource_exhausted"
    SECURITY_VIOLATION = "security_violation"
    ERROR = "error"
    ABORTED = "aborted"


class VerificationState(str, Enum):
    """Integrity and correctness status of workload output."""
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class CleanupStatus(str, Enum):
    """Outcome status of sandbox cleanup."""
    CLEANED = "cleaned"
    RETAINED = "retained"
    FAILED = "failed"


# ── Policies ─────────────────────────────────────────────────────────────


class FilesystemPolicy(BaseModel):
    """Security rules governing filesystem isolation for sandboxed workloads."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    enforce_workspace_confinement: bool = Field(default=True)
    allow_symlinks_outside_root: bool = Field(default=False)
    read_only_root_filesystem: bool = Field(default=True)
    disallowed_paths: tuple[str, ...] = Field(
        default=(
            "/etc",
            "/var",
            "/proc",
            "/sys",
            "/dev",
            "/root",
            "~",
            "/var/run/docker.sock",
            "/private",
        )
    )


class NetworkPolicy(BaseModel):
    """Security rules governing network access for sandboxed workloads."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    mode: NetworkMode = Field(default=NetworkMode.DENY)
    allowed_hosts: tuple[str, ...] = Field(default_factory=tuple)
    blocked_subnets: tuple[str, ...] = Field(
        default=(
            "127.0.0.0/8",      # Loopback
            "::1/128",          # IPv6 Loopback
            "10.0.0.0/8",       # RFC1918 Private
            "172.16.0.0/12",    # RFC1918 Private
            "192.168.0.0/16",   # RFC1918 Private
            "169.254.0.0/16",   # Link Local / Cloud Metadata (169.254.169.254)
        )
    )
    block_localhost: bool = Field(default=True)


class ResourceLimits(BaseModel):
    """Hard upper bounds on resource consumption for a workload."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    max_cpu_seconds: float = Field(default=30.0, gt=0.0)
    max_memory_bytes: int = Field(default=512 * 1024 * 1024, gt=0)  # 512 MB default
    max_output_bytes: int = Field(default=2 * 1024 * 1024, gt=0)    # 2 MB default
    max_processes: int = Field(default=32, gt=0)
    max_workspace_bytes: int = Field(default=100 * 1024 * 1024, gt=0) # 100 MB default
    timeout_seconds: float = Field(default=60.0, gt=0.0, le=3600.0)


class ProcessPolicy(BaseModel):
    """Rules controlling executable invocation and process creation."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    allow_shell: bool = Field(default=False)
    allow_privileged: bool = Field(default=False)
    run_as_root: bool = Field(default=False)
    disallowed_binaries: tuple[str, ...] = Field(
        default=(
            "mkfs",
            "dd",
            "shutdown",
            "reboot",
            "init",
            "systemctl",
            "sudo",
            "su",
            "pkexec",
            "chown",
            "chgrp",
        )
    )
    disallowed_commands: tuple[str, ...] = Field(
        default=(
            "rm -rf /",
            "rm -f -r /",
            "rm -r -f /",
            ":(){ :|:& };:",
            "chmod -R 777",
            "| bash",
            "| sh",
            "| zsh",
            "> /dev/sda",
            "> /dev/null",
        )
    )


class SecretPolicy(BaseModel):
    """Rules ensuring host credentials and secrets do not leak into workloads."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    disallowed_env_prefixes: tuple[str, ...] = Field(
        default=(
            "AWS_",
            "GITHUB_",
            "GH_",
            "OPENAI_",
            "ANTHROPIC_",
            "GEMINI_",
            "GOOGLE_",
            "AZURE_",
            "SECRET_",
            "PRIVATE_KEY",
            "ID_RSA",
            "TOKEN",
            "API_KEY",
            "PASSWORD",
            "SSH_",
            "DOCKER_",
            "KUBECONFIG",
        )
    )
    disallowed_env_keys: tuple[str, ...] = Field(
        default=(
            "LD_PRELOAD",
            "LD_LIBRARY_PATH",
            "DYLD_INSERT_LIBRARIES",
            "DYLD_LIBRARY_PATH",
        )
    )
    default_env_allowlist: tuple[str, ...] = Field(
        default=(
            "PATH",
            "LANG",
            "LC_ALL",
            "PYTHONUNBUFFERED",
            "PYTHONPATH",
            "HOME",
            "TMPDIR",
            "TERM",
        )
    )


# ── Workload Specification ───────────────────────────────────────────────


class WorkloadSpec(BaseModel):
    """
    Canonical specification of a generated or customer workload to execute.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    workload_id: str = Field(default_factory=_new_uuid_str)
    project_id: str = Field(default="project-default")
    command: list[str] = Field(..., min_length=1, description="Command argv list (no shell injection).")
    cwd: str | None = Field(default=None, description="Working directory relative to sandbox workspace.")
    env: dict[str, str] = Field(default_factory=dict, description="Custom workload environment variables.")
    env_allowlist: tuple[str, ...] = Field(default_factory=tuple, description="Optional extra allowed env vars.")

    # Policies
    filesystem_policy: FilesystemPolicy = Field(default_factory=FilesystemPolicy)
    network_policy: NetworkPolicy = Field(default_factory=NetworkPolicy)
    resource_limits: ResourceLimits = Field(default_factory=ResourceLimits)
    process_policy: ProcessPolicy = Field(default_factory=ProcessPolicy)
    secret_policy: SecretPolicy = Field(default_factory=SecretPolicy)
    cleanup_policy: CleanupPolicy = Field(default=CleanupPolicy.DESTROY_ALWAYS)
    security_profile: SecurityProfile = Field(default=SecurityProfile.UNTRUSTED)

    # Output & Artifacts
    artifact_paths: list[str] = Field(default_factory=list, description="Relative paths to collect after execution.")
    expected_outputs: list[str] = Field(default_factory=list)
    timeout_seconds: float | None = Field(default=None)


# ── Results & Telemetry ──────────────────────────────────────────────────


class ResourceUsage(BaseModel):
    """Measured resource consumption of an executed workload."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    cpu_time_seconds: float = Field(default=0.0)
    peak_memory_bytes: int = Field(default=0)
    output_bytes: int = Field(default=0)
    process_count: int = Field(default=1)


class WorkloadResult(BaseModel):
    """
    Structured outcome of a sandboxed workload execution.
    """
    model_config = ConfigDict(frozen=True, extra="forbid")

    workload_id: str
    success: bool
    exit_code: int
    stdout: str = Field(default="")
    stderr: str = Field(default="")
    duration_seconds: float = Field(default=0.0)
    resource_usage: ResourceUsage = Field(default_factory=ResourceUsage)
    artifact_paths: list[str] = Field(default_factory=list)
    verification_state: VerificationState = Field(default=VerificationState.PASSED)
    termination_reason: TerminationReason = Field(default=TerminationReason.NORMAL)
    security_violations: list[str] = Field(default_factory=list)
    timed_out: bool = Field(default=False)
    cleanup_status: CleanupStatus = Field(default=CleanupStatus.CLEANED)
    executed_at: datetime = Field(default_factory=_utc_now)


class PreparedWorkload(BaseModel):
    """Workload prepared for launch by a sandbox provider."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    spec: WorkloadSpec
    sandbox_workspace: Path
    sanitized_env: dict[str, str]
    created_at: datetime = Field(default_factory=_utc_now)


class CleanupReport(BaseModel):
    """Report produced upon sandbox destruction."""
    model_config = ConfigDict(frozen=True, extra="forbid")

    workload_id: str
    status: CleanupStatus
    orphans_reaped: int = 0
    duration_seconds: float = 0.0
    details: dict[str, Any] = Field(default_factory=dict)
