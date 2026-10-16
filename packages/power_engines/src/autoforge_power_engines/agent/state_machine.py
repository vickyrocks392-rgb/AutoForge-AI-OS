"""Execution State Machine and Telemetry Collector for Customer Agents (Phase 18-COMMERCIAL-B)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class AgentExecutionState(str, Enum):
    """Explicit lifecycle states for the customer agent execution loop."""
    IDLE = "IDLE"
    RECEIVING_INPUT = "RECEIVING_INPUT"
    THINKING = "THINKING"
    TOOL_PENDING = "TOOL_PENDING"
    EXECUTING_TOOL = "EXECUTING_TOOL"
    OBSERVING = "OBSERVING"
    VERIFYING = "VERIFYING"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    TIMEOUT = "TIMEOUT"


# Valid deterministic state transitions graph
_VALID_TRANSITIONS: Dict[AgentExecutionState, List[AgentExecutionState]] = {
    AgentExecutionState.IDLE: [
        AgentExecutionState.RECEIVING_INPUT,
        AgentExecutionState.CANCELLED,
    ],
    AgentExecutionState.RECEIVING_INPUT: [
        AgentExecutionState.THINKING,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
    ],
    AgentExecutionState.THINKING: [
        AgentExecutionState.TOOL_PENDING,
        AgentExecutionState.VERIFYING,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMEOUT,
    ],
    AgentExecutionState.TOOL_PENDING: [
        AgentExecutionState.EXECUTING_TOOL,
        AgentExecutionState.THINKING,  # On repair prompt retry
        AgentExecutionState.VERIFYING,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMEOUT,
    ],
    AgentExecutionState.EXECUTING_TOOL: [
        AgentExecutionState.OBSERVING,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMEOUT,
    ],
    AgentExecutionState.OBSERVING: [
        AgentExecutionState.THINKING,
        AgentExecutionState.TOOL_PENDING,
        AgentExecutionState.VERIFYING,
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMEOUT,
    ],
    AgentExecutionState.VERIFYING: [
        AgentExecutionState.COMPLETED,
        AgentExecutionState.THINKING,  # On repair retry
        AgentExecutionState.FAILED,
        AgentExecutionState.CANCELLED,
        AgentExecutionState.TIMEOUT,
    ],
    AgentExecutionState.COMPLETED: [],
    AgentExecutionState.FAILED: [],
    AgentExecutionState.CANCELLED: [],
    AgentExecutionState.TIMEOUT: [],
}


class StateTransitionRecord(BaseModel):
    from_state: AgentExecutionState
    to_state: AgentExecutionState
    timestamp: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    reason: Optional[str] = None


class AgentTelemetry(BaseModel):
    """Execution telemetry captured for observability without proprietary leakage."""
    execution_id: str
    session_id: str
    current_state: AgentExecutionState = AgentExecutionState.IDLE
    iterations: int = 0
    model_call_count: int = 0
    tool_call_count: int = 0
    retry_count: int = 0
    failure_count: int = 0
    start_time: float = Field(default_factory=time.time)
    end_time: Optional[float] = None
    duration_ms: float = 0.0
    transitions: List[StateTransitionRecord] = Field(default_factory=list)
    completion_reason: Optional[str] = None
    errors: List[str] = Field(default_factory=list)

    def finish(self, reason: Optional[str] = None) -> None:
        self.end_time = time.time()
        self.duration_ms = (self.end_time - self.start_time) * 1000.0
        self.completion_reason = reason


class AgentStateMachine:
    """Controls and validates deterministic transitions of the agent runtime."""

    def __init__(self, execution_id: str, session_id: str):
        self.telemetry = AgentTelemetry(execution_id=execution_id, session_id=session_id)
        self.state = AgentExecutionState.IDLE

    def transition_to(self, new_state: AgentExecutionState, reason: Optional[str] = None) -> None:
        if self.state == new_state:
            return
        if self.is_terminal():
            err = f"Terminal state '{self.state.value}' is final; cannot transition to '{new_state.value}'."
            self.telemetry.errors.append(err)
            raise ValueError(err)
        valid_next = _VALID_TRANSITIONS.get(self.state, [])
        if new_state not in valid_next:
            err = f"Illegal state transition from {self.state.value} to {new_state.value}."
            self.telemetry.errors.append(err)
            raise ValueError(err)

        rec = StateTransitionRecord(from_state=self.state, to_state=new_state, reason=reason)
        self.telemetry.transitions.append(rec)
        self.state = new_state
        self.telemetry.current_state = new_state

        if new_state in (AgentExecutionState.COMPLETED, AgentExecutionState.FAILED, AgentExecutionState.CANCELLED, AgentExecutionState.TIMEOUT):
            self.telemetry.finish(reason=reason or new_state.value)

    def is_terminal(self) -> bool:
        return self.state in (
            AgentExecutionState.COMPLETED,
            AgentExecutionState.FAILED,
            AgentExecutionState.CANCELLED,
            AgentExecutionState.TIMEOUT,
        )
