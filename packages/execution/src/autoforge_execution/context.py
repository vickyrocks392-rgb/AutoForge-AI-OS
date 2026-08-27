"""
Execution Context — aggregates engineering task requirements, project state, and history.

Adheres to ADR-003: Context Engineering composes existing sources (task definition,
workspace filesystem, previous attempt diagnostics) into structured reasoning contexts
without creating a separate competing knowledge/memory store.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoforge_workflows.models import TaskDefinition

from autoforge_execution.models import DiagnosisReport, EvaluationResult, LoopIterationRecord


@dataclass
class ExecutionContext:
    """
    Structured context assembled for an engineering worker task.
    """

    task_id: str
    task_name: str
    task_type: str = "coding"
    task_description: str = ""
    input_data: dict[str, Any] = field(default_factory=dict)
    workspace_root: Path = field(default_factory=Path.cwd)

    workflow_id: uuid.UUID | None = None
    project_id: uuid.UUID | None = None
    correlation_id: uuid.UUID | None = None
    attempt_number: int = 1

    # Project metadata / file list
    project_files: list[str] = field(default_factory=list)
    file_contents: dict[str, str] = field(default_factory=dict)

    # Historical context from prior iterations in this loop
    prior_iterations: list[LoopIterationRecord] = field(default_factory=list)
    last_evaluation: EvaluationResult | None = None
    last_diagnosis: DiagnosisReport | None = None

    metadata: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_task_definition(
        cls,
        task_def: TaskDefinition,
        workspace_root: Path,
        *,
        workflow_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
        attempt_number: int = 1,
    ) -> ExecutionContext:
        return cls(
            task_id=task_def.task_id,
            task_name=task_def.name,
            task_type=task_def.task_type,
            task_description=task_def.description,
            input_data=task_def.input_data,
            workspace_root=workspace_root,
            workflow_id=workflow_id,
            project_id=project_id,
            correlation_id=correlation_id,
            attempt_number=attempt_number,
            metadata=dict(task_def.metadata),
        )

    def format_reasoning_prompt(self, current_iteration: int) -> dict[str, Any]:
        """
        Produce a structured prompt payload for AI Infrastructure.
        """
        payload: dict[str, Any] = {
            "task_id": self.task_id,
            "task_name": self.task_name,
            "task_type": self.task_type,
            "description": self.task_description,
            "input_data": self.input_data,
            "iteration": current_iteration,
            "project_files": self.project_files,
            "known_files": list(self.file_contents.keys()),
        }

        if self.prior_iterations:
            payload["prior_attempts"] = [
                {
                    "iteration": it.iteration,
                    "action_plan": it.action_plan,
                    "changed_files": it.changed_files,
                    "passed": it.passed,
                    "failures": it.evaluation.failures if it.evaluation else [],
                    "diagnosis": it.diagnosis.root_cause if it.diagnosis else None,
                    "suggested_fix": it.diagnosis.suggested_fix if it.diagnosis else None,
                }
                for it in self.prior_iterations
            ]

        if self.last_diagnosis:
            payload["latest_diagnosis"] = {
                "root_cause": self.last_diagnosis.root_cause,
                "failure_mechanism": self.last_diagnosis.failure_mechanism,
                "affected_files": self.last_diagnosis.affected_files,
                "suggested_fix": self.last_diagnosis.suggested_fix,
            }

        return payload
