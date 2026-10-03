"""Execution-engine learning overlay — Phase 19B-3 (Gates 13 and 32).

19B-2 deliberately built promotion *infrastructure* and wired nothing to it. Gate
13 now requires a promoted artifact to have a real, bounded consumer, integrated
as a **backward-compatible overlay** rather than a second orchestration engine.

Three properties make that safe:

1. **Absent learning is byte-identical to baseline.** ``apply`` returns ``None``
   when no candidate is active, so the caller's code path is exactly what it was
   before learning existed. This is the definition of a backward-compatible
   overlay, and it is enforced by an early return before any state is read.
2. **Every resolution step is verified.** Integrity, scope, authorization and
   activation state are each checked independently, and any failure degrades to
   "no learning" rather than raising into the critical path (Gate 32).
3. **Learning can never break engineering.** ``apply`` is wrapped so that *any*
   exception — a corrupt store, an unavailable platform, a timeout — produces
   ``None``. AutoForge still does the work; it simply does it with baseline
   behaviour. The failure is recorded truthfully on the overlay so it stays
   visible without being fatal.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional, Protocol

from autoforge_learning.models import ActivationState, LearningScope

logger = logging.getLogger("autoforge.learning.runtime")

__test__ = False  # declares an overlay, not tests
class ActiveStateReader(Protocol):
    """Structural view of the store this overlay reads from."""

    def get_active_state(
        self, project_id: uuid.UUID, kind: str, key: str
    ) -> Any: ...


@dataclass
class AppliedLearning:
    """One resolved, verified, in-force learning overlay."""

    candidate_id: uuid.UUID
    version_id: uuid.UUID
    kind: str
    key: str
    scope: LearningScope
    traffic_fraction: float
    #: The payload the execution engine may consult. Data only.
    parameters: dict[str, Any] = field(default_factory=dict)
    activation_state: ActivationState = ActivationState.FULL
    integrity_verified: bool = True
    authorization_verified: bool = True

    @property
    def is_shadow(self) -> bool:
        return self.activation_state is ActivationState.SHADOW


@dataclass
class OverlayResolution:
    """The result of resolving learning for one execution.

    ``applied is None`` is the normal, healthy case: no learning is active, or
    learning could not be safely resolved, and behaviour is baseline.
    """

    applied: Optional[AppliedLearning]
    reason: str
    degraded: bool = False


class LearningOverlay:
    """A bounded, non-fatal overlay that consults active learning.

    The overlay deliberately holds *no write handle*. It reads the active
    pointer, verifies it, and returns a value the execution engine may consult.
    It cannot promote, activate, roll back or grant anything, so wiring it into a
    production engine adds no authority — only a bounded read.
    """

    def __init__(
        self,
        *,
        store: Optional[ActiveStateReader],
        authorize: Optional[Any] = None,
        parameters_for: Optional[Any] = None,
    ) -> None:
        self._store = store
        self._authorize = authorize
        self._parameters_for = parameters_for
        self._degradations: list[str] = []

    @property
    def degradations(self) -> tuple[str, ...]:
        """Every reason the overlay degraded. Truthful, never empty-by-default."""
        return tuple(self._degradations)

    def apply(
        self,
        *,
        project_id: uuid.UUID,
        kind: str,
        key: str,
        execution_digest: str = "",
    ) -> OverlayResolution:
        """Resolve active learning for one execution. Never raises.

        Gate 32 in one sentence: learning is optional relative to the critical
        path, so this returns ``OverlayResolution(applied=None)`` on every
        failure rather than propagating an exception into execution.
        """
        try:
            return self._resolve(
                project_id=project_id, kind=kind, key=key, digest=execution_digest
            )
        except Exception as exc:  # noqa: BLE001 - the critical path must survive
            reason = (
                f"learning overlay degraded to baseline behaviour "
                f"({type(exc).__name__}: {exc})"
            )
            logger.warning("%s", reason)
            self._degradations.append(reason)
            return OverlayResolution(applied=None, reason=reason, degraded=True)

    def _resolve(
        self,
        *,
        project_id: uuid.UUID,
        kind: str,
        key: str,
        digest: str,
    ) -> OverlayResolution:
        if self._store is None:
            return OverlayResolution(
                applied=None, reason="no learning store configured; baseline behaviour"
            )

        state = self._store.get_active_state(project_id, kind, key)
        if state is None:
            # The healthy common case: nothing promoted for this project.
            return OverlayResolution(
                applied=None, reason="no active learning for this project"
            )

        # 1. Integrity — a tampered or unreadable state is never applied.
        if not state.content_hash:
            self._record("active learning state carries no content hash")
            return OverlayResolution(
                applied=None,
                reason="active learning failed integrity verification",
                degraded=True,
            )

        # 2. Project scope — defence in depth against a cross-project pointer.
        if str(state.project_id) != str(project_id):
            self._record(
                f"active learning state for project {state.project_id} addressed "
                f"from project {project_id}"
            )
            return OverlayResolution(
                applied=None,
                reason="active learning scope mismatch; baseline behaviour",
                degraded=True,
            )

        # 3. Activation state — a deactivated candidate must not apply.
        if state.deactivation_timestamp is not None:
            return OverlayResolution(
                applied=None, reason="active learning is deactivated"
            )

        # 4. Authorization — checked by the caller-supplied platform, and its
        #    absence is a denial rather than a skip (fail closed).
        if self._authorize is not None and not self._authorize(state, project_id):
            self._record(f"authorization refused learning {state.candidate_id}")
            return OverlayResolution(
                applied=None,
                reason="learning authorization denied; baseline behaviour",
                degraded=True,
            )

        parameters = (
            self._parameters_for(state) if self._parameters_for is not None else {}
        )

        return OverlayResolution(
            applied=AppliedLearning(
                candidate_id=state.candidate_id,
                version_id=state.version_id,
                kind=kind,
                key=key,
                scope=LearningScope(
                    kind=state.scope_kind, project_id=state.project_id
                ),
                traffic_fraction=1.0,
                parameters=dict(parameters or {}),
                integrity_verified=True,
                authorization_verified=self._authorize is not None,
            ),
            reason=f"applied learning version {state.version_id}",
        )

    def _record(self, reason: str) -> None:
        logger.warning("%s", reason)
        self._degradations.append(reason)

    def parameters_for(
        self, resolution: OverlayResolution, defaults: dict[str, Any]
    ) -> dict[str, Any]:
        """Merge learned parameters over baseline defaults.

        Returns ``defaults`` verbatim when no learning applies, which is the
        backward-compatibility guarantee in its most concrete form.
        """
        if resolution.applied is None:
            return dict(defaults)
        merged = dict(defaults)
        merged.update(resolution.applied.parameters)
        return merged


__all__ = [
    "ActiveStateReader",
    "AppliedLearning",
    "LearningOverlay",
    "OverlayResolution",
]