"""
Workforce collaboration mechanisms.
"""

from __future__ import annotations
from typing import Any
from autoforge_workflows.models import TaskDefinition

def create_downstream_collaboration_task(
    upstream_task_id: str,
    downstream_worker_type: str,
    artifact_content: str,
    task_name: str,
    description: str = "",
) -> TaskDefinition:
    """
    Creates a downstream task carrying context from an upstream worker's artifact.
    Enforces the A -> Artifact -> Workflow -> B architecture pattern.
    """
    return TaskDefinition(
        task_id=f"collab-{upstream_task_id}-{downstream_worker_type}",
        name=task_name,
        description=description,
        task_type=downstream_worker_type,
        input_data={
            "upstream_task": upstream_task_id,
            "artifact_context": artifact_content,
        }
    )
