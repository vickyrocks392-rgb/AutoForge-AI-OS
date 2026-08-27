"""Test Specialized Reviewers (Section 8).

Each reviewer runs deterministic rules first (sections 7, 21), classifies
findings, and optionally supplements with AI reasoning through Phase 7
(section 22). AI proposals never override deterministic findings.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_execution.models import CommandResult

from autoforge_review.ai_reviewer import AIReviewResult, ProposedFinding
from autoforge_review.models import (
    AISourceMetadata,
    FindingClassification,
    ReviewCategory,
    ReviewEvidence,
    ReviewFinding,
    ReviewRequest,
    Severity,
)
from autoforge_review.policies import (
    ReviewPolicy,
    default_review_policy,
)
from autoforge_review.reviewers import (
    ArchitectureReviewer,
    CodeReviewer,
    DocumentationReviewer,
    PerformanceReviewer,
    REVIEWER_REGISTRY,
    ReviewContext,
    SecurityReviewer,
)

pytestmark = pytest.mark.asyncio


class StubAI:
    """Deterministic ReviewAIProvider double (no external provider)."""

    def __init__(self, proposals=None, error: Exception | None = None) -> None:
        self.proposals = list(proposals or [])
        self.error = error
        self.calls: list[object] = []

    async def review(self, task):
        self.calls.append(task)
        if self.error is not None:
            raise self.error
        return AIReviewResult(
            findings=list(self.proposals),
            ai_source=AISourceMetadata(
                executed=True,
                provider_id="stub",
                model_id="stub-model",
                prompt_version="review.v1",
            ),
        )


def _ctx(
    files: dict[str, str] | None = None,
    *,
    policy: ReviewPolicy | None = None,
    ai_provider=None,
    review_id: str = "r-1",
):
    req = ReviewRequest(
        review_id=review_id,
        correlation_id=uuid.uuid4(),
        evidence=ReviewEvidence(source_files=files or {}),
    )
    pol = policy or default_review_policy()
    return ReviewContext(
        request=req,
        policy=pol,
        review_id=review_id,
        correlation_id=req.correlation_id,
        ai_provider=ai_provider,
    )


def _run(reviewer_cls, ctx):
    return reviewer_cls(ctx.policy, ctx).review_sync(ctx.request.evidence)


def _titles(findings: list[ReviewFinding]) -> list[str]:
    return [f.title.lower() for f in findings]


async def test_architecture_reviewer_detects_forbidden_import() -> None:
    """Architecture review flags banned frameworks deterministically (s.9/35)."""
    ctx = _ctx(files={"app.py": "from langgraph import Graph\n"})
    findings = await _run(ArchitectureReviewer, ctx)
    assert any("forbidden" in t for t in _titles(findings))
    f = findings[0]
    assert f.classification == FindingClassification.DETERMINISTIC
    assert f.blocking  # forbidden frameworks are policy violations


async def test_architecture_reviewer_boundary_map() -> None:
    """Custom boundary rules flag prohibited coupling (s.9)."""
    policy = ReviewPolicy(boundary_map={"svc/": ("autoforge_workflows",)})
    ctx = _ctx(
        files={"svc/mod.py": "from autoforge_workflows import engine\n"},
        policy=policy,
    )
    findings = await _run(ArchitectureReviewer, ctx)
    assert any("architecture boundary" in t for t in _titles(findings))


async def test_architecture_reviewer_duplicate_responsibility() -> None:
    """The same class in two files is an architecture finding (s.9)."""
    ctx = _ctx(
        files={
            "a.py": "class Dup:\n    pass\n",
            "b.py": "class Dup:\n    pass\n",
        }
    )
    findings = await _run(ArchitectureReviewer, ctx)
    assert any("duplicate responsibility" in t for t in _titles(findings))


async def test_code_reviewer_detects_bare_except() -> None:
    """Code review flags bare except clauses (s.10)."""
    ctx = _ctx(files={"app.py": "try:\n    x = 1\nexcept:\n    pass\n"})
    findings = await _run(CodeReviewer, ctx)
    assert any("bare except" in t for t in _titles(findings))


async def test_code_reviewer_detects_forbidden_dependency() -> None:
    """Dependency policy applies in code review too (s.7/10/35)."""
    ctx = _ctx(files={"app.py": "import celery\n"})
    findings = await _run(CodeReviewer, ctx)
    assert any("forbidden" in t for t in _titles(findings))


async def test_security_reviewer_detects_dangerous_execution() -> None:
    """Security review flags shell/subprocess dangers and blocks (s.11)."""
    ctx = _ctx(
        files={"app.py": "import subprocess\nsubprocess.call('ls', shell=True)\n"}
    )
    findings = await _run(SecurityReviewer, ctx)
    assert any("dangerous execution" in t for t in _titles(findings))
    sec = [f for f in findings if "dangerous execution" in f.title.lower()]
    assert sec[0].blocking  # HIGH security finding under default policy


async def test_security_reviewer_detects_secret_leak() -> None:
    """Security review flags credential material (s.11)."""
    ctx = _ctx(files={"config.py": "API_KEY = 'sk-1234567890abcdef'\n"})
    findings = await _run(SecurityReviewer, ctx)
    assert any("secret leak" in t for t in _titles(findings))


async def test_documentation_reviewer_detects_missing_required_files() -> None:
    """Documentation review flags missing required files (s.13)."""
    ctx = _ctx(files={"app.py": "# no docs\n"})
    findings = await _run(DocumentationReviewer, ctx)
    assert any("required files" in t for t in _titles(findings))


async def test_documentation_reviewer_detects_missing_sections() -> None:
    """Strict policies demand README sections (s.13)."""
    policy = ReviewPolicy(required_readme_sections=["Installation", "Usage"])
    ctx = _ctx(files={"README.md": "# Title\n\nBody.\n"}, policy=policy)
    findings = await _run(DocumentationReviewer, ctx)
    assert any("readme sections" in t for t in _titles(findings))


async def test_performance_reviewer_detects_budget_breach() -> None:
    """Performance review uses measured metrics against a budget (s.12)."""
    policy = ReviewPolicy(perf_budget_ms=100.0)
    ctx = _ctx(files={"app.py": "x = 1\n"}, policy=policy)
    ctx.request.evidence.metrics["duration_ms"] = 500.0
    findings = await _run(PerformanceReviewer, ctx)
    assert any("perf time" in t for t in _titles(findings))


async def test_performance_reviewer_detects_timeout() -> None:
    """Timed-out command evidence is a deterministic perf finding (s.12)."""
    ctx = _ctx(files={"app.py": "x = 1\n"})
    ctx.request.evidence.command_results.append(
        CommandResult(
            command=["pytest", "-q"],
            exit_code=124,
            duration_seconds=61.0,
            timed_out=True,
        )
    )
    findings = await _run(PerformanceReviewer, ctx)
    assert any("perf timeout" in t for t in _titles(findings))


async def test_every_reviewer_declares_its_category() -> None:
    """Each reviewer owns exactly one canonical category (s.8)."""
    mapping = {
        ArchitectureReviewer: ReviewCategory.ARCHITECTURE,
        CodeReviewer: ReviewCategory.CODE,
        SecurityReviewer: ReviewCategory.SECURITY,
        PerformanceReviewer: ReviewCategory.PERFORMANCE,
        DocumentationReviewer: ReviewCategory.DOCUMENTATION,
    }
    for cls, expected in mapping.items():
        assert cls.category == expected
    assert set(REVIEWER_REGISTRY) == set(mapping.values())


async def test_all_deterministic_findings_are_classified() -> None:
    """Deterministic findings carry the DETERMINISTIC classification (s.9)."""
    ctx = _ctx(
        files={
            "bad.py": "import os\nos.system('ls')\n",
            "good.py": "print('hello')\n",
        }
    )
    findings = await _run(SecurityReviewer, ctx)
    assert findings
    for f in findings:
        assert f.classification == FindingClassification.DETERMINISTIC


async def test_ai_proposals_are_clamped_by_policy() -> None:
    """AI severity recommendations are clamped by policy (s.15, 22)."""
    policy = ReviewPolicy(ai_enabled=True)  # max_ai_severity=MEDIUM
    stub = StubAI(
        proposals=[
            ProposedFinding(
                title="AI Says Critical",
                severity=Severity.CRITICAL,
                description="LLM overreaction",
                confidence=0.9,
            )
        ]
    )
    ctx = _ctx(files={"app.py": "x = 1\n"}, policy=policy, ai_provider=stub)
    findings = await _run(CodeReviewer, ctx)
    ai = [f for f in findings if f.classification == FindingClassification.AI_ASSISTED]
    assert len(ai) == 1
    assert ai[0].severity == Severity.MEDIUM  # clamped, never raised by AI
    assert ai[0].blocking is False  # clamped AI findings never block
    assert ai[0].requires_hitl  # high-severity AI acceptance needs a human
    assert ai[0].provenance is not None
    assert ai[0].provenance.ai_source is not None
    assert ai[0].provenance.ai_source.model_id == "stub-model"


async def test_ai_assist_records_failure_and_degrades() -> None:
    """AI failures degrade safely: recorded, never fatal (s.4, 22)."""
    policy = ReviewPolicy(ai_enabled=True)
    stub = StubAI(error=RuntimeError("provider down"))
    ctx = _ctx(files={"app.py": "x = 1\n"}, policy=policy, ai_provider=stub)
    reviewer = CodeReviewer(policy, ctx)
    findings = await reviewer.review_sync(ctx.request.evidence)
    assert findings == []  # clean file, AI failed → no findings at all
    assert reviewer.ai_source is not None
    assert reviewer.ai_source.executed is False
    assert "provider down" in (reviewer.ai_source.error_message or "")


async def test_ai_not_invoked_when_policy_disables() -> None:
    """Default policy keeps AI off — deterministic-only review (s.7)."""
    stub = StubAI(proposals=[ProposedFinding(title="X", severity=Severity.HIGH)])
    ctx = _ctx(files={"app.py": "x = 1\n"}, ai_provider=stub)
    findings = await _run(CodeReviewer, ctx)
    assert stub.calls == []  # AI never consulted
    assert findings == []

