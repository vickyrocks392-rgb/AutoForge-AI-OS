"""
Event type definitions for the AutoForge AI platform.

Defines the canonical ``EventCategory`` and ``EventType`` enumerations
used by every event in the system.
"""

from __future__ import annotations

from enum import Enum


class EventCategory(str, Enum):
    """
    High-level category for a domain event.

    Categories group related event types together and are used for
    routing, filtering, and subscription patterns in the Event Bus.
    """

    PROJECT = "project"
    """Events related to project lifecycle (create, archive, etc.)."""

    TASK = "task"
    """Events related to task lifecycle (create, start, complete, etc.)."""

    EXECUTION = "execution"
    """Events related to execution sessions (start, complete, fail, etc.)."""

    ARTIFACT = "artifact"
    """Events related to artifacts (create, update, etc.)."""

    MEMORY = "memory"
    """Events related to memory entries (store, update, delete, etc.)."""

    SYSTEM_EVENT = "system_event"
    """Events related to system-level operations."""

    LOOP = "loop"
    """Events related to engineering loop lifecycle."""

    APPROVAL = "approval"
    """Events related to human approval flow."""

    FAILURE = "failure"
    """Events related to failures and recovery."""

    REVIEW = "review"
    """Events related to review engine."""

    SERVICE = "service"
    """Events related to infrastructure services."""

    CHECKPOINT = "checkpoint"
    """Events related to checkpoint creation and restoration."""


class EventType(str, Enum):
    """
    The specific type of a domain event.

    Each value represents a distinct occurrence in the system.
    Event types are strongly typed — they are not generic strings.
    """

    # ------------------------------------------------------------------
    # Project events
    # ------------------------------------------------------------------
    PROJECT_CREATED = "project.created"
    """A new project was created."""

    PROJECT_UPDATED = "project.updated"
    """An existing project was updated."""

    PROJECT_ARCHIVED = "project.archived"
    """A project was archived (soft-deleted)."""

    PROJECT_DELETED = "project.deleted"
    """A project was permanently deleted."""

    PROJECT_STARTED = "project.started"
    """Project execution begins."""

    PROJECT_PLANNING = "project.planning"
    """Planning phase begins."""

    PROJECT_RUNNING = "project.running"
    """Execution begins."""

    PROJECT_REVIEWING = "project.reviewing"
    """Awaiting human review."""

    PROJECT_PAUSED = "project.paused"
    """Execution paused."""

    PROJECT_RESUMED = "project.resumed"
    """Execution resumes."""

    PROJECT_COMPLETING = "project.completing"
    """Validating completion."""

    PROJECT_FINISHED = "project.finished"
    """Project completed."""

    PROJECT_FAILED = "project.failed"
    """Project failed."""

    PROJECT_CANCELLED = "project.cancelled"
    """Project cancelled."""

    # ------------------------------------------------------------------
    # Task events
    # ------------------------------------------------------------------
    TASK_CREATED = "task.created"
    """A new task was created within a project."""

    TASK_UPDATED = "task.updated"
    """An existing task was updated."""

    TASK_QUEUED = "task.queued"
    """A task was queued and is waiting for scheduling."""

    TASK_READY = "task.ready"
    """All task dependencies are satisfied; the task is ready to execute."""

    TASK_STARTED = "task.started"
    """A task has begun execution."""

    TASK_PAUSED = "task.paused"
    """A task was paused (e.g. waiting for external input)."""

    TASK_RESUMED = "task.resumed"
    """A paused task was resumed."""

    TASK_COMPLETED = "task.completed"
    """A task completed successfully."""

    TASK_FAILED = "task.failed"
    """A task failed with an error."""

    TASK_CANCELLED = "task.cancelled"
    """A task was cancelled before completion."""

    TASK_BLOCKED = "task.blocked"
    """A task is blocked by an unresolved dependency."""

    TASK_DELETED = "task.deleted"
    """A task was deleted."""

    TASK_DISPATCHED = "task.dispatched"
    """Task dispatched to worker."""

    TASK_RETRYING = "task.retrying"
    """Task retrying."""

    TASK_WAITING = "task.waiting"
    """Task waiting for approval."""

    # ------------------------------------------------------------------
    # Worker dispatch events
    # ------------------------------------------------------------------
    WORKER_DISPATCHED = "worker.dispatched"
    """Worker dispatched to task."""

    WORKER_ASSIGNED = "worker.assigned"
    """Capability-driven worker was assigned to a stage."""

    WORKER_STARTED = "worker.started"
    """The assigned worker actually started executing its loop."""

    WORKER_COMPLETED = "worker.completed"
    """The assigned worker finished executing successfully."""

    WORKER_FAILED = "worker.failed"
    """The assigned worker failed during execution."""

    # ------------------------------------------------------------------
    # Intent and planning events
    # ------------------------------------------------------------------
    INTENT_ANALYZED = "intent.analyzed"
    """Intent analysis completed."""

    PLAN_CREATED = "plan.created"
    """Execution plan created."""

    # ------------------------------------------------------------------
    # Execution events
    # ------------------------------------------------------------------
    EXECUTION_STARTED = "execution.started"
    """An execution session has started."""

    EXECUTION_COMPLETED = "execution.completed"
    """An execution session completed successfully."""

    EXECUTION_FAILED = "execution.failed"
    """An execution session failed with an error."""

    EXECUTION_PAUSED = "execution.paused"
    """An execution session was paused."""

    EXECUTION_RESUMED = "execution.resumed"
    """A paused execution session was resumed."""

    EXECUTION_CANCELLED = "execution.cancelled"
    """An execution session was cancelled."""

    EXECUTION_TIMED_OUT = "execution.timed_out"
    """An execution session exceeded its time limit."""

    # ------------------------------------------------------------------
    # Artifact events
    # ------------------------------------------------------------------
    ARTIFACT_CREATED = "artifact.created"
    """A new artifact was produced."""

    ARTIFACT_UPDATED = "artifact.updated"
    """An existing artifact was updated."""

    ARTIFACT_DELETED = "artifact.deleted"
    """An artifact was deleted."""

    # ------------------------------------------------------------------
    # Memory events
    # ------------------------------------------------------------------
    MEMORY_STORED = "memory.stored"
    """A new memory entry was stored."""

    MEMORY_UPDATED = "memory.updated"
    """An existing memory entry was updated."""

    MEMORY_DELETED = "memory.deleted"
    """A memory entry was deleted."""

    MEMORY_RETRIEVED = "memory.retrieved"
    """A memory entry was retrieved (read access)."""

    # ------------------------------------------------------------------
    # Loop lifecycle events
    # ------------------------------------------------------------------
    LOOP_STARTED = "loop.started"
    """Engineering loop begins."""

    LOOP_PLANNING = "loop.planning"
    """Loop in planning phase."""

    LOOP_EXECUTING = "loop.executing"
    """Loop executing tasks."""

    LOOP_REVIEWING = "loop.reviewing"
    """Loop reviewing outputs."""

    LOOP_COMPLETED = "loop.completed"
    """Loop completed successfully."""

    LOOP_REMEDIATING = "loop.remediating"
    """Loop requires remediation."""

    LOOP_ESCALATED = "loop.escalated"
    """Loop escalated to human."""

    LOOP_FAILED = "loop.failed"
    """Loop failed."""

    # ------------------------------------------------------------------
    # Approval events
    # ------------------------------------------------------------------
    APPROVAL_REQUIRED = "approval.required"
    """Human approval needed."""

    APPROVAL_DECIDED = "approval.decided"
    """Human made decision."""

    APPROVAL_TIMEOUT = "approval.timeout"
    """Approval timeout."""

    APPROVAL_ESCALATED = "approval.escalated"
    """Approval escalated."""

    # ------------------------------------------------------------------
    # Failure and recovery events
    # ------------------------------------------------------------------
    FAILURE_DETECTED = "failure.detected"
    """Failure detected."""

    RECOVERY_STARTED = "recovery.started"
    """Recovery begins."""

    RECOVERY_COMPLETED = "recovery.completed"
    """Recovery completed."""

    RECOVERY_FAILED = "recovery.failed"
    """Recovery failed."""

    CHECKPOINT_RESTORED = "checkpoint.restored"
    """Checkpoint restored."""

    # ------------------------------------------------------------------
    # Review events
    # ------------------------------------------------------------------
    REVIEW_COMPLETED = "review.completed"
    """Review completed."""

    REVIEW_APPROVED = "review.approved"
    """Artifact approved."""

    REVIEW_REJECTED = "review.rejected"
    """Artifact rejected."""

    REVIEW_CHANGES_REQUESTED = "review.changes_requested"
    """Changes requested."""

    # ------------------------------------------------------------------
    # Workflow lifecycle events (Phase 18 orchestration)
    # ------------------------------------------------------------------
    WORKFLOW_STARTED = "workflow.started"
    """Workflow execution started."""

    WORKFLOW_COMPLETED = "workflow.completed"
    """Workflow execution completed successfully."""

    WORKFLOW_FAILED = "workflow.failed"
    """Workflow execution failed."""

    WORKFLOW_PAUSED = "workflow.paused"
    """Workflow execution paused (awaiting human approval or recovery)."""

    WORKFLOW_RESUMED = "workflow.resumed"
    """Workflow execution resumed."""

    WORKFLOW_CANCELLED = "workflow.cancelled"
    """Workflow execution cancelled."""

    # ------------------------------------------------------------------
    # Stage lifecycle events (Phase 18 orchestration)
    # ------------------------------------------------------------------
    STAGE_READY = "stage.ready"
    """Stage transitioned to READY."""

    STAGE_STARTED = "stage.started"
    """Stage started execution."""

    STAGE_SUCCEEDED = "stage.succeeded"
    """Stage completed successfully."""

    STAGE_FAILED = "stage.failed"
    """Stage failed."""

    STAGE_BLOCKED = "stage.blocked"
    """Stage blocked by a failed dependency or unavailable resource."""

    STAGE_SKIPPED = "stage.skipped"
    """Stage skipped (policy or preconditions)."""

    STAGE_CANCELLED = "stage.cancelled"
    """Stage cancelled."""

    STAGE_RETRYING = "stage.retrying"
    """Stage waiting for a retry due to a transient infrastructure failure."""

    STAGE_WAITING_APPROVAL = "stage.waiting_approval"
    """Stage paused at an HITL approval gate."""

    # ------------------------------------------------------------------
    # Orchestration allocation / reasoning events (Phase 18)
    # ------------------------------------------------------------------
    EXECUTION_CREATED = "execution.created"
    """A project execution record was created."""

    MODEL_ROUTED = "model.routed"
    """A model/node routing decision was made for a stage."""

    INFERENCE_STARTED = "inference.started"
    """A model inference began."""

    INFERENCE_COMPLETED = "inference.completed"
    """A model inference completed."""

    EVALUATION_COMPLETED = "evaluation.completed"
    """A stage evaluation gate produced a structured verdict."""

    DIAGNOSIS_COMPLETED = "diagnosis.completed"
    """A failure diagnosis completed."""

    REPAIR_STARTED = "repair.started"
    """An engineering repair/reimplementation began."""

    REPAIR_COMPLETED = "repair.completed"
    """An engineering repair/reimplementation completed."""

    RECTIFICATION_STARTED = "rectification.started"
    """A rectification loop was entered."""

    RECTIFICATION_COMPLETED = "rectification.completed"
    """A rectification loop completed (success or bound exhausted)."""

    # ------------------------------------------------------------------
    # Deployment events (Phase 18)
    # ------------------------------------------------------------------
    DEPLOYMENT_STARTED = "deployment.started"
    """Deployment stage started."""

    DEPLOYMENT_COMPLETED = "deployment.completed"
    """Deployment stage completed successfully."""

    DEPLOYMENT_UNAVAILABLE = "deployment.unavailable"
    """Deployment is explicitly unavailable for the requested target."""

    # ------------------------------------------------------------------
    # Service events
    # ------------------------------------------------------------------
    SERVICE_DEGRADED = "service.degraded"
    """Service degraded."""

    SERVICE_RECOVERED = "service.recovered"
    """Service recovered."""

    SERVICE_FAILED = "service.failed"
    """Service failed."""

    # ------------------------------------------------------------------
    # Kernel lifecycle events
    # ------------------------------------------------------------------
    KERNEL_CREATED = "kernel.created"
    """Kernel instance created."""

    KERNEL_STARTING = "kernel.starting"
    """Kernel is starting up."""

    KERNEL_STARTED = "kernel.started"
    """Kernel has started."""

    KERNEL_PAUSING = "kernel.pausing"
    """Kernel is pausing."""

    KERNEL_PAUSED = "kernel.paused"
    """Kernel is paused."""

    KERNEL_RESUMING = "kernel.resuming"
    """Kernel is resuming."""

    KERNEL_READY = "kernel.ready"
    """Kernel is ready to accept requests."""

    KERNEL_STOPPING = "kernel.stopping"
    """Kernel is stopping."""

    KERNEL_STOPPED = "kernel.stopped"
    """Kernel has stopped."""

    # ------------------------------------------------------------------
    # Checkpoint events
    # ------------------------------------------------------------------
    CHECKPOINT_CREATED = "checkpoint.created"
    """A checkpoint of execution state was created."""

    # NOTE: CHECKPOINT_RESTORED ("checkpoint.restored") is defined with the
    # execution lifecycle events above; no duplicate is added here.
    CHECKPOINT_DELETED = "checkpoint.deleted"
    """A checkpoint was deleted."""

    # ------------------------------------------------------------------
    # System events (for backward compatibility)
    # ------------------------------------------------------------------
    CREATED = "created"
    """Generic created event."""

    UPDATED = "updated"
    """Generic updated event."""

    STARTED = "started"
    """Generic started event."""

    COMPLETED = "completed"
    """Generic completed event."""

    FAILED = "failed"
    """Generic failed event."""

    PAUSED = "paused"
    """Generic paused event."""

    RESUMED = "resumed"
    """Generic resumed event."""

    CANCELLED = "cancelled"
    """Generic cancelled event."""

    APPROVED = "approved"
    """Generic approved event."""

    REJECTED = "rejected"
    """Generic rejected event."""

    CHANGES_REQUESTED = "changes_requested"
    """Generic changes requested event."""

    RESTORED = "restored"
    """Generic restored event."""

    DEGRADED = "degraded"
    """Generic degraded event."""

    RECOVERED = "recovered"
    """Generic recovered event."""

    SYSTEM_EVENT = "system_event"
    """Fallback for unknown event types."""