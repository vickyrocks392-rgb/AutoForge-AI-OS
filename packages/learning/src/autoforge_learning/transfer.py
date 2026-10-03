"""Cross-project learning policy and safe transfer — Phase 19B-3 (Gates 22, 23).

Gate 22's rule is that generalization is never automatic:

    Project A learning must never become Project B behaviour without an
    explicit policy.

That is enforced by :class:`TransferPolicy`, which requires a *named human
authorizer* and a *target project id* before a cross-project transfer can even
be evaluated, and by :func:`assert_no_implicit_generalization`, which refuses
any attempt to apply project-A learning to project B with an empty policy.

Gate 23's rule is that a failed transfer must not modify target behaviour.
:class:`TransferEvaluator` computes every check *before* any state is written
and returns a verdict; the caller applies it only on ``APPROVED``, and a
rejected transfer leaves the target untouched by construction because nothing
was written during evaluation.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional

from autoforge_learning.models import LearningClass, LearningScope

logger = logging.getLogger("autoforge.learning.transfer")

__test__ = False  # declares transfer policy, not tests
class TransferRefused(RuntimeError):
    """A cross-project transfer was refused."""


class TransferVerdict(str, Enum):
    APPROVED = "approved"
    REFUSED = "refused"


#: Checks Gate 23 requires before any transfer; all of them must pass.
REQUIRED_TRANSFER_CHECKS: tuple[str, ...] = (
    "provenance",
    "compatibility",
    "evidence",
    "regression_evaluation",
    "scope",
    "security",
)


@dataclass
class TransferPolicy:
    """The explicit policy that must exist before learning crosses projects."""

    #: A named human. Empty means no policy, which means no transfer.
    authorized_by: str = ""
    #: Learning class the target receives. A transfer never *becomes* global
    #: merely by being applied somewhere else.
    target_class: LearningClass = LearningClass.PROJECT_SPECIFIC
    #: Independent validations required for GLOBAL_VALIDATED.
    required_validations: int = 2
    reason: str = ""

    @property
    def permits_transfer(self) -> bool:
        return bool(self.authorized_by.strip())

    @property
    def is_global_validated(self) -> bool:
        return self.target_class is LearningClass.GLOBAL_VALIDATED


@dataclass
class TransferRequest:
    """A request to apply project-A learning inside project B."""

    source_project_id: uuid.UUID
    target_project_id: uuid.UUID
    candidate_id: uuid.UUID
    kind: str
    key: str
    policy: TransferPolicy = field(default_factory=TransferPolicy)


@dataclass
class TransferOutcome:
    """The verdict plus the evidence behind it."""

    verdict: TransferVerdict
    checks: dict[str, bool]
    reasons: tuple[str, ...] = ()
    learning_class: LearningClass = LearningClass.PROJECT_SPECIFIC

    @property
    def approved(self) -> bool:
        return self.verdict is TransferVerdict.APPROVED

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(name for name, ok in self.checks.items() if not ok)

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return (
            f"TransferOutcome({self.verdict.value}, failed={self.failed_checks})"
        )


class TransferEvaluator:
    """Evaluates a transfer without writing anything to the target."""

    def evaluate(
        self,
        request: TransferRequest,
        *,
        provenance_ok: bool,
        compatible: bool,
        evidence_ok: bool,
        regression_ok: bool,
        scope_ok: bool,
        security_ok: bool,
        independent_validations: int = 0,
    ) -> TransferOutcome:
        """Run all six Gate 23 checks and return a verdict.

        This function is pure: it writes nothing. A refused transfer therefore
        cannot have modified the target, which satisfies Gate 23 structurally
        rather than by unwinding.
        """
        supplied = {
            "provenance": provenance_ok,
            "compatibility": compatible,
            "evidence": evidence_ok,
            "regression_evaluation": regression_ok,
            "scope": scope_ok,
            "security": security_ok,
        }
        checks = {name: supplied[name] for name in REQUIRED_TRANSFER_CHECKS}

        # Gate 22: no explicit policy means no transfer at all — not even an
        # evaluation that could later be mistaken for approval.
        if not request.policy.permits_transfer:
            return TransferOutcome(
                verdict=TransferVerdict.REFUSED,
                checks=checks,
                reasons=(
                    "no explicit transfer policy: cross-project generalization "
                    "requires a named human authorizer (Project A learning never "
                    "becomes Project B behaviour automatically)",
                ),
                learning_class=LearningClass.PROJECT_SPECIFIC,
            )

        if request.source_project_id == request.target_project_id:
            # Same-project use needs provenance and evidence, but the human
            # authorization requirement is already satisfied by promotion.
            checks["scope"] = True

        reasons = [
            f"required transfer check failed: {name}"
            for name, ok in checks.items()
            if not ok
        ]

        if request.policy.is_global_validated and independent_validations < (
            request.policy.required_validations
        ):
            reasons.append(
                "GLOBAL_VALIDATED_LEARNING requires "
                f"{request.policy.required_validations} independent validations; "
                f"{independent_validations} supplied"
            )
            checks["regression_evaluation"] = False

        approved = not reasons
        return TransferOutcome(
            verdict=TransferVerdict.APPROVED if approved else TransferVerdict.REFUSED,
            checks=checks,
            reasons=tuple(reasons),
            learning_class=request.policy.target_class,
        )


def assert_no_implicit_generalization(
    *,
    learning_scope: LearningScope,
    target_project_id: uuid.UUID,
    policy: TransferPolicy,
) -> None:
    """Refuse to apply project-A learning to project B without a policy.

    Called at the point of use, so even a caller that skipped
    :class:`TransferEvaluator` still cannot generalize implicitly.
    """
    if learning_scope.project_id == target_project_id:
        return
    if not policy.permits_transfer:
        raise TransferRefused(
            f"learning from project {learning_scope.project_id} cannot be applied "
            f"to project {target_project_id}: cross-project transfer requires an "
            "explicit policy naming an authorized human"
        )


__all__ = [
    "REQUIRED_TRANSFER_CHECKS",
    "TransferEvaluator",
    "TransferOutcome",
    "TransferPolicy",
    "TransferRefused",
    "TransferRequest",
    "TransferVerdict",
    "assert_no_implicit_generalization",
]