"""
Task Queue — Phase 9.

Implements a deterministic, priority-aware, readiness-aware task queue for
the Workflow Platform.

Design principles
-----------------
- Deterministic: equal-priority tasks are ordered by enqueue sequence (FIFO).
- Priority-aware: CRITICAL > HIGH > MEDIUM > LOW.
- Readiness-aware: tasks can only be dequeued when their status is READY.
- No duplicate execution: attempting to enqueue a task already in the queue
  raises QueueError.
- Cancellation: tasks can be removed from the queue before dequeue.
- All operations are synchronous and in-process (no distributed queue).

Priority mapping
----------------
    critical = 0   (highest — smallest integer wins)
    high     = 1
    medium   = 2
    low      = 3
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Iterator

from autoforge_workflows.errors import QueueError
from autoforge_workflows.models import WorkflowTaskStatus


# ── Priority mapping ──────────────────────────────────────────────────────

_PRIORITY_ORDER: dict[str, int] = {
    "critical": 0,
    "high": 1,
    "medium": 2,
    "low": 3,
}


def _priority_key(priority: str) -> int:
    """Map a priority string to a numeric sort key (lower = higher priority)."""
    return _PRIORITY_ORDER.get(priority.lower(), 2)


# ── Queue Entry ───────────────────────────────────────────────────────────


@dataclass(order=True)
class QueueEntry:
    """
    An entry in the task queue.

    Entries are ordered first by priority (numeric, lower = higher priority),
    then by sequence number (FIFO within the same priority band).
    """

    # sort fields first
    priority_key: int = field(compare=True)
    sequence: int = field(compare=True)

    # non-sort fields
    task_id: str = field(compare=False)
    workflow_id: str = field(compare=False)
    priority: str = field(compare=False)
    enqueued_at: float = field(compare=False, default_factory=time.monotonic)

    @classmethod
    def create(
        cls,
        task_id: str,
        workflow_id: str,
        priority: str,
        sequence: int,
    ) -> QueueEntry:
        """Factory constructor."""
        return cls(
            priority_key=_priority_key(priority),
            sequence=sequence,
            task_id=task_id,
            workflow_id=workflow_id,
            priority=priority,
        )


# ── Task Queue ────────────────────────────────────────────────────────────


class TaskQueue:
    """
    A deterministic, priority-aware, readiness-aware task queue.

    The queue stores QueueEntry objects ordered by (priority, sequence).
    Dequeue operations respect task readiness — a task can only be dequeued
    if its recorded status is READY.

    Thread-safety
    -------------
    This queue is NOT thread-safe.  Callers requiring concurrent access must
    add external synchronisation.  The Workflow Engine uses it from a single
    asyncio event loop, which is sufficient for in-process orchestration.
    """

    def __init__(self) -> None:
        self._entries: list[QueueEntry] = []
        self._enqueued_ids: set[str] = set()  # task_ids currently in the queue
        self._sequence: int = 0

    # ── Enqueue ───────────────────────────────────────────────────────────

    def enqueue(
        self,
        task_id: str,
        workflow_id: str,
        priority: str = "medium",
    ) -> QueueEntry:
        """
        Add a task to the queue.

        Args:
            task_id: Unique task identifier.
            workflow_id: Workflow the task belongs to.
            priority: 'low' | 'medium' | 'high' | 'critical'.

        Returns:
            The created QueueEntry.

        Raises:
            QueueError: If the task is already in the queue.
        """
        if task_id in self._enqueued_ids:
            raise QueueError(
                f"Task {task_id!r} is already in the queue.",
                details={"task_id": task_id, "workflow_id": workflow_id},
            )

        self._sequence += 1
        entry = QueueEntry.create(
            task_id=task_id,
            workflow_id=workflow_id,
            priority=priority,
            sequence=self._sequence,
        )
        # Insert in sorted position (simple insertion — queue sizes are small
        # relative to the cost of task execution itself).
        self._entries.append(entry)
        self._entries.sort()
        self._enqueued_ids.add(task_id)
        return entry

    # ── Dequeue ───────────────────────────────────────────────────────────

    def dequeue(
        self,
        task_statuses: dict[str, WorkflowTaskStatus],
    ) -> QueueEntry | None:
        """
        Remove and return the highest-priority READY task.

        Args:
            task_statuses: Current status of all tasks.  A task is dequeued
                only if its status is READY.

        Returns:
            The highest-priority READY QueueEntry, or None if no ready task
            is available.
        """
        for i, entry in enumerate(self._entries):
            status = task_statuses.get(entry.task_id, WorkflowTaskStatus.PENDING)
            if status == WorkflowTaskStatus.READY:
                self._entries.pop(i)
                self._enqueued_ids.discard(entry.task_id)
                return entry
        return None

    def dequeue_batch(
        self,
        task_statuses: dict[str, WorkflowTaskStatus],
        max_count: int = 1,
    ) -> list[QueueEntry]:
        """
        Remove and return up to ``max_count`` READY tasks.

        Returns entries ordered by (priority, sequence).

        Args:
            task_statuses: Current task statuses.
            max_count: Maximum number of entries to dequeue.

        Returns:
            List of dequeued QueueEntry objects.
        """
        result: list[QueueEntry] = []
        to_remove: list[int] = []

        for i, entry in enumerate(self._entries):
            if len(result) >= max_count:
                break
            status = task_statuses.get(entry.task_id, WorkflowTaskStatus.PENDING)
            if status == WorkflowTaskStatus.READY:
                to_remove.append(i)
                result.append(entry)

        # Remove in reverse index order to preserve indices during deletion.
        for i in reversed(to_remove):
            self._enqueued_ids.discard(self._entries[i].task_id)
            self._entries.pop(i)

        return result

    # ── Cancel ────────────────────────────────────────────────────────────

    def cancel(self, task_id: str) -> bool:
        """
        Remove a task from the queue without executing it.

        Args:
            task_id: Task to remove.

        Returns:
            True if the task was found and removed, False if not present.
        """
        for i, entry in enumerate(self._entries):
            if entry.task_id == task_id:
                self._entries.pop(i)
                self._enqueued_ids.discard(task_id)
                return True
        return False

    # ── Query ─────────────────────────────────────────────────────────────

    def contains(self, task_id: str) -> bool:
        """Return True if the task is currently in the queue."""
        return task_id in self._enqueued_ids

    def peek(self) -> QueueEntry | None:
        """Return (but do not remove) the highest-priority entry."""
        return self._entries[0] if self._entries else None

    def ready_count(self, task_statuses: dict[str, WorkflowTaskStatus]) -> int:
        """Return the number of READY tasks currently in the queue."""
        return sum(
            1 for e in self._entries
            if task_statuses.get(e.task_id, WorkflowTaskStatus.PENDING)
            == WorkflowTaskStatus.READY
        )

    def __len__(self) -> int:
        return len(self._entries)

    def __bool__(self) -> bool:
        return bool(self._entries)

    def __iter__(self) -> Iterator[QueueEntry]:
        """Iterate over all entries in priority order (non-destructive)."""
        return iter(list(self._entries))

    def snapshot(self) -> list[dict[str, object]]:
        """Return a serialisable snapshot of the queue for checkpointing."""
        return [
            {
                "task_id": e.task_id,
                "workflow_id": e.workflow_id,
                "priority": e.priority,
                "priority_key": e.priority_key,
                "sequence": e.sequence,
                "enqueued_at": e.enqueued_at,
            }
            for e in self._entries
        ]

    @classmethod
    def from_snapshot(cls, data: list[dict[str, object]]) -> TaskQueue:
        """Restore a TaskQueue from a checkpoint snapshot."""
        q = cls()
        for item in data:
            entry = QueueEntry(
                priority_key=int(item["priority_key"]),  # type: ignore[arg-type]
                sequence=int(item["sequence"]),  # type: ignore[arg-type]
                task_id=str(item["task_id"]),
                workflow_id=str(item["workflow_id"]),
                priority=str(item["priority"]),
                enqueued_at=float(item.get("enqueued_at", 0.0)),  # type: ignore[arg-type]
            )
            q._entries.append(entry)
            q._enqueued_ids.add(entry.task_id)
            if entry.sequence > q._sequence:
                q._sequence = entry.sequence
        q._entries.sort()
        return q
