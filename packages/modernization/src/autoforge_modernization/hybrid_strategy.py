"""Transformation strategy selection (hybrid deterministic + LLM).

The system prefers the deterministic path when semantics are sufficiently
formal.  LLM reasoning is used when:

* business intent is ambiguous
* architecture decisions are required
* target idioms require reasoning
* complex legacy constructs cannot be mapped deterministically
* multiple valid target implementations exist
* deterministic transformation produces unresolved semantics

The strategy selection itself is observable: every decision records its
rationale, evidence, and the availability of LLM/RAG at decision time.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class TransformationStrategy(str, Enum):
    DETERMINISTIC = "deterministic"
    LLM_ASSISTED = "llm_assisted"
    LLM_GENERATED = "llm_generated"
    HYBRID = "hybrid"
    BLOCKED = "blocked"
    REVIEW_REQUIRED = "review_required"


DETERMINISTIC_THRESHOLD = 0.85
REVIEW_THRESHOLD = 0.5


class StrategyDecision(BaseModel):
    """One observable strategy-selection decision."""

    decision_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    unit_id: str = ""
    source_technology: str = ""
    target_technology: str = ""
    strategy: TransformationStrategy
    rationale: str = ""
    reasons: list[str] = Field(default_factory=list)
    semantic_coverage: float = 0.0
    unresolved_semantics: list[str] = Field(default_factory=list)
    deterministic_mappable: bool = False
    llm_available: bool = False
    rag_available: bool = False
    decided_at: datetime = Field(default_factory=_utc_now)

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision_id": self.decision_id,
            "unit_id": self.unit_id,
            "source_technology": self.source_technology,
            "target_technology": self.target_technology,
            "strategy": self.strategy.value,
            "rationale": self.rationale,
            "reasons": self.reasons,
            "semantic_coverage": self.semantic_coverage,
            "unresolved_semantics": self.unresolved_semantics,
            "deterministic_mappable": self.deterministic_mappable,
            "llm_available": self.llm_available,
            "rag_available": self.rag_available,
            "decided_at": self.decided_at.isoformat(),
        }


class TransformationStrategySelector:
    """Deterministic, observable selection of the transformation strategy."""

    def __init__(
        self,
        *,
        llm_available: bool = False,
        rag_available: bool = False,
        deterministic_threshold: float = DETERMINISTIC_THRESHOLD,
        review_threshold: float = REVIEW_THRESHOLD,
        llm_available_fn: Any = None,
        rag_available_fn: Any = None,
    ) -> None:
        self.deterministic_threshold = deterministic_threshold
        self.review_threshold = review_threshold
        self._llm_available_fn = llm_available_fn or (lambda: llm_available)
        self._rag_available_fn = rag_available_fn or (lambda: rag_available)
        self._decisions: list[StrategyDecision] = []

    def decisions(self) -> list[StrategyDecision]:
        return list(self._decisions)

    def select(
        self,
        *,
        source_technology: str,
        target_technology: str,
        semantic_coverage: float,
        unresolved_semantics: list[str] | None = None,
        deterministic_mappable: bool = True,
        ambiguity_level: float = 0.0,
        architecture_decision_required: bool = False,
        multiple_valid_targets: bool = False,
        unit_id: str = "",
        llm_available: bool | None = None,
        rag_available: bool | None = None,
    ) -> StrategyDecision:
        """Select and record the transformation strategy for one unit."""
        llm_ok = (
            self._llm_available_fn()
            if llm_available is None
            else bool(llm_available)
        )
        rag_ok = (
            self._rag_available_fn()
            if rag_available is None
            else bool(rag_available)
        )
        unresolved = list(unresolved_semantics or [])
        reasons: list[str] = []
        coverage = max(0.0, min(1.0, float(semantic_coverage)))

        if not deterministic_mappable and not llm_ok:
            strategy = TransformationStrategy.BLOCKED
            reasons.append(
                f"No deterministic mapping to {target_technology} and LLM unavailable"
            )
        elif not deterministic_mappable and llm_ok:
            strategy = TransformationStrategy.LLM_GENERATED
            reasons.append(
                f"No deterministic mapping to {target_technology}; "
                "LLM generation required"
            )
        elif coverage >= self.deterministic_threshold and not unresolved:
            strategy = TransformationStrategy.DETERMINISTIC
            reasons.append(
                f"Semantic coverage {coverage:.2f} >= {self.deterministic_threshold} "
                "with no unresolved semantics"
            )
        elif (
            coverage >= self.deterministic_threshold
            and unresolved
            and llm_ok
        ):
            strategy = TransformationStrategy.HYBRID
            reasons.append(
                "Deterministic analysis establishes facts; "
                f"{len(unresolved)} unresolved semantics require LLM synthesis"
            )
        elif (
            coverage >= self.deterministic_threshold
            and unresolved
            and not llm_ok
        ):
            strategy = TransformationStrategy.REVIEW_REQUIRED
            reasons.append(
                "Deterministic path available but unresolved semantics remain "
                "and LLM is unavailable — human review required"
            )
        elif coverage >= self.review_threshold and llm_ok:
            if (
                ambiguity_level >= 0.5
                or architecture_decision_required
                or multiple_valid_targets
            ):
                strategy = TransformationStrategy.LLM_GENERATED
                reasons.append(
                    "Business/architecture ambiguity requires "
                    "LLM-reasoned generation"
                )
            else:
                strategy = TransformationStrategy.LLM_ASSISTED
                reasons.append(
                    f"Coverage {coverage:.2f} below deterministic threshold; "
                    "LLM assists deterministic transformation"
                )
        elif coverage >= self.review_threshold and not llm_ok:
            strategy = TransformationStrategy.REVIEW_REQUIRED
            reasons.append(
                f"Coverage {coverage:.2f} insufficient for deterministic "
                "completion and LLM unavailable"
            )
        elif coverage < self.review_threshold and llm_ok:
            strategy = TransformationStrategy.LLM_GENERATED
            reasons.append(
                f"Low coverage ({coverage:.2f} < {self.review_threshold}); "
                "LLM reasoning is required to interpret semantics"
            )
        else:
            strategy = TransformationStrategy.BLOCKED
            reasons.append(
                f"Coverage {coverage:.2f} too low and LLM unavailable"
            )

        decision = StrategyDecision(
            unit_id=unit_id,
            source_technology=source_technology,
            target_technology=target_technology,
            strategy=strategy,
            rationale="; ".join(reasons),
            reasons=reasons,
            semantic_coverage=coverage,
            unresolved_semantics=unresolved,
            deterministic_mappable=bool(deterministic_mappable),
            llm_available=llm_ok,
            rag_available=rag_ok,
        )
        self._decisions.append(decision)
        return decision

    def roadmap(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for decision in self._decisions:
            counts[decision.strategy.value] = (
                counts.get(decision.strategy.value, 0) + 1
            )
        return counts


__all__ = [
    "TransformationStrategy",
    "StrategyDecision",
    "TransformationStrategySelector",
    "DETERMINISTIC_THRESHOLD",
    "REVIEW_THRESHOLD",
]