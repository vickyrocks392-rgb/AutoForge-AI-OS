"""
Workflow Platform error hierarchy — Phase 9.

All workflow errors derive from WorkflowError so callers can catch the
entire platform's exceptions with a single base clause.
"""

from __future__ import annotations

from typing import Any


class WorkflowError(Exception):
    """Base exception for the AutoForge Workflow Platform."""

    def __init__(self, message: str, *, details: dict[str, Any] | None = None) -> None:
        self.details: dict[str, Any] = details or {}
        super().__init__(message)


class WorkflowValidationError(WorkflowError):
    """
    Raised when a workflow definition or task definition fails structural
    or semantic validation (e.g. missing task IDs, cycle detected).
    """


class WorkflowNotFoundError(WorkflowError):
    """Raised when a requested workflow or task cannot be found."""


class DependencyError(WorkflowError):
    """
    Raised when a dependency condition cannot be satisfied or is invalid
    (e.g. referencing a non-existent task ID as a dependency).
    """


class DAGValidationError(WorkflowValidationError):
    """
    Raised when the workflow DAG fails structural validation
    (e.g. duplicate task IDs, missing referenced tasks).
    """


class CycleDetectedError(DAGValidationError):
    """
    Raised when Kahn's topological sort detects a cycle in the
    workflow dependency graph.
    """


class SchedulerError(WorkflowError):
    """Raised when the scheduler encounters an internal inconsistency."""


class QueueError(WorkflowError):
    """
    Raised when a queue operation fails (e.g. duplicate enqueue,
    dequeue from empty queue).
    """


class RetryLimitExceeded(WorkflowError):
    """
    Raised when a task has been retried the maximum number of times
    allowed by its retry policy and has not succeeded.
    """


class RecoveryError(WorkflowError):
    """
    Raised when a workflow or task recovery operation fails (e.g. snapshot
    is corrupted, checkpoint cannot be restored).
    """


class ApprovalError(WorkflowError):
    """
    Raised when an approval gate operation fails (e.g. approval gate does
    not exist, duplicate decision recorded).
    """
