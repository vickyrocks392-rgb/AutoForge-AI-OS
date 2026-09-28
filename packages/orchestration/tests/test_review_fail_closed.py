"""
Pre-Brain Safety Repair — review fail-closed regression suite.

Proves the safety invariant:

    A review outcome that is not an explicit APPROVED must NEVER produce an
    APPROVED decision or a successful REVIEW stage.

These tests exercise the exact previously vulnerable path
(``OrchestrationEngine._process_review_stage``) and pin the preserved
legitimate semantics so they cannot regress silently.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _pkg in ["orchestration", "workforce", "execution", "ai_infrastructure",
             "events", "artifacts", "security", "review", "knowledge",
             "connectors", "workflows", "composition"]:
    _src = _ROOT / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_orchestration.orchestrator import OrchestrationConfig, OrchestrationEngine
from autoforge_orchestration.models import ReviewVerdict, StageKind, StageStatus
from autoforge_review.models import (
    GateStatus,
    QualityGateResult,
    ReviewDecision,
    ReviewResult,
)

from test_helpers import SimpleEventSink


# ── Review engine doubles ────────────────────────────────────────────────────


class _ScriptedReviewEngine:
    """Returns a scripted value, or raises a scripted exception."""

    def __init__(self, *, result: Any = None, raises: BaseException | None = None) -> None:
        self._result = result
        self._raises = raises
        self.calls = 0

    async def review(self, request: Any) -> Any:
        self.calls += 1
        if self._raises is not None:
            raise self._raises
        return self._result


def _review_result(decision: ReviewDecision) -> ReviewResult:
    approved = decision is ReviewDecision.APPROVED
    return ReviewResult(
        review_id="rev-test-0001",
        categories_run=["correctness"],
        findings=[],
        count_by_category={"correctness": 0},
        count_by_severity={},
        blocking_findings=0 if approved else 1,
        gate=QualityGateResult(
            status=GateStatus.PASS if approved else GateStatus.FAIL,
            satisfied_gates=["correctness"] if approved else [],
            violated_gates=[] if approved else ["correctness"],
        ),
        decision=decision,
    )


class _LegacyVerdictEngine:
    """Legacy engine exposing a ``.verdict`` attribute (pre-ReviewDecision)."""

    def __init__(self, verdict: Any) -> None:
        self._verdict = verdict

    async def review(self, request: Any) -> Any:
        return type("LegacyResult", (), {"verdict": self._verdict})()


# ── Harness ──────────────────────────────────────────────────────────────────


def _config(workspace_root: Path) -> OrchestrationConfig:
    return OrchestrationConfig(
        workspace_root=str(workspace_root),
        state_dir=str(workspace_root / ".autoforge" / "state"),
        max_concurrent_executions=1,
        global_timeout_seconds=120.0,
        default_worker_timeout_seconds=60.0,
        max_rectification_loops=1,
        max_attempts_per_stage=1,
        require_hitl_for_deployment=False,
        enable_persistence=True,
        security_guard_enabled=False,
    )


async def _review_stage(engine: OrchestrationEngine):
    """Create a project and return (state, review_stage_state)."""
    state = await engine.create_project(
        objective="Build a calculator", workflow_id="greenfield"
    )
    review_id = next(
        sid for sid, ss in state.stages.items() if ss.definition.kind is StageKind.REVIEW
    )
    stage_state = state.stages[review_id]
    stage_state.status = StageStatus.RUNNING
    return state, stage_state


def _engine(workspace_root: Path, review_engine: Any) -> OrchestrationEngine:
    return OrchestrationEngine(
        _config(workspace_root),
        event_sink=SimpleEventSink(),
        review_engine=review_engine,
    )


# ── 1. The core invariant: exceptions must never approve ─────────────────────


@pytest.mark.asyncio
async def test_review_engine_exception_does_not_approve(tmp_path: Path):
    """REGRESSION: a raising Review Engine must NOT yield APPROVED."""
    engine = _engine(tmp_path, _ScriptedReviewEngine(raises=RuntimeError("review backend down")))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.status is StageStatus.FAILED, (
        f"review exception must fail the stage, got {stage_state.status}"
    )
    assert stage_state.review is None or stage_state.review.verdict.value != "APPROVED"


@pytest.mark.asyncio
async def test_review_exception_records_reason_and_error(tmp_path: Path):
    """The failure must be inspectable, not silently swallowed.

    NOTE: ``stage_state.output`` is overwritten by ``_finalize_stage_failure``,
    so the durable evidence is (a) the typed ``stage_state.review`` gate record
    and (b) the failure reason the finalizer persists.
    """
    engine = _engine(tmp_path, _ScriptedReviewEngine(raises=ValueError("boom")))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.review is not None, "a failed review must still leave a gate record"
    assert stage_state.review.verdict is ReviewVerdict.BLOCKED
    assert "boom" in (stage_state.output or {}).get("error", ""), (
        f"exception detail must reach the failure record, got {stage_state.output}"
    )


@pytest.mark.asyncio
async def test_review_exception_emits_failure_detected_event(tmp_path: Path):
    """Existing recovery/error evidence behaviour must be preserved."""
    sink = SimpleEventSink()
    engine = OrchestrationEngine(
        _config(tmp_path),
        event_sink=sink,
        review_engine=_ScriptedReviewEngine(raises=RuntimeError("down")),
    )
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    types = {getattr(e, "event_type", None) and e.event_type.name for e in sink.events}
    assert "STAGE_FAILED" in types, f"STAGE_FAILED not emitted, got {types}"
    assert "FAILURE_DETECTED" in types, f"FAILURE_DETECTED not emitted, got {types}"


# ── 2. Missing / malformed / indeterminate results must not approve ───────────


@pytest.mark.asyncio
async def test_review_returning_none_does_not_approve(tmp_path: Path):
    """A review engine that returns nothing produced no verdict."""
    engine = _engine(tmp_path, _ScriptedReviewEngine(result=None))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.status is StageStatus.FAILED


@pytest.mark.asyncio
async def test_review_dict_without_decision_does_not_approve(tmp_path: Path):
    """REGRESSION: a dict with no decision key must not default to 'approved'."""
    engine = _engine(tmp_path, _ScriptedReviewEngine(result={"note": "no verdict here"}))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.status is StageStatus.FAILED


@pytest.mark.asyncio
async def test_review_malformed_decision_value_does_not_approve(tmp_path: Path):
    """An uninterpretable decision value must not fall through to approval."""
    engine = _engine(tmp_path, _ScriptedReviewEngine(result={"decision": "maybe"}))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.status is StageStatus.FAILED


@pytest.mark.asyncio
@pytest.mark.parametrize("indeterminate", ["BLOCKED", "NEEDS_REVISION"])
async def test_indeterminate_verdict_does_not_approve(tmp_path: Path, indeterminate: str):
    """REGRESSION: only REJECTED was handled before; BLOCKED/NEEDS_REVISION
    silently fell through to stage success."""
    engine = _engine(tmp_path, _LegacyVerdictEngine(indeterminate))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.status is StageStatus.FAILED, f"{indeterminate} must not approve"


# ── 3. The live production defect: signature mismatch ────────────────────────


@pytest.mark.asyncio
async def test_production_review_adapter_signature_mismatch_fails_closed(tmp_path: Path):
    """REGRESSION (production): the wired review adapter is called with one
    positional argument but requires two, so it raised TypeError on every
    REVIEW stage and that was converted to APPROVED. It must now fail closed."""
    from autoforge_composition.kernel_adapters import KernelReviewEngineAdapter
    from autoforge_review.engine import ReviewEngine

    adapter = KernelReviewEngineAdapter(concrete_engine=ReviewEngine())
    engine = _engine(tmp_path, adapter)
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, None, [])

    assert stage_state.status is StageStatus.FAILED, (
        "production review adapter mismatch must fail closed, not approve"
    )
    assert stage_state.review is not None
    assert stage_state.review.verdict is ReviewVerdict.BLOCKED
    err = (stage_state.output or {}).get("error", "")
    assert "TypeError" in err, f"expected the real TypeError to be recorded, got {err!r}"


# ── 4. Legitimate semantics must be preserved ────────────────────────────────


@pytest.mark.asyncio
async def test_explicit_approval_still_succeeds(tmp_path: Path):
    """Normal successful review keeps its existing successful outcome."""
    engine = _engine(
        tmp_path, _ScriptedReviewEngine(result=_review_result(ReviewDecision.APPROVED))
    )
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, [], [])

    assert stage_state.status is StageStatus.SUCCEEDED
    assert stage_state.review is not None
    assert stage_state.review.verdict.value == "APPROVED"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "decision",
    [ReviewDecision.REJECTED, ReviewDecision.CHANGES_REQUESTED, ReviewDecision.REQUIRES_HITL],
)
async def test_non_approving_decisions_still_fail(tmp_path: Path, decision: ReviewDecision):
    """Existing rejection behaviour is unchanged."""
    engine = _engine(tmp_path, _ScriptedReviewEngine(result=_review_result(decision)))
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, [], [])

    assert stage_state.status is StageStatus.FAILED
    assert stage_state.review is not None
    assert stage_state.review.verdict.value == "REJECTED"


@pytest.mark.asyncio
async def test_review_engine_not_configured_is_preserved(tmp_path: Path):
    """PINNED, DELIBERATE: the review gate is an OPTIONAL dependency. When no
    review engine is wired, no review was attempted, so this is configured
    optionality and not a review failure. Existing semantics preserved."""
    engine = _engine(tmp_path, None)
    state, stage_state = await _review_stage(engine)

    await engine._process_review_stage(state, stage_state, [], [])

    assert stage_state.status is StageStatus.SUCCEEDED
    # No review was attempted, so no review gate record is fabricated.
    assert stage_state.review is None, (
        "an unconfigured review gate must not fabricate a review record"
    )


# ── 5. Governance evidence must not report a non-approval as approved ───────


@pytest.mark.asyncio
@pytest.mark.parametrize("verdict_value", ["APPROVED", "REJECTED", "BLOCKED", "NEEDS_REVISION"])
async def test_governance_evidence_maps_only_explicit_approval(tmp_path: Path, verdict_value: str):
    """REGRESSION: BLOCKED/NEEDS_REVISION were reported as APPROVED evidence."""
    from autoforge_orchestration.models import ReviewGateResult, ReviewVerdict

    engine = OrchestrationEngine(_config(tmp_path), event_sink=SimpleEventSink())
    state, stage_state = await _review_stage(engine)

    verdict = ReviewVerdict(verdict_value)
    stage_state.review = ReviewGateResult(verdict=verdict)

    results = engine._get_review_results(state)
    assert results, f"no governance review evidence for {verdict_value}"
    reported = results[0].decision

    if verdict is ReviewVerdict.APPROVED:
        assert reported == "APPROVED"
    else:
        assert reported == "REJECTED", (
            f"{verdict_value} must not be reported as {reported}"
        )