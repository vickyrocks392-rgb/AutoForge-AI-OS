"""
Context Assembly Observability — content-free by construction.

Gate 2 §8. The record answers every question the mandate asks ("what was selected,
why, what was mandatory, what was rejected, which dependencies expanded, what budget
applied, did it fit, did a mandatory failure occur") **without storing context text**.

Content-freedom is structural, not a policy: nothing in this module has a field that
can hold a context payload. Only identifiers, categories, counts, token estimates,
and reasons are recorded.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from autoforge_execution.context_budget import ContextWindowBudget
from autoforge_execution.context_items import ContextItem


@dataclass(frozen=True)
class SelectedContextEntry:
    """One delivered item, described without its payload."""

    context_id: str
    category: str
    required: bool
    estimated_tokens: int
    cacheability: str
    provenance_ref: str
    provenance_inferred: bool
    required_for: tuple[str, ...] = ()
    dependency_depth: int = 0


@dataclass(frozen=True)
class ExcludedContextEntry:
    """One rejected candidate, with the reason it did not make it."""

    context_id: str
    category: str
    required: bool
    reason: str


@dataclass
class ContextAssemblyRecord:
    """Per-operation record of one Context Engineering assembly."""

    task_id: str
    stage: str = ""
    correlation_id: str = ""
    attempt_number: int = 1
    model_id: str = ""

    declared_required_window_tokens: int = 0
    context_window_tokens: int = 0
    budget: dict[str, Any] = field(default_factory=dict)

    considered_count: int = 0
    selected_count: int = 0
    excluded_count: int = 0
    selected: list[SelectedContextEntry] = field(default_factory=list)
    excluded: list[ExcludedContextEntry] = field(default_factory=list)
    category_breakdown: dict[str, int] = field(default_factory=dict)
    deduplicated_count: int = 0

    expansion_depth_reached: int = 0
    expansion_items_added: int = 0
    expansion_truncated_by_bound: bool = False

    mandatory_tokens: int = 0
    optional_tokens: int = 0
    stable_prefix_tokens: int = 0
    char_fallback_used: bool = False
    budget_source: str = ""
    construction_duration_ms: float = 0.0
    mandatory_overflow: bool = False

    @property
    def delivered_context_ids(self) -> tuple[str, ...]:
        """Ids that actually reached the model (Gate 2 section 5)."""
        return tuple(entry.context_id for entry in self.selected)

    def as_dict(self) -> dict[str, Any]:
        """Serializable, content-free view suitable for logging or persistence."""
        return {
            "task_id": self.task_id,
            "stage": self.stage,
            "correlation_id": self.correlation_id,
            "attempt_number": self.attempt_number,
            "model_id": self.model_id,
            "declared_required_window_tokens": self.declared_required_window_tokens,
            "context_window_tokens": self.context_window_tokens,
            "budget": dict(self.budget),
            "considered_count": self.considered_count,
            "selected_count": self.selected_count,
            "excluded_count": self.excluded_count,
            "category_breakdown": dict(self.category_breakdown),
            "deduplicated_count": self.deduplicated_count,
            "expansion": {
                "depth_reached": self.expansion_depth_reached,
                "items_added": self.expansion_items_added,
                "truncated_by_bound": self.expansion_truncated_by_bound,
            },
            "mandatory_tokens": self.mandatory_tokens,
            "optional_tokens": self.optional_tokens,
            "stable_prefix_tokens": self.stable_prefix_tokens,
            "char_fallback_used": self.char_fallback_used,
            "budget_source": self.budget_source,
            "construction_duration_ms": self.construction_duration_ms,
            "mandatory_overflow": self.mandatory_overflow,
            "selected": [
                {
                    "context_id": e.context_id,
                    "category": e.category,
                    "required": e.required,
                    "estimated_tokens": e.estimated_tokens,
                    "cacheability": e.cacheability,
                    "provenance_ref": e.provenance_ref,
                    "provenance_inferred": e.provenance_inferred,
                    "required_for": list(e.required_for),
                    "dependency_depth": e.dependency_depth,
                }
                for e in self.selected
            ],
            "excluded": [
                {
                    "context_id": e.context_id,
                    "category": e.category,
                    "required": e.required,
                    "reason": e.reason,
                }
                for e in self.excluded
            ],
        }


def selected_entry(item: ContextItem) -> SelectedContextEntry:
    """Build the content-free record entry for a delivered item."""
    provenance = item.provenance
    return SelectedContextEntry(
        context_id=item.context_id,
        category=item.category.value,
        required=item.required,
        estimated_tokens=item.estimated_tokens,
        cacheability=item.cacheability.value,
        provenance_ref=(
            f"{provenance.acquired_from}:{provenance.source_ref}" if provenance else ""
        ),
        provenance_inferred=bool(provenance.inferred) if provenance else True,
        required_for=tuple(item.required_for),
        dependency_depth=item.dependency_depth,
    )


    mandatory_tokens: int = 0
    optional_tokens: int = 0
    stable_prefix_tokens: int = 0

def build_record(
    *,
    task_id: str,
    stage: str,
    correlation_id: str,
    attempt_number: int,
    budget: ContextWindowBudget,
    selected: list[ContextItem],
    excluded: list[tuple[ContextItem, str]],
    considered_count: int,
    deduplicated_count: int,
    expansion_depth_reached: int,
    expansion_items_added: int,
    expansion_truncated_by_bound: bool,
    construction_duration_ms: float,
    char_fallback_used: bool = False,
) -> ContextAssemblyRecord:
    """Assemble a complete, content-free record for one operation."""
    category_breakdown: dict[str, int] = {}
    for item in selected:
        category_breakdown[item.category.value] = (
            category_breakdown.get(item.category.value, 0) + 1
        )

    stable_prefix = sum(
        item.estimated_tokens
        for item in selected
        if item.cacheability.value in {"stable_system", "stable_project"}
    )

    return ContextAssemblyRecord(
        task_id=task_id,
        stage=stage,
        correlation_id=correlation_id,
        attempt_number=attempt_number,
        model_id=budget.model_id,
        declared_required_window_tokens=budget.declared_required_window_tokens,
        context_window_tokens=budget.model_context_window_tokens,
        budget=budget.snapshot(),
        considered_count=considered_count,
        selected_count=len(selected),
        excluded_count=len(excluded),
        selected=[selected_entry(item) for item in selected],
        excluded=[
            ExcludedContextEntry(
                context_id=item.context_id,
                category=item.category.value,
                required=item.required,
                reason=reason,
            )
            for item, reason in excluded
        ],
        category_breakdown=category_breakdown,
        deduplicated_count=deduplicated_count,
        expansion_depth_reached=expansion_depth_reached,
        expansion_items_added=expansion_items_added,
        expansion_truncated_by_bound=expansion_truncated_by_bound,
        mandatory_tokens=sum(i.estimated_tokens for i in selected if i.required),
        optional_tokens=sum(i.estimated_tokens for i in selected if not i.required),
        stable_prefix_tokens=stable_prefix,
        char_fallback_used=char_fallback_used,
        budget_source=budget.budget_source.value,
        construction_duration_ms=construction_duration_ms,
        mandatory_overflow=False,
    )

    char_fallback_used: bool = False
    budget_source: str = ""
    construction_duration_ms: float = 0.0
    mandatory_overflow: bool = False

    @property
    def delivered_context_ids(self) -> tuple[str, ...]:
        """Ids that actually reached the model (Gate 2 §5)."""
        return tuple(entry.context_id for entry in self.selected)
