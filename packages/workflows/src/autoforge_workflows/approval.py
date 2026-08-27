"""
HITL Approval Gate — Phase 9.

Supports workflow pause/resume at consequential governance boundaries.

Design
------
An ApprovalGate is a lightweight value object that tracks the state of an
HITL approval request.  The workflow engine:

1. Creates an ApprovalGate when a task finishes and has an ApprovalGatePolicy.
2. Transitions the task to WAITING_APPROVAL and the workflow to PAUSED.
3. Stores the gate so an external caller can ``decide()`` on it.
4. On approval, the engine resumes the task → RUNNING (or to the next step).
5. On rejection, the engine cancels the task and (by policy) the workflow.

This module intentionally does NOT:
- Make the approval decision automatically.
- Use an AI model to evaluate whether to approve.
- Provide a network endpoint (that is Phase 15 Security / API).

The gate is entirely in-process.  For future distributed approval, the gate
state can be persisted via the checkpoint mechanism.

Approval lifecycle
------------------
  PENDING_APPROVAL  (gate created, waiting for human decision)
       │
       ├── approve()  → APPROVED
       │
       └── reject()   → REJECTED

  APPROVED  (terminal — workflow may continue)
  REJECTED  (terminal — workflow cancelled by policy)
  TIMED_OUT (terminal — set externally if timeout_seconds elapses)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from autoforge_workflows.errors import ApprovalError


# ── Status ────────────────────────────────────────────────────────────────


class ApprovalStatus(str, Enum):
    """Lifecycle status of an approval gate."""

    PENDING_APPROVAL = "pending_approval"
    """Gate is open and awaiting human decision."""

    APPROVED = "approved"
    """Approved — workflow may proceed (terminal)."""

    REJECTED = "rejected"
    """Rejected — workflow should be cancelled (terminal)."""

    TIMED_OUT = "timed_out"
    """Timed out without a decision (terminal)."""


# ── Decision ──────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ApprovalDecision:
    """A human approval decision record."""

    outcome: ApprovalOutcome
    decided_by: str
    """Identity of the human approver (name, email, or user ID)."""
    reason: str = ""
    """Optional human-readable rationale."""
    metadata: dict[str, Any] = field(default_factory=dict)
    decided_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class ApprovalOutcome(str, Enum):
    """Outcome of an approval decision."""

    APPROVED = "approved"
    REJECTED = "rejected"


# ── Approval Gate ─────────────────────────────────────────────────────────


@dataclass
class ApprovalGate:
    """
    An HITL approval gate attached to a workflow task.

    The gate is created by the WorkflowEngine when a task finishes its
    execution phase and has an ApprovalGatePolicy.  External callers
    (e.g. a future API server or CLI) call ``decide()`` to provide the
    human decision.

    The gate is mutable because it accumulates decisions over time
    (multi-approver scenarios).
    """

    gate_id: str
    task_id: str
    workflow_id: uuid.UUID
    description: str = ""
    required_approvers: int = 1
    timeout_seconds: float | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    status: ApprovalStatus = ApprovalStatus.PENDING_APPROVAL
    decisions: list[ApprovalDecision] = field(default_factory=list)
    """All decisions recorded so far."""

    # ── Actions ───────────────────────────────────────────────────────────

    def decide(self, decision: ApprovalDecision) -> ApprovalStatus:
        """
        Record a human approval decision.

        Args:
            decision: The approval decision.

        Returns:
            The new gate status after recording the decision.

        Raises:
            ApprovalError: If the gate is already in a terminal state.
        """
        if self.status != ApprovalStatus.PENDING_APPROVAL:
            raise ApprovalError(
                f"Approval gate {self.gate_id!r} is already in terminal "
                f"state: {self.status.value!r}",
                details={
                    "gate_id": self.gate_id,
                    "current_status": self.status.value,
                },
            )

        self.decisions.append(decision)

        if decision.outcome == ApprovalOutcome.REJECTED:
            # Any rejection immediately closes the gate.
            self.status = ApprovalStatus.REJECTED

        elif decision.outcome == ApprovalOutcome.APPROVED:
            approval_count = sum(
                1 for d in self.decisions
                if d.outcome == ApprovalOutcome.APPROVED
            )
            if approval_count >= self.required_approvers:
                self.status = ApprovalStatus.APPROVED

        return self.status

    def timeout(self) -> None:
        """
        Mark the gate as timed out.

        Raises:
            ApprovalError: If the gate is already in a terminal state.
        """
        if self.status != ApprovalStatus.PENDING_APPROVAL:
            raise ApprovalError(
                f"Cannot time out gate {self.gate_id!r} in state {self.status.value!r}.",
                details={"gate_id": self.gate_id, "current_status": self.status.value},
            )
        self.status = ApprovalStatus.TIMED_OUT

    # ── Properties ────────────────────────────────────────────────────────

    @property
    def is_resolved(self) -> bool:
        """True if the gate is in a terminal state."""
        return self.status in {
            ApprovalStatus.APPROVED,
            ApprovalStatus.REJECTED,
            ApprovalStatus.TIMED_OUT,
        }

    @property
    def approval_count(self) -> int:
        """Number of APPROVED decisions recorded."""
        return sum(1 for d in self.decisions if d.outcome == ApprovalOutcome.APPROVED)

    @property
    def rejection_count(self) -> int:
        """Number of REJECTED decisions recorded."""
        return sum(1 for d in self.decisions if d.outcome == ApprovalOutcome.REJECTED)

    def is_timed_out_now(self) -> bool:
        """
        Check whether the gate's timeout has elapsed (deterministic).

        Returns True only if timeout_seconds is set and the elapsed time
        since creation exceeds it.
        """
        if self.timeout_seconds is None:
            return False
        elapsed = (datetime.now(timezone.utc) - self.created_at).total_seconds()
        return elapsed >= self.timeout_seconds

    # ── Serialisation ─────────────────────────────────────────────────────

    def to_snapshot(self) -> dict[str, Any]:
        """Serialize for checkpointing."""
        return {
            "gate_id": self.gate_id,
            "task_id": self.task_id,
            "workflow_id": str(self.workflow_id),
            "description": self.description,
            "required_approvers": self.required_approvers,
            "timeout_seconds": self.timeout_seconds,
            "created_at": self.created_at.isoformat(),
            "status": self.status.value,
            "decisions": [
                {
                    "outcome": d.outcome.value,
                    "decided_by": d.decided_by,
                    "reason": d.reason,
                    "decided_at": d.decided_at.isoformat(),
                    "metadata": d.metadata,
                }
                for d in self.decisions
            ],
        }

    @classmethod
    def from_snapshot(cls, data: dict[str, Any]) -> ApprovalGate:
        """Restore from a checkpoint snapshot."""
        gate = cls(
            gate_id=data["gate_id"],
            task_id=data["task_id"],
            workflow_id=uuid.UUID(data["workflow_id"]),
            description=data.get("description", ""),
            required_approvers=data.get("required_approvers", 1),
            timeout_seconds=data.get("timeout_seconds"),
            created_at=datetime.fromisoformat(data["created_at"]),
            status=ApprovalStatus(data["status"]),
        )
        for d_raw in data.get("decisions", []):
            gate.decisions.append(
                ApprovalDecision(
                    outcome=ApprovalOutcome(d_raw["outcome"]),
                    decided_by=d_raw["decided_by"],
                    reason=d_raw.get("reason", ""),
                    decided_at=datetime.fromisoformat(d_raw["decided_at"]),
                    metadata=d_raw.get("metadata", {}),
                )
            )
        return gate
