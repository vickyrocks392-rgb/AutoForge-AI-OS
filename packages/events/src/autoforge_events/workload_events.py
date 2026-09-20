"""
Workload sandboxing events for the AutoForge AI platform (Phase 18-I).

These events capture state changes and security occurrences in a sandboxed
workload's lifecycle: creation, execution, completion, failures, timeouts,
termination, and security policy rejections or violations.
"""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import Field

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType


class WorkloadBaseEvent(BaseEvent):
    """Base event for all workload sandboxing events."""

    aggregate_id: uuid.UUID = Field(
        default_factory=uuid.uuid4,
        description="Aggregate identifier (UUID).",
    )
    aggregate_type: str = Field(
        default="Workload",
        description="The type name of the aggregate.",
    )
    event_category: EventCategory = Field(
        default=EventCategory.WORKLOAD,
        description="The high-level category this event belongs to.",
    )


class WorkloadCreated(WorkloadBaseEvent):
    """Emitted when a sandboxed workload environment is initialized."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_CREATED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    project_id: str = Field(..., description="Project ID owning the workload.")
    provider_type: str = Field(..., description="Provider handling the sandbox (e.g. local_restricted, docker).")
    security_profile: str = Field(..., description="Security profile assigned to the workload.")
    workspace_path: str = Field(..., description="Path to isolated sandbox workspace.")


class WorkloadStarted(WorkloadBaseEvent):
    """Emitted when a sandboxed workload process begins execution."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_STARTED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    command: list[str] = Field(..., description="Command argv list.")
    timeout_seconds: float = Field(..., description="Timeout budget in seconds.")
    process_id: int | None = Field(default=None, description="Host PID or container PID.")


class WorkloadCompleted(WorkloadBaseEvent):
    """Emitted when a sandboxed workload finishes execution with exit code 0."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_COMPLETED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    exit_code: int = Field(default=0, description="Process return code.")
    duration_seconds: float = Field(..., description="Total execution duration in seconds.")
    artifact_count: int = Field(default=0, description="Number of produced artifacts extracted.")


class WorkloadFailed(WorkloadBaseEvent):
    """Emitted when a sandboxed workload exits with non-zero code or internal failure."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_FAILED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    exit_code: int = Field(..., description="Process return code.")
    error_message: str = Field(..., description="Error message or stderr excerpt.")
    duration_seconds: float = Field(..., description="Duration before failure.")


class WorkloadTimeout(WorkloadBaseEvent):
    """Emitted when a sandboxed workload exceeds its execution time budget."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_TIMEOUT,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    timeout_seconds: float = Field(..., description="Configured timeout threshold.")
    duration_seconds: float = Field(..., description="Elapsed duration.")


class WorkloadTerminated(WorkloadBaseEvent):
    """Emitted when a sandboxed workload is forcefully terminated."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_TERMINATED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    reason: str = Field(..., description="Reason for termination.")
    signal_used: str = Field(default="SIGKILL", description="Signal used to terminate process.")


class WorkloadPolicyRejected(WorkloadBaseEvent):
    """Emitted when a workload specification violates security policy before execution."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_POLICY_REJECTED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    policy_name: str = Field(..., description="Name of policy that rejected execution.")
    violation_details: str = Field(..., description="Details of the policy violation.")


class WorkloadNetworkBlocked(WorkloadBaseEvent):
    """Emitted when a workload attempts an unauthorized network operation."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_NETWORK_BLOCKED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    target_destination: str = Field(..., description="Attempted destination host/IP or socket.")
    rule: str = Field(default="DEFAULT_DENY", description="Enforced rule.")


class WorkloadFilesystemViolation(WorkloadBaseEvent):
    """Emitted when a workload attempts path traversal or unauthorized filesystem access."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_FILESYSTEM_VIOLATION,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    attempted_path: str = Field(..., description="Attempted file path or symlink target.")
    violation_type: str = Field(..., description="Type of filesystem violation.")


class WorkloadResourceLimit(WorkloadBaseEvent):
    """Emitted when a workload exceeds configured resource limits."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_RESOURCE_LIMIT,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    resource_type: str = Field(..., description="Resource type exceeded (memory, cpu, output_size, processes).")
    observed_value: float = Field(..., description="Measured resource usage.")
    limit_value: float = Field(..., description="Configured limit threshold.")


class WorkloadSecretAccessBlocked(WorkloadBaseEvent):
    """Emitted when a workload attempts access to host secrets or credentials."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_SECRET_ACCESS_BLOCKED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    secret_key_pattern: str = Field(..., description="Secret or credential pattern detected.")
    action_taken: str = Field(default="STRIPPED_OR_BLOCKED", description="Remediation action taken.")


class WorkloadCleanupCompleted(WorkloadBaseEvent):
    """Emitted when a workload sandbox workspace and processes are safely destroyed."""

    event_type: EventType = Field(
        default=EventType.WORKLOAD_CLEANUP_COMPLETED,
        description="The specific type of event.",
    )

    workload_id: str = Field(..., description="Unique workload identifier.")
    workspace_path: str = Field(..., description="Cleaned workspace path.")
    duration_seconds: float = Field(..., description="Time taken to perform cleanup.")
    orphans_reaped: int = Field(default=0, description="Count of processes or dangling resources cleaned up.")
