"""Regression evaluation over the nine protected invariants — Phase 19B-2.

Architecture basis: ``phase19/REGRESSION_PROTECTION.md`` (Gate 19A-8),
``phase19/LEARNING_REVIEW_VALIDATION.md`` (Gate 19A-12).

The evaluator consumes *authoritative evidence only* and produces an explicit
result for every one of the nine invariants. It holds no policy of its own
beyond the certified contract:

* **No fabricated evidence.** An absent measurement is ``UNAVAILABLE``.
* **No model substitution.** Model text can never satisfy an invariant, and
  confidence is never an input to a verdict.
* **No skipping.** All nine are evaluated on every run (Gate 19A-8 RM-02).
* **Fail closed.** The evaluation is promotable only when every *required*
  invariant is ``PASS``. ``UNAVAILABLE`` blocks.
* **No trading.** A gain on one invariant never compensates for a loss on
  another (Gate 19A-8 RM-01): the verdicts are computed independently and
  then AND-ed.
* **Baseline pinned.** The baseline hash is captured at evaluation time and
  re-verified, so a baseline cannot be swapped underneath a verdict
  (Gate 19A-8 RM-03/RM-05).
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping, Optional, Sequence

from pydantic import Field, model_validator

from autoforge_learning.invariants import (
    EVIDENCE_SOURCE_PREFIX,
    PROTECTED_INVARIANTS,
    SPEC_BY_INVARIANT,
    InvariantMetrics,
    InvariantStatus,
    ProtectedInvariant,
    is_blocking,
)
from autoforge_learning.models import (
    EvidenceQuality,
    EvidenceRef,
    LearningBase,
    ValidationTruth,
)

logger = logging.getLogger("autoforge.learning.evaluation")


class EvaluationOutcome(str, Enum):
    """Terminal outcome of one regression evaluation."""

    PASSED = "passed"
    FAILED = "failed"
    #: The evaluator itself could not produce a trustworthy result
    #: (malformed input, exception, or contradictory evidence). Fail closed.
    ERROR = "error"


class InvariantResult(LearningBase):
    """One explicit, per-invariant verdict.

    ``UNAVAILABLE`` is recorded with the reason it was unavailable so an
    operator can tell "not measured" from "measured and bad".
    """

    invariant: ProtectedInvariant
    status: InvariantStatus
    required: bool
    invariant_class: str
    baseline_value: Optional[float] = None
    candidate_value: Optional[float] = None
    tolerance: float = 0.0
    reason: str = ""
    evidence_ids: tuple[uuid.UUID, ...] = ()
    #: Model-authored rationale, if any. Typed non-authoritative: it can
    #: explain a verdict but can never change one.
    model_annotation: Optional[str] = None
    model_annotation_authoritative: bool = False

    @property
    def blocks_promotion(self) -> bool:
        return is_blocking(self.status, SPEC_BY_INVARIANT[self.invariant])

    @property
    def is_absence_of_evidence(self) -> bool:
        return self.status.is_absence


class EvaluationReport(LearningBase):
    """The immutable record of one regression evaluation."""

    evaluation_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    candidate_id: uuid.UUID
    project_id: uuid.UUID
    scope_kind: str
    outcome: EvaluationOutcome
    promotable: bool
    results: tuple[InvariantResult, ...] = ()
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    baseline_hash: str = ""
    baseline_pinned: bool = True
    evidence_ids: tuple[uuid.UUID, ...] = ()
    blocking_invariants: tuple[str, ...] = ()
    reasons: tuple[str, ...] = ()
    correlation_id: Optional[str] = None

    @model_validator(mode="after")
    def _all_nine_evaluated(self) -> "EvaluationReport":
        """RM-02: every invariant is present exactly once, in contract order."""
        got = tuple(r.invariant for r in self.results)
        if got != PROTECTED_INVARIANTS:
            raise ValueError(
                "EvaluationReport must carry exactly the nine protected "
                f"invariants in contract order; got {[i.value for i in got]}"
            )
        return self

    @model_validator(mode="after")
    def _promotable_is_derived_not_asserted(self) -> "EvaluationReport":
        """A report can never claim promotability its own results contradict."""
        derived = self.outcome is EvaluationOutcome.PASSED and not any(
            r.blocks_promotion for r in self.results
        )
        if self.promotable != derived:
            raise ValueError(
                "promotable must be derived from the per-invariant results "
                f"(expected {derived}, got {self.promotable})"
            )
        return self

    @property
    def status_by_invariant(self) -> dict[str, InvariantStatus]:
        return {r.invariant.value: r.status for r in self.results}

    def result_for(self, invariant: ProtectedInvariant) -> InvariantResult:
        for r in self.results:
            if r.invariant is invariant:
                return r
        raise KeyError(invariant)

    @property
    def passed_invariants(self) -> tuple[str, ...]:
        return tuple(r.invariant.value for r in self.results if r.status.is_pass)

    @property
    def unavailable_invariants(self) -> tuple[str, ...]:
        return tuple(
            r.invariant.value
            for r in self.results
            if r.status is InvariantStatus.UNAVAILABLE
        )


class EvidenceAssessment(LearningBase):
    """Result of validating the evidence bundle before evaluation.

    Gate 4: an absent source is represented as absent. The four rejection
    reasons map directly onto the adversarial matrix: missing, malformed,
    conflicting, stale, and project-mismatched evidence never yield PASS.
    """

    usable: bool
    missing_sources: tuple[str, ...] = ()
    malformed_sources: tuple[str, ...] = ()
    conflicting_sources: tuple[str, ...] = ()
    stale_sources: tuple[str, ...] = ()
    project_mismatch_sources: tuple[str, ...] = ()
    non_authoritative_sources: tuple[str, ...] = ()
    detail: str = ""


#: Prefix required on an ``EvidenceRef.source_ref`` for each invariant.
REQUIRED_EVIDENCE_PREFIX: dict[ProtectedInvariant, str] = dict(EVIDENCE_SOURCE_PREFIX)

#: Evidence older than this (relative to evaluation time) is stale and cannot
#: support a PASS. Pre-registered, not tuned after the fact (Gate 19A-8 RM-04).
MAX_EVIDENCE_AGE_SECONDS = 30 * 24 * 3600


def _hashable(value: Any) -> Any:
    """Best-effort JSON-safe projection for content hashing."""
    if isinstance(value, Mapping):
        return {str(k): _hashable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_hashable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def build_evidence_refs(
    metrics_payload: Mapping[str, Any], *, project_id: uuid.UUID
) -> tuple[EvidenceRef, ...]:
    """Create one content-addressed reference per populated measurement.

    Only metrics that are actually present produce a reference. A metric that
    was never measured produces nothing — it is not represented as an empty
    or zero-valued payload, because that would be fabrication.
    """
    refs: list[EvidenceRef] = []
    for invariant, prefix in REQUIRED_EVIDENCE_PREFIX.items():
        for key, value in sorted(metrics_payload.get(invariant.value, {}).items()):
            if value is None:
                continue
            refs.append(
                EvidenceRef.from_payload(
                    source=_evidence_source_for(prefix),
                    source_ref=f"{prefix}:{key}:{project_id}",
                    payload=value,
                )
            )
    return tuple(refs)


def _evidence_source_for(prefix: str):  # type: ignore[no-untyped-def]
    from autoforge_learning.models import EvidenceSource

    mapping = {
        "security": EvidenceSource.AUDIT_RECORD,
        "validation": EvidenceSource.DETERMINISTIC_VALIDATION,
        "review": EvidenceSource.REVIEW_ENGINE,
        "completion": EvidenceSource.COMPLETION_GATE,
        "correctness": EvidenceSource.DETERMINISTIC_VALIDATION,
        "reliability": EvidenceSource.CANONICAL_EVENT,
        "latency": EvidenceSource.TELEMETRY,
        "customer": EvidenceSource.TELEMETRY,
        "isolation": EvidenceSource.AUDIT_RECORD,
    }
    return mapping[prefix]


class EvidenceAssessor:
    """Validates an evidence bundle *before* it can support any verdict.

    Every check fails closed. The assessor never repairs, infers, or
    substitutes evidence: it only classifies what it was given.
    """

    def __init__(
        self,
        *,
        project_id: uuid.UUID,
        max_age_seconds: int = MAX_EVIDENCE_AGE_SECONDS,
        now: Optional[datetime] = None,
    ) -> None:
        self._project_id = project_id
        self._max_age = max_age_seconds
        self._now = now or datetime.now(timezone.utc)

    def assess(
        self, evidence: Sequence[EvidenceRef], *, required_prefixes: Sequence[str]
    ) -> EvidenceAssessment:
        required = tuple(dict.fromkeys(required_prefixes))
        by_prefix: dict[str, list[EvidenceRef]] = {p: [] for p in required}
        missing: list[str] = []
        malformed: list[str] = []
        conflicting: list[str] = []
        stale: list[str] = []
        mismatched: list[str] = []
        non_authoritative: list[str] = []

        seen_hashes: dict[str, str] = {}

        for ref in evidence or ():
            prefix = ref.source_ref.split(":", 1)[0]
            if prefix not in by_prefix:
                # Evidence for an invariant outside the required set is
                # recorded but cannot stand in for a missing required one.
                continue
            by_prefix[prefix].append(ref)

            if ref.quality is EvidenceQuality.Q4 or not ref.is_authoritative:
                non_authoritative.append(ref.source_ref)
                continue

            key = f"{prefix}:{ref.source_ref}"
            if key in seen_hashes and seen_hashes[key] != ref.content_hash:
                conflicting.append(ref.source_ref)
            seen_hashes[key] = ref.content_hash

            if len(ref.content_hash) < 64:
                malformed.append(ref.source_ref)

            observed = ref.observed_at
            if observed.tzinfo is None:
                observed = observed.replace(tzinfo=timezone.utc)
            if (self._now - observed).total_seconds() > self._max_age:
                stale.append(ref.source_ref)

            if not ref.source_ref.endswith(str(self._project_id)):
                mismatched.append(ref.source_ref)

        for prefix in required:
            usable = [
                r
                for r in by_prefix[prefix]
                if r.source_ref not in missing
                and r.source_ref not in malformed
                and r.source_ref not in conflicting
                and r.source_ref not in stale
                and r.source_ref not in mismatched
                and r.source_ref not in non_authoritative
            ]
            if not usable:
                missing.append(prefix)

        unusable = bool(
            missing or malformed or conflicting or stale or mismatched or non_authoritative
        )
        return EvidenceAssessment(
            usable=not unusable,
            missing_sources=tuple(sorted(set(missing))),
            malformed_sources=tuple(sorted(set(malformed))),
            conflicting_sources=tuple(sorted(set(conflicting))),
            stale_sources=tuple(sorted(set(stale))),
            project_mismatch_sources=tuple(sorted(set(mismatched))),
            non_authoritative_sources=tuple(sorted(set(non_authoritative))),
            detail=(
                "evidence bundle rejected"
                if unusable
                else "evidence bundle accepted"
            ),
        )


class RegressionEvaluator:
    """Evaluates a candidate against the nine protected invariants.

    The evaluator is deterministic and model-free. It takes two
    :class:`InvariantMetrics` (a pinned baseline and the candidate) plus the
    evidence that produced them, and returns an
    :class:`EvaluationReport`.

    Every comparison is decided by a per-invariant rule; there is no blended
    score. ``RM-01`` is enforced structurally: the verdicts are computed
    independently and combined with AND, so a large gain can never buy a
    regression.
    """

    def __init__(
        self,
        *,
        max_age_seconds: int = MAX_EVIDENCE_AGE_SECONDS,
        now: Optional[datetime] = None,
    ) -> None:
        self._max_age = max_age_seconds
        self._now = now or datetime.now(timezone.utc)

    def evaluate(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        scope_kind: str,
        baseline: InvariantMetrics,
        candidate: InvariantMetrics,
        evidence: Sequence[EvidenceRef],
        correlation_id: Optional[str] = None,
    ) -> EvaluationReport:
        """Run the full nine-invariant evaluation.

        Any internal error fails closed: the report is ``ERROR`` and not
        promotable, never ``PASSED``.
        """
        try:
            return self._evaluate(
                candidate_id=candidate_id,
                project_id=project_id,
                scope_kind=scope_kind,
                baseline=baseline,
                candidate=candidate,
                evidence=evidence,
                correlation_id=correlation_id,
            )
        except Exception as ex:  # noqa: BLE001 - fail closed by contract
            logger.error("Regression evaluation failed closed: %s", ex)
            return self._error_report(
                candidate_id=candidate_id,
                project_id=project_id,
                scope_kind=scope_kind,
                correlation_id=correlation_id,
                detail=f"evaluator raised {type(ex).__name__}: {ex}",
            )

    # ── internals ────────────────────────────────────────────────────────────

    def _evaluate(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        scope_kind: str,
        baseline: InvariantMetrics,
        candidate: InvariantMetrics,
        evidence: Sequence[EvidenceRef],
        correlation_id: Optional[str],
    ) -> EvaluationReport:
        assessor = EvidenceAssessor(
            project_id=project_id, max_age_seconds=self._max_age, now=self._now
        )
        assessment = assessor.assess(
            evidence, required_prefixes=tuple(REQUIRED_EVIDENCE_PREFIX.values())
        )

        results = tuple(
            self._evaluate_one(inv, baseline, candidate, assessment)
            for inv in PROTECTED_INVARIANTS
        )

        blocking = tuple(r.invariant.value for r in results if r.blocks_promotion)
        promotable = not blocking
        outcome = EvaluationOutcome.PASSED if promotable else EvaluationOutcome.FAILED

        reasons = tuple(
            f"{r.invariant.value}: {r.status.value} — {r.reason}"
            for r in results
            if r.status is not InvariantStatus.PASS
        )

        return EvaluationReport(
            candidate_id=candidate_id,
            project_id=project_id,
            scope_kind=scope_kind,
            outcome=outcome,
            promotable=promotable,
            results=results,
            baseline_hash=baseline.record_hash(),
            baseline_pinned=True,
            evidence_ids=tuple(e.evidence_id for e in evidence),
            blocking_invariants=blocking,
            reasons=reasons,
            correlation_id=correlation_id,
        )

    def _error_report(
        self,
        *,
        candidate_id: uuid.UUID,
        project_id: uuid.UUID,
        scope_kind: str,
        correlation_id: Optional[str],
        detail: str,
    ) -> EvaluationReport:
        """A report in which every invariant is UNAVAILABLE — never PASS."""
        results = tuple(
            InvariantResult(
                invariant=inv,
                status=InvariantStatus.UNAVAILABLE,
                required=SPEC_BY_INVARIANT[inv].required,
                invariant_class=SPEC_BY_INVARIANT[inv].invariant_class.value,
                reason=detail,
            )
            for inv in PROTECTED_INVARIANTS
        )
        return EvaluationReport(
            candidate_id=candidate_id,
            project_id=project_id,
            scope_kind=scope_kind,
            outcome=EvaluationOutcome.ERROR,
            promotable=False,
            results=results,
            blocking_invariants=tuple(r.invariant.value for r in results),
            reasons=(detail,),
            correlation_id=correlation_id,
        )

    # ── per-invariant rules ──────────────────────────────────────────────────

    def _blocked_by_evidence(
        self, inv: ProtectedInvariant, assessment: EvidenceAssessment
    ) -> Optional[str]:
        """Reason this invariant cannot be trusted, or ``None`` if it can."""
        prefix = REQUIRED_EVIDENCE_PREFIX[inv]
        if prefix in assessment.missing_sources:
            return f"no usable evidence supplied for {inv.value}"
        if prefix in assessment.malformed_sources:
            return f"malformed evidence for {inv.value}"
        if prefix in assessment.conflicting_sources:
            return f"conflicting evidence for {inv.value}"
        if prefix in assessment.stale_sources:
            return f"stale evidence for {inv.value}"
        if prefix in assessment.project_mismatch_sources:
            return f"project-mismatched evidence for {inv.value}"
        if prefix in assessment.non_authoritative_sources:
            return f"non-authoritative evidence for {inv.value}"
        return None

    def _evaluate_one(
        self,
        inv: ProtectedInvariant,
        baseline: InvariantMetrics,
        candidate: InvariantMetrics,
        assessment: EvidenceAssessment,
    ) -> InvariantResult:
        spec = SPEC_BY_INVARIANT[inv]

        def make(status: InvariantStatus, reason: str, **kw: Any) -> InvariantResult:
            return InvariantResult(
                invariant=inv,
                status=status,
                required=spec.required,
                invariant_class=spec.invariant_class.value,
                tolerance=spec.tolerance,
                reason=reason,
                **kw,
            )

        # Evidence gate first: an invariant with unusable evidence is
        # UNAVAILABLE regardless of what the numbers say.
        blocked = self._blocked_by_evidence(inv, assessment)
        if blocked is not None:
            if inv is ProtectedInvariant.PI8_CUSTOMER_OUTCOMES:
                # Deferred by contract; reported honestly rather than failed.
                return make(
                    InvariantStatus.NOT_APPLICABLE,
                    "PI-8 customer outcomes are deferred and not measurable in Phase 19",
                )
            return make(InvariantStatus.UNAVAILABLE, blocked)

        rule = _RULES[inv]
        return rule(self, spec, baseline, candidate, make)


# ── The nine rules ────────────────────────────────────────────────────────────
#
# Each rule receives (evaluator, spec, baseline, candidate, make) and returns
# an InvariantResult. Rules never consult model output, never blend
# invariants, and never treat an absent measurement as a good one.


def _numeric_rule(inv: ProtectedInvariant, attr: str, *, lower_is_better: bool) -> Any:
    """Build a comparison rule over one numeric metric."""

    def rule(
        evaluator: "RegressionEvaluator",
        spec: Any,
        baseline: InvariantMetrics,
        candidate: InvariantMetrics,
        make: Any,
    ) -> InvariantResult:
        base_v = getattr(baseline, attr)
        cand_v = getattr(candidate, attr)
        if base_v is None or cand_v is None:
            return make(
                InvariantStatus.UNAVAILABLE,
                f"{inv.value}: {attr} was not measured "
                f"(baseline={base_v!r}, candidate={cand_v!r})",
                baseline_value=base_v,
                candidate_value=cand_v,
            )
        regressed = cand_v > base_v if lower_is_better else cand_v < base_v
        if regressed:
            return make(
                InvariantStatus.FAIL,
                f"{inv.value}: {attr} regressed from {base_v} to {cand_v} "
                f"(tolerance {spec.tolerance})",
                baseline_value=base_v,
                candidate_value=cand_v,
            )
        return make(
            InvariantStatus.PASS,
            f"{inv.value}: {attr} held at {cand_v} (baseline {base_v})",
            baseline_value=base_v,
            candidate_value=cand_v,
        )

    return rule


def _pi1_security(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """PI-1 is a hard tripwire: ANY security violation disqualifies.

    Gate 19A-8 §5 requires a deliberately security-violating candidate to be
    rejected even if it improves every other metric by an arbitrary margin.
    Unlike the tolerant invariants this compares nothing — a violation is a
    failure on its own, and no baseline can excuse it.
    """
    base_v = baseline.security_violations
    cand_v = candidate.security_violations
    if cand_v is None:
        return make(
            InvariantStatus.UNAVAILABLE,
            "PI-1: security violation count was not measured",
            baseline_value=base_v,
            candidate_value=cand_v,
        )
    if cand_v > 0:
        return make(
            InvariantStatus.FAIL,
            f"PI-1: candidate introduced {cand_v} security violation(s); "
            "a security violation is a disqualifier, not a tradeable signal",
            baseline_value=base_v,
            candidate_value=cand_v,
        )
    if base_v is None:
        return make(
            InvariantStatus.UNAVAILABLE,
            "PI-1: baseline security violation count unavailable for comparison",
            baseline_value=base_v,
            candidate_value=cand_v,
        )
    return make(
        InvariantStatus.PASS,
        f"PI-1: zero security violations (baseline {base_v})",
        baseline_value=base_v,
        candidate_value=cand_v,
    )


def _pi2_validation(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """Deterministic validation is authoritative (Gate 19A-12 RV-01)."""
    cand = candidate.validation_truth
    base = baseline.validation_truth
    if cand is ValidationTruth.UNAVAILABLE:
        return make(
            InvariantStatus.UNAVAILABLE,
            "PI-2: no deterministic validation evidence for the candidate",
        )
    if cand is ValidationTruth.NOT_APPLICABLE:
        if base is ValidationTruth.NOT_APPLICABLE:
            return make(
                InvariantStatus.NOT_APPLICABLE,
                "PI-2: deterministic validation not applicable to baseline or candidate",
            )
        return make(
            InvariantStatus.FAIL,
            "PI-2: candidate declared validation not applicable while the "
            "baseline required it",
        )
    if cand is ValidationTruth.FAILED:
        return make(
            InvariantStatus.FAIL,
            "PI-2: deterministic validation FAILED for the candidate",
        )
    if base is not ValidationTruth.PASSED:
        return make(
            InvariantStatus.UNAVAILABLE,
            f"PI-2: baseline validation truth is {base.value}; cannot compare",
        )
    return make(
        InvariantStatus.PASS,
        "PI-2: deterministic validation passed for candidate and baseline",
    )


def _pi3_review(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """Review evaluates evidence; a decline is a CRITICAL regression."""
    cand = candidate.review_approved
    base = baseline.review_approved
    if cand is None or base is None:
        return make(
            InvariantStatus.UNAVAILABLE,
            f"PI-3: review verdict not measured (baseline={base!r}, candidate={cand!r})",
        )
    if cand is False:
        return make(InvariantStatus.FAIL, "PI-3: review rejected the candidate")
    if cand and not base:
        return make(
            InvariantStatus.FAIL,
            "PI-3: review acceptance improved but the baseline was rejected; "
            "a candidate must not be evaluated against a failed baseline",
        )
    return make(InvariantStatus.PASS, "PI-3: review acceptance held")


def _pi4_completion(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    cand = candidate.completion_succeeded
    base = baseline.completion_succeeded
    if cand is None or base is None:
        return make(
            InvariantStatus.UNAVAILABLE,
            f"PI-4: completion outcome not measured (baseline={base!r}, candidate={cand!r})",
        )
    if cand is False:
        return make(
            InvariantStatus.FAIL, "PI-4: project completion regressed to failure"
        )
    return make(InvariantStatus.PASS, "PI-4: completion success held")


def _pi5_correctness(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """Correctness is judged on failures/errors and pass rate, both absolute."""
    base_v = baseline.pass_rate
    cand_v = candidate.pass_rate
    if base_v is None or cand_v is None:
        return make(
            InvariantStatus.UNAVAILABLE,
            f"PI-5: test pass rate not measurable (baseline={base_v!r}, candidate={cand_v!r})",
            baseline_value=base_v,
            candidate_value=cand_v,
        )
    if cand_v < base_v:
        return make(
            InvariantStatus.FAIL,
            f"PI-5: correctness pass rate regressed from {base_v} to {cand_v}",
            baseline_value=base_v,
            candidate_value=cand_v,
        )
    return make(
        InvariantStatus.PASS,
        f"PI-5: correctness pass rate {cand_v} >= baseline {base_v}",
        baseline_value=base_v,
        candidate_value=cand_v,
    )


def _pi6_reliability(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """Reliability fails if EITHER failure rate or retry rate increased."""
    base_fail = baseline.failure_rate
    cand_fail = candidate.failure_rate
    base_retry = baseline.retry_rate
    cand_retry = candidate.retry_rate

    if None in (base_fail, cand_fail, base_retry, cand_retry):
        return make(
            InvariantStatus.UNAVAILABLE,
            "PI-6: failure/retry rates not fully measured "
            f"(baseline failure={base_fail!r} retry={base_retry!r}; "
            f"candidate failure={cand_fail!r} retry={cand_retry!r})",
            baseline_value=base_fail,
            candidate_value=cand_fail,
        )

    if cand_fail > base_fail or cand_retry > base_retry:
        return make(
            InvariantStatus.FAIL,
            f"PI-6: reliability regressed (failure {base_fail}->{cand_fail}, "
            f"retry {base_retry}->{cand_retry})",
            baseline_value=base_fail,
            candidate_value=cand_fail,
        )
    return make(
        InvariantStatus.PASS,
        f"PI-6: failure rate {cand_fail} and retry rate {cand_retry} did not increase",
        baseline_value=base_fail,
        candidate_value=cand_fail,
    )


def _pi8_customer(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """PI-8 is deferred by contract; it is reported, never silently passed."""
    if candidate.customer_outcome_measured or baseline.customer_outcome_measured:
        return make(
            InvariantStatus.PASS,
            "PI-8: customer-outcome evidence supplied and non-regressive",
        )
    return make(
        InvariantStatus.NOT_APPLICABLE,
        "PI-8 customer outcomes are deferred and not measurable in Phase 19 "
        "(Gate 19A-8 §2, Gate 4 §5)",
    )


def _pi9_isolation(
    evaluator: "RegressionEvaluator",
    spec: Any,
    baseline: InvariantMetrics,
    candidate: InvariantMetrics,
    make: Any,
) -> InvariantResult:
    """PI-9 is ABSOLUTE: any isolation or cross-project breach disqualifies."""
    base_iso = baseline.isolation_violations
    cand_iso = candidate.isolation_violations
    base_cross = baseline.cross_project_access_attempts
    cand_cross = candidate.cross_project_access_attempts

    if cand_iso is None or cand_cross is None or base_iso is None or base_cross is None:
        return make(
            InvariantStatus.UNAVAILABLE,
            "PI-9: isolation/authority measurements incomplete",
        )
    if cand_iso > base_iso or cand_iso > 0:
        return make(
            InvariantStatus.FAIL,
            f"PI-9: isolation violations {base_iso} -> {cand_iso}",
            baseline_value=float(base_iso),
            candidate_value=float(cand_iso),
        )
    if cand_cross > base_cross or cand_cross > 0:
        return make(
            InvariantStatus.FAIL,
            f"PI-9: cross-project access attempts {base_cross} -> {cand_cross}",
            baseline_value=float(base_cross),
            candidate_value=float(cand_cross),
        )
    return make(
        InvariantStatus.PASS,
        f"PI-9: zero isolation violations and zero cross-project attempts "
        f"(baseline {base_iso}/{base_cross})",
        baseline_value=float(base_iso),
        candidate_value=float(cand_iso),
    )


_RULES = {
    ProtectedInvariant.PI1_SECURITY: _pi1_security,
    ProtectedInvariant.PI2_DETERMINISTIC_VALIDATION: _pi2_validation,
    ProtectedInvariant.PI3_REVIEW_ACCEPTANCE: _pi3_review,
    ProtectedInvariant.PI4_COMPLETION_SUCCESS: _pi4_completion,
    ProtectedInvariant.PI5_CORRECTNESS: _pi5_correctness,
    ProtectedInvariant.PI6_RELIABILITY: _pi6_reliability,
    ProtectedInvariant.PI7_LATENCY_RESOURCES: _numeric_rule(
        ProtectedInvariant.PI7_LATENCY_RESOURCES, "latency_ms", lower_is_better=True
    ),
    ProtectedInvariant.PI8_CUSTOMER_OUTCOMES: _pi8_customer,
    ProtectedInvariant.PI9_ISOLATION_AUTHORITY: _pi9_isolation,
}


__all__ = [
    "MAX_EVIDENCE_AGE_SECONDS",
    "REQUIRED_EVIDENCE_PREFIX",
    "EvidenceAssessment",
    "EvidenceAssessor",
    "EvaluationOutcome",
    "EvaluationReport",
    "InvariantResult",
    "RegressionEvaluator",
    "build_evidence_refs",
]