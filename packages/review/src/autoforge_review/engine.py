"""Review Engine — deterministic quality-control core (section 5).

The ReviewEngine is a QUALITY CONTROL subsystem.  It consumes evidence
produced by previous stages (Phase 10 Execution) and produces structured
findings and quality-gate decisions.  It is NOT a workflow engine,
execution engine, artifact manager, or agent runtime.

Lifecycle (section 29):

    Receive Artifact
    -> Analyze
    -> Validate
    -> Test
    -> Review
    -> Report Findings
    -> Approve / Reject

Deterministic-first (section 7): every answer that can be determined
deterministically is.  AI reasoning is invoked only where judgment is
required and can never override a deterministic blocking policy.
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from typing import Any

from autoforge_review.errors import ReviewValidationError
from autoforge_review.events import ReviewEvents
from autoforge_review.models import (
    GateStatus,
    QualityGateResult,
    ReviewCategory,
    ReviewCycleRecord,
    ReviewDecision,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
    ReviewResult,
    ReviewLoopResult,
    ReviewLoopStatus,
    Severity,
    is_at_least,

)
from autoforge_review.models import RepairRequest
from autoforge_review.policies import ReviewPolicy, default_review_policy
from autoforge_review.reviewers import (
    REVIEWER_REGISTRY,
    ReviewContext,
    SpecializedReviewer,
)



def _required_docs_present(evidence: ReviewEvidence, policy: ReviewPolicy) -> bool:
    """Deterministic check: every required documentation file is present."""
    files = set(evidence.source_files) | set(evidence.changed_files)
    return all(req in files for req in policy.required_documentation)


def _tests_pass(evidence: ReviewEvidence) -> bool:
    """Deterministic check: test results indicate no failures."""
    if evidence.test_results is None:
        return True  # absence is not a failure — treat as "not asserted"
    return (evidence.test_results.failed_tests + evidence.test_results.error_tests) == 0


def _build_gates(policy: ReviewPolicy) -> list[QualityGate]:
    """Context-free default gate set (section 16).

    Context-dependent gates (required docs / required categories) are appended
    by the engine per run, because they depend on the run's category scope.
    """
    return QualityGate.default_gates(policy)


@dataclass
class QualityGate:
    """Deterministic quality-gate evaluation (section 16).

    Each gate is a named, ordered check.  Gates are evaluated in
    declaration order; the first failing gate determines the outcome.
    """

    name: str
    check: Any  # callable(findings, evidence) -> tuple[bool, str]

    @staticmethod
    def default_gates(policy: ReviewPolicy) -> list["QualityGate"]:
        """Standard gate set for Phase 11 (section 16 examples)."""
        return [
            QualityGate(
                name="no_critical_findings",
                check=lambda f, e: (
                    not any(
                        fi.severity == Severity.CRITICAL and fi.blocking
                        for fi in f
                    ),
                    "No CRITICAL blocking findings allowed."
                    if any(fi.severity == Severity.CRITICAL and fi.blocking for fi in f)
                    else "",
                ),
            ),
            QualityGate(
                name="no_blocking_findings",
                check=lambda f, e: (
                    not any(fi.blocking for fi in f),
                    "No blocking findings allowed."
                    if any(fi.blocking for fi in f)
                    else "",
                ),
            ),
            QualityGate(
                name="no_high_severity_findings",
                check=lambda f, e: (
                    not any(
                        fi.severity in (Severity.HIGH, Severity.CRITICAL) for fi in f
                    ),
                    "High-severity findings require attention."
                    if any(fi.severity in (Severity.HIGH, Severity.CRITICAL) for fi in f)
                    else "",
                ),
            ),
            QualityGate(
                name="policy_compliant",
                check=lambda f, e: (
                    not any(
                        fi.requires_hitl and fi.blocking for fi in f
                    ),
                    "Policy violations present."
                    if any(fi.requires_hitl and fi.blocking for fi in f)
                    else "",
                ),
            ),
            QualityGate(
                name="tests_pass",
                check=lambda f, e: (
                    _tests_pass(e),
                    "Required tests failing.",
                ),
            ),
        ]

class ReviewEngine:
    """Central review orchestrator (section 5)."""

    def __init__(
        self,
        *,
        policy=None,
        ai_provider=None,
        event_sink=None,
        max_cycles: int = 3,
    ) -> None:
        self._policy = policy or default_review_policy()
        self._ai_provider = ai_provider
        self._events = ReviewEvents(event_sink) if event_sink else ReviewEvents(None)
        self._max_cycles = max_cycles

    async def review(self, request: ReviewRequest) -> ReviewResult:
        """Run a single, bounded review over request."""
        if not isinstance(request, ReviewRequest):
            raise ReviewValidationError(
                "review() requires a ReviewRequest instance",
                details={"received": type(request).__name__},
            )
        await self._events.emit("review.started", request)

        evidence = request.evidence
        has_files = bool(evidence.review_files or evidence.source_files)
        has_signals = (
            evidence.test_results is not None
            or evidence.build_exit_code is not None
            or bool(evidence.metrics)
            or bool(evidence.command_results)
        )
        if not has_files and not has_signals:
            # Nothing at all to review: vacuous pass (explicit, inspectable).
            result = ReviewResult(
                review_id=request.review_id,
                project_id=request.project_id,
                workflow_id=request.workflow_id,
                task_id=request.task_id,
                execution_id=request.execution_id,
                worker_id=request.worker_id,
                attempt_number=request.attempt_number,
                correlation_id=request.correlation_id,
                categories_run=[],
                findings=[],
                gate=QualityGateResult(
                    status=GateStatus.PASS,
                    satisfied_gates=["no_target"],
                ),
                decision=ReviewDecision.APPROVED,
                policy_version=self._policy.version,
            )
            await self._events.emit("review.completed", result)
            return result

        categories = self._policy.resolve_categories(request.categories)
        executed: list[ReviewCategory] = []
        all_findings: list = []
        ctx = ReviewContext(
            request=request,
            policy=self._policy,
            review_id=request.review_id,
            correlation_id=request.correlation_id,
            ai_provider=self._ai_provider,
        )

        for category in categories:
            review_cls = REVIEWER_REGISTRY.get(category)
            if review_cls is None:
                continue
            reviewer = review_cls(self._policy, ctx)
            review_findings = await reviewer.review_sync(request.evidence)
            all_findings.extend(review_findings)
            executed.append(category)

        gate = self._evaluate_gates(all_findings, request.evidence, categories, executed)
        decision = self._make_decision(gate, all_findings)

        result = ReviewResult(
            review_id=request.review_id,
            project_id=request.project_id,
            workflow_id=request.workflow_id,
            task_id=request.task_id,
            execution_id=request.execution_id,
            worker_id=request.worker_id,
            attempt_number=request.attempt_number,
            correlation_id=request.correlation_id,
            categories_run=[c.value for c in executed],
            findings=all_findings,
            count_by_category=_count_by(fi.category.value for fi in all_findings),
            count_by_severity=_count_by(fi.severity.value for fi in all_findings),
            deterministic_findings=sum(1 for fi in all_findings if fi.is_deterministic),
            ai_findings=sum(1 for fi in all_findings if fi.classification.value == "ai_assisted"),
            blocking_findings=sum(1 for fi in all_findings if fi.blocking),
            gate=gate,
            decision=decision,
            policy_version=self._policy.version,
        )

        if result.rejected:
            result = result.model_copy(
                update={"repair": RepairRequest.build(
                    review_id=request.review_id,
                    findings=all_findings,
                    task_id=request.task_id,
                    workflow_id=request.workflow_id,
                    project_id=request.project_id,
                    correlation_id=request.correlation_id,
                )}
            )

        await self._events.emit("review.completed", result)
        return result


    def _evaluate_gates(self, findings, evidence, categories=(), executed=None) -> QualityGateResult:
        gates = _build_gates(self._policy)

        # Context-dependent gates: closures over THIS run's scope.
        # - required docs only apply when documentation was actually reviewed.
        # - required-categories: every policy-required category within the
        #   requested scope must have been executed.  A scoped request is
        #   legitimate (section 5: the engine identifies review scope); the
        #   gate fails only when a required category in scope was never run
        #   (e.g. no registered reviewer).
        if ReviewCategory.DOCUMENTATION in categories:
            gates.append(
                QualityGate(
                    name="required_docs_present",
                    check=lambda f, e: (
                        _required_docs_present(e, self._policy),
                        "Required documentation missing.",
                    ),
                )
            )
        scoped = frozenset(categories)
        ran = frozenset(executed if executed is not None else categories)
        needed = self._policy.required() & scoped
        gates.append(
            QualityGate(
                name="required_categories_complete",
                check=lambda f, e: (
                    needed.issubset(ran),
                    "Required review categories not completed.",
                ),
            )
        )

        satisfied = []
        violated = []
        reasons = []

        for gate in gates:
            passed, msg = gate.check(findings, evidence)
            if passed:
                satisfied.append(gate.name)
            else:
                violated.append(gate.name)
                if msg:
                    reasons.append(msg)

        # Section 16: gate outcome must preserve status semantics.
        #   BLOCKED        hard deterministic stop (CRITICAL security etc.)
        #   REQUIRES_HITL  policy says a consequential decision needs a human
        #   FAIL           quality violated → repair loop
        #   PASS           all gates satisfied
        violated_set = set(violated)
        if "no_critical_findings" in violated_set:
            status = GateStatus.BLOCKED
        elif "policy_compliant" in violated_set:
            status = GateStatus.REQUIRES_HITL
        elif violated_set:
            status = GateStatus.FAIL
        else:
            status = GateStatus.PASS

        return QualityGateResult(
            status=status,
            reasons=reasons,
            satisfied_gates=satisfied,
            violated_gates=violated,
        )

    def _make_decision(self, gate, findings) -> ReviewDecision:
        if gate.status == GateStatus.BLOCKED:
            return ReviewDecision.REJECTED
        if gate.status == GateStatus.FAIL:
            return ReviewDecision.CHANGES_REQUESTED
        if gate.status == GateStatus.REQUIRES_HITL:
            return ReviewDecision.REQUIRES_HITL
        return ReviewDecision.APPROVED

    async def review_loop(self, request, *, max_cycles=None) -> ReviewLoopResult:
        cycles_limit = max_cycles or self._max_cycles
        cycles = []
        last_result = None

        for cycle in range(1, cycles_limit + 1):
            result = await self.review(request)
            last_result = result
            cycle_record = ReviewCycleRecord(
                cycle=cycle,
                review_id=result.review_id,
                gate=result.gate,
                decision=result.decision,
                finding_count=len(result.findings),
            )
            cycles.append(cycle_record)
            await self._events.emit("review.cycle_completed", cycle_record)

            if result.approved:
                return ReviewLoopResult(
                    status=ReviewLoopStatus.COMPLETED,
                    cycles=cycles,
                    final_result=result,
                )
            if result.rejected:
                return ReviewLoopResult(
                    status=ReviewLoopStatus.REPAIR_REQUESTED,
                    cycles=cycles,
                    final_result=result,
                    repair=result.repair,
                )
            if result.decision == ReviewDecision.REQUIRES_HITL:
                return ReviewLoopResult(
                    status=ReviewLoopStatus.HITL,
                    cycles=cycles,
                    final_result=result,
                )

        return ReviewLoopResult(
            status=ReviewLoopStatus.LIMIT_EXCEEDED,
            cycles=cycles,
            final_result=last_result,
        )


class ReviewLoop:
    """Bounded review loop wrapper (section 29)."""

    def __init__(self, engine: ReviewEngine) -> None:
        self._engine = engine

    async def run(self, request: ReviewRequest, *, max_cycles=None) -> ReviewLoopResult:
        return await self._engine.review_loop(request, max_cycles=max_cycles)


def _count_by(values) -> dict:
    counts = {}
    for v in values:
        key = str(v)
        counts[key] = counts.get(key, 0) + 1
    return counts


__all__ = ["ReviewEngine", "QualityGate", "ReviewLoop"]
