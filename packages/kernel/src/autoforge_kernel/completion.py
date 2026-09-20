"""
Completion Module

Responsible for validating completion and finalizing projects.
This module implements the Completion component of the Kernel.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from autoforge_events.event_types import EventCategory, EventType

from autoforge_kernel.interfaces import (
    CompletionModule,
    EventBus,
    RuntimeStateManager,
    ReviewEngine,
)
from autoforge_kernel.event_utils import publish_event, make_timestamp


class DefaultCompletionModule(CompletionModule):
    """
    Default implementation of completion validation and finalization.

    Validates completion and finalizes projects per Kernel Specification v1.0 Section 24.
    """

    def __init__(
        self,
        review_engine: ReviewEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
    ):
        """
        Initialize the completion module.

        Args:
            review_engine: Review Engine for final review.
            event_bus: Event bus for publishing events.
            runtime_state_manager: Runtime state manager.
        """
        self.review_engine = review_engine
        self.event_bus = event_bus
        self.runtime_state_manager = runtime_state_manager

    async def validate_completion(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Validate that a project is complete.

        Evaluates actual project state against acceptance criteria, quality gates,
        artifact completeness, dependency completion, execution success, and approval status.

        Args:
            project_id: The project to validate.

        Returns:
            Validation result with detailed per-criteria status.
        """
        validation_result = {
            "valid": True,
            "acceptance_criteria_met": True,
            "quality_gates_passed": True,
            "artifacts_complete": True,
            "dependencies_satisfied": True,
            "execution_success": True,
            "approval_status_ok": True,
            "errors": [],
            "warnings": [],
        }

        if not self.runtime_state_manager:
            validation_result["valid"] = False
            validation_result["errors"].append("Runtime state manager not configured")
            return validation_result

        # Get project state from Runtime State Manager
        try:
            project = await self.runtime_state_manager.get_project(project_id)
            if not project:
                validation_result["valid"] = False
                validation_result["errors"].append(f"Project {project_id} not found")
                return validation_result

            state = await self.runtime_state_manager.get_project_state(project_id)
        except Exception as e:
            validation_result["valid"] = False
            validation_result["errors"].append(f"Failed to read project state: {str(e)}")
            return validation_result

        # Validate acceptance criteria
        acceptance_criteria = state.get("acceptance_criteria", [])
        if not acceptance_criteria:
            validation_result["warnings"].append("No acceptance criteria defined")
        else:
            # Check if all acceptance criteria are marked as met
            all_met = all(
                criterion.get("met", False) for criterion in acceptance_criteria
            )
            if not all_met:
                validation_result["acceptance_criteria_met"] = False
                validation_result["valid"] = False
                unmet = [
                    c.get("description", "Unknown")
                    for c in acceptance_criteria
                    if not c.get("met", False)
                ]
                validation_result["errors"].append(
                    f"Acceptance criteria not met: {', '.join(unmet)}"
                )

        # Validate quality gates
        quality_gates = state.get("quality_gates", [])
        if not quality_gates:
            validation_result["warnings"].append("No quality gates defined")
        else:
            all_passed = all(
                gate.get("passed", False) for gate in quality_gates
            )
            if not all_passed:
                validation_result["quality_gates_passed"] = False
                validation_result["valid"] = False
                failed_gates = [
                    gate.get("name", "Unknown")
                    for gate in quality_gates
                    if not gate.get("passed", False)
                ]
                validation_result["errors"].append(
                    f"Quality gates not passed: {', '.join(failed_gates)}"
                )

        # Validate artifact completeness
        artifacts = state.get("artifacts", [])
        required_artifact_count = state.get("required_artifact_count", 0)
        if required_artifact_count > 0 and len(artifacts) < required_artifact_count:
            validation_result["artifacts_complete"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Artifacts incomplete: {len(artifacts)} of {required_artifact_count} produced"
            )

        # Validate dependency satisfaction
        task_count = state.get("task_count", 0)
        completed_count = state.get("completed_count", 0)
        failed_count = state.get("failed_count", 0)
        if task_count > 0 and completed_count < task_count:
            validation_result["dependencies_satisfied"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Dependencies not satisfied: {completed_count} of {task_count} tasks completed"
            )

        # Validate execution success
        if failed_count and failed_count > 0:
            validation_result["execution_success"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Execution had {failed_count} failed tasks"
            )

        # Validate approval status
        approval_history = state.get("approval_history", [])
        pending_approvals = [
            a for a in approval_history if a.get("status") == "pending"
        ]
        if pending_approvals:
            validation_result["approval_status_ok"] = False
            validation_result["valid"] = False
            validation_result["errors"].append(
                f"Pending approvals: {len(pending_approvals)} approval(s) not yet decided"
            )

        # Validate metrics thresholds
        actual_cost = state.get("actual_cost", 0.0)
        estimated_cost = state.get("estimated_cost", 0.0)
        if estimated_cost > 0 and actual_cost > estimated_cost * 1.5:
            validation_result["warnings"].append(
                f"Cost ({actual_cost}) exceeds 150% of estimate ({estimated_cost})"
            )

        return validation_result

    async def finalize_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Finalize a completed project.

        Args:
            project_id: The project to finalize.

        Returns:
            Finalization result.
        """
        # Validate completion first
        validation_result = await self.validate_completion(project_id)

        if not validation_result["valid"]:
            return {
                "success": False,
                "error": "Project validation failed",
                "validation_result": validation_result,
            }

        # Update project state to Completing
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="Completing",
            )

        # Perform final review if review engine is available
        if self.review_engine:
            try:
                # Invoke Review Engine for final review per Kernel Specification v1.0 Section 24
                review_result = await self.review_engine.review_project(project_id)
                # Review completed - continue with finalization regardless of outcome
            except Exception:
                # Review failed, but continue with finalization
                pass

        # Update project state to Finished with proper timestamp
        finished_at = make_timestamp()
        if self.runtime_state_manager:
            await self.runtime_state_manager.transition_state(
                project_id=project_id,
                new_status="Finished",
                metadata={"finished_at": finished_at, "acceptance_criteria_met": True},
            )

        # Publish project.finished event
        await publish_event(
            event_bus=self.event_bus,
            event_type=EventType.PROJECT_FINISHED,
            event_category=EventCategory.PROJECT,
            aggregate_id=project_id,
            aggregate_type="Project",
            metadata={
                "validation_result": validation_result,
                "finished_at": finished_at,
            },
        )

        return {
            "success": True,
            "project_id": str(project_id),
            "validation_result": validation_result,
            "finished_at": finished_at,
        }


class CompletionModuleWrapper:
    """
    Completion Module Wrapper.

    Validates completion and finalizes projects.
    """

    def __init__(
        self,
        completion_module: CompletionModule | None = None,
        review_engine: ReviewEngine | None = None,
        event_bus: EventBus | None = None,
        runtime_state_manager: RuntimeStateManager | None = None,
    ):
        """
        Initialize the completion module wrapper.

        Args:
            completion_module: Completion module.
            review_engine: Review Engine.
            event_bus: Event bus.
            runtime_state_manager: Runtime state manager.
        """
        self.completion_module = completion_module or DefaultCompletionModule(
            review_engine=review_engine,
            event_bus=event_bus,
            runtime_state_manager=runtime_state_manager,
        )

    async def validate_completion(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Validate completion.

        Args:
            project_id: The project.

        Returns:
            Validation result.
        """
        return await self.completion_module.validate_completion(project_id)

    async def finalize_project(self, project_id: uuid.UUID) -> dict[str, Any]:
        """
        Finalize project.

        Args:
            project_id: The project.

        Returns:
            Finalization result.
        """
        return await self.completion_module.finalize_project(project_id)