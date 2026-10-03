"""Bounded reward learning — Phase 19B-3 (Gates 8 and 25).

Gate 8's central rule is one sentence long and everything here follows from it:

    Reward is NOT authority.

A high reward cannot bypass security, cannot bypass validation, cannot bypass
HITL, cannot bypass rollback, cannot grant permissions and cannot alter
governance. This is not a policy statement enforced by convention; it is
structural, in three independent ways:

1. **The type carries no authority.** :class:`Reward` has no capability,
   permission, scope-widening or decision field, and it is frozen, so it cannot
   grow one. There is nothing to exchange it for.
2. **The reward function is blind to protected signals.** A reward may only be
   derived from *measured, objective* quantities. Passing a security, validation
   or isolation measurement into the aggregator is refused rather than scored,
   so "high reward" can never be manufactured by violating a boundary.
3. **Deterministic validation outranks reward.** Every aggregated reward carries
   the set of deterministic verdicts observed in the same window; a single
   failing verdict pins the aggregate at or below zero regardless of magnitude.

Anti-reward-hacking (Gate 25) is enforced by :class:`RewardLedger`, which
detects and refuses the concrete attacks the gate names: fabricated reward,
inflation, contradiction, and a reward that conflicts with deterministic
validation.
"""

from __future__ import annotations

import hashlib
import logging
import uuid
from dataclasses import dataclass, field
from typing import Mapping, Optional, Sequence

from autoforge_learning.models import Reward, RewardPolarity

logger = logging.getLogger("autoforge.learning.rewards")

__test__ = False  # declares a ledger, not tests


class RewardRejected(Exception):
    """A reward was refused. It is never silently dropped."""


#: Metrics the reward function is permitted to read. Anything outside this set
#: is refused at the aggregator boundary, which is what makes it impossible to
#: score "how well did we violate the boundary".
OPTIMIZABLE_METRICS: frozenset[str] = frozenset(
    {
        "latency_ms",
        "resource_units",
        "retry_count",
        "task_success_rate",
        "tool_success_rate",
        "validation_pass_rate",
        "review_approval_rate",
    }
)

#: Metrics that describe a *protected* outcome. These are never optimizable:
#: they are inputs to the deterministic verdict, not to the objective.
PROTECTED_METRICS: frozenset[str] = frozenset(
    {
        "security_violations",
        "isolation_violations",
        "cross_project_access_attempts",
        "authorization_denials",
        "credential_leaks",
        "validation_truth",
    }
)

def normalize(raw: float, *, minimum: float, maximum: float) -> float:
    """Map ``raw`` into ``[-1.0, 1.0]`` given observed bounds.

    The final clamp is applied *after* the affine transform, not before it: a
    value far outside the observed range would otherwise be scaled to something
    beyond ``[-1, 1]``. This is Gate 25's "reward inflation" defence at the
    arithmetic layer — an inflated input cannot produce an inflated normalized
    reward.
    """
    if maximum <= minimum:
        return 0.0
    scaled = (raw - minimum) / (maximum - minimum)
    return round(max(-1.0, min(1.0, scaled * 2.0 - 1.0)), 6)


@dataclass
class RewardWindow:
    """Every reward observed in one evaluation window, plus its guards.

    ``deterministic_verdicts`` records what deterministic validation actually
    said during the same window. It is stored *beside* the rewards precisely so
    a reader can see that the aggregate was clamped by a failing verdict rather
    than that the verdict was ignored.
    """

    window_id: uuid.UUID = field(default_factory=uuid.uuid4)
    rewards: tuple[Reward, ...] = ()
    deterministic_verdicts: tuple[str, ...] = ()
    objective_bounds: dict[str, tuple[float, float]] = field(default_factory=dict)
    aggregate: float = 0.0
    clamped_by_determinism: bool = False
    rejections: tuple[str, ...] = ()

    @property
    def is_clean(self) -> bool:
        return not self.rejections and not self.clamped_by_determinism


class RewardLedger:
    """Records, normalises and audits reward without ever granting anything."""

    def __init__(self) -> None:
        self._history: list[Reward] = []
        self._rejections: list[str] = []

    def record(
        self,
        *,
        scope,
        objective: str,
        raw_value: float,
        provenance_ref: str,
        provenance_payload,
        polarity: RewardPolarity = RewardPolarity.POSITIVE,
        bounds: tuple[float, float] = (-1.0, 1.0),
        experiment_run_id: Optional[uuid.UUID] = None,
        candidate_id: Optional[uuid.UUID] = None,
        confidence: float = 0.0,
    ) -> Reward:
        """Record one reward, refusing anything without real provenance.

        A caller that cannot name where its number came from is fabricating a
        reward, so :class:`RewardRejected` is raised rather than a record being
        written (Gate 8 "fabricated reward").
        """
        if not provenance_ref.strip():
            self._reject("fabricated reward: no provenance reference supplied")
        if objective in PROTECTED_METRICS:
            # EX-12: a security outcome is never a measured reward.
            self._reject(
                f"objective {objective!r} is a protected metric and may never be scored"
            )

        reward = Reward(
            scope=scope,
            objective=objective,
            polarity=polarity,
            raw_value=float(raw_value),
            normalized_value=normalize(
                raw_value, minimum=bounds[0], maximum=bounds[1]
            ),
            provenance_ref=provenance_ref,
            provenance_hash=_digest(provenance_payload),
            experiment_run_id=experiment_run_id,
            candidate_id=candidate_id,
            confidence=confidence,
        )
        self._history.append(reward)
        return reward

    def aggregate(
        self,
        rewards: Sequence[Reward],
        *,
        deterministic_verdicts: Sequence[str] = (),
        bounds: Mapping[str, tuple[float, float]] | None = None,
    ) -> RewardWindow:
        """Combine rewards, subject to deterministic validation outranking them.

        The clamp is the whole point of Gate 8: if any deterministic verdict in
        the window is not a pass, the aggregate cannot be positive, no matter
        how large the rewards are.
        """
        bounds = bounds or {}
        rejected: list[str] = []
        usable: list[Reward] = []

        for reward in rewards:
            if reward.objective in PROTECTED_METRICS:
                rejected.append(
                    f"reward {reward.reward_id} scores protected metric "
                    f"{reward.objective!r}"
                )
                continue
            if reward.objective not in OPTIMIZABLE_METRICS:
                rejected.append(
                    f"reward {reward.reward_id} uses non-optimizable metric "
                    f"{reward.objective!r}"
                )
                continue
            if 0.0 < reward.confidence < 0.5:
                # Low-confidence reward may inform a report, never a decision.
                rejected.append(
                    f"reward {reward.reward_id} below the confidence floor"
                )
                continue
            usable.append(reward)

        failing = [v for v in deterministic_verdicts if v != "pass"]
        clamped = bool(failing)

        if not usable:
            return RewardWindow(
                rewards=(),
                deterministic_verdicts=tuple(deterministic_verdicts),
                aggregate=0.0,
                clamped_by_determinism=clamped,
                rejections=tuple(rejected),
            )

        total = sum(
            r.normalized_value * (r.confidence or 1.0) for r in usable
        ) / len(usable)
        if clamped and total > 0.0:
            # Deterministic validation outranks reward, unconditionally.
            total = 0.0

        return RewardWindow(
            rewards=tuple(usable),
            deterministic_verdicts=tuple(deterministic_verdicts),
            objective_bounds=dict(bounds),
            aggregate=round(total, 6),
            clamped_by_determinism=clamped,
            rejections=tuple(rejected),
        )

    # ── anti-reward-hacking (Gate 25) ─────────────────────────────────────

    def detect_inflation(
        self, candidate_id: uuid.UUID, *, ceiling: float
    ) -> list[str]:
        """Flag rewards whose total exceeds a declared ceiling.

        Gate 25 "reward inflation": an unbounded objective is the classic way a
        reward loop stops measuring quality and starts measuring itself.
        """
        owned = [r for r in self._history if r.candidate_id == candidate_id]
        if not owned:
            return []
        total = sum(r.normalized_value for r in owned)
        if total <= ceiling:
            return []
        return [
            f"candidate {candidate_id} accumulated reward {total} exceeding the "
            f"declared ceiling {ceiling} across {len(owned)} reward(s)"
        ]

    def detect_contradiction(
        self, candidate_id: uuid.UUID, *, verdicts: Sequence[str]
    ) -> list[str]:
        """Flag positive reward contradicted by a failing deterministic verdict."""
        owned = [
            r
            for r in self._history
            if r.candidate_id == candidate_id
            and r.polarity is RewardPolarity.POSITIVE
        ]
        failing = [v for v in verdicts if v != "pass"]
        if owned and failing:
            return [
                f"candidate {candidate_id} holds {len(owned)} positive reward(s) "
                f"while deterministic validation reports {sorted(set(failing))}"
            ]
        return []

    def detect_replayed_evidence(self, candidate_id: uuid.UUID) -> list[str]:
        """Flag the same reward evidence replayed under a new identity."""
        seen: dict[tuple[str, str], int] = {}
        for reward in self._history:
            if reward.candidate_id != candidate_id:
                continue
            key = (reward.objective, reward.provenance_hash)
            seen[key] = seen.get(key, 0) + 1
        return [
            f"reward evidence {objective}/{digest[:12]} replayed {count} times for "
            f"candidate {candidate_id}"
            for (objective, digest), count in seen.items()
            if count > 1
        ]

    # ── history ──────────────────────────────────────────────────────────

    @property
    def history(self) -> tuple[Reward, ...]:
        return tuple(self._history)

    @property
    def rejections(self) -> tuple[str, ...]:
        return tuple(self._rejections)

    def _reject(self, reason: str) -> None:
        self._rejections.append(reason)
        logger.warning("reward rejected: %s", reason)
        raise RewardRejected(reason)


def _digest(payload) -> str:
    """Deterministic hash of the authoritative record a reward came from."""
    canonical = (
        repr(sorted(payload.items()))
        if isinstance(payload, Mapping)
        else str(payload)
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = [
    "OPTIMIZABLE_METRICS",
    "PROTECTED_METRICS",
    "RewardLedger",
    "RewardRejected",
    "RewardWindow",
    "normalize",
]