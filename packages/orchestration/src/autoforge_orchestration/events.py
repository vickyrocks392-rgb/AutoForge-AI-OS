"""Canonical Phase 18 orchestration event publisher.

Emits ONLY the existing canonical vocabulary (``autoforge_events``) via an
injected sink. Event-sink failures are swallowed so observability can never
break authoritative orchestration execution (ADR-008 rule).
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType


class EventSinkProtocol(Protocol):
    """Minimal sink protocol for publishing canonical events."""

    def publish(self, event: Any) -> None:  # noqa: ANN401
        ...


class OrchestrationEvents:
    """Facade publishing canonical lifecycle events for Phase 18 execution."""

    def __init__(self, sink: EventSinkProtocol | None = None) -> None:
        self._sink = sink

    def attach(self, sink: EventSinkProtocol | None) -> None:
        self._sink = sink

    def _emit(
        self,
        event_type: EventType,
        category: EventCategory,
        *,
        execution: Any,
        stage_id: str | None = None,
        duration_ms: float | None = None,
        **meta: Any,
    ) -> None:
        if self._sink is None:
            return
        try:
            project_id = getattr(execution, "project_id", None)
            workflow_id = getattr(execution, "workflow_id", None)
            exec_id = getattr(execution, "execution_id", None)
            metadata: dict[str, Any] = {}
            if project_id:
                metadata["project_id"] = str(project_id)
            if workflow_id:
                metadata["workflow_id"] = str(workflow_id)
            if exec_id:
                metadata["execution_id"] = str(exec_id)
            if stage_id:
                metadata["stage_id"] = stage_id
            if duration_ms is not None:
                metadata["duration_ms"] = round(duration_ms, 3)
            metadata.update(meta)
            aggregate = uuid.UUID(exec_id) if exec_id else None
            event = BaseEvent(
                event_type=event_type,
                event_category=category,
                aggregate_id=aggregate or uuid.uuid4(),
                aggregate_type="ProjectExecution",
                correlation_id=aggregate,
                metadata=metadata,
            )
            self._sink.publish(event)
        except Exception:
            # Observability must never break orchestration.
            pass

    # ── Project / workflow lifecycle ─────────────────────────────────────

    def execution_created(self, execution: Any) -> None:
        self._emit(EventType.EXECUTION_CREATED, EventCategory.EXECUTION, execution=execution)

    def workflow_started(self, execution: Any) -> None:
        self._emit(EventType.WORKFLOW_STARTED, EventCategory.SYSTEM_EVENT, execution=execution)

    def workflow_completed(self, execution: Any, duration_ms: float | None = None) -> None:
        self._emit(
            EventType.WORKFLOW_COMPLETED,
            EventCategory.SYSTEM_EVENT,
            execution=execution,
            duration_ms=duration_ms,
        )

    def workflow_failed(self, execution: Any) -> None:
        self._emit(EventType.WORKFLOW_FAILED, EventCategory.SYSTEM_EVENT, execution=execution)

    def workflow_paused(self, execution: Any, reason: str = "") -> None:
        self._emit(
            EventType.WORKFLOW_PAUSED,
            EventCategory.SYSTEM_EVENT,
            execution=execution,
            reason=reason,
        )

    def workflow_resumed(self, execution: Any) -> None:
        self._emit(EventType.WORKFLOW_RESUMED, EventCategory.SYSTEM_EVENT, execution=execution)

    def workflow_cancelled(self, execution: Any, reason: str = "") -> None:
        self._emit(
            EventType.WORKFLOW_CANCELLED,
            EventCategory.SYSTEM_EVENT,
            execution=execution,
            reason=reason,
        )

    # ── Stage lifecycle ───────────────────────────────────────────────────

    def stage_ready(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_READY, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_started(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_STARTED, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_succeeded(self, execution: Any, stage_id: str, duration_ms: float | None = None) -> None:
        self._emit(
            EventType.STAGE_SUCCEEDED,
            EventCategory.TASK,
            execution=execution,
            stage_id=stage_id,
            duration_ms=duration_ms,
        )

    def stage_failed(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_FAILED, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_blocked(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_BLOCKED, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_skipped(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_SKIPPED, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_cancelled(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_CANCELLED, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_retrying(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.STAGE_RETRYING, EventCategory.TASK, execution=execution, stage_id=stage_id)

    def stage_waiting_approval(self, execution: Any, stage_id: str, gate: Any) -> None:
        self._emit(
            EventType.STAGE_WAITING_APPROVAL,
            EventCategory.TASK,
            execution=execution,
            stage_id=stage_id,
            approval_type="orchestration_hitl",
            gate_id=getattr(gate, "gate_id", ""),
            risk_level=getattr(gate, "risk_level", "medium"),
        )
# ── Allocation / reasoning ────────────────────────────────────────────

    def worker_assigned(self, execution: Any, stage_id: str, assignment: Any) -> None:
        self._emit(
            EventType.WORKER_ASSIGNED,
            EventCategory.SYSTEM_EVENT,
            execution=execution,
            stage_id=stage_id,
            worker_id=getattr(assignment, "worker_id", ""),
            worker_type=getattr(assignment, "worker_type", ""),
        )

    def model_routed(self, execution: Any, stage_id: str, decision: Any) -> None:
        self._emit(
            EventType.MODEL_ROUTED,
            EventCategory.SYSTEM_EVENT,
            execution=execution,
            stage_id=stage_id,
            model_id=getattr(decision, "model_id", ""),
            provider_id=getattr(decision, "provider_id", ""),
            node_id=getattr(decision, "node_id", ""),
            policy_name=getattr(decision, "policy_name", ""),
        )

    def inference_started(self, execution: Any, stage_id: str, decision: Any) -> None:
        self._emit(
            EventType.INFERENCE_STARTED,
            EventCategory.EXECUTION,
            execution=execution,
            stage_id=stage_id,
            model_id=getattr(decision, "model_id", ""),
            node_id=getattr(decision, "node_id", ""),
        )

    def inference_completed(self, execution: Any, stage_id: str, decision: Any, duration_ms: float | None = None) -> None:
        self._emit(
            EventType.INFERENCE_COMPLETED,
            EventCategory.EXECUTION,
            execution=execution,
            stage_id=stage_id,
            model_id=getattr(decision, "model_id", ""),
            node_id=getattr(decision, "node_id", ""),
            duration_ms=duration_ms,
        )

    def evaluation_completed(
        self,
        execution: Any,
        stage_id: str,
        verdict: str,
        duration_ms: float | None = None,
    ) -> None:
        self._emit(
            EventType.EVALUATION_COMPLETED,
            EventCategory.REVIEW,
            execution=execution,
            stage_id=stage_id,
            verdict=verdict,
            duration_ms=duration_ms,
        )

    def diagnosis_completed(self, execution: Any, stage_id: str, root_cause: str) -> None:
        self._emit(
            EventType.DIAGNOSIS_COMPLETED,
            EventCategory.FAILURE,
            execution=execution,
            stage_id=stage_id,
            root_cause=root_cause,
        )

    def repair_started(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.REPAIR_STARTED, EventCategory.LOOP, execution=execution, stage_id=stage_id)

    def repair_completed(self, execution: Any, stage_id: str, success: bool) -> None:
        self._emit(
            EventType.REPAIR_COMPLETED,
            EventCategory.LOOP,
            execution=execution,
            stage_id=stage_id,
            success=success,
        )

    def rectification_started(self, execution: Any, stage_id: str) -> None:
        self._emit(
            EventType.RECTIFICATION_STARTED,
            EventCategory.LOOP,
            execution=execution,
            stage_id=stage_id,
        )

    def rectification_completed(self, execution: Any, stage_id: str, success: bool) -> None:
        self._emit(
            EventType.RECTIFICATION_COMPLETED,
            EventCategory.LOOP,
            execution=execution,
            stage_id=stage_id,
            success=success,
        )

    # ── Review / HITL / deployment ─────────────────────────────────────────

    def review_started(self, execution: Any, stage_id: str) -> None:
        self._emit(EventType.REVIEW_STARTED, EventCategory.REVIEW, execution=execution, stage_id=stage_id)

    def hitl_required(self, execution: Any, stage_id: str, gate: Any) -> None:
        self._emit(
            EventType.APPROVAL_REQUIRED,
            EventCategory.APPROVAL,
            execution=execution,
            stage_id=stage_id,
            approval_type="orchestration_hitl",
            approval_id=getattr(gate, "gate_id", ""),
            risk_level=getattr(gate, "risk_level", "medium"),
        )

    def hitl_decided(self, execution: Any, stage_id: str, gate: Any, decision: str, actor: str) -> None:
        self._emit(
            EventType.APPROVAL_DECIDED,
            EventCategory.APPROVAL,
            execution=execution,
            stage_id=stage_id,
            approval_id=getattr(gate, "gate_id", ""),
            decision=decision,
            actor=actor,
        )

    def deployment_started(self, execution: Any, stage_id: str, target: str) -> None:
        self._emit(
            EventType.DEPLOYMENT_STARTED,
            EventCategory.EXECUTION,
            execution=execution,
            stage_id=stage_id,
            deployment_target=target,
        )

    def deployment_completed(self, execution: Any, stage_id: str, target: str) -> None:
        self._emit(
            EventType.DEPLOYMENT_COMPLETED,
            EventCategory.EXECUTION,
            execution=execution,
            stage_id=stage_id,
            deployment_target=target,
        )

    def deployment_unavailable(self, execution: Any, stage_id: str, target: str) -> None:
        self._emit(
            EventType.DEPLOYMENT_UNAVAILABLE,
            EventCategory.EXECUTION,
            execution=execution,
            stage_id=stage_id,
            deployment_target=target,
        )