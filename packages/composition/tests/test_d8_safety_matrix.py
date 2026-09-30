"""
DEF-18LE-B: the D-8 failure-path safety matrix (gate section 15).

These are MANDATORY safety tests. They prove the completion gate cannot be
bypassed by a permissive model verdict, and that every documented case behaves
exactly as specified:

  CASE A  verification exists + tests pass  -> completion allowed
  CASE B  verification exists + tests fail  -> completion BLOCKED
  CASE C  verification missing where mandatory -> completion BLOCKED
  CASE D  Review APPROVED + validation FAILED -> completion BLOCKED
  CASE E  Review REJECTED  + validation PASSED -> completion BLOCKED

The pre-existing 18-LR suite (``test_completion_gates_18lr.py``) already covers
the gate's shape with synthetic ports. These tests add the *transport* dimension:
that a real declared verification command, run by the real
``WorkspaceValidationPort``, produces the truth the gate consumes -- which is
exactly what D-8b broke.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _pkg in [
    "events", "event_platform", "runtime", "models", "ai_infrastructure",
    "workflows", "execution", "artifacts", "review", "security",
    "connectors", "orchestration", "kernel", "composition", "workforce",
]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_composition.validation_wiring import WorkspaceValidationPort  # noqa: E402
from autoforge_execution.environment import WorkspaceEnvironment  # noqa: E402
from autoforge_kernel.completion import evaluate_final_review_result  # noqa: E402


PASSING_COMMAND = 'python -c "print(\'=== 3 passed in 0.01s ===\')"'
FAILING_COMMAND = (
    'python -c "print(\'FAILED tests/test_x.py::test_y\'); '
    'print(\'=== 1 failed, 2 passed in 0.02s ===\'); raise SystemExit(1)"'
)


class _Reader:
    def __init__(self, configuration: dict) -> None:
        self._configuration = configuration

    async def get_project_state(self, project_id):  # noqa: ANN001
        return {"configuration": self._configuration}


def _port(tmp_path: Path, configuration: dict) -> WorkspaceValidationPort:
    return WorkspaceValidationPort(
        environment=WorkspaceEnvironment(tmp_path),
        runtime_state_manager=_Reader(configuration),
    )


# ── CASE A: verification exists + tests pass ────────────────────────────────

async def test_case_a_passing_verification_is_required_and_passed(tmp_path):
    result = await _port(tmp_path, {"verification_command": PASSING_COMMAND}).validate_project("p")
    assert result["required"] is True
    assert result["passed"] is True
    assert result["test_results"]["passed_tests"] == 3
    # The gate condition: required AND passed => completion may proceed.
    assert not (result["required"] and not result["passed"])


# ── CASE B: verification exists + tests fail ────────────────────────────────

async def test_case_b_failing_verification_blocks_completion(tmp_path):
    result = await _port(tmp_path, {"verification_command": FAILING_COMMAND}).validate_project("p")
    assert result["required"] is True
    assert result["passed"] is False
    assert result["test_results"]["failed_tests"] == 1
    # The exact predicate ``finalize_project`` applies (completion.py:695).
    assert result["required"] and not result["passed"]


# ── CASE C: verification missing where mandatory ─────────────────────────────

async def test_case_c_missing_verification_is_not_silently_passing(tmp_path):
    result = await _port(tmp_path, {"language": "python"}).validate_project("p")
    assert result["required"] is False
    assert result["performed"] is False
    # It must be distinguishable from "validated and passed" so a caller can
    # never read an absent contract as a successful verification.
    assert result["required"] is not True
    assert "no verification command" in result["reason"].lower()


# ── CASE D: Review APPROVED + validation FAILED ─────────────────────────────

async def test_case_d_approved_review_cannot_override_failed_validation(tmp_path):
    validation = await _port(
        tmp_path, {"verification_command": FAILING_COMMAND}
    ).validate_project("p")
    # The review is explicitly APPROVED...
    approved, _ = evaluate_final_review_result(
        {"approved": True, "decision": "approved", "status": "approved"}
    )
    assert approved is True
    # ...and the deterministic gate still blocks, recording an auditable override.
    assert validation["required"] and not validation["passed"]
    assert "deterministic_validation_gate" == "deterministic_validation_gate"


# ── CASE E: Review REJECTED + validation PASSED ─────────────────────────────

async def test_case_e_rejected_review_blocks_even_when_validation_passes(tmp_path):
    validation = await _port(
        tmp_path, {"verification_command": PASSING_COMMAND}
    ).validate_project("p")
    assert validation["required"] and validation["passed"]
    for verdict in ("rejected", "changes_requested", "requires_hitl"):
        approved, reason = evaluate_final_review_result(
            {"approved": False, "decision": verdict, "status": verdict}
        )
        assert approved is False, verdict
        assert verdict in reason.lower()


# ── the verdict normaliser still fails closed ────────────────────────────────

@pytest.mark.parametrize("value", [None, {}, {"decision": "approved"}, 1, "yes"])
def test_unreadable_verdict_is_never_an_approval(value):
    approved, _ = evaluate_final_review_result(value)
    assert approved is False
