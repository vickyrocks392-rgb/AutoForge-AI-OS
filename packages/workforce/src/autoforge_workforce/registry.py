"""
Deterministic Worker Registry for AutoForge.
"""

from __future__ import annotations
from typing import Any, Type
from autoforge_workforce.capabilities import ExpertiseModel

class WorkerRegistry:
    """
    Registry that registers and retrieves worker classes and expertise models deterministically.
    """

    def __init__(self) -> None:
        self._workers: dict[str, Type[Any]] = {}
        self._expertise: dict[str, ExpertiseModel] = {}
        self._task_compatibility: dict[str, list[str]] = {} # worker_type -> list of compatible task_types

    def register(
        self,
        worker_type: str,
        worker_class: Type[Any],
        expertise: ExpertiseModel,
        compatible_tasks: list[str] | None = None,
    ) -> None:
        self._workers[worker_type] = worker_class
        self._expertise[worker_type] = expertise
        self._task_compatibility[worker_type] = compatible_tasks or [worker_type]

    def lookup(self, worker_type: str) -> Type[Any] | None:
        return self._workers.get(worker_type)

    def get_expertise(self, worker_type: str) -> ExpertiseModel | None:
        return self._expertise.get(worker_type)

    def list_workers(self) -> list[str]:
        return list(self._workers.keys())

    def match_capabilities(self, required_capabilities: list[str]) -> list[str]:
        """
        Find worker types that support all required capabilities.
        """
        matches = []
        for worker_type, exp in self._expertise.items():
            if all(cap in exp.capabilities for cap in required_capabilities):
                matches.append(worker_type)
        return matches

    def check_task_compatibility(self, worker_type: str, task_type: str) -> bool:
        """
        Check if a worker type is compatible with a given task type.
        """
        if worker_type == task_type:
            return True
        compat = self._task_compatibility.get(worker_type, [])
        return task_type in compat or "*" in compat

    def validate_permission(self, worker_type: str, operation: str, resource: str) -> bool:
        """
        Validate if the worker has permission to perform an operation on a resource.
        """
        exp = self.get_expertise(worker_type)
        if not exp:
            return False
        return exp.validates_permissions(operation, resource)

# Global registry instance
WORKER_REGISTRY = WorkerRegistry()
