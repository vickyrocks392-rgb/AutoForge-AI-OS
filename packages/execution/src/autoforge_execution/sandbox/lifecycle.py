"""
Deterministic Lifecycle Management and Canonical Event Emission for Workloads (Phase 18-I).

Drives each workload through strict observable stages:
CREATE -> PREPARE -> VALIDATE -> START -> EXECUTE -> OBSERVE -> COLLECT -> VERIFY -> TERMINATE -> CLEANUP -> DESTROY
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Protocol

from autoforge_events.base import BaseEvent
from autoforge_events.workload_events import (
    WorkloadCleanupCompleted,
    WorkloadCompleted,
    WorkloadCreated,
    WorkloadFailed,
    WorkloadFilesystemViolation,
    WorkloadNetworkBlocked,
    WorkloadPolicyRejected,
    WorkloadResourceLimit,
    WorkloadSecretAccessBlocked,
    WorkloadStarted,
    WorkloadTerminated,
    WorkloadTimeout,
)
from autoforge_execution.events import EventSinkProtocol
from autoforge_execution.sandbox.models import (
    WorkloadLifecycleState,
    WorkloadSpec,
)


@dataclass
class StateTransition:
    """Record of a single lifecycle transition."""
    from_state: WorkloadLifecycleState
    to_state: WorkloadLifecycleState
    timestamp: float = field(default_factory=time.time)
    details: dict[str, Any] = field(default_factory=dict)


class SandboxLifecycleManager:
    """
    Manages deterministic lifecycle progression and publishes canonical
    domain events for sandboxed workloads.
    """

    def __init__(self, event_sink: EventSinkProtocol | None = None) -> None:
        self._sink = event_sink
        self._history: dict[str, list[StateTransition]] = {}
        self._current_states: dict[str, WorkloadLifecycleState] = {}

    def _publish(self, event: BaseEvent) -> None:
        if not self._sink:
            return
        try:
            self._sink.publish(event)
        except Exception:
            # Event emission must never crash execution
            pass

    def get_state(self, workload_id: str) -> WorkloadLifecycleState:
        """Get the current state of a workload."""
        return self._current_states.get(workload_id, WorkloadLifecycleState.CREATED)

    def get_history(self, workload_id: str) -> list[StateTransition]:
        """Return full transition audit trail for a workload."""
        return list(self._history.get(workload_id, []))

    def transition(
        self,
        workload_id: str,
        new_state: WorkloadLifecycleState,
        details: dict[str, Any] | None = None,
    ) -> None:
        """Advance the lifecycle state of a workload."""
        current = self.get_state(workload_id)
        transition = StateTransition(
            from_state=current,
            to_state=new_state,
            details=details or {},
        )
        if workload_id not in self._history:
            self._history[workload_id] = []
        self._history[workload_id].append(transition)
        self._current_states[workload_id] = new_state

    # ── Canonical Event Publishers ────────────────────────────────────────

    def emit_workload_created(self, spec: WorkloadSpec, provider_type: str, workspace_path: str) -> None:
        self.transition(spec.workload_id, WorkloadLifecycleState.CREATED)
        self._publish(
            WorkloadCreated(
                workload_id=spec.workload_id,
                project_id=spec.project_id,
                provider_type=provider_type,
                security_profile=spec.security_profile.value,
                workspace_path=workspace_path,
            )
        )

    def emit_workload_started(self, workload_id: str, command: list[str], timeout_seconds: float, process_id: int | None = None) -> None:
        self.transition(workload_id, WorkloadLifecycleState.STARTING, {"pid": process_id})
        self._publish(
            WorkloadStarted(
                workload_id=workload_id,
                command=command,
                timeout_seconds=timeout_seconds,
                process_id=process_id,
            )
        )

    def emit_workload_completed(self, workload_id: str, exit_code: int, duration_seconds: float, artifact_count: int = 0) -> None:
        self.transition(workload_id, WorkloadLifecycleState.OBSERVING)
        self._publish(
            WorkloadCompleted(
                workload_id=workload_id,
                exit_code=exit_code,
                duration_seconds=duration_seconds,
                artifact_count=artifact_count,
            )
        )

    def emit_workload_failed(self, workload_id: str, exit_code: int, error_message: str, duration_seconds: float) -> None:
        self.transition(workload_id, WorkloadLifecycleState.FAILED, {"exit_code": exit_code, "error": error_message})
        self._publish(
            WorkloadFailed(
                workload_id=workload_id,
                exit_code=exit_code,
                error_message=error_message,
                duration_seconds=duration_seconds,
            )
        )

    def emit_workload_timeout(self, workload_id: str, timeout_seconds: float, duration_seconds: float) -> None:
        self.transition(workload_id, WorkloadLifecycleState.TERMINATING, {"reason": "timeout"})
        self._publish(
            WorkloadTimeout(
                workload_id=workload_id,
                timeout_seconds=timeout_seconds,
                duration_seconds=duration_seconds,
            )
        )

    def emit_workload_terminated(self, workload_id: str, reason: str, signal_used: str = "SIGKILL") -> None:
        self.transition(workload_id, WorkloadLifecycleState.TERMINATING, {"reason": reason, "signal": signal_used})
        self._publish(
            WorkloadTerminated(
                workload_id=workload_id,
                reason=reason,
                signal_used=signal_used,
            )
        )

    def emit_policy_rejected(self, workload_id: str, policy_name: str, violation_details: str) -> None:
        self.transition(workload_id, WorkloadLifecycleState.FAILED, {"violation": violation_details})
        self._publish(
            WorkloadPolicyRejected(
                workload_id=workload_id,
                policy_name=policy_name,
                violation_details=violation_details,
            )
        )

    def emit_network_blocked(self, workload_id: str, target: str, rule: str = "DEFAULT_DENY") -> None:
        self._publish(
            WorkloadNetworkBlocked(
                workload_id=workload_id,
                target_destination=target,
                rule=rule,
            )
        )

    def emit_filesystem_violation(self, workload_id: str, attempted_path: str, violation_type: str) -> None:
        self._publish(
            WorkloadFilesystemViolation(
                workload_id=workload_id,
                attempted_path=attempted_path,
                violation_type=violation_type,
            )
        )

    def emit_resource_limit_exceeded(self, workload_id: str, resource_type: str, observed: float, limit: float) -> None:
        self._publish(
            WorkloadResourceLimit(
                workload_id=workload_id,
                resource_type=resource_type,
                observed_value=observed,
                limit_value=limit,
            )
        )

    def emit_secret_access_blocked(self, workload_id: str, secret_pattern: str, action: str = "STRIPPED") -> None:
        self._publish(
            WorkloadSecretAccessBlocked(
                workload_id=workload_id,
                secret_key_pattern=secret_pattern,
                action_taken=action,
            )
        )

    def emit_cleanup_completed(self, workload_id: str, workspace_path: str, duration_seconds: float, orphans_reaped: int = 0) -> None:
        self.transition(workload_id, WorkloadLifecycleState.DESTROYED, {"duration": duration_seconds})
        self._publish(
            WorkloadCleanupCompleted(
                workload_id=workload_id,
                workspace_path=workspace_path,
                duration_seconds=duration_seconds,
                orphans_reaped=orphans_reaped,
            )
        )
