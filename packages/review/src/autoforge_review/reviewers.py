"""Specialized Reviewers — shared infrastructure, separate responsibilities.

One reviewer per canonical domain (section 8). All share the same
``SpecializedReviewer`` base and the ``ReviewContext`` contract so
the ReviewEngine is never duplicated five times. Each reviewer:

1. Runs deterministic rules (``RuleCheck``) first.
2. Optionally invokes AI reasoning (through Phase 7) for qualitative judgment.
3. Returns structured ``ReviewFinding`` records; policy finalisation
   (blocking / HITL / severity clamp) is applied centrally by the engine.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from typing import Any

from autoforge_review.ai_reviewer import AIReviewTask, ReviewAIProvider
from autoforge_review.checks import (
    check_architecture_import,
    check_bare_exceptions,
    check_build_success,
    check_complexity,
    check_dangerous_execution,
    check_execution_time,
    check_forbidden_imports,
    check_path_traversal,
    check_readme_sections,
    check_required_files,
    check_secret_leak,
    check_test_results,
    check_timeout,
    RuleCheck,
)
from autoforge_review.models import (
    AISourceMetadata,
    FindingClassification,
    FindingKind,
    FindingProvenance,
    ReviewCategory,
    ReviewFinding,
    ReviewRequest,
    Severity,
    is_at_least,
)
from autoforge_review.policies import ReviewPolicy


@dataclass
class ReviewContext:
    """Shared context passed to every reviewer for one review run."""

    request: ReviewRequest
    policy: ReviewPolicy
    review_id: str
    correlation_id: Any = field(default=None)
    ai_provider: ReviewAIProvider | None = field(default=None)


class SpecializedReviewer:
    """Base for all specialised reviewers (shared infrastructure)."""

    category: ReviewCategory

    def __init__(self, policy: ReviewPolicy, ctx: ReviewContext) -> None:
        self._policy = policy
        self._ctx = ctx
        self.ai_source: AISourceMetadata | None = None

    def run_checks(self, evidence: Any) -> list[RuleCheck]:
        """Subclasses implement deterministic rule evaluation against evidence."""
        raise NotImplementedError

    async def review_sync(self, evidence: Any) -> list[ReviewFinding]:
        """Run deterministic checks then optional AI assistance (section 29).

        Deterministic findings are always produced first; AI proposals
        supplement but never override them (sections 7, 21).
        """
        deterministic: list[ReviewFinding] = []
        for rule in self.run_checks(evidence):
            if not rule.passed:
                deterministic.append(self._from_rule(rule, self._ctx.review_id))
        ai = await self._ai_assist()
        return deterministic + ai

    async def _ai_assist(self) -> list[ReviewFinding]:
        """Optionally invoke AI reasoning through Phase 7 (section 22)."""
        if not self._policy.ai_enabled or not self._ctx.ai_provider:
            return []
        scope = self._ctx.request.evidence.review_files
        if not scope:
            return []
        task = AIReviewTask(
            category=self.category,
            scope=scope,
            policy_context=(
                f"Reviewing category: {self.category.value}; "
                f"policy {self._policy.to_version_dict()}"
            ),
        )
        try:
            result = await self._ctx.ai_provider.review(task)
        except Exception as exc:  # noqa: BLE001
            self.ai_source = AISourceMetadata(
                executed=False, prompt_version="review.v1", error_message=str(exc)
            )
            return []
        self.ai_source = result.ai_source
        findings: list[ReviewFinding] = []
        for prop in result.findings:
            clamped = self._policy.clamp_ai_severity(prop.severity)
            findings.append(
                ReviewFinding(
                    review_id=self._ctx.review_id,
                    category=self.category,
                    severity=clamped,
                    title=prop.title,
                    description=prop.description,
                    evidence=prop.evidence,
                    file=prop.file,
                    confidence=prop.confidence,
                    classification=FindingClassification.AI_ASSISTED,
                    kind=prop.kind,
                    remediation=prop.remediation,
                    blocking=is_at_least(
                        severity=clamped, threshold=Severity.CRITICAL
                    ),
                    requires_hitl=self._ai_hitl_required(prop, clamped),
                    provenance=FindingProvenance(
                        policy_version=self._policy.version,
                        ai_source=self.ai_source,
                    ),
                )
            )
        return findings


    def _ai_hitl_required(self, prop: Any, severity: Severity) -> bool:
        """Policy decides whether an AI finding triggers HITL."""
        if self._policy.ai_high_severity_requires_hitl and is_at_least(
            severity=severity, threshold=self._policy.max_ai_severity
        ):
            return True
        return self._policy.requires_hitl(prop.kind)

    def _from_rule(self, rule: RuleCheck, review_id: str) -> ReviewFinding:
        """Translate a deterministic RuleCheck into a ReviewFinding.

        The Policy decides blocking status (section 6): a deterministic
        rule is blocking when it is CRITICAL, or HIGH in a blocking category,
        unless an explicit exception is recorded.
        """
        blocking = False
        if not self._policy.is_exception_allowed(rule.rule_id):
            if rule.severity == Severity.CRITICAL:
                blocking = True
            elif (
                is_at_least(
                    severity=rule.severity,
                    threshold=self._policy.blocking_severity(),
                )
                and self._policy.is_blocking_category(self.category)
            ):
                blocking = True
        return ReviewFinding(
            finding_id=uuid.uuid4(),
            review_id=review_id,
            category=self.category,
            severity=rule.severity,
            title=rule.rule_id.replace("_", " ").title(),
            description=rule.message,
            evidence=rule.evidence,
            file=rule.file,
            start_line=rule.line,
            classification=FindingClassification.DETERMINISTIC,
            kind=rule.kind,
            blocking=blocking,
            requires_hitl=self._policy.requires_hitl(rule.kind),
            provenance=FindingProvenance(
                policy_version=self._policy.version,
                rule_id=rule.rule_id,
            ),
        )


# ── Architecture Review (section 9) ──────────────────────────────────────


class ArchitectureReviewer(SpecializedReviewer):
    category = ReviewCategory.ARCHITECTURE

    def run_checks(self, evidence: Any) -> list[RuleCheck]:
        checks: list[RuleCheck] = []
        for path, content in evidence.review_files.items():
            checks.append(check_forbidden_imports(content, file=path))
            if self._policy.boundary_map:
                for prefix in self._policy.boundary_map:
                    if path.startswith(prefix):
                        checks.append(
                            check_architecture_import(
                                content,
                                importer_prefix=prefix,
                                boundary=self._policy.boundary_map,
                                file=path,
                            )
                        )
        checks.extend(_duplicate_responsibility(evidence.review_files))
        return checks


def _duplicate_responsibility(files: dict[str, str]) -> list[RuleCheck]:
    """LOW finding: the same class is defined in multiple files."""
    klass_by_file: dict[str, list[str]] = {}
    for path, content in files.items():
        klass_by_file[path] = re.findall(
            r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]*)", content, re.MULTILINE
        )
    owners: dict[str, list[str]] = {}
    for path, names in klass_by_file.items():
        for n in names:
            owners.setdefault(n, []).append(path)
    dupes = {n: paths for n, paths in owners.items() if len(paths) > 1}
    if not dupes:
        return []
    return [
        RuleCheck(
            rule_id="duplicate_responsibility",
            passed=False,
            message=f"class defined in multiple files: {', '.join(dupes)}",
            severity=Severity.LOW,
            kind=FindingKind.ARCHITECTURE_EXCEPTION,
            evidence=[f"{n}: {', '.join(paths)}" for n, paths in dupes.items()],
        )
    ]



# ── Code Review (section 10) ─────────────────────────────────────────────


class CodeReviewer(SpecializedReviewer):
    category = ReviewCategory.CODE

    def run_checks(self, evidence: Any) -> list[RuleCheck]:
        checks: list[RuleCheck] = []
        for path, content in evidence.review_files.items():
            checks.append(check_complexity(content, file=path))
            checks.append(check_bare_exceptions(content, file=path))
            # Dependency policy (sections 7, 10, 35): forbidden frameworks
            # are a deterministic code-level violation as well.
            checks.append(check_forbidden_imports(content, file=path))
        checks.append(check_test_results(evidence.test_results))
        checks.append(check_build_success(evidence.build_exit_code))
        return checks


# ── Security Review (section 11) ──────────────────────────────────────────


class SecurityReviewer(SpecializedReviewer):
    """Deterministic-first security review (section 11).

    Inspects command injection, shell usage, path traversal, secret
    leakage, unsafe subprocess invocation, and authorization boundaries.
    """

    category = ReviewCategory.SECURITY

    def run_checks(self, evidence: Any) -> list[RuleCheck]:
        checks: list[RuleCheck] = []
        for path, content in evidence.review_files.items():
            checks.append(check_secret_leak(content, file=path))
            checks.append(check_dangerous_execution(content, file=path))
            checks.append(check_path_traversal(content, file=path))
            checks.append(check_forbidden_imports(content, file=path))
        return checks


# ── Performance Review (section 12) ───────────────────────────────────────


class PerformanceReviewer(SpecializedReviewer):
    """Performance review using deterministic metrics (section 12).

    Uses execution time, timeout events, and resource usage where available.
    AI may reason about algorithmic complexity but never invents benchmarks.
    """

    category = ReviewCategory.PERFORMANCE

    def run_checks(self, evidence: Any) -> list[RuleCheck]:
        checks: list[RuleCheck] = []
        checks.append(
            check_execution_time(
                evidence.metrics, budget_ms=self._policy.perf_budget_ms
            )
        )
        checks.append(check_timeout(evidence.command_results))
        return checks


# ── Documentation Review (section 13) ─────────────────────────────────────


class DocumentationReviewer(SpecializedReviewer):
    """Documentation quality review (section 13).

    Deterministic checks for required files and README sections; AI may
    supplement with qualitative consistency review.
    """

    category = ReviewCategory.DOCUMENTATION

    def run_checks(self, evidence: Any) -> list[RuleCheck]:
        checks: list[RuleCheck] = []
        checks.append(
            check_required_files(
                evidence.source_files, self._policy.required_documentation
            )
        )
        if self._policy.required_readme_sections:
            checks.append(
                check_readme_sections(
                    evidence.source_files,
                    self._policy.required_readme_sections,
                )
            )
        return checks


#: Registry mapping category -> reviewer class. Allows future workers
#: to receive domain-specific findings without hardcoding worker types.
REVIEWER_REGISTRY: dict[ReviewCategory, type[SpecializedReviewer]] = {
    ReviewCategory.ARCHITECTURE: ArchitectureReviewer,
    ReviewCategory.CODE: CodeReviewer,
    ReviewCategory.SECURITY: SecurityReviewer,
    ReviewCategory.PERFORMANCE: PerformanceReviewer,
    ReviewCategory.DOCUMENTATION: DocumentationReviewer,
}

__all__ = [
    "ReviewContext",
    "SpecializedReviewer",
    "ArchitectureReviewer",
    "CodeReviewer",
    "SecurityReviewer",
    "PerformanceReviewer",
    "DocumentationReviewer",
    "REVIEWER_REGISTRY",
]

