"""Audit emission for the learning lifecycle — Phase 19B-2 (Gate 9 / M-14).

Architecture basis: ``phase19/LEARNING_LIFECYCLE.md`` (LC-08) and Gate 19A-5
§6, which require ``AuditEngine`` — *not a parallel audit system* — to record
every transition.

The certified ``AuditEngine`` (``packages/security/audit.py``) already:
* sanitises every ``details`` payload through ``SecretsManager.redact_structure``,
* carries project/workflow/task/worker/execution/correlation/trace lineage,
* publishes to the canonical security event sink.

So this module **delegates** to it. Its job is only to:
1. name the fifteen canonical learning lifecycle events,
2. map each onto the existing ``AuthorizationRequest``/``AuditRecord``
   contract, and
3. guarantee that an audit failure is never silently converted into a
   successful promotion (Gate 17).
"""

from __future__ import annotations

import logging
import threading
import uuid
from enum import Enum
from typing import Any, Optional

from autoforge_learning.models import LearningBase
from autoforge_security.audit import AuditEngine
from autoforge_security.models import (
    AuditRecord,
    AuthorizationRequest,
    DecisionType,
    Subject,
    SubjectType,
)

logger = logging.getLogger("autoforge.learning.audit")

__test__ = False  # declares data models, not tests


class LearningAuditAction(str, Enum):
    """The fifteen canonical learning lifecycle audit events (Gate 9)."""

    CANDIDATE_CREATED = "learning.candidate_created"
    EVIDENCE_COLLECTED = "learning.evidence_collected"
    EVALUATION_STARTED = "learning.evaluation_started"
    EVALUATION_COMPLETED = "learning.evaluation_completed"
    EVALUATION_FAILED = "learning.evaluation_failed"
    APPROVAL_REQUESTED = "learning.approval_requested"
    APPROVAL_GRANTED = "learning.approval_granted"
    APPROVAL_REJECTED = "learning.approval_rejected"
    ROLLBACK_HANDLE_CREATED = "learning.rollback_handle_created"
    PROMOTION_ATTEMPTED = "learning.promotion_attempted"
    PROMOTION_SUCCEEDED = "learning.promotion_succeeded"
    PROMOTION_FAILED = "learning.promotion_failed"
    ROLLBACK_ATTEMPTED = "learning.rollback_attempted"
    ROLLBACK_SUCCEEDED = "learning.rollback_succeeded"
    ROLLBACK_FAILED = "learning.rollback_failed"


ALL_AUDIT_ACTIONS: tuple[LearningAuditAction, ...] = tuple(LearningAuditAction)


class LearningAuditError(RuntimeError):
    """Audit emission failed.

    Promotion treats this as fatal: an unaudited promotion is not a
    successful promotion.
    """


class LearningAuditEvent(LearningBase):
    """A lightweight, immutable record of what was emitted.

    Retained so telemetry can be derived from *actual emitted events*
    (Gate 16) rather than from counters someone incremented by hand.
    """

    action: LearningAuditAction
    project_id: uuid.UUID
    candidate_id: Optional[uuid.UUID] = None
    actor_id: str
    outcome: str
    reason: str = ""
    correlation_id: Optional[str] = None
    record_id: Optional[uuid.UUID] = None


#: Keys whose values must never reach the audit trail. The certified
#: ``AuditEngine`` redacts them; this list documents the contract so a future
#: refactor cannot quietly drop it.
FORBIDDEN_DETAIL_KEYS = frozenset(
    {"password", "secret", "token", "api_key", "credential", "private_key"}
)


class LearningAuditor:
    """Emits learning lifecycle events through the certified ``AuditEngine``.

    The auditor holds no policy: it cannot approve, promote, or veto. It can
    only record. Its one power is negative — it can *fail* a promotion by
    refusing to let an unaudited change be reported as successful.
    """

    def __init__(
        self,
        audit_engine: Optional[AuditEngine],
        *,
        system_actor_id: str = "autoforge.learning",
    ) -> None:
        # An absent engine means auditing is unavailable. That is NOT a
        # licence to skip auditing; it is a reason to refuse to promote.
        self._engine = audit_engine
        self._system_actor_id = system_actor_id
        self._lock = threading.RLock()
        self._events: list[LearningAuditEvent] = []

    @property
    def available(self) -> bool:
        return self._engine is not None

    @property
    def events(self) -> tuple[LearningAuditEvent, ...]:
        with self._lock:
            return tuple(self._events)

    def _system_subject(self, actor: Optional[Subject] = None) -> Subject:
        if actor is not None:
            return actor
        return Subject(
            subject_id=self._system_actor_id,
            display_name="AutoForge Learning",
            subject_type=SubjectType.SERVICE,
        )

    def emit(
        self,
        action: LearningAuditAction,
        *,
        project_id: uuid.UUID,
        candidate_id: Optional[uuid.UUID] = None,
        actor: Optional[Subject] = None,
        decision: DecisionType = DecisionType.ALLOW,
        outcome: str = "success",
        reason: str = "",
        correlation_id: Optional[str] = None,
        details: Optional[dict[str, Any]] = None,
        record_id: Optional[uuid.UUID] = None,
        strict: bool = True,
    ) -> Optional[AuditRecord]:
        """Emit one lifecycle event.

        With ``strict=True`` (the default, used for anything that would make
        a promotion look successful) an audit failure raises
        :class:`LearningAuditError`. That is what makes Gate 17's rule hold:
        an audit failure cannot be converted into a silent success.
        """
        subject = self._system_subject(actor)

        payload = dict(details or {})
        # Defence in depth: refuse to place obviously sensitive material in
        # the trail even before the certified redactor sees it.
        for key in list(payload):
            if key.lower() in FORBIDDEN_DETAIL_KEYS:
                payload[key] = "***"

        resource = (
            f"learning-candidate:{candidate_id}"
            if candidate_id
            else f"learning-project:{project_id}"
        )

        if self._engine is None:
            logger.error("No AuditEngine configured; cannot emit %s", action.value)
            self._record(
                LearningAuditEvent(
                    action=action,
                    project_id=project_id,
                    candidate_id=candidate_id,
                    actor_id=subject.subject_id,
                    outcome="audit_unavailable",
                    reason=reason,
                    correlation_id=correlation_id,
                    record_id=record_id,
                )
            )
            if strict:
                raise LearningAuditError(
                    f"cannot emit {action.value}: no AuditEngine is configured"
                )
            return None

        try:
            audit_record = self._engine.record_security_event(
                actor=subject,
                action=action.value,
                resource=resource,
                decision=decision,
                reason=reason,
                outcome=outcome,
                project_id=str(project_id),
                correlation_id=correlation_id,
                details=payload,
            )
        except Exception as ex:  # noqa: BLE001 - never silently unaudited
            logger.error("Audit emission failed for %s: %s", action.value, ex)
            if strict:
                raise LearningAuditError(
                    f"audit emission failed for {action.value}: {ex}"
                ) from ex
            return None

        self._record(
            LearningAuditEvent(
                action=action,
                project_id=project_id,
                candidate_id=candidate_id,
                actor_id=subject.subject_id,
                outcome=outcome,
                reason=reason,
                correlation_id=correlation_id,
                record_id=record_id,
            )
        )
        return audit_record

    def _record(self, event: LearningAuditEvent) -> None:
        with self._lock:
            self._events.append(event)

    def count(self, action: LearningAuditAction) -> int:
        return sum(1 for e in self.events if e.action is action)


__all__ = [
    "ALL_AUDIT_ACTIONS",
    "FORBIDDEN_DETAIL_KEYS",
    "LearningAuditAction",
    "LearningAuditError",
    "LearningAuditEvent",
    "LearningAuditor",
]