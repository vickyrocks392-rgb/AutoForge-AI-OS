"""
DEF-P1-EVIDENCE — end-to-end review evidence integration tests.

These exercise the REAL production path with the REAL Review Engine and the
REAL 18-K durable artifact pipeline:

    project request -> DefaultOrchestrationEngine -> execution -> artifact
    production -> completion -> real evidence collection
    -> KernelReviewEngineAdapter -> ReviewEngine -> explicit decision
    -> completion gate

They prove the final review evaluates the project's ACTUAL output, that no
synthetic placeholder is used, and that every non-approval fails closed.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
for _pkg in ["kernel", "events", "runtime", "models", "ai_infrastructure",
             "review", "artifacts", "security", "workflows", "execution",
             "orchestration", "composition", "workforce", "connectors",
             "event_platform", "persistence", "observability", "knowledge_platform"]:
    _src = _ROOT / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from tests.review_evidence_helpers import (  # noqa: E402
    PROJECT_DELIVERABLE,
    register_project_deliverable,
)


def _status_value(state) -> str:
    """Normalise a project status to its comparable value string."""
    raw = state["status"]
    return str(getattr(raw, "value", raw)).lower()


async def _planned_system(workspace: Path):
    """Build the real system and plan a real project (no execution yet)."""
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    system = build_autoforge_system(workspace_root=str(workspace))
    await system.initialize()
    res = await system.kernel.submit_request(
        Request(
            user_id=uuid.uuid4(),
            request_text="Build an authenticated payment webhook endpoint with tests",
            configuration={"environment": "production", "execute": False},
        )
    )
    return system, res["project_id"]


async def _workflow_id(system, project_id) -> str:
    state = await system.runtime_facade.get_project_state(project_id)
    return system.kernel.completion_module._project_workflow_id(state)


# ── A. Valid real project: real artifacts -> review approves -> completes ─────


@pytest.mark.asyncio
async def test_real_project_with_real_deliverable_completes(tmp_path: Path):
    workspace = tmp_path / "ws"
    system, pid = await _planned_system(workspace)
    try:
        wf = await _workflow_id(system, pid)
        assert wf, "workflow correlation must be durable"
        registered = register_project_deliverable(system, wf)
        assert "README.md" in registered

        gate = await system.kernel.completion_module._run_final_review(pid)

        # The review genuinely received the real project output.
        assert gate["evidence_files"] >= len(registered)
        assert gate["approved"] is True
        rr = gate["review_result"]
        assert rr["approved"] is True
        assert rr["decision"] == "approved"
    finally:
        await system.shutdown()




# ── B/E. Missing required evidence: real review rejection fails closed ───────


@pytest.mark.asyncio
async def test_project_without_required_documentation_does_not_complete(tmp_path: Path):
    """The real Review Engine's Required Files check must still function.

    A project with a real but incomplete deliverable (no README.md) is genuinely
    rejected. This proves the review semantics were NOT weakened.
    """
    workspace = tmp_path / "ws"
    system, pid = await _planned_system(workspace)
    try:
        wf = await _workflow_id(system, pid)
        register_project_deliverable(
            system, wf, files={"app.py": PROJECT_DELIVERABLE["app.py"]}
        )

        # Drive the real lifecycle; the completion gate must block finalization.
        await system.kernel.execute_project(pid)

        state = await system.runtime_facade.get_project_state(pid)
        assert _status_value(state) != "finished", (
            "a project whose real deliverable fails the mandatory review gate "
            "must not be finalized"
        )

        # And the gate itself must report the genuine, specific review reason.
        gate = await system.kernel.completion_module._run_final_review(pid)
        assert gate["approved"] is False
        assert gate["review_result"]["decision"] == "changes_requested"
        titles = [f.get("title") for f in gate["review_result"].get("findings") or []]
        assert "Required Files" in titles, (
            "the review must surface the genuine documentation finding"
        )
    finally:
        await system.shutdown()


@pytest.mark.asyncio
async def test_no_placeholder_makes_unreviewable_project_appear_reviewable(
    tmp_path: Path,
):
    """No placeholder evidence may make an unreviewable project appear reviewable.

    DEF-18LR-B1 CONTRACT CHANGE. This test previously asserted that an
    empty-evidence project still received a real review result whose findings
    merely lacked a "Required Files" title. That encoded the FAIL-OPEN: the
    Review Engine's legitimate ``no_target`` verdict was being consumed by the
    MANDATORY project-completion gate, so a project that produced nothing at
    all reached ``Finished``.

    The 18-LR contract is now:

        mandatory review + zero reviewable evidence = NOT APPROVED

    The original intent is preserved and strengthened: the project is now
    *more* clearly unreviewable, and no placeholder is manufactured to hide
    that. The Review Engine's own ``no_target`` semantics are untouched --
    ``test_empty_evidence_reaches_engine_unmodified`` still proves that
    adapter-level, non-mandatory review returns the documented verdict.
    """
    workspace = tmp_path / "ws"
    system, pid = await _planned_system(workspace)
    try:
        gate = await system.kernel.completion_module._run_final_review(pid)

        # Nothing was produced, so there is nothing to review.
        assert gate["evidence_files"] == 0

        # The mandatory gate must fail closed rather than consume no_target.
        assert gate["approved"] is False, (
            "empty evidence must never satisfy the mandatory project-completion "
            "review gate"
        )
        assert "no reviewable evidence" in gate["reason"]
        assert gate["review_result"] is None, (
            "no review may be run (and no placeholder synthesised) for a project "
            "with zero evidence"
        )

        # And the project must not reach Finished.
        await system.kernel.execute_project(pid)
        state = await system.runtime_facade.get_project_state(pid)
        assert _status_value(state) != "finished"
    finally:
        await system.shutdown()


# ── G. Placeholder is gone from the production review path ───────────────────


def test_review_adapter_manufactures_no_placeholder_evidence():
    from autoforge_composition.kernel_adapters import KernelReviewEngineAdapter
    import ast
    import inspect

    src = inspect.getsource(KernelReviewEngineAdapter._execute_review)
    # Assert on executable code only: the explanatory comment legitimately names
    # the historical placeholder so future readers know it must not return.
    tree = ast.parse(inspect.cleandoc(src))
    literals = [
        n.value
        for n in ast.walk(tree)
        if isinstance(n, ast.Constant) and isinstance(n.value, str)
    ]
    assert not any("manifest.json" in lit for lit in literals), (
        "the synthetic manifest placeholder must not be reinstated in code"
    )


@pytest.mark.asyncio
async def test_empty_evidence_reaches_engine_unmodified():
    """F: genuinely empty evidence reaches the Review Engine so its own
    explicitly-empty branch runs (``no_target``), not fabricated content."""
    from autoforge_composition.kernel_adapters import KernelReviewEngineAdapter
    from autoforge_review.engine import ReviewEngine

    adapter = KernelReviewEngineAdapter(concrete_engine=ReviewEngine())
    result = await adapter.review_project(uuid.uuid4())

    assert result["evidence_files"] == 0
    assert result["decision"] == "approved"
    assert result["findings_count"] == 0


# ── I. Real artifact content reaches the review unchanged ────────────────────


@pytest.mark.asyncio
async def test_real_artifact_content_reaches_review_verbatim(tmp_path: Path):
    workspace = tmp_path / "ws"
    system, pid = await _planned_system(workspace)
    try:
        wf = await _workflow_id(system, pid)
        register_project_deliverable(system, wf)

        collected = system.kernel.completion_module.evidence_collector.collect(pid, wf)

        assert set(collected) == set(PROJECT_DELIVERABLE)
        for name, content in PROJECT_DELIVERABLE.items():
            assert collected[name] == content, f"{name} must reach review unchanged"
    finally:
        await system.shutdown()


# ── D. Evidence collection failure fails closed ──────────────────────────────


@pytest.mark.asyncio
async def test_evidence_collection_exception_fails_closed():
    from unittest.mock import AsyncMock, MagicMock
    from autoforge_kernel.completion import (
        DefaultCompletionModule,
        FinalReviewEvidenceCollector,
    )
    from autoforge_kernel.interfaces import RuntimeStateManager

    class _ExplodingCatalog:
        def find_by_workflow(self, wf):
            raise RuntimeError("catalog unavailable")

    runtime = AsyncMock(spec=RuntimeStateManager)
    runtime.get_project.return_value = MagicMock()
    runtime.get_project_state.return_value = {"configuration": {"workflow_id": "x"}}

    module = DefaultCompletionModule(
        review_engine=AsyncMock(),
        runtime_state_manager=runtime,
        evidence_collector=FinalReviewEvidenceCollector(durable_catalog=_ExplodingCatalog()),
    )

    gate = await module._run_final_review(uuid.uuid4())

    assert gate["approved"] is False
    assert "evidence collection" in gate["reason"].lower()
    assert "catalog unavailable" in gate["reason"]


# ── Orchestrator authority preserved ─────────────────────────────────────────


@pytest.mark.asyncio
async def test_production_orchestrator_authority_unchanged(tmp_path: Path):
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.orchestration import DefaultOrchestrationEngine

    system = build_autoforge_system(workspace_root=str(tmp_path / "ws"))
    await system.initialize()
    try:
        assert isinstance(system.orchestration_engine, DefaultOrchestrationEngine)
        assert system.kernel.completion_module.evidence_collector is not None
    finally:
        await system.shutdown()

@pytest.mark.asyncio
async def test_full_lifecycle_reaches_finished_with_real_evidence(tmp_path: Path):
    """End-to-end: the project reaches Finished only via an explicit approval."""
    workspace = tmp_path / "ws"
    system, pid = await _planned_system(workspace)
    try:
        wf = await _workflow_id(system, pid)
        register_project_deliverable(system, wf)

        await system.kernel.execute_project(pid)

        state = await system.runtime_facade.get_project_state(pid)
        assert _status_value(state) == "finished"
    finally:
        await system.shutdown()
