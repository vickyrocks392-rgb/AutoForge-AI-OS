"""Dependency-aware async scheduler for modernization units.

Schedule units in topological order, respecting:
  * explicit dependencies
  * max concurrent workers
  * capacity per target technology
  * bounded queueing
"""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict, deque
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Awaitable, Callable

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TaskStatus(str, Enum):
    PENDING = "pending"
    READY = "ready"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ScheduledTask(BaseModel):
    task_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    unit_id: str = ""
    target_technology: str = ""
    depends_on: list[str] = Field(default_factory=list)
    status: TaskStatus = TaskStatus.PENDING
    result: dict[str, Any] = Field(default_factory=dict)
    error: str = ""
    started_at: datetime | None = None
    completed_at: datetime | None = None


class CapacityScheduler:
    """Run a fixed set of units respecting deps + concurrency limits."""

    def __init__(
        self,
        *,
        max_concurrent: int = 4,
        per_tech_concurrency: dict[str, int] | None = None,
    ) -> None:
        self._max_concurrent = max(1, int(max_concurrent))
        self._per_tech = dict(per_tech_concurrency or {})
        self._tasks: dict[str, ScheduledTask] = {}
        self._in_flight: dict[str, str] = {}   # task_id -> tech
        self._per_tech_in_flight: dict[str, int] = defaultdict(int)
        self._lock = asyncio.Lock()
        self._done = asyncio.Event()
        self._completion_count = 0
        self._total = 0
        self._on_progress: Callable[[ScheduledTask], Awaitable[None]] | None = None

    def add_unit(
        self,
        *,
        unit_id: str,
        target_technology: str,
        depends_on: list[str] | None = None,
    ) -> ScheduledTask:
        task = ScheduledTask(
            unit_id=unit_id,
            target_technology=target_technology,
            depends_on=list(depends_on or []),
        )
        self._tasks[task.task_id] = task
        self._total += 1
        return task

    def tasks(self) -> list[ScheduledTask]:
        return list(self._tasks.values())

    def on_progress(
        self, callback: Callable[[ScheduledTask], Awaitable[None]]
    ) -> None:
        """Register a progress callback (called per unit completion)."""
        self._on_progress = callback

    def _has_tech_capacity(self, tech: str) -> bool:
        cap = self._per_tech.get(tech, self._max_concurrent)
        return self._per_tech_in_flight[tech] < cap

    def _all_dependencies_done(self, task: ScheduledTask) -> bool:
        return all(
            self._tasks[d].status == TaskStatus.COMPLETED
            for d in task.depends_on
            if d in self._tasks
        )

    async def run_all(
        self,
        executor: Callable[[ScheduledTask], Awaitable[dict[str, Any]]],
    ) -> list[ScheduledTask]:
        """Run all scheduled units, respecting deps + concurrency."""
        for t in self._tasks.values():
            t.status = TaskStatus.PENDING
        # Topological dispatch: queue of READY tasks, run with bounded workers.
        self._in_flight.clear()
        self._per_tech_in_flight.clear()
        self._completion_count = 0
        self._done.clear()

        for t in self._tasks.values():
            t.status = TaskStatus.READY

        workers = [
            asyncio.create_task(self._worker_loop(executor))
            for _ in range(self._max_concurrent)
        ]
        await self._done.wait()
        for w in workers:
            w.cancel()
        return self.tasks()

    async def _worker_loop(
        self,
        executor: Callable[[ScheduledTask], Awaitable[dict[str, Any]]],
    ) -> None:
        while True:
            task = await self._claim_next_task()
            if task is None:
                if self._completion_count >= self._total:
                    return
                await asyncio.sleep(0.02)
                continue

            async with self._lock:
                self._in_flight[task.task_id] = task.target_technology
                self._per_tech_in_flight[task.target_technology] += 1
                task.status = TaskStatus.RUNNING
                task.started_at = _utc_now()

            try:
                result = await executor(task)
                task.result = result
                task.status = TaskStatus.COMPLETED
            except Exception as exc:  # noqa: BLE001
                task.error = str(exc)
                task.status = TaskStatus.FAILED
            finally:
                async with self._lock:
                    self._per_tech_in_flight[task.target_technology] -= 1
                    self._in_flight.pop(task.task_id, None)
                task.completed_at = _utc_now()
                self._completion_count += 1
                if self._on_progress is not None:
                    try:
                        await self._on_progress(task)
                    except Exception:  # noqa: BLE001
                        pass
                if self._completion_count >= self._total:
                    self._done.set()

    async def _claim_next_task(self) -> ScheduledTask | None:
        async with self._lock:
            for task in self._tasks.values():
                if task.status != TaskStatus.READY:
                    continue
                if not self._has_tech_capacity(task.target_technology):
                    continue
                if not self._all_dependencies_done(task):
                    continue
                return task
        return None


__all__ = [
    "TaskStatus",
    "ScheduledTask",
    "CapacityScheduler",
]