"""DAG scheduler for modernization (Phase 18-G.3).

Dependency-aware predecessor graph that schedules transformations in
topological order. NOT ThreadPoolExecutor — pure sequential order
derived from dependency analysis.
"""
from __future__ import annotations
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable


def _utc_now(): return datetime.now(timezone.utc)


@dataclass
class ScheduledTask:
    node_name: str
    node_kind: str
    status: str = "pending"  # pending | running | done | failed
    error: str | None = None
    elapsed_ms: int = 0
    result: Any = None


class DAGScheduler:
    def __init__(self, graph):
        self.graph = graph
        self.tasks = {}  # name -> ScheduledTask
        self._build_tasks()

    def _build_tasks(self):
        for key, node in self.graph.nodes.items():
            name, kind = key
            self.tasks[name] = ScheduledTask(node_name=name, node_kind=kind)

    def schedule(self, transformer: Callable[[dict], Any]) -> list[ScheduledTask]:
        """Schedule all tasks in topological order, execute transformer."""
        order = []
        try:
            order = self.graph.topological_sort()
        except ValueError as e:
            raise RuntimeError(f"Cannot schedule: {e}") from e
        results = []
        for node in order:
            task = self.tasks.get(node.name)
            if not task:
                task = ScheduledTask(node_name=node.name, node_kind=node.kind)
                self.tasks[node.name] = task
            start = time.time()
            task.status = "running"
            try:
                ctx = {"node": node, "attrs": node.attrs, "kind": node.kind}
                task.result = transformer(ctx)
                task.status = "done"
            except Exception as ex:
                task.status = "failed"
                task.error = str(ex)
            task.elapsed_ms = int((time.time() - start) * 1000)
            results.append(task)
        return results

    def summary(self) -> dict:
        tasks = list(self.tasks.values())
        return {
            "total": len(tasks),
            "done": sum(1 for t in tasks if t.status == "done"),
            "failed": sum(1 for t in tasks if t.status == "failed"),
            "total_ms": sum(t.elapsed_ms for t in tasks),
            "by_kind": {
                kind: {
                    "total": sum(1 for t in tasks if t.node_kind == kind),
                    "done": sum(1 for t in tasks if t.node_kind == kind and t.status == "done"),
                    "failed": sum(1 for t in tasks if t.node_kind == kind and t.status == "failed"),
                }
                for kind in set(t.node_kind for t in tasks)
            },
        }


__all__ = ["DAGScheduler", "ScheduledTask"]
