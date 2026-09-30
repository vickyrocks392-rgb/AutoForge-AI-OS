"""
P-1 production review-gating regression suite.

Proves the canonical completion contract required by
``architecture/ARCHITECTURE.md`` section 10 ("the Review Engine ... is the
quality gate of the platform") and ``docs/subsystems/kernel/KERNEL_SPECIFICATION.md``
section 24.1 ("All reviews approved"):

    PRODUCTION COMPLETION MUST NOT SUCCEED UNLESS THE REQUIRED FINAL REVIEW
    EXPLICITLY PASSES.

These tests exercise the exact production path
(``DefaultCompletionModule.finalize_project``) reached from
``Kernel.execute_project`` -> ``completion_module.finalize_project``.

The repair is confined to the Kernel completion boundary. ``autoforge_orchestration``
is NOT production-wired and this suite deliberately makes no change to it.
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

from autoforge_kernel.completion import (  # noqa: E402
    DefaultCompletionModule,
    evaluate_final_review_result,
)
from autoforge_kernel.interfaces import EventBus, RuntimeStateManager  # noqa: E402


# ── Helpers ──────────────────────────────────────────────────────────────────


def _approving_review_engine() -> AsyncMock:
    """A review engine returning the documented explicit approval."""
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


def _state(**overrides: Any) -> dict[str, Any]:
    """A valid, completable project state (no failures, criteria met)."""
    state = {
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
    state.update(overrides)
    return state


def _module(review_engine: Any, state: dict[str, Any] | None = None) -> DefaultCompletionModule:
    runtime = AsyncMock(spec=RuntimeStateManager)
    runtime.get_project.return_value = MagicMock()
    runtime.get_project_state.return_value = state if state is not None else _state()
    return DefaultCompletionModule(
        review_engine=review_engine,
        event_bus=AsyncMock(spec=EventBus),
        runtime_state_manager=runtime,
    )


def _transitions(module: DefaultCompletionModule) -> list[Any]:
    return [
        c.kwargs.get("new_status")
        for c in module.runtime_state_manager.transition_state.await_args_list
    ]




# ── 1. Explicit APPROVED review -> completion succeeds ────────────────────────


@pytest.mark.asyncio
async def test_explicit_approved_review_succeeds():
    module = _module(_approving_review_engine())

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is True
    assert result["final_review"]["approved"] is True
    # The project actually reached the Finished state.
    assert "Finished" in _transitions(module)


# ── 2-4. Every non-approving ReviewDecision blocks completion ────────────────


@pytest.mark.parametrize("decision", ["rejected", "changes_requested", "requires_hitl"])
@pytest.mark.asyncio
async def test_non_approving_decision_blocks_completion(decision: str):
    """R-4: a non-approved decision must NOT become a successful completion."""
    module = _module(_review_engine_returning({
        "approved": False,
        "decision": decision,
        "status": decision,
        "findings": [],
        "findings_count": 1,
    }))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert decision in result["review_gate"]["reason"]
    # The project must NOT have reached Finished.
    assert "Finished" not in _transitions(module)


@pytest.mark.asyncio
async def test_requires_hitl_does_not_silently_succeed():
    """Requirement 4: REQUIRES_HITL must not silently complete."""
    module = _module(_review_engine_returning({
        "approved": False,
        "decision": "requires_hitl",
        "status": "requires_hitl",
        "findings": [],
        "findings_count": 0,
    }))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert "Finished" not in _transitions(module)


# ── 5. review_project raises -> completion does not succeed ──────────────────


@pytest.mark.asyncio
async def test_review_exception_blocks_completion():
    """R-4: the old ``except Exception: pass`` converted a failed review into a
    successful completion. An exception must now block finalization."""
    module = _module(_review_engine_raising(RuntimeError("review backend down")))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert "RuntimeError" in result["review_gate"]["reason"]
    assert "review backend down" in result["review_gate"]["reason"]
    assert "Finished" not in _transitions(module)


# ── 7. Malformed / unexpected results -> completion does not succeed ──────────


@pytest.mark.parametrize(
    "value",
    [
        {},
        {"decision": "approved"},                      # no approval flag
        {"approved": "yes", "decision": "approved"},    # non-boolean flag
        {"approved": None},                             # null flag
        "approved",                                     # bare string
        42,                                             # unrelated scalar
        {"approved": True, "decision": "rejected"},     # contradictory
    ],
    ids=["empty-dict", "no-approval-flag", "non-bool-flag",
         "null-flag", "bare-string", "scalar", "contradictory"],
)
@pytest.mark.asyncio
async def test_malformed_review_result_blocks_completion(value: Any):
    module = _module(_review_engine_returning(value))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert "Finished" not in _transitions(module)


# ── 8. Review approves while generic quality-gate evidence is absent ─────────


@pytest.mark.asyncio
async def test_approved_review_with_absent_quality_gates_still_succeeds():
    """Requirement 8: the generic ``quality_gates`` list is NOT the platform
    quality gate (that is the Review Engine). Its absence must not block a
    legitimate approval, but it must be reported as vacuous rather than as real
    gate evidence."""
    module = _module(_approving_review_engine(), state=_state(quality_gates=[]))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is True
    assert result["validation_result"]["quality_gates_vacuous"] is True
    assert result["validation_result"]["final_review_required"] is True


@pytest.mark.asyncio
async def test_quality_gates_present_are_not_vacuous_and_still_gate():
    """Legitimate non-review quality-gate semantics are preserved: a real gate
    list is honoured, and a failing generic gate still blocks completion."""
    passing = _module(
        _approving_review_engine(),
        state=_state(quality_gates=[{"name": "lint", "passed": True}]),
    )
    ok = await passing.finalize_project(uuid.uuid4())
    assert ok["success"] is True
    assert ok["validation_result"]["quality_gates_vacuous"] is False

    failing = _module(
        _approving_review_engine(),
        state=_state(quality_gates=[{"name": "lint", "passed": False}]),
    )
    bad = await failing.finalize_project(uuid.uuid4())
    assert bad["success"] is False
    assert bad["error"] == "Project validation failed"


# ── 9. No review engine at all -> mandatory evidence absent, fails closed ────


@pytest.mark.asyncio
async def test_missing_review_engine_blocks_completion():
    """D-3: absence of the mandatory review evidence must not silently establish
    successful completion."""
    module = _module(None)

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert "No review engine" in result["review_gate"]["reason"]
    assert "Finished" not in _transitions(module)


# ── 10-11. Existing legitimate semantics remain intact ───────────────────────


@pytest.mark.asyncio
async def test_pre_existing_validation_failure_still_blocks():
    """Existing failure semantics are unchanged: a project with failed tasks
    fails before the review gate is reached, and the review is not called."""
    review = _approving_review_engine()
    module = _module(review, state=_state(task_count=2, completed_count=1, failed_count=1))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["error"] == "Project validation failed"
    assert any("failed" in e.lower() for e in result["validation_result"]["errors"])
    review.review_project.assert_not_called()


@pytest.mark.asyncio
async def test_pending_approval_still_blocks_completion():
    module = _module(
        _approving_review_engine(),
        state=_state(approval_history=[{"status": "pending"}]),
    )

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert "Finished" not in _transitions(module)


# ── Normalisation unit coverage ──────────────────────────────────────────────


@pytest.mark.parametrize(
    "value,expected",
    [
        ({"approved": True, "decision": "approved"}, True),
        ({"approved": True, "status": "approved"}, True),
        ({"approved": True}, True),
        ({"approved": True, "decision": "APPROVED"}, True),
        ({"approved": False, "decision": "rejected"}, False),
        ({"approved": False, "decision": "changes_requested"}, False),
        ({"approved": False, "decision": "requires_hitl"}, False),
        ({"approved": False}, False),
        (None, False),
        ({}, False),
        ({"approved": "true"}, False),
        ({"approved": 1}, False),
    ],
)
def test_evaluate_final_review_result(value: Any, expected: bool):
    approved, reason = evaluate_final_review_result(value)
    assert approved is expected
    assert isinstance(reason, str) and reason


def test_evaluate_accepts_object_shaped_result():
    """The Kernel is not coupled to one concrete return shape."""

    class _Result:
        approved = True
        decision = "approved"

    approved, _ = evaluate_final_review_result(_Result())
    assert approved is True


# ── 6. review_project returns None -> completion does not succeed ────────────


@pytest.mark.asyncio
async def test_review_returning_none_blocks_completion():
    module = _module(_review_engine_returning(None))

    result = await module.finalize_project(uuid.uuid4())

    assert result["success"] is False
    assert result["review_gate"]["approved"] is False
    assert "no result" in result["review_gate"]["reason"].lower()
    assert "Finished" not in _transitions(module)


# ── 12-14. Orchestrator authority invariants ─────────────────────────────────


def test_production_composition_still_builds_default_orchestration_engine():
    """Requirement 12: the production composition root still constructs
    ``DefaultOrchestrationEngine`` (O-2) as the authoritative orchestrator."""
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.orchestration import DefaultOrchestrationEngine

    system = build_autoforge_system()

    assert isinstance(system.orchestration_engine, DefaultOrchestrationEngine)
    assert isinstance(system.kernel.orchestration_engine, DefaultOrchestrationEngine)
    # The completion module is wired with a review engine in production, so the
    # mandatory final-review gate is satisfiable.
    assert system.kernel.completion_module.review_engine is not None


def test_o1_orchestration_engine_remains_production_unwired():
    """Requirements 13 / D-2: ``autoforge_orchestration.orchestrator`` must stay
    unreachable from the shipped production composition root. This gate does not
    wire it in."""
    import ast

    offenders: list[str] = []
    sources = list(_ROOT.glob("packages/*/src/**/*.py")) + list(
        _ROOT.glob("apps/*/src/**/*.py")
    )
    for path in sources:
        if "/tests/" in str(path):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and (node.module or "").startswith(
                "autoforge_orchestration"
            ):
                if "orchestrator" in (node.module or ""):
                    offenders.append(f"{path}:{node.lineno}")
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name.startswith("autoforge_orchestration.orchestrator"):
                        offenders.append(f"{path}:{node.lineno}")
    assert offenders == [], (
        "autoforge_orchestration.orchestrator must not be imported by any "
        f"production source: {offenders}"
    )


@pytest.mark.asyncio
async def test_o1_review_stage_semantics_unchanged_by_this_gate():
    """Requirement 14 / D-2: this gate does not alter O-1. Its existing
    fail-closed review-stage behavior is re-verified here to prove the repair is
    isolated to the Kernel completion boundary."""
    from autoforge_orchestration.models import ReviewVerdict, StageKind, StageStatus
    from autoforge_orchestration.orchestrator import (
        OrchestrationConfig,
        OrchestrationEngine,
    )

    tmp = Path(str(uuid.uuid4()))

    class _Sink:
        def __getattr__(self, _name):
            async def _noop(*_a, **_k):
                return None

            return _noop

    async def _approved(_request):
        # O-1 reads ``.decision`` as a ``ReviewDecision``. This mirrors the
        # contract used by the existing O-1 suites; it is intentionally a
        # different shape from the Kernel adapter's dict, which is itself the
        # subject of the deferred R-2 finding.
        from autoforge_review.models import (
            GateStatus,
            QualityGateResult,
            ReviewDecision,
            ReviewResult,
        )

        return ReviewResult(
            review_id="rev-p1-0001",
            categories_run=["correctness"],
            findings=[],
            count_by_category={"correctness": 0},
            count_by_severity={},
            blocking_findings=0,
            gate=QualityGateResult(
                status=GateStatus.PASS,
                satisfied_gates=["correctness"],
                violated_gates=[],
            ),
            decision=ReviewDecision.APPROVED,
        )

    engine = OrchestrationEngine(
        OrchestrationConfig(
            workspace_root=str(tmp),
            state_dir=str(tmp / ".autoforge" / "state"),
            require_hitl_for_deployment=False,
            security_guard_enabled=False,
        ),
        event_sink=_Sink(),
        review_engine=AsyncMock(review=_approved),
    )

    state = await engine.create_project(objective="x", workflow_id="greenfield")
    stage = next(
        s for s in state.stages.values() if s.definition.kind is StageKind.REVIEW
    )
    stage.status = StageStatus.RUNNING

    await engine._process_review_stage(state, stage, None, [])

    assert stage.status is StageStatus.SUCCEEDED
    assert stage.review is not None
    assert stage.review.verdict is ReviewVerdict.APPROVED
