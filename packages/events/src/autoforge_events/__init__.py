"""
AutoForge AI — Canonical Runtime Event Model.

This package defines the immutable, strongly-typed event model used
throughout the AutoForge AI platform. Events are data-only records
of something that happened in the system. They contain no behaviour,
no handlers, no subscribers, and no event bus integration.

The event model is designed to be transported by the Event Bus
(see ``docs/EVENT_BUS.md``) in a future integration layer.
"""

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType

from autoforge_events.project_events import (
    ProjectCreated,
    ProjectUpdated,
    ProjectArchived,
    ProjectDeleted,
)

from autoforge_events.task_events import (
    TaskCreated,
    TaskUpdated,
    TaskQueued,
    TaskReady,
    TaskStarted,
    TaskPaused,
    TaskResumed,
    TaskCompleted,
    TaskFailed,
    TaskCancelled,
    TaskBlocked,
    TaskDeleted,
)

from autoforge_events.execution_events import (
    ExecutionStarted,
    ExecutionCompleted,
    ExecutionFailed,
    ExecutionPaused,
    ExecutionResumed,
    ExecutionCancelled,
    ExecutionTimedOut,
)

from autoforge_events.artifact_events import (
    ArtifactCreated,
    ArtifactUpdated,
    ArtifactDeleted,
)

from autoforge_events.memory_events import (
    MemoryStored,
    MemoryUpdated,
    MemoryDeleted,
    MemoryRetrieved,
)

from autoforge_events.workload_events import (
    WorkloadCreated,
    WorkloadStarted,
    WorkloadCompleted,
    WorkloadFailed,
    WorkloadTimeout,
    WorkloadTerminated,
    WorkloadPolicyRejected,
    WorkloadNetworkBlocked,
    WorkloadFilesystemViolation,
    WorkloadResourceLimit,
    WorkloadSecretAccessBlocked,
    WorkloadCleanupCompleted,
)

__all__ = [
    # Base
    "BaseEvent",
    # Enums
    "EventCategory",
    "EventType",
    # Project events
    "ProjectCreated",
    "ProjectUpdated",
    "ProjectArchived",
    "ProjectDeleted",
    # Task events
    "TaskCreated",
    "TaskUpdated",
    "TaskQueued",
    "TaskReady",
    "TaskStarted",
    "TaskPaused",
    "TaskResumed",
    "TaskCompleted",
    "TaskFailed",
    "TaskCancelled",
    "TaskBlocked",
    "TaskDeleted",
    # Execution events
    "ExecutionStarted",
    "ExecutionCompleted",
    "ExecutionFailed",
    "ExecutionPaused",
    "ExecutionResumed",
    "ExecutionCancelled",
    "ExecutionTimedOut",
    # Artifact events
    "ArtifactCreated",
    "ArtifactUpdated",
    "ArtifactDeleted",
    # Memory events
    "MemoryStored",
    "MemoryUpdated",
    "MemoryDeleted",
    "MemoryRetrieved",
    # Workload events
    "WorkloadCreated",
    "WorkloadStarted",
    "WorkloadCompleted",
    "WorkloadFailed",
    "WorkloadTimeout",
    "WorkloadTerminated",
    "WorkloadPolicyRejected",
    "WorkloadNetworkBlocked",
    "WorkloadFilesystemViolation",
    "WorkloadResourceLimit",
    "WorkloadSecretAccessBlocked",
    "WorkloadCleanupCompleted",
]