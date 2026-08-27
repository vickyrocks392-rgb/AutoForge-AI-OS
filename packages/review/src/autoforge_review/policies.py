"""Review Policies — explicit, inspectable, deterministic policies (section 6).

Policies determine which categories are reviewed, which deterministic checks
apply, severity thresholds, blocking conditions, required documentation,
allowed exceptions, and HITL-required decisions.

Rules are DATA, not hidden prompt text.  An LLM may recommend severity, but the
Policy finalises classification and an LLM can never override a deterministic
blocking policy (sections 16, 21).
"""

from __future__ import annotations

from typing import Any

from autoforge_review.models import ReviewCategory, FindingKind, Severity


class ReviewPolicy:
    """Deterministic policy object governing a review run."""

    def __init__(
        self,
        *,
        policy_id: str = "default",
        version: str = "1.0.0",
        enabled_categories: frozenset[ReviewCategory] | None = None,
        required_categories: frozenset[ReviewCategory] | None = None,
        ai_enabled: bool = False,
        blocking_categories: frozenset[ReviewCategory] | None = None,
        hitl_required_kinds: frozenset[FindingKind] | None = None,
        required_documentation: list[str] | None = None,
        required_readme_sections: list[str] | None = None,
        perf_budget_ms: float = 5000.0,
        max_ai_severity: Severity = Severity.MEDIUM,
        ai_high_severity_requires_hitl: bool = True,
        blocking_severity: Severity = Severity.HIGH,
        boundary_map: dict[str, tuple[str, ...]] | None = None,
        allowed_exceptions: frozenset[str] | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.policy_id = policy_id
        self.version = version
        self.metadata = dict(metadata or {})

        self._enabled = (
            enabled_categories
            if enabled_categories is not None
            else frozenset(ReviewCategory)
        )
        self._required = (
            required_categories
            if required_categories is not None
            else frozenset(ReviewCategory)
        )
        self.ai_enabled = ai_enabled
        self._blocking = (
            blocking_categories
            if blocking_categories is not None
            else frozenset({ReviewCategory.SECURITY, ReviewCategory.ARCHITECTURE})
        )
        self.hitl_required_kinds = (
            hitl_required_kinds
            if hitl_required_kinds is not None
            else frozenset(
                {
                    FindingKind.TECH_STACK_FINALIZATION,
                    FindingKind.SECURITY_EXCEPTION,
                    FindingKind.ARCHITECTURE_EXCEPTION,
                }
            )
        )
        self.required_documentation = list(required_documentation or ["README.md"])
        self.required_readme_sections = list(required_readme_sections or [])
        self.perf_budget_ms = perf_budget_ms
        self.max_ai_severity = max_ai_severity
        self.ai_high_severity_requires_hitl = ai_high_severity_requires_hitl
        self._blocking_severity = blocking_severity
        self.boundary_map: dict[str, tuple[str, ...]] = dict(boundary_map or {})
        self.allowed_exceptions: frozenset[str] = frozenset(allowed_exceptions or ())

    # ── scope resolution ───────────────────────────────────────────────────

    def enabled(self) -> frozenset[ReviewCategory]:
        return self._enabled

    def required(self) -> frozenset[ReviewCategory]:
        return self._required

    def resolve_categories(self, requested: frozenset[ReviewCategory] | None) -> list[ReviewCategory]:
        """Return ordered categories for this run (request ∩ enabled, else enabled)."""
        if requested:
            chosen = [c for c in ReviewCategory if c in requested and c in self._enabled]
        else:
            chosen = [c for c in ReviewCategory if c in self._enabled]
        return chosen

    def is_aspect_blocking(self) -> int:
        """Return ordering used for deterministic gate blocking (security first)."""
        return {
            ReviewCategory.SECURITY: 0,
            ReviewCategory.ARCHITECTURE: 1,
            ReviewCategory.PERFORMANCE: 2,
            ReviewCategory.CODE: 3,
            ReviewCategory.DOCUMENTATION: 4,
        }

    def is_blocking_category(self, category: ReviewCategory) -> bool:
        return category in self._blocking

    def blocking_severity(self) -> Severity:
        """Deterministic severity threshold: findings at/above it block."""
        return self._blocking_severity

    def requires_hitl(self, kind: FindingKind) -> bool:
        return kind in self.hitl_required_kinds

    def is_exception_allowed(self, rule_id: str) -> bool:
        """A deterministic rule may be non-blocking only via an explicit exception."""
        return rule_id in self.allowed_exceptions

    # ── AI behaviour ───────────────────────────────────────────────────────

    def clamp_ai_severity(self, severity: Severity) -> Severity:
        """AI-recommended severities are clamped to policy; the LLM never raises."""
        rank_ai = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        rank_max = rank_ai[self.max_ai_severity.value]
        if rank_ai[severity.value] > rank_max:
            for key, rank in rank_ai.items():
                if rank == rank_max:
                    return Severity(key)
        return severity

    def to_version_dict(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "version": self.version,
            "enabled_categories": sorted(c.value for c in self._enabled),
            "required_categories": sorted(c.value for c in self._required),
            "ai_enabled": self.ai_enabled,
            "blocking_categories": sorted(c.value for c in self._blocking),
            "hitl_required_kinds": sorted(k.value for k in self.hitl_required_kinds),
            "required_documentation": self.required_documentation,
            "max_ai_severity": self.max_ai_severity.value,
            "blocking_severity": self._blocking_severity.value,
        }


#: Simple factory for a policy that reviews every category deterministically.
def default_review_policy(**kwargs: Any) -> ReviewPolicy:
    return ReviewPolicy(**kwargs)


#: Strict policy: every category blocking, lower tolerance, tighter AI ceiling.
def strict_review_policy(**kwargs: Any) -> ReviewPolicy:
    return ReviewPolicy(
        policy_id="strict",
        enabled_categories=frozenset(ReviewCategory),
        required_categories=frozenset(ReviewCategory),
        blocking_categories=frozenset(ReviewCategory),
        blocking_severity=Severity.MEDIUM,
        max_ai_severity=Severity.LOW,
        required_readme_sections=["Installation", "Usage"],
        **kwargs,
    )


#: Permissive policy: only security blocks at CRITICAL; AI ceiling raised.
def permissive_review_policy(**kwargs: Any) -> ReviewPolicy:
    return ReviewPolicy(
        policy_id="permissive",
        enabled_categories=frozenset(ReviewCategory),
        required_categories=frozenset(
            {ReviewCategory.CODE, ReviewCategory.SECURITY}
        ),
        blocking_categories=frozenset({ReviewCategory.SECURITY}),
        blocking_severity=Severity.CRITICAL,
        max_ai_severity=Severity.HIGH,
        ai_high_severity_requires_hitl=False,
        **kwargs,
    )