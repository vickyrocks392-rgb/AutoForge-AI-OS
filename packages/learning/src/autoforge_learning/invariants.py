"""The nine protected invariants — Phase 19B-2 (Gate 3 / M-08).

Architecture basis: ``phase19/REGRESSION_PROTECTION.md`` (Gate 19A-8 §2).

This module is a *transcription* of the certified contract, not a redesign.
The nine invariants, their class (ABSOLUTE / CRITICAL / HIGH / DEFERRED) and
their floors come verbatim from Gate 19A-8 §2. Nothing here adds an
invariant, renumbers one, or reclassifies one, and no scoring function is
substituted for them.

Three rules are load-bearing:

1. **Explicit result per invariant.** Every invariant receives exactly one
   :class:`InvariantStatus` — ``PASS``, ``FAIL``, ``UNAVAILABLE`` or
   ``NOT_APPLICABLE``. There is no implicit outcome and no default.
2. **Absence is never a pass.** ``UNAVAILABLE`` is a first-class outcome
   (Gate 19A-8 RM-06: insufficient evidence BLOCKS promotion).
3. **Only PI-8 may be ``NOT_APPLICABLE``.** Gate 19A-8 §2 records PI-8
   (customer outcomes) as *deferred — not measurable in Phase 19*. That is
   the single invariant the contract explicitly licenses as safely N/A, so
   it is the only entry in :data:`NA_PERMITTED_BY_CONTRACT`.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional

from pydantic import Field

from autoforge_learning.models import LearningBase, ValidationTruth

__test__ = False  # this module declares data models, not tests


class ProtectedInvariant(str, Enum):
    """The nine protected invariants of Gate 19A-8 §2, unmodified."""

    PI1_SECURITY = "PI-1"
    PI2_DETERMINISTIC_VALIDATION = "PI-2"
    PI3_REVIEW_ACCEPTANCE = "PI-3"
    PI4_COMPLETION_SUCCESS = "PI-4"
    PI5_CORRECTNESS = "PI-5"
    PI6_RELIABILITY = "PI-6"
    PI7_LATENCY_RESOURCES = "PI-7"
    PI8_CUSTOMER_OUTCOMES = "PI-8"
    PI9_ISOLATION_AUTHORITY = "PI-9"


class InvariantClass(str, Enum):
    """Gate 19A-8 §2 "Class" column."""

    ABSOLUTE = "absolute"
    CRITICAL = "critical"
    HIGH = "high"
    DEFERRED = "deferred"


class InvariantStatus(str, Enum):
    """Explicit per-invariant evaluation outcome.

    There is deliberately no ``SKIPPED``: Gate 19A-8 RM-02 requires every
    invariant to be evaluated, and an invariant that cannot be evaluated
    reports ``UNAVAILABLE`` rather than disappearing from the report.
    """

    PASS = "pass"
    FAIL = "fail"
    UNAVAILABLE = "unavailable"
    NOT_APPLICABLE = "not_applicable"

    @property
    def is_pass(self) -> bool:
        return self is InvariantStatus.PASS

    @property
    def is_absence(self) -> bool:
        """True when the outcome is an absence of evidence, not a success."""
        return self in (InvariantStatus.UNAVAILABLE, InvariantStatus.NOT_APPLICABLE)


class InvariantSpec(LearningBase):
    """Immutable description of one protected invariant."""

    invariant: ProtectedInvariant
    name: str
    invariant_class: InvariantClass
    floor: str
    measurement_source: str
    #: Required invariants must be PASS for a candidate to be promotable.
    required: bool
    #: Only invariants the 19A contract explicitly defers may be N/A.
    na_permitted_by_contract: bool = False
    #: Absolute invariants admit zero tolerance (Gate 19A-8 §2.1).
    tolerance: float = 0.0

    @property
    def is_absolute(self) -> bool:
        return self.invariant_class is InvariantClass.ABSOLUTE
def is_blocking(status: InvariantStatus, spec: InvariantSpec) -> bool:
    """Does this result prevent promotion of a candidate?

    Fail-closed in every branch: only an explicit PASS is non-blocking, and
    ``NOT_APPLICABLE`` is non-blocking *only* where the 19A contract says the
    invariant is not measurable.
    """
    if status is InvariantStatus.PASS:
        return False
    if status is InvariantStatus.NOT_APPLICABLE and spec.na_permitted_by_contract:
        return False
    return True


class InvariantMetrics(LearningBase):
    """Measured values for one subject (a baseline or a candidate).

    Every field is ``Optional``. An absent measurement stays absent; it is
    never defaulted to a favourable value. That is the whole point of the
    type: ``None`` and ``0`` are different facts.
    """

    security_violations: Optional[int] = Field(default=None, ge=0)
    validation_truth: ValidationTruth = ValidationTruth.UNAVAILABLE
    review_approved: Optional[bool] = None
    completion_succeeded: Optional[bool] = None
    tests_total: Optional[int] = Field(default=None, ge=0)
    tests_passed: Optional[int] = Field(default=None, ge=0)
    tests_failed: Optional[int] = Field(default=None, ge=0)
    tests_errors: Optional[int] = Field(default=None, ge=0)
    failure_rate: Optional[float] = Field(default=None, ge=0.0)
    retry_rate: Optional[float] = Field(default=None, ge=0.0)
    latency_ms: Optional[float] = Field(default=None, ge=0.0)
    isolation_violations: Optional[int] = Field(default=None, ge=0)
    cross_project_access_attempts: Optional[int] = Field(default=None, ge=0)
    customer_outcome_measured: bool = False

    @property
    def pass_rate(self) -> Optional[float]:
        if self.tests_total is None or self.tests_total == 0:
            return None
        passed = self.tests_passed
        if passed is None:
            return None
        return passed / self.tests_total


__all__ = [
    "EVIDENCE_SOURCE_PREFIX",
    "INVARIANT_IDS",
    "NA_PERMITTED_BY_CONTRACT",
    "PROTECTED_INVARIANTS",
    "SPECS",
    "SPEC_BY_INVARIANT",
    "InvariantClass",
    "InvariantMetrics",
    "InvariantSpec",
    "InvariantStatus",
    "ProtectedInvariant",
    "is_blocking",
]
SPECS: tuple[InvariantSpec, ...] = (
    InvariantSpec(
        invariant=ProtectedInvariant.PI1_SECURITY,
        name="Security",
        invariant_class=InvariantClass.ABSOLUTE,
        floor="ZERO regression, zero tolerance",
        measurement_source="audit security events; guardrail denials",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI2_DETERMINISTIC_VALIDATION,
        name="Deterministic validation",
        invariant_class=InvariantClass.ABSOLUTE,
        floor="ZERO regression",
        measurement_source="deterministic validation; completion gate",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI3_REVIEW_ACCEPTANCE,
        name="Review acceptance",
        invariant_class=InvariantClass.CRITICAL,
        floor="No decline beyond pre-registered tolerance",
        measurement_source="final review approved/rejected",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI4_COMPLETION_SUCCESS,
        name="Completion success",
        invariant_class=InvariantClass.CRITICAL,
        floor="No decline beyond pre-registered tolerance",
        measurement_source="project completion result",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI5_CORRECTNESS,
        name="Correctness",
        invariant_class=InvariantClass.CRITICAL,
        floor="No decline in pass rate / exit-code outcomes",
        measurement_source="deterministic test outcomes",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI6_RELIABILITY,
        name="Reliability",
        invariant_class=InvariantClass.HIGH,
        floor="No increase in failure or retry rate",
        measurement_source="execution failures; task retries",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI7_LATENCY_RESOURCES,
        name="Latency and resource usage",
        invariant_class=InvariantClass.HIGH,
        floor="No unbounded regression",
        measurement_source="model call cost/latency records",
        required=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI8_CUSTOMER_OUTCOMES,
        name="Customer outcomes",
        invariant_class=InvariantClass.DEFERRED,
        floor="Not measurable in Phase 19",
        measurement_source="deferred (Gate 4 §5)",
        required=False,
        na_permitted_by_contract=True,
    ),
    InvariantSpec(
        invariant=ProtectedInvariant.PI9_ISOLATION_AUTHORITY,
        name="Isolation and authority integrity",
        invariant_class=InvariantClass.ABSOLUTE,
        floor="ZERO regression",
        measurement_source="project-scoped access; authorization denials; HITL decisions",
        required=True,
    ),
)

SPEC_BY_INVARIANT: dict[ProtectedInvariant, InvariantSpec] = {s.invariant: s for s in SPECS}

#: Contract-ordered tuple — the evaluation report is checked against this exact
#: sequence, so a dropped or reordered invariant is a hard failure (RM-02).
PROTECTED_INVARIANTS: tuple[ProtectedInvariant, ...] = tuple(s.invariant for s in SPECS)

#: The only invariants the 19A contract permits to be ``NOT_APPLICABLE``.
NA_PERMITTED_BY_CONTRACT: frozenset[ProtectedInvariant] = frozenset(
    s.invariant for s in SPECS if s.na_permitted_by_contract
)

#: Convenience view of the contract identifiers, e.g. ``"PI-1"``.
INVARIANT_IDS: tuple[str, ...] = tuple(i.value for i in PROTECTED_INVARIANTS)

#: Prefixes used to attribute an ``EvidenceRef`` to an invariant when detecting
#: conflicting evidence. Deliberately explicit — no fuzzy matching.
EVIDENCE_SOURCE_PREFIX: dict[ProtectedInvariant, str] = {
    ProtectedInvariant.PI1_SECURITY: "security",
    ProtectedInvariant.PI2_DETERMINISTIC_VALIDATION: "validation",
    ProtectedInvariant.PI3_REVIEW_ACCEPTANCE: "review",
    ProtectedInvariant.PI4_COMPLETION_SUCCESS: "completion",
    ProtectedInvariant.PI5_CORRECTNESS: "correctness",
    ProtectedInvariant.PI6_RELIABILITY: "reliability",
    ProtectedInvariant.PI7_LATENCY_RESOURCES: "latency",
    ProtectedInvariant.PI8_CUSTOMER_OUTCOMES: "customer",
    ProtectedInvariant.PI9_ISOLATION_AUTHORITY: "isolation",
}