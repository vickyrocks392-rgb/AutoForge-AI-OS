"""Workflow State Machine & Observable Transition Telemetry (18-COMMERCIAL-C)."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

logger = logging.getLogger("autoforge.power_engines.automation.state_machine")


class WorkflowState(str, Enum):
    """Canonical workflow execution states."""
    CREATED = "CREATED"
    READY = "READY"
    RUNNING = "RUNNING"
    WAITING_FOR_TRIGGER = "WAITING_FOR_TRIGGER"
    WAITING_FOR_APPROVAL = "WAITING_FOR_APPROVAL"
    EXECUTING_STEP = "EXECUTING_STEP"
    RETRYING = "RETRYING"
    VERIFYING = "VERIFYING"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    COMPLETED = "COMPLETED"


class StepExecutionState(str, Enum):
    """Execution state for an individual step node."""
    PENDING = "PENDING"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    VERIFYING = "VERIFYING"
    WAITING_APPROVAL = "WAITING_APPROVAL"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    SKIPPED = "SKIPPED"


class StateTransitionRecord(BaseModel):
    """Observable record of a state transition."""
    from_state: str
    to_state: str
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: Optional[str] = None
    step_id: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class WorkflowStateMachine:
    """
    Manages workflow and step state transitions with deterministic validation and audit logging.
    """

    # Allowed workflow transitions
    VALID_WORKFLOW_TRANSITIONS: Dict[WorkflowState, List[WorkflowState]] = {
        WorkflowState.CREATED: [WorkflowState.READY, WorkflowState.WAITING_FOR_TRIGGER, WorkflowState.RUNNING, WorkflowState.FAILED],
        WorkflowState.WAITING_FOR_TRIGGER: [WorkflowState.READY, WorkflowState.RUNNING, WorkflowState.CANCELLED],
        WorkflowState.READY: [WorkflowState.RUNNING, WorkflowState.CANCELLED],
        WorkflowState.RUNNING: [
            WorkflowState.EXECUTING_STEP,
            WorkflowState.WAITING_FOR_APPROVAL,
            WorkflowState.VERIFYING,
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        ],
        WorkflowState.EXECUTING_STEP: [
            WorkflowState.RETRYING,
            WorkflowState.VERIFYING,
            WorkflowState.WAITING_FOR_APPROVAL,
            WorkflowState.RUNNING,
            WorkflowState.COMPLETED,
            WorkflowState.FAILED,
            WorkflowState.CANCELLED,
        ],
        WorkflowState.RETRYING: [WorkflowState.EXECUTING_STEP, WorkflowState.FAILED, WorkflowState.CANCELLED],
        WorkflowState.VERIFYING: [WorkflowState.RUNNING, WorkflowState.RETRYING, WorkflowState.COMPLETED, WorkflowState.FAILED],
        WorkflowState.WAITING_FOR_APPROVAL: [WorkflowState.EXECUTING_STEP, WorkflowState.RUNNING, WorkflowState.CANCELLED, WorkflowState.FAILED],
        WorkflowState.FAILED: [],
        WorkflowState.CANCELLED: [],
        WorkflowState.COMPLETED: [],
    }

    def __init__(self, on_transition: Optional[Callable[[StateTransitionRecord], None]] = None):
        self.current_state: WorkflowState = WorkflowState.CREATED
        self.step_states: Dict[str, StepExecutionState] = {}
        self.history: List[StateTransitionRecord] = []
        self.on_transition = on_transition

    def transition_workflow(
        self,
        new_state: WorkflowState,
        reason: Optional[str] = None,
        step_id: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> StateTransitionRecord:
        """
        Transitions the workflow to a new state if valid.
        """
        allowed = self.VALID_WORKFLOW_TRANSITIONS.get(self.current_state, [])
        if new_state not in allowed and self.current_state != new_state:
            raise ValueError(
                f"Invalid state transition: Cannot move from {self.current_state.value} to {new_state.value}"
            )

        record = StateTransitionRecord(
            from_state=self.current_state.value,
            to_state=new_state.value,
            reason=reason,
            step_id=step_id,
            details=details or {},
        )
        self.current_state = new_state
        self.history.append(record)

        logger.info(f"Workflow State Transition: {record.from_state} -> {record.to_state} (Reason: {reason})")

        if self.on_transition:
            try:
                self.on_transition(record)
            except Exception as e:
                logger.warning(f"Error in on_transition callback: {e}")

        return record

    def set_step_state(self, step_id: str, state: StepExecutionState) -> None:
        self.step_states[step_id] = state

    def get_step_state(self, step_id: str) -> StepExecutionState:
        return self.step_states.get(step_id, StepExecutionState.PENDING)

    def is_terminal(self) -> bool:
        return self.current_state in (WorkflowState.COMPLETED, WorkflowState.FAILED, WorkflowState.CANCELLED)
