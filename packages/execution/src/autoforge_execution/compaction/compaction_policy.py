"""
Context Compaction — Policy: information classification, triggers, retention
(18-L Gate 3, implementing Gate 2 §6, §7, §15, §16).

Two things matter here and nothing else:

1. **Classification.** Every compacted item is mapped onto one of the Gate 2
   preservation classes, derived from the *real* AutoForge structures rather than
   from guesswork (Gate 2 §6). The class drives what compaction is allowed to do
   with the item.

2. **Triggers.** Compaction fires on deterministic, measurable conditions only —
   never on a model's judgement (Gate 2 §16, Gate 3 §16).

**Thresholds are evidence-derived, not guessed.** Gate 2 §34 Q-1/Q-2 marked them
UNKNOWN. They were measured in ``context-compaction-gate3/measure_growth.py``:
a mean raw ``LoopIterationRecord`` is **311.3** estimated tokens and its structured
projection **80.7** tokens, a **74%** deterministic reduction. The defaults below
are derived from those measurements and are documented in ``policy_version`` so a
future change is explicit (Gate 2 §20).

Provider neutrality: this module imports no runtime, provider or model. It
operates purely on structured AutoForge state.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

from autoforge_execution.context_items import ContextCategory, ContextItem
from autoforge_execution.compaction.compaction_schema import (
    CompactionTrigger,
    PreservationClass,
)

#: Bump whenever classification or trigger semantics change (Gate 2 §20). A bump
#: changes the request fingerprint, so previously compacted records are never
#: silently reinterpreted — they are superseded by a new logical version.
DEFAULT_POLICY_VERSION = 1


# ── Evidence-derived defaults (Gate 3 §15) ────────────────────────────────

#: Mean estimated tokens of one raw ``LoopIterationRecord`` (measured).
MEAN_RAW_ITERATION_TOKENS = 311.3

#: Mean estimated tokens of its structured projection (measured).
MEAN_PROJECTION_ITERATION_TOKENS = 80.7

#: How many recent iterations stay inline. 3 iterations ≈ 934 tokens ≈ 2.9% of a
#: 32k window, which preserves the active attempt -> failure -> correction loop
#: the next operation needs (Gate 2 §10, Gate 3 §15).
DEFAULT_RETENTION_WINDOW = 3

#: Fire once history exceeds the retention window, so at least one iteration is
#: always compacted. Deterministic, and meaningful by construction.
DEFAULT_ITERATION_COUNT_TRIGGER = 4

#: Budget-pressure floor, measured below one full raw iteration record, so
#: compaction fires *before* MSC starts excluding optional items for budget.
DEFAULT_BUDGET_PRESSURE_FLOOR_TOKENS = 2048

#: Candidate-count pressure: well above a normal assembly (4 measured), so it
#: only fires on genuinely large candidate pools.
DEFAULT_CANDIDATE_COUNT_TRIGGER = 12


# ── Classification (Gate 2 §6) ────────────────────────────────────────────

#: Categories whose content must never be dropped, summarised or model-transformed
#: (Gate 2 §6 Irreplaceable). Derived from Gate 2 E-3 plus Gate 3 §7: the task
#: objective, project/system constraints and decision/governance material.
IRREPLACEABLE_CATEGORIES: frozenset[ContextCategory] = frozenset(
    {
        ContextCategory.TASK,
        ContextCategory.SYSTEM,
        ContextCategory.PROJECT,
        ContextCategory.DECISION,
    }
)

#: Categories that represent observed/verified state. They are preserved
#: inline, but are *reconstructable* from durable artifacts, so a compacted copy
#: may reference the artifact instead of inlining the body.
RECONSTRUCTABLE_CATEGORIES: frozenset[ContextCategory] = frozenset(
    {
        ContextCategory.EVIDENCE,
        ContextCategory.VERIFICATION,
        ContextCategory.EXECUTION,
        ContextCategory.TOOL,
        ContextCategory.TEST_OUTPUT,
        ContextCategory.GIT,
    }
)

#: Everything else (dependency edges, runtime state views) is contextual and
#: reconstructable from authoritative runtime state.
RECONSTRUCTABLE_DEFAULT = True

#: Source kinds whose items are explicitly marked Irreplaceable regardless of
#: category, because they carry governance authority (Gate 2 §14).
IRREPLACEABLE_SOURCE_KINDS: frozenset[str] = frozenset(
    {"approval", "governance", "policy", "user_instruction"}
)


def classify_item(item: ContextItem) -> PreservationClass:
    """Map one item onto its preservation class (Gate 2 §6).

    Deterministic and total: every item gets a class. Nothing is silently
    unclassified, which is what makes "every intentional omission must be
    explainable" (Gate 3 §7) verifiable.
    """
    if item.source.kind in IRREPLACEABLE_SOURCE_KINDS:
        return PreservationClass.IRREPLACEABLE
    if item.category in IRREPLACEABLE_CATEGORIES:
        return PreservationClass.IRREPLACEABLE
    if item.category in RECONSTRUCTABLE_CATEGORIES:
        return PreservationClass.RECONSTRUCTABLE
    return (
        PreservationClass.RECONSTRUCTABLE
        if RECONSTRUCTABLE_DEFAULT
        else PreservationClass.HISTORICAL
    )


def classify_items(items: Iterable[ContextItem]) -> dict[str, int]:
    """Count items per preservation class, for the observability record."""
    counts: dict[str, int] = {}
    for item in items:
        cls = classify_item(item).value
        counts[cls] = counts.get(cls, 0) + 1
    return counts


# ── Triggers (Gate 2 §7, §16; Gate 3 §16) ────────────────────────────────


@dataclass(frozen=True)
class CompactionPolicy:
    """Bounded, deterministic, configurable compaction policy.

    Every field is a hard number: compaction decisions are reproducible and
    explainable, never emergent or model-judged (Gate 2 §16).
    """

    enabled: bool = False
    """Gate 3 §29/§30: default OFF. Context Engineering stays ON; this is a
    separate, independently reversible feature."""

    policy_version: int = DEFAULT_POLICY_VERSION
    retention_window: int = DEFAULT_RETENTION_WINDOW
    iteration_count_trigger: int = DEFAULT_ITERATION_COUNT_TRIGGER
    budget_pressure_floor_tokens: int = DEFAULT_BUDGET_PRESSURE_FLOOR_TOKENS
    candidate_count_trigger: int = DEFAULT_CANDIDATE_COUNT_TRIGGER
    max_record_tokens: int = 8192
    """Upper bound on a compact record's own estimated size (Gate 2 V-7)."""

    def should_compact(
        self,
        *,
        iteration_count: int,
        candidate_count: int,
        remaining_budget_tokens: int | None,
    ) -> tuple[bool, str | None]:
        """Decide whether to compact, and why.

        Returns ``(True, trigger)`` or ``(False, None)``. Pure function of its
        inputs — no clock, no randomness, no model.
        """
        if not self.enabled:
            return False, None
        if iteration_count >= self.iteration_count_trigger:
            return True, CompactionTrigger.ITERATION_BOUNDARY.value
        if (
            remaining_budget_tokens is not None
            and remaining_budget_tokens < self.budget_pressure_floor_tokens
        ):
            return True, CompactionTrigger.BUDGET_PRESSURE.value
        if candidate_count >= self.candidate_count_trigger:
            return True, CompactionTrigger.CANDIDATE_PRESSURE.value
        return False, None

    def iterations_to_retain(self, iteration_count: int) -> int:
        """How many recent iterations stay inline (Gate 2 §10)."""
        return max(0, min(iteration_count, self.retention_window))

    def iterations_to_compact(self, iteration_count: int) -> int:
        """How many older iterations are eligible for compaction."""
        return max(0, iteration_count - self.retention_window)

    def describe(self) -> dict[str, Any]:
        """Content-free description of the active policy."""
        return {
            "enabled": self.enabled,
            "policy_version": self.policy_version,
            "retention_window": self.retention_window,
            "iteration_count_trigger": self.iteration_count_trigger,
            "budget_pressure_floor_tokens": self.budget_pressure_floor_tokens,
            "candidate_count_trigger": self.candidate_count_trigger,
            "max_record_tokens": self.max_record_tokens,
        }


#: The Gate 3 production posture: compaction exists but is OFF (Gate 3 §30).
DEFAULT_POLICY = CompactionPolicy(enabled=False)


__all__ = [
    "DEFAULT_BUDGET_PRESSURE_FLOOR_TOKENS",
    "DEFAULT_CANDIDATE_COUNT_TRIGGER",
    "DEFAULT_ITERATION_COUNT_TRIGGER",
    "DEFAULT_POLICY",
    "DEFAULT_POLICY_VERSION",
    "DEFAULT_RETENTION_WINDOW",
    "IRREPLACEABLE_CATEGORIES",
    "IRREPLACEABLE_SOURCE_KINDS",
    "MEAN_PROJECTION_ITERATION_TOKENS",
    "MEAN_RAW_ITERATION_TOKENS",
    "RECONSTRUCTABLE_CATEGORIES",
    "CompactionPolicy",
    "classify_item",
    "classify_items",
]
