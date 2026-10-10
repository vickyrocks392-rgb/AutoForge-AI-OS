"""Gate C3 -- Declarative remediation contract tests (T1-T14 + negatives).

Certifies that an authorised REMEDIATE maps to a *declarative*
``RemediationRequest`` (frozen data: stage, evidence, bounded budget) and
that COMPLETE / ESCALATE / FAILED yield no request. Negative tests prove
the module structurally cannot execute a retry, mutate a counter, invoke a
worker / Power Engine / Model Router / LLM, or create an approval request.
"""

from __future__ import annotations

import ast
import pathlib
import socket

import pytest

from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_composition.lifecycle_decision import (
    LifecycleDecision,
    LifecycleDecisionError,
    RemediationBudget,
    RemediationRequest,
    decide_lifecycle,
    describe_remediation,
)
from autoforge_composition.lifecycle_taxonomy import (
    DEFAULT_STAGE_MAX_ATTEMPTS,
    O1_ORCHESTRATOR_MAX_ATTEMPTS_PER_STAGE,
)

_REPO = pathlib.Path(__file__).resolve().parents[3]
_DECISION_MODULE = _REPO / "packages/composition/src/autoforge_composition/lifecycle_decision.py"


def _outcome(
    status: OutcomeStatus,
    *,
    passed: bool | None = None,
    findings: list[str] | None = None,
    loop_type: str = "coding",
) -> ExecutionOutcome:
    if passed is None:
        passed = status is OutcomeStatus.COMPLETE
    kwargs: dict = {}
    if findings is not None:
        kwargs["findings"] = findings
    return ExecutionOutcome(status=status, loop_type=loop_type, passed=passed, **kwargs)


def _budget(attempt: int = 1, max_attempts: int = 3) -> RemediationBudget:
    return RemediationBudget(attempt=attempt, max_attempts=max_attempts)


def _forged(
    status: OutcomeStatus,
    *,
    attempt: int = 1,
    remediation_allowed: bool,
    requires_human_approval: bool = False,
    terminal: bool = False,
    reason: str = "forged decision",
) -> LifecycleDecision:
    return LifecycleDecision(
        status=status,
        attempt=attempt,
        remediation_allowed=remediation_allowed,
        requires_human_approval=requires_human_approval,
        terminal=terminal,
        reason=reason,
    )


# ── T1-T5: mapping table ─────────────────────────────────────────────────


def test_t1_remediate_decision_maps_to_declarative_request():
    outcome = _outcome(
        OutcomeStatus.REMEDIATE, findings=["evaluation failed: contract violation"]
    )
    budget = _budget(1, 3)
    decision = decide_lifecycle(outcome, budget=budget)
    request = describe_remediation(decision, outcome, budget=budget)
    assert isinstance(request, RemediationRequest)
    assert request.stage == "coding"  # default stage = the loop's unit of work
    assert request.loop_type == "coding"
    assert request.findings == ["evaluation failed: contract violation"]
    assert request.budget == budget
    assert request.reason == decision.reason


def test_t2_complete_outcome_yields_no_request():
    outcome = _outcome(OutcomeStatus.COMPLETE)
    decision = decide_lifecycle(outcome, budget=_budget())
    assert decision.status is OutcomeStatus.COMPLETE
    assert describe_remediation(decision, outcome, budget=_budget()) is None


def test_t3_escalate_yields_no_request_and_no_approval_object():
    outcome = _outcome(OutcomeStatus.ESCALATE)
    decision = decide_lifecycle(outcome, budget=_budget())
    assert decision.requires_human_approval is True
    assert describe_remediation(decision, outcome, budget=_budget()) is None
    assert set(RemediationRequest.model_fields) == {
        "stage",
        "loop_type",
        "findings",
        "budget",
        "reason",
    }


def test_t4_failed_outcome_yields_no_request():
    outcome = _outcome(OutcomeStatus.FAILED)
    decision = decide_lifecycle(outcome, budget=_budget())
    assert decision.status is OutcomeStatus.FAILED
    assert describe_remediation(decision, outcome, budget=_budget()) is None


def test_t5_exhausted_budget_fails_closed_with_no_request():
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["flaky test"])
    budget = _budget(3, 3)
    decision = decide_lifecycle(outcome, budget=budget)
    assert decision.status is OutcomeStatus.FAILED
    assert decision.remediation_allowed is False
    assert describe_remediation(decision, outcome, budget=budget) is None


# ── T6-T7: determinism, purity, fail-closed negatives ────────────────────


def test_t6_identical_inputs_produce_identical_requests():
    def build():
        outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["lint error"])
        budget = _budget(2, 5)
        decision = decide_lifecycle(outcome, budget=budget)
        return describe_remediation(decision, outcome, budget=budget)

    first, second = build(), build()
    assert first is not None and second is not None
    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_t6_request_carries_no_executable_fields():
    """Every request field is inert data: no callable, no handle, no endpoint."""
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["x"])
    budget = _budget()
    decision = decide_lifecycle(outcome, budget=budget)
    request = describe_remediation(decision, outcome, budget=budget)
    assert request is not None
    dump = request.model_dump(mode="python")
    assert set(dump) == {"stage", "loop_type", "findings", "budget", "reason"}
    for value in (dump["stage"], dump["loop_type"], dump["reason"]):
        assert isinstance(value, str)
    assert isinstance(dump["findings"], list)
    assert isinstance(dump["budget"], dict)


def test_t7_permit_on_non_remediate_decision_is_refused():
    decision = _forged(
        OutcomeStatus.COMPLETE, attempt=1, remediation_allowed=True, terminal=True
    )
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(decision, _outcome(OutcomeStatus.COMPLETE), budget=_budget())


def test_t7_remediate_without_permit_is_refused():
    decision = _forged(OutcomeStatus.REMEDIATE, attempt=1, remediation_allowed=False)
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(
            decision, _outcome(OutcomeStatus.REMEDIATE), budget=_budget()
        )


def test_t7_terminal_remediate_is_refused():
    decision = _forged(
        OutcomeStatus.REMEDIATE, attempt=1, remediation_allowed=True, terminal=True
    )
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(
            decision, _outcome(OutcomeStatus.REMEDIATE), budget=_budget()
        )


def test_t7_remediate_requiring_human_approval_is_refused():
    decision = _forged(
        OutcomeStatus.REMEDIATE,
        attempt=1,
        remediation_allowed=True,
        requires_human_approval=True,
    )
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(
            decision, _outcome(OutcomeStatus.REMEDIATE), budget=_budget()
        )


def test_t7_budget_attempt_mismatch_is_refused():
    decision = _forged(OutcomeStatus.REMEDIATE, attempt=1, remediation_allowed=True)
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(
            decision, _outcome(OutcomeStatus.REMEDIATE), budget=_budget(2, 3)
        )


def test_t7_exhausted_budget_against_forged_remediate_is_refused():
    decision = _forged(OutcomeStatus.REMEDIATE, attempt=3, remediation_allowed=True)
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(
            decision, _outcome(OutcomeStatus.REMEDIATE), budget=_budget(3, 3)
        )


def test_t7_outcome_contradicting_decision_is_refused():
    decision = decide_lifecycle(_outcome(OutcomeStatus.REMEDIATE), budget=_budget())
    with pytest.raises(LifecycleDecisionError):
        describe_remediation(decision, _outcome(OutcomeStatus.COMPLETE), budget=_budget())


# ── T8-T10: frozen data, stage naming, non-aliasing ──────────────────────


def test_t8_request_is_frozen_and_forbids_extra_fields():
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["x"])
    budget = _budget()
    decision = decide_lifecycle(outcome, budget=budget)
    request = describe_remediation(decision, outcome, budget=budget)
    assert request is not None
    with pytest.raises(Exception):
        request.stage = "other"  # frozen
    with pytest.raises(Exception):
        RemediationRequest(
            stage="s",
            loop_type="coding",
            findings=[],
            budget=budget,
            reason="r",
            executor="evil",  # extra=forbid
        )


def test_t9_narrower_stage_is_recorded_never_validated():
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["x"])
    budget = _budget()
    decision = decide_lifecycle(outcome, budget=budget)
    narrowed = describe_remediation(decision, outcome, budget=budget, stage="testing")
    assert narrowed is not None and narrowed.stage == "testing"
    bogus = describe_remediation(
        decision, outcome, budget=budget, stage="stage_that_does_not_exist"
    )
    assert bogus is not None and bogus.stage == "stage_that_does_not_exist"
    empty = describe_remediation(decision, outcome, budget=budget, stage="")
    assert empty is not None and empty.stage == "coding"  # empty names nothing -> default


def test_t9_non_remediate_decisions_name_no_stage():
    # COMPLETE / ESCALATE / FAILED name no stage: they yield no request at all.
    for status in (OutcomeStatus.COMPLETE, OutcomeStatus.ESCALATE, OutcomeStatus.FAILED):
        outcome = _outcome(status)
        decision = decide_lifecycle(outcome, budget=_budget())
        assert describe_remediation(decision, outcome, budget=_budget()) is None


def test_t10_findings_are_copied_never_aliased():
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["original"])
    budget = _budget()
    decision = decide_lifecycle(outcome, budget=budget)
    request = describe_remediation(decision, outcome, budget=budget)
    assert request is not None
    assert request.findings is not outcome.findings
    snapshot = list(outcome.findings)
    request.findings.append("injected")
    assert outcome.findings == snapshot == ["original"]
    assert budget.attempt == 1 and budget.max_attempts == 3  # inputs untouched


# ── T11-T14: AST safety proofs, boundedness, purity, unwired ─────────────


def _decision_tree() -> ast.Module:
    return ast.parse(
        _DECISION_MODULE.read_text(encoding="utf-8"), filename=str(_DECISION_MODULE)
    )


def _c3_nodes() -> list[ast.AST]:
    """Nodes of the C3 additions: RemediationRequest + describe_remediation."""
    tree = _decision_tree()
    keep: list[ast.AST] = []
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.ClassDef) and name == "RemediationRequest":
            keep.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name == (
            "describe_remediation"
        ):
            keep.append(node)
    assert len(keep) == 2, "C3 additions missing from decision module"
    return keep


def test_t11_no_execution_worker_router_llm_or_approval_invocation():
    banned_calls = {
        "execute", "exec", "invoke", "dispatch", "submit", "retry", "rerun",
        "run", "start", "spawn", "apply_async", "delay", "send", "publish",
        "complete", "approve", "approve_request", "create_approval", "call",
        "predict", "chat", "generate", "openai", "route_model", "select_model",
    }
    banned_attr_markers = (
        "executor", "worker", "engine", "router", "llm", "approval", "client",
    )
    offenders: list[str] = []
    for node in _c3_nodes():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                target = sub.func
                if isinstance(target, ast.Attribute):
                    leaf = target.attr
                elif isinstance(target, ast.Name):
                    leaf = target.id
                else:
                    leaf = ""
                if leaf.lower() in banned_calls:
                    offenders.append(f"call -> {leaf}")
                src = ast.unparse(target).lower()
                if any(marker in src for marker in banned_attr_markers):
                    offenders.append(f"attribute invocation -> {src}")
    assert offenders == [], f"C3 must not invoke execution infrastructure: {offenders}"


def test_t11_c3_additions_import_nothing_new():
    tree = _decision_tree()
    allowed_modules = {
        "autoforge_composition.execution_outcome",
        "autoforge_composition.lifecycle_taxonomy",
        "pydantic",
        "__future__",
    }
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name or "" for alias in node.names)
    assert imported <= allowed_modules, f"unexpected imports: {imported - allowed_modules}"


def test_t12_no_recursion_and_no_retry_loop_in_c3():
    for node in _c3_nodes():
        for sub in ast.walk(node):
            if isinstance(sub, (ast.For, ast.While)):
                raise AssertionError(
                    f"{getattr(node, 'name', '?')} contains a loop; remediation "
                    "must never iterate toward re-execution"
                )
            if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                assert sub.func.id not in {"describe_remediation", "decide_lifecycle"}, (
                    "self-recursion is forbidden in the remediation path"
                )


def test_t12_request_contains_no_retry_counter_mutation():
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["x"])
    budget = _budget(1, 3)
    decision = decide_lifecycle(outcome, budget=budget)
    request = describe_remediation(decision, outcome, budget=budget)
    assert request is not None
    # frozen models reject every mutation route, including counters
    with pytest.raises(Exception):
        request.budget = RemediationBudget(attempt=2, max_attempts=3)
    with pytest.raises(Exception):
        budget.attempt = 2
    with pytest.raises(Exception):
        budget.max_attempts = 999
    assert budget.attempt == 1 and budget.max_attempts == 3


def test_t13_describe_runs_with_network_disabled(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network must not be used by describe_remediation")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    for status in OutcomeStatus:
        outcome = _outcome(status)
        budget = _budget()
        decision = decide_lifecycle(outcome, budget=budget)
        result = describe_remediation(decision, outcome, budget=budget)
        assert result is None or isinstance(result, RemediationRequest)


def test_t13_c3_source_contains_no_impure_or_infra_tokens():
    # Whole-module: no impure runtime tokens anywhere.
    source = _DECISION_MODULE.read_text(encoding="utf-8").lower()
    for token in (
        "socket.", "urlopen", "datetime.now", "time.time", "random.",
        "requests.", "httpx", "subprocess", "await ",
    ):
        assert token not in source, f"impure token in decision module: {token!r}"
    # C3 nodes only: no reference to O-2's dead remediation branch. (The
    # phrases legitimately appear in the C2-certified docstring as *evidence*
    # of the gap, but must never appear as capability in the C3 code.)
    c3_source = " ".join(
        ast.get_source_segment(source, node) or "" for node in _c3_nodes()
    ).lower()
    for token in ("remediation_tasks", "handle_remediation", "loop_result"):
        assert token not in c3_source, f"infra token in C3 additions: {token!r}"


def test_t14_capability_stays_production_unwired():
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
                modules: list[str] = []
                names: list[str] = []
                if isinstance(node, ast.Import):
                    modules = [alias.name or "" for alias in node.names]
                elif isinstance(node, ast.ImportFrom):
                    modules = [node.module or ""]
                    names = [alias.name or "" for alias in node.names]
                if any("lifecycle_decision" in m for m in modules) or any(
                    n in {"RemediationRequest", "describe_remediation"} for n in names
                ):
                    offenders.append(str(path.relative_to(_REPO)))
    assert offenders == [], f"C3 capability must stay unwired: {offenders}"