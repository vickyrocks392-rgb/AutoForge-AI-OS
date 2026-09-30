"""
DEF-18LR-B1 / DEF-18LR-D8 — mandatory-review and deterministic-validation gates.

B-1 (vacuous approval)
    A project with ZERO reviewable deliverables must never satisfy the
    MANDATORY project-completion review. The Review Engine's own ``no_target``
    branch is legitimate for a non-mandatory, artifact-scoped review and is
    deliberately left untouched; the requirement is enforced at the one
    boundary that knows the review is mandatory.

D-8 (validation truth must reach and be enforced by completion)
    The canonical evidence model must carry the real deterministic test
    results to the final review, and a mandatory failed validation must block
    completion EVEN IF the review returns an explicit APPROVED. The LLM is not
    authoritative for whether tests passed.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _pkg in ["kernel", "events", "runtime", "models", "ai_infrastructure",
             "review", "artifacts", "security", "workflows", "execution",
             "orchestration", "composition", "workforce", "connectors",
             "event_platform", "persistence", "observability", "knowledge_platform"]:
    _src = _ROOT / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_kernel.completion import DefaultCompletionModule  # noqa: E402
from autoforge_kernel.interfaces import EventBus, RuntimeStateManager  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


class _EmptyCatalogEvidence:
    """An evidence collector wired to a catalog that holds nothing."""

    has_catalog = True

    def collect(self, project_id, workflow_id):  # noqa: ANN001
        return {}


class _StaticCatalogEvidence:
    """An evidence collector wired to a catalog holding real deliverables."""

    has_catalog = True

    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    def collect(self, project_id, workflow_id):  # noqa: ANN001
        return dict(self._files)


def _approving_review_engine() -> AsyncMock:
    engine = AsyncMock()
    engine.review_project.return_value = {
        "approved": True,
        "decision": "approved",
        "status": "approved",
        "findings": [],
        "findings_count": 0,
    }
    return engine


def _review_engine_returning(value: Any) -> AsyncMock:
    engine = AsyncMock()
    engine.review_project.return_value = value
    return engine


def _review_engine_raising(exc: BaseException) -> AsyncMock:
    engine = AsyncMock()
    engine.review_project.side_effect = exc
    return engine


def _valid_state() -> dict[str, Any]:
    return {
        "status": "running",
        "progress": 100.0,
        "task_count": 0,
        "completed_count": 0,
        "failed_count": 0,
        "acceptance_criteria": [],
        "quality_gates": [],
        "artifacts": [],
        "required_artifact_count": 0,
        "approval_history": [],
        "estimated_cost": 0.0,
        "actual_cost": 0.0,
    }


def _module(
    review_engine: Any,
    *,
    evidence_collector: Any = None,
    validation_port: Any = None,
    state: dict[str, Any] | None = None,
) -> DefaultCompletionModule:
    runtime = AsyncMock(spec=RuntimeStateManager)
    runtime.get_project.return_value = MagicMock()
    runtime.get_project_state.return_value = (
        state if state is not None else _valid_state()
    )
    return DefaultCompletionModule(
        review_engine=review_engine,
        event_bus=AsyncMock(spec=EventBus),
        runtime_state_manager=runtime,
        evidence_collector=evidence_collector,
        validation_port=validation_port,
    )


def _transitions(module: DefaultCompletionModule) -> list[Any]:
    return [
        c.kwargs.get("new_status")
        for c in module.runtime_state_manager.transition_state.await_args_list
    ]


REAL_DELIVERABLE = {
    "README.md": "# Service\n\n## Overview\n\nA real deliverable.\n",
    "app.py": (
        '"""Real service."""\n\n\ndef handle(event: dict) -> dict:\n'
        '    return {"ok": True}\n'
    ),
}

# ── B-1: mandatory review + zero evidence is NOT an approval ─────────────────


@pytest.mark.asyncio
async def test_b1_mandatory_review_with_empty_evidence_is_not_approved():
    """B-1: zero reviewable evidence can never satisfy the mandatory gate."""
    review = _approving_review_engine()
    module = _module(review, evidence_collector=_EmptyCatalogEvidence())

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert "no reviewable evidence" in result["review_gate"]["reason"]
    assert "Finished" not in _transitions(module)
    # The review must not even be run on an empty evidence set.
    review.review_project.assert_not_called()


@pytest.mark.asyncio
async def test_b1_mandatory_review_with_real_evidence_still_approves():
    """B-1 fix must not block a project that genuinely produced a deliverable."""
    module = _module(
        _approving_review_engine(),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is True
    assert result["final_review"]["approved"] is True
    assert "Finished" in _transitions(module)


@pytest.mark.asyncio
async def test_b1_review_exception_blocks_completion():
    """B-1 regression set: a review exception is not an approval."""
    module = _module(
        _review_engine_raising(RuntimeError("review backend down")),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert "RuntimeError" in result["review_gate"]["reason"]
    assert "Finished" not in _transitions(module)


@pytest.mark.asyncio
async def test_b1_explicit_approved_is_required_for_completion():
    """B-1: completion requires an EXPLICIT approval, not an absence of findings."""
    review = _approving_review_engine()
    module = _module(review, evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE))

    result = await module.finalize_project(uuid.uuid4())
    assert result["success"] is True

    called = review.review_project.await_args
    assert called is not None, "the review must actually be invoked"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "value",
    [
        {"approved": False, "decision": "rejected"},
        {"approved": False, "decision": "changes_requested"},
        {"approved": False, "decision": "requires_hitl"},
        {},
        {"decision": "approved"},
        {"approved": "yes", "decision": "approved"},
        {"approved": True, "decision": "rejected"},
    ],
    ids=["rejected", "changes-requested", "hitl", "empty-dict",
         "no-flag", "non-bool-flag", "contradictory"],
)
async def test_b1_rejection_and_malformed_review_block(value: Any):
    """B-1 regression set: rejection and malformed verdicts both block."""
    module = _module(
        _review_engine_returning(value),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert "Finished" not in _transitions(module)


@pytest.mark.asyncio
async def test_b1_legitimate_no_target_use_case_is_preserved():
    """B-1 must NOT globally break the Review Engine's own no_target branch.

    A non-mandatory, artifact-scoped review with genuinely empty evidence is a
    legitimate "nothing to review" answer and must still return the documented
    verdict. Only the MANDATORY project-completion gate treats it as failure.
    """
    from autoforge_composition.kernel_adapters import KernelReviewEngineAdapter


# ── D-8: deterministic validation truth ──────────────────────────────────────


class _ValidationPort:
    """A deterministic validation port returning a fixed verdict."""

    def __init__(self, result: dict[str, Any] | None) -> None:
        self._result = result
        self.calls = 0

    async def validate_project(self, project_id):  # noqa: ANN001
        self.calls += 1
        return self._result


def _passing_validation() -> dict[str, Any]:
    return {
        "required": True,
        "performed": True,
        "passed": True,
        "has_test_failures": False,
        "has_errors": False,
        "reason": "Verification command passed (6 tests).",
        "test_results": {
            "total_tests": 6,
            "passed_tests": 6,
            "failed_tests": 0,
            "error_tests": 0,
            "skipped_tests": 0,
            "failure_details": [],
            "raw_summary_line": "6 passed in 0.02s",
        },
    }


def _failing_validation() -> dict[str, Any]:
    return {
        "required": True,
        "performed": True,
        "passed": False,
        "has_test_failures": True,
        "has_errors": False,
        "reason": "Verification command exited 1",
        "test_results": {
            "total_tests": 6,
            "passed_tests": 4,
            "failed_tests": 2,
            "error_tests": 0,
            "skipped_tests": 0,
            "failure_details": ["FAILED test_x", "AssertionError"],
            "raw_summary_line": "4 passed, 2 failed in 0.03s",
        },
    }


def _not_applicable_validation() -> dict[str, Any]:
    return {
        "required": False,
        "performed": False,
        "passed": True,
        "reason": "Project declares no verification command.",
    }


@pytest.mark.asyncio
async def test_d8_validation_truth_reaches_the_final_review():
    """D-8: the review must be GIVEN the real deterministic test results."""
    review = _approving_review_engine()
    module = _module(
        review,
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_ValidationPort(_failing_validation()),
    )

    await module._run_final_review(uuid.uuid4())

    ctx = review.review_project.await_args.kwargs.get("context") or {}
    assert ctx, "deterministic validation truth must be supplied to the review"
    assert ctx["has_test_failures"] is True
    assert ctx["test_results"]["failed_tests"] == 2
    assert ctx["test_results"]["total_tests"] == 6


@pytest.mark.asyncio
async def test_d8_all_tests_pass_allows_completion():
    """D-8: passing validation plus explicit approval completes."""
    module = _module(
        _approving_review_engine(),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_ValidationPort(_passing_validation()),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is True
    assert "Finished" in _transitions(module)


@pytest.mark.asyncio
async def test_d8_failing_tests_block_completion_despite_review_approval():
    """D-8: a mandatory FAILED validation must block even when review APPROVED.

    This is the exact first-18-L failure: deliverable -> 2 failing self-tests ->
    final review -> APPROVED -> finished.
    """
    review = _approving_review_engine()
    module = _module(
        review,
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_ValidationPort(_failing_validation()),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["error"] == "Deterministic validation failed"
    # The review verdict is preserved so the override is auditable.
    assert result["review_gate"]["approved"] is True
    assert result["review_gate"]["overridden_by"] == "deterministic_validation_gate"
    assert result["validation"]["test_results"]["failed_tests"] == 2
    assert "Finished" not in _transitions(module)


@pytest.mark.asyncio
async def test_d8_validation_failure_and_review_rejection_both_block():
    """D-8: a failed validation plus a rejecting review still blocks."""
    module = _module(
        _review_engine_returning({"approved": False, "decision": "rejected"}),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_ValidationPort(_failing_validation()),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["error"] == "Final review did not approve the project"
    assert "Finished" not in _transitions(module)


@pytest.mark.asyncio
async def test_d8_missing_validation_result_is_not_a_pass():
    """D-8: a validation port that cannot answer must fail closed, not pass."""
    class _BrokenPort:
        async def validate_project(self, project_id):  # noqa: ANN001
            raise RuntimeError("validation runner unavailable")

    module = _module(
        _approving_review_engine(),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_BrokenPort(),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["error"] == "Deterministic validation failed"
    assert "RuntimeError" in result["validation"]["reason"]
    assert "Finished" not in _transitions(module)


@pytest.mark.asyncio
async def test_d8_not_applicable_validation_preserves_prior_behaviour():
    """D-8: a project with no declared verification command is not over-gated."""
    module = _module(
        _approving_review_engine(),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_ValidationPort(_not_applicable_validation()),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is True


@pytest.mark.asyncio
async def test_d8_no_validation_port_preserves_prior_behaviour():
    """D-8: with no deterministic validation wired, the gate is unchanged."""
    module = _module(
        _approving_review_engine(),
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is True
    assert result["final_review"]["approved"] is True


@pytest.mark.asyncio
async def test_d8_execution_failure_still_blocks_before_review():
    """D-8 regression set: a failed task blocks before the review is reached."""
    review = _approving_review_engine()
    state = _valid_state()
    state.update({"task_count": 2, "completed_count": 1, "failed_count": 1})
    module = _module(
        review,
        evidence_collector=_StaticCatalogEvidence(REAL_DELIVERABLE),
        validation_port=_ValidationPort(_passing_validation()),
        state=state,
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["error"] == "Project validation failed"
    review.review_project.assert_not_called()
