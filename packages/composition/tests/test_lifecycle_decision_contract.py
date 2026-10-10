"""Gate C2 -- Canonical lifecycle decision contract tests (T1-T6)."""

from __future__ import annotations

import ast
import pathlib
import socket

import pytest

from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_composition.lifecycle_decision import (
    LifecycleDecision,
    RemediationBudget,
    decide_lifecycle,
)

_REPO = pathlib.Path(__file__).resolve().parents[3]
_DECISION_MODULE = (
    _REPO / "packages/composition/src/autoforge_composition/lifecycle_decision.py"
)


def _outcome(status: OutcomeStatus, *, passed: bool | None = None) -> ExecutionOutcome:
    if passed is None:
        passed = status is OutcomeStatus.COMPLETE
    return ExecutionOutcome(status=status, loop_type="coding", passed=passed)


def _budget(attempt: int = 1, max_attempts: int = 3) -> RemediationBudget:
    return RemediationBudget(attempt=attempt, max_attempts=max_attempts)


def test_t1_complete_outcome_maps_to_complete():
    d = decide_lifecycle(_outcome(OutcomeStatus.COMPLETE), budget=_budget())
    assert d.status is OutcomeStatus.COMPLETE
    assert d.is_complete is True
    assert d.terminal is True
    assert d.remediation_allowed is False
    assert d.requires_human_approval is False
    assert d.attempt == 1
    assert d.reason != ""


def test_t2_remediate_outcome_maps_to_remediate_within_budget():
    d = decide_lifecycle(_outcome(OutcomeStatus.REMEDIATE), budget=_budget(attempt=1, max_attempts=3))
    assert d.status is OutcomeStatus.REMEDIATE
    assert d.remediation_allowed is True
    assert d.terminal is False
    assert d.requires_human_approval is False
    assert d.attempt == 1


def test_t2_remediate_with_exhausted_budget_fails_closed_to_failed():
    d = decide_lifecycle(_outcome(OutcomeStatus.REMEDIATE), budget=_budget(attempt=3, max_attempts=3))
    assert d.status is OutcomeStatus.FAILED
    assert d.remediation_allowed is False
    assert d.terminal is True
    assert d.is_complete is False


def test_t3_escalate_outcome_maps_to_escalate_requiring_human():
    d = decide_lifecycle(_outcome(OutcomeStatus.ESCALATE), budget=_budget())
    assert d.status is OutcomeStatus.ESCALATE
    assert d.is_escalated is True
    assert d.requires_human_approval is True
    assert d.terminal is True
    assert d.remediation_allowed is False


def test_t4_failed_outcome_maps_to_failed():
    d = decide_lifecycle(_outcome(OutcomeStatus.FAILED), budget=_budget())
    assert d.status is OutcomeStatus.FAILED
    assert d.terminal is True
    assert d.remediation_allowed is False
    assert d.requires_human_approval is False
    assert d.is_complete is False


@pytest.mark.parametrize(
    "status",
    [OutcomeStatus.COMPLETE, OutcomeStatus.REMEDIATE, OutcomeStatus.ESCALATE, OutcomeStatus.FAILED],
)
def test_t5_identical_inputs_produce_identical_decisions(status: OutcomeStatus):
    first = decide_lifecycle(_outcome(status), budget=_budget(attempt=2, max_attempts=5))
    second = decide_lifecycle(_outcome(status), budget=_budget(attempt=2, max_attempts=5))
    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_t5_reason_is_stable_across_time():
    import time

    before = decide_lifecycle(_outcome(OutcomeStatus.REMEDIATE), budget=_budget(attempt=1, max_attempts=2))
    time.sleep(0.01)
    after = decide_lifecycle(_outcome(OutcomeStatus.REMEDIATE), budget=_budget(attempt=1, max_attempts=2))
    assert before == after


def test_t6_decision_logic_contains_no_network_or_model_calls():
    source = _DECISION_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_DECISION_MODULE))
    banned = {"socket", "requests", "urllib", "httpx", "aiohttp", "openai",
              "anthropic", "select_model", "route_model", "ModelRouter"}
    found: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                if (alias.name or "").split(".")[0] in banned:
                    found.append(alias.name or "")
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module.split(".")[0] in banned or module in banned:
                found.append(module)
    assert found == [], f"decision module imports infrastructure: {found}"
    lowered = source.lower()
    for token in ("socket.", "urlopen", "datetime.now", "time.time", "random."):
        assert token not in lowered, f"impure token in decision module: {token!r}"


def test_t7_complete_without_passing_verdict_is_refused():
    from autoforge_composition.lifecycle_decision import LifecycleDecisionError

    with pytest.raises(LifecycleDecisionError):
        decide_lifecycle(_outcome(OutcomeStatus.COMPLETE, passed=False), budget=_budget())


def test_t7_inverted_budget_is_rejected_not_clamped():
    with pytest.raises(Exception):
        RemediationBudget(attempt=0, max_attempts=3)
    with pytest.raises(Exception):
        RemediationBudget(attempt=1, max_attempts=0)
    # attempt > max_attempts is representable (it IS the exhausted state) and
    # must decide FAILED, never clamp or loop.
    d = decide_lifecycle(
        _outcome(OutcomeStatus.REMEDIATE),
        budget=RemediationBudget(attempt=4, max_attempts=3),
    )
    assert d.status is OutcomeStatus.FAILED
    assert d.terminal is True


def test_t7_non_outcome_input_is_rejected():
    with pytest.raises(Exception):
        decide_lifecycle({"status": "complete", "passed": True}, budget=_budget())  # type: ignore[arg-type]


def test_t7_decision_model_rejects_extra_fields():
    from autoforge_composition.lifecycle_decision import LifecycleDecision as LD

    d = decide_lifecycle(_outcome(OutcomeStatus.COMPLETE), budget=_budget())
    with pytest.raises(Exception):
        LD(status=d.status, attempt=d.attempt, remediation_allowed=d.remediation_allowed,
           requires_human_approval=d.requires_human_approval, terminal=d.terminal,
           reason=d.reason, telemetry={"fabricated": True})


def test_t8_taxonomy_still_exposes_hitl_wait_state():
    from autoforge_composition.lifecycle_taxonomy import (
        StageStatus, get_allowed_stage_transitions, is_stage_terminal,
        validate_stage_transition, LifecycleContractError,
    )
    from autoforge_composition.lifecycle_decision import LifecycleDecisionError

    assert StageStatus.WAITING_FOR_HITL.value == "waiting_for_hitl"
    assert StageStatus.WAITING_FOR_HITL in get_allowed_stage_transitions(StageStatus.RUNNING)
    assert not is_stage_terminal(StageStatus.WAITING_FOR_HITL)
    validate_stage_transition(StageStatus.RUNNING, StageStatus.WAITING_FOR_HITL, stage_id="s-1")
    assert issubclass(LifecycleDecisionError, LifecycleContractError)


def test_t9_decision_reuses_outcome_status_without_redefining_it():
    source = _DECISION_MODULE.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(_DECISION_MODULE))
    class_defs = [n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)]
    assert "OutcomeStatus" not in class_defs, "must not redefine OutcomeStatus"
    assert "ExecutionOutcome" not in class_defs, "must not redefine ExecutionOutcome"
    assert LifecycleDecision.model_fields["status"].annotation is OutcomeStatus


def test_t9_every_outcome_status_maps_to_a_decision():
    for status in OutcomeStatus:
        assert decide_lifecycle(_outcome(status), budget=_budget()).status in set(OutcomeStatus)


def test_t10_lifecycle_decision_remains_production_unwired():
    offenders: list[str] = []
    for pkg in ("packages/*/src/**/*.py", "apps/*/src/**/*.py"):
        for path in _REPO.glob(pkg):
            if path == _DECISION_MODULE:
                continue
            try:
                tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            except Exception:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    for alias in node.names:
                        if "lifecycle_decision" in (alias.name or ""):
                            offenders.append(str(path.relative_to(_REPO)))
                elif isinstance(node, ast.ImportFrom):
                    if "lifecycle_decision" in (node.module or ""):
                        offenders.append(str(path.relative_to(_REPO)))
    assert offenders == [], f"lifecycle_decision must stay unwired: {offenders}"


def test_t10_composition_root_does_not_load_decision_contract():
    import sys

    for mod in ("lifecycle_decision", "lifecycle_taxonomy", "execution_outcome"):
        sys.modules.pop(f"autoforge_composition.{mod}", None)
    import autoforge_composition.composition_root  # noqa: F401

    assert [m for m in sys.modules if m == "autoforge_composition.lifecycle_decision"] == []


def test_t6_decision_runs_with_network_disabled(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network must not be used by decide_lifecycle")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    for status in OutcomeStatus:
        assert isinstance(decide_lifecycle(_outcome(status), budget=_budget()), LifecycleDecision)
