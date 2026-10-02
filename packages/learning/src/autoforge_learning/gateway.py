"""ProposalGateway — the security boundary for learning candidates.

Phase 19B-1's non-negotiable requirement (M-04 / Gate 5):

    learning candidate
        ↓
    ProposalGateway
        ↓
    AIGuardrailsEngine.evaluate_learning_proposal()   <-- the ONLY authority
        ↓
    fail-closed decision
        ↓
    permitted / denied

Gate 19A established that ``evaluate_learning_proposal`` had **zero production
callers**. This module is that call site, and it is on the real production
proposal path (see ``autoforge_kernel.learning_engine``).

Fail-closed semantics (Gate 5)
------------------------------
The proposal is DENIED — never permitted — when the boundary:

* raises,
* returns a malformed object,
* returns an unrecognised decision value,
* is unavailable / ``None``,
* explicitly denies.

There is deliberately **no** ``except Exception: pass`` and no
"unavailable means allow" branch. Gate 19A Gate 7 §3.1 requires the capability
of denial to be structural, not a convention.

Authority semantics (Gate 11)
-----------------------------
``PERMITTED`` means *"this proposal may proceed to the next controlled learning
stage."* It does **not** mean approved, promoted, or activated. The gateway
never returns an approval decision and has no promotion capability at all.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Optional, Protocol

from pydantic import Field

from autoforge_learning.models import LearningAuthority, LearningBase, LearningCandidate
from autoforge_security.ai_guardrails import (
    LEARNABLE_PROPOSAL_KINDS,
    LEARNING_FORBIDDEN_CAPABILITIES,
    Capability,
    GuardrailDecisionType,
    LearningProposal,
    LearningProposalDecision,
)

logger = logging.getLogger("autoforge.learning.gateway")


class ProposalOutcome(str, Enum):
    """Local outcome vocabulary.

    Deliberately distinct from ``GuardrailDecisionType``: the gateway's own
    states include ``BLOCKED_*`` conditions with no guardrail equivalent (for
    example a self-elevation attempt caught before submission).
    """

    PERMITTED = "permitted"
    DENIED = "denied"


class GatewayDenialReason(str, Enum):
    """Explicit, inspectable denial causes."""

    BOUNDARY_DENIED = "boundary_denied"
    BOUNDARY_RAISED = "boundary_raised"
    BOUNDARY_MALFORMED = "boundary_malformed"
    BOUNDARY_UNAVAILABLE = "boundary_unavailable"
    BOUNDARY_UNKNOWN_DECISION = "boundary_unknown_decision"
    NON_AUTHORITY_CAPABILITY = "non_authority_capability"
    UNKNOWN_PROPOSAL_KIND = "unknown_proposal_kind"
    L5_AUTHORITY_REQUEST = "l5_authority_request"
    MISSING_PROJECT_SCOPE = "missing_project_scope"


class _Boundary(Protocol):
    """Structural view of the security boundary the gateway depends on."""

    def evaluate_learning_proposal(self, proposal: Any) -> Any: ...


class ProposalDecision(LearningBase):
    """Immutable record of one gateway evaluation.

    ``permitted_to_proceed`` is deliberately **not** named ``approved``.
    Permitted-to-proceed, approved-for-promotion, and activated are three
    separate states, and this gate implements only the first (Gate 11).
    """

    decision_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate_id: uuid.UUID
    scope_project_id: uuid.UUID
    outcome: str
    denial_reason: Optional[str] = None
    detail: str = ""

    #: Verbatim guardrail decision, so an auditor sees what the boundary
    #: actually said rather than a paraphrase.
    boundary_decision: Optional[str] = None
    boundary_reason: str = ""
    promotion_requires: tuple[str, ...] = ()

    evaluated_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    @property
    def permitted_to_proceed(self) -> bool:
        return self.outcome == ProposalOutcome.PERMITTED.value

    @property
    def is_denied(self) -> bool:
        return not self.permitted_to_proceed

    @property
    def is_approved(self) -> bool:
        """Always ``False``. The gateway cannot approve anything (Gate 11)."""
        return False


class ProposalGateway:
    """The only sanctioned entry point for a learning candidate.

    The gateway performs four independent checks, in order, and denies on the
    first failure:

    1. **Self-elevation** — the candidate must not carry Level 5 authority.
    2. **Project scope** — mandatory; there is no scopeless candidate.
    3. **Capability** — requested capabilities must not intersect
       ``LEARNING_FORBIDDEN_CAPABILITIES``.
    4. **Kind** — the proposal kind must be in ``LEARNABLE_PROPOSAL_KINDS``.
    5. **Boundary** — the certified
       ``AIGuardrailsEngine.evaluate_learning_proposal`` decides, fail-closed.

    Checks 1–4 exist so that the *gateway itself* enforces the boundary rather
    than relying on caller behaviour (Gate 6). The boundary call remains
    authoritative even when every local check passes.
    """

    def __init__(self, boundary: _Boundary | None) -> None:
        # ``None`` is tolerated so a misconfigured system fails closed at
        # evaluation time with a clear reason, instead of raising at import.
        self._boundary = boundary

    @property
    def boundary_available(self) -> bool:
        return self._boundary is not None

    # ── public API ──────────────────────────────────────────────────────────

    def evaluate(self, candidate: LearningCandidate) -> ProposalDecision:
        """Evaluate one candidate. Never raises for untrusted input."""
        try:
            return self._evaluate(candidate)
        except Exception as exc:  # noqa: BLE001 - fail-closed by construction
            logger.warning("ProposalGateway evaluation raised: %s", exc)
            return self._deny(
                candidate,
                GatewayDenialReason.BOUNDARY_RAISED,
                f"Proposal evaluation raised {type(exc).__name__}: {exc}",
            )

    def permits(self, candidate: LearningCandidate) -> bool:
        """Convenience predicate. Prefer :meth:`evaluate` to keep the audit."""
        return self.evaluate(candidate).permitted_to_proceed

    # ── internals ───────────────────────────────────────────────────────────

    def _evaluate(self, candidate: LearningCandidate) -> ProposalDecision:
        # 1. Self-elevation / Level 5 is unreachable by construction.
        if candidate.authority is LearningAuthority.L5_SECURITY_POLICY:
            return self._deny(
                candidate,
                GatewayDenialReason.L5_AUTHORITY_REQUEST,
                "No learning candidate may hold Level 5 security/policy authority.",
            )

        # 2. Project scope is mandatory.
        if candidate.scope.project_id is None:
            return self._deny(
                candidate,
                GatewayDenialReason.MISSING_PROJECT_SCOPE,
                "Candidate carries no project scope; project isolation is mandatory.",
            )

        # 3. Capability deny-list (local pre-check; the boundary re-checks).
        forbidden = self._forbidden_capabilities()
        requested = candidate.capability_names & forbidden
        if requested:
            return self._deny(
                candidate,
                GatewayDenialReason.NON_AUTHORITY_CAPABILITY,
                (
                    f"Candidate requests non-authority capability/capabilities "
                    f"{sorted(requested)}. Learning may never escalate its own "
                    f"security boundary."
                ),
            )

        # 4. Proposal-kind allow-list (local pre-check; the boundary re-checks).
        if candidate.kind not in LEARNABLE_PROPOSAL_KINDS:
            return self._deny(
                candidate,
                GatewayDenialReason.UNKNOWN_PROPOSAL_KIND,
                (
                    f"Proposal kind '{candidate.kind}' is not an approved "
                    f"learnable kind. Approved: {sorted(LEARNABLE_PROPOSAL_KINDS)}."
                ),
            )

        return self._call_boundary(candidate)

    # ── boundary invocation ─────────────────────────────────────────────────

    def _call_boundary(self, candidate: LearningCandidate) -> ProposalDecision:
        """Delegate to the certified security boundary, fail-closed."""
        if self._boundary is None:
            return self._deny(
                candidate,
                GatewayDenialReason.BOUNDARY_UNAVAILABLE,
                "Self-improvement security boundary is unavailable; failing closed.",
            )

        try:
            raw = self._boundary.evaluate_learning_proposal(self._to_proposal(candidate))
        except Exception as exc:  # noqa: BLE001 - fail closed, never allow
            return self._deny(
                candidate,
                GatewayDenialReason.BOUNDARY_RAISED,
                f"Security boundary raised {type(exc).__name__}: {exc}",
            )

        if not isinstance(raw, LearningProposalDecision):
            return self._deny(
                candidate,
                GatewayDenialReason.BOUNDARY_MALFORMED,
                "Security boundary returned a malformed decision object.",
            )

        if (
            raw.decision is _ALLOWED_BOUNDARY_DECISION
            and raw.is_permitted
        ):
            return ProposalDecision(
                candidate_id=candidate.candidate_id,
                scope_project_id=candidate.scope.project_id,
                outcome=ProposalOutcome.PERMITTED.value,
                boundary_decision=raw.decision.value,
                boundary_reason=raw.reason,
                promotion_requires=raw.promotion_requires,
            )

        # Everything else denies. A boundary that returns anything other than a
        # clean ALLOW -- an unknown value, a DENY, or an internally inconsistent
        # response -- must never let a proposal continue.
        raw_decision = getattr(raw.decision, "value", raw.decision)
        denial = (
            GatewayDenialReason.BOUNDARY_DENIED
            if raw.decision is GuardrailDecisionType.DENY
            else GatewayDenialReason.BOUNDARY_UNKNOWN_DECISION
        )

        return ProposalDecision(
            candidate_id=candidate.candidate_id,
            scope_project_id=candidate.scope.project_id,
            outcome=ProposalOutcome.DENIED.value,
            denial_reason=denial.value,
            detail=raw.reason,
            boundary_decision=str(raw_decision),
            boundary_reason=raw.reason,
            promotion_requires=raw.promotion_requires,
        )

    # ── helpers ─────────────────────────────────────────────────────────────

    @staticmethod
    def _forbidden_capabilities() -> frozenset[str]:
        return frozenset(c.value for c in LEARNING_FORBIDDEN_CAPABILITIES)

    def _to_proposal(self, candidate: LearningCandidate) -> LearningProposal:
        """Translate into the certified guardrail proposal shape.

        An unrecognised capability name is **not** silently dropped. It is an
        unknown authority request, so the proposal is converted into one the
        boundary will definitely deny.
        """
        capabilities: set[Capability] = set()
        for name in candidate.requested_capabilities:
            try:
                capabilities.add(Capability(name))
            except ValueError:
                capabilities.add(Capability.SECURITY_MODIFY)
                break
        return LearningProposal(
            proposal_id=str(candidate.candidate_id),
            proposal_kind=candidate.kind,
            proposed_by=candidate.created_by,
            target_scope=str(candidate.scope.project_id),
            requested_capabilities=frozenset(capabilities),
            rationale=candidate.rationale,
        )

    def _deny(
        self,
        candidate: Any,
        reason: GatewayDenialReason,
        detail: str,
    ) -> ProposalDecision:
        logger.info(
            "ProposalGateway DENIED candidate=%s reason=%s",
            getattr(candidate, "candidate_id", "<unknown>"),
            reason.value,
        )
        return ProposalDecision(
            candidate_id=_safe_uuid(getattr(candidate, "candidate_id", None)),
            scope_project_id=_safe_uuid(
                getattr(getattr(candidate, "scope", None), "project_id", None)
            ),
            outcome=ProposalOutcome.DENIED.value,
            denial_reason=reason.value,
            detail=detail,
        )


def _safe_uuid(value: Any) -> uuid.UUID:
    """Coerce to a UUID, or mint an identifier for a malformed candidate.

    A denial record must always be constructible, even when the input was
    garbage. Failing to *build the record* would be a fail-open failure mode:
    the caller would see an exception instead of a denial.
    """
    if isinstance(value, uuid.UUID):
        return value
    try:
        return uuid.UUID(str(value))
    except (ValueError, TypeError, AttributeError):
        return uuid.uuid4()


#: The only boundary decision that permits a proposal to continue. Anything
#: else -- DENY, INVALID_REQUEST, an unknown value, or an inconsistent response
#: -- denies. Defined as an explicit allow-list so a future guardrail decision
#: type cannot silently become permissive.
_ALLOWED_BOUNDARY_DECISION = GuardrailDecisionType.ALLOW


__all__ = [
    "GatewayDenialReason",
    "ProposalDecision",
    "ProposalGateway",
    "ProposalOutcome",
]
