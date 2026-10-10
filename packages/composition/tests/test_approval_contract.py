"""Gate C4 -- Canonical escalation / human-approval contract tests (T1-T20).

Certifies that a certified ESCALATE maps to a *declarative*
``HumanApprovalRequirement`` (frozen data: stage, evidence, justification)
and that COMPLETE / REMEDIATE / FAILED yield no requirement. Negative
tests prove the module structurally cannot approve, persist, pause,
resume, or invoke an executor / worker / Power Engine / Model Router /
LLM / API; regression tests re-run the C3, C2 and B2 contract suites.
"""

from __future__ import annotations

import ast
import copy
import pathlib
import socket
import subprocess
import sys

import pytest

from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_composition.lifecycle_decision import (
    HumanApprovalRequirement,
    LifecycleDecision,
    LifecycleDecisionError,
    RemediationBudget,
    decide_lifecycle,
    describe_approval,
    describe_remediation,
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


def _decide(status: OutcomeStatus, **outcome_kwargs) -> tuple[LifecycleDecision, ExecutionOutcome]:
    outcome = _outcome(status, **outcome_kwargs)
    return decide_lifecycle(outcome, budget=_budget()), outcome


def _forged(
    status: OutcomeStatus,
    *,
    attempt: int = 1,
    remediation_allowed: bool = False,
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


# ── T1-T8: mapping table, evidence, determinism, immutability ──────────────


def test_t1_escalate_decision_produces_human_approval_requirement():
    decision, outcome = _decide(
        OutcomeStatus.ESCALATE, findings=["power engine awaits human approval"]
    )
    requirement = describe_approval(decision, outcome)
    assert isinstance(requirement, HumanApprovalRequirement)
    assert requirement.stage == "coding"
    assert requirement.loop_type == "coding"
    assert requirement.findings == ["power engine awaits human approval"]
    assert requirement.reason == decision.reason
    assert decision.requires_human_approval is True


def test_t1_requirement_is_data_not_an_action():
    """The value is inert data: no field can act, approve, or continue work."""
    decision, outcome = _decide(OutcomeStatus.ESCALATE, findings=["x"])
    requirement = describe_approval(decision, outcome)
    assert requirement is not None
    dump = requirement.model_dump(mode="python")
    for value in (dump["stage"], dump["loop_type"], dump["reason"]):
        assert isinstance(value, str)
    assert isinstance(dump["findings"], list)
    assert all(not callable(v) for v in dump.values())


def test_t2_complete_produces_no_approval_requirement():
    decision, outcome = _decide(OutcomeStatus.COMPLETE)
    assert decision.status is OutcomeStatus.COMPLETE
    assert describe_approval(decision, outcome) is None


def test_t3_remediate_produces_no_approval_requirement():
    decision, outcome = _decide(OutcomeStatus.REMEDIATE, findings=["flaky test"])
    assert decision.status is OutcomeStatus.REMEDIATE
    assert decision.requires_human_approval is False
    assert describe_approval(decision, outcome) is None


def test_t3_exhausted_remediate_fails_closed_to_failed_without_requirement():
    outcome = _outcome(OutcomeStatus.REMEDIATE, findings=["flaky test"])
    decision = decide_lifecycle(outcome, budget=_budget(3, 3))
    assert decision.status is OutcomeStatus.FAILED
    assert describe_approval(decision, outcome) is None


def test_t4_failed_preserves_existing_semantics():
    decision, outcome = _decide(OutcomeStatus.FAILED)
    assert decision.status is OutcomeStatus.FAILED
    assert decision.terminal is True
    assert decision.remediation_allowed is False
    assert decision.requires_human_approval is False
    # Certified C2 reason string, byte-identical: C4 never rewrites FAILED.
    assert decision.reason == "Executor reported FAILED; no re-execution is permitted."
    assert describe_approval(decision, outcome) is None


def test_t4_failed_yields_no_remediation_request_either():
    # C3's mapping is untouched by C4: FAILED still yields no artefact there.
    decision, outcome = _decide(OutcomeStatus.FAILED)
    assert describe_remediation(decision, outcome, budget=_budget()) is None


def test_t5_requirement_carries_stage_and_context():
    decision, outcome = _decide(
        OutcomeStatus.ESCALATE, findings=["blocked gate"], loop_type="testing"
    )
    requirement = describe_approval(decision, outcome)
    assert requirement is not None
    # Default stage = the loop's only canonical unit-of-work label.
    assert requirement.stage == "testing"
    assert requirement.loop_type == "testing"


def test_t5_narrower_stage_is_recorded_never_validated():
    decision, outcome = _decide(OutcomeStatus.ESCALATE, findings=["x"])
    narrowed = describe_approval(decision, outcome, stage="deployment")
    assert narrowed is not None and narrowed.stage == "deployment"
    bogus = describe_approval(decision, outcome, stage="stage_that_does_not_exist")
    assert bogus is not None and bogus.stage == "stage_that_does_not_exist"
    empty = describe_approval(decision, outcome, stage="")
    assert empty is not None and empty.stage == "coding"  # empty names nothing -> default


def test_t5_empty_stage_on_direct_construction_is_rejected():
    with pytest.raises(Exception):
        HumanApprovalRequirement(stage="", loop_type="coding", findings=[], reason="r")


def test_t6_requirement_carries_evidence_and_findings():
    decision, outcome = _decide(
        OutcomeStatus.ESCALATE, findings=["finding A", "finding B"]
    )
    requirement = describe_approval(decision, outcome)
    assert requirement is not None
    assert requirement.findings == ["finding A", "finding B"]
    assert requirement.reason == decision.reason
    assert requirement.reason != ""


def test_t6_findings_are_copied_never_aliased():
    outcome = _outcome(OutcomeStatus.ESCALATE, findings=["original"])
    decision = decide_lifecycle(outcome, budget=_budget())
    requirement = describe_approval(decision, outcome)
    assert requirement is not None
    assert requirement.findings is not outcome.findings
    snapshot = list(outcome.findings)
    requirement.findings.append("injected")
    assert outcome.findings == snapshot == ["original"]


def test_t7_identical_inputs_produce_identical_requirements():
    def build():
        decision, outcome = _decide(
            OutcomeStatus.ESCALATE, findings=["lint error at line 1"]
        )
        return describe_approval(decision, outcome)

    first, second = build(), build()
    assert first is not None and second is not None
    assert first == second
    assert first.model_dump(mode="json") == second.model_dump(mode="json")


def test_t7_requirement_is_stable_across_time():
    import time

    decision, outcome = _decide(OutcomeStatus.ESCALATE, findings=["x"])
    before = describe_approval(decision, outcome)
    time.sleep(0.01)
    after = describe_approval(decision, outcome)
    assert before == after
    # No wall-clock or novelty field exists on the contract at all.
    assert set(HumanApprovalRequirement.model_fields) == {
        "stage",
        "loop_type",
        "findings",
        "reason",
    }


def test_t8_requirement_is_frozen_and_forbids_extra_fields():
    decision, outcome = _decide(OutcomeStatus.ESCALATE, findings=["x"])
    requirement = describe_approval(decision, outcome)
    assert requirement is not None
    with pytest.raises(Exception):
        requirement.stage = "other"  # frozen
    with pytest.raises(Exception):
        requirement.findings = []  # frozen
    with pytest.raises(Exception):
        HumanApprovalRequirement(
            stage="s",
            loop_type="coding",
            findings=[],
            reason="r",
            executor="evil",  # extra=forbid
        )
    with pytest.raises(Exception):
        HumanApprovalRequirement(
            stage="s",
            loop_type="coding",
            findings=[],
            reason="r",
            approval_id="invented-identity",  # extra=forbid: no identity here
        )


# ── T9-T14: AST safety proofs, purity, fail-closed negatives ───────────────


def _decision_tree() -> ast.Module:
    return ast.parse(
        _DECISION_MODULE.read_text(encoding="utf-8"), filename=str(_DECISION_MODULE)
    )


def _c4_nodes() -> list[ast.AST]:
    """Nodes of the C4 additions: HumanApprovalRequirement + describe_approval."""
    tree = _decision_tree()
    keep: list[ast.AST] = []
    for node in tree.body:
        name = getattr(node, "name", None)
        if isinstance(node, ast.ClassDef) and name == "HumanApprovalRequirement":
            keep.append(node)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and name == (
            "describe_approval"
        ):
            keep.append(node)
    assert len(keep) == 2, "C4 additions missing from decision module"
    return keep


def _without_docstrings(nodes: list[ast.AST]) -> list[ast.AST]:
    """Deep copies of ``nodes`` with their leading docstring statement removed."""
    stripped: list[ast.AST] = []
    for node in nodes:
        clone = copy.deepcopy(node)
        body = getattr(clone, "body", None)
        if (
            body
            and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)
        ):
            body.pop(0)
        stripped.append(clone)
    return stripped


def _c4_code_text() -> str:
    """Executable code of the C4 nodes: docstrings removed, comments erased."""
    return " ".join(ast.unparse(n) for n in _without_docstrings(_c4_nodes())).lower()


def test_t9_no_approval_record_is_created_or_persisted():
    # 1. The contract has exactly the four declarative fields: no identity,
    #    no status, no actor, no timestamp -- nothing an approval record needs.
    assert set(HumanApprovalRequirement.model_fields) == {
        "stage",
        "loop_type",
        "findings",
        "reason",
    }
    # 2. No identity or persistence call exists anywhere in the C4 code.
    code = _c4_code_text()
    for token in ("uuid", "persist", "save", "store", "pending_approvals", "record("):
        assert token not in code, f"persistence/identity token in C4 code: {token!r}"
    for node in _c4_nodes():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                leaf = (
                    sub.func.attr
                    if isinstance(sub.func, ast.Attribute)
                    else getattr(sub.func, "id", "")
                )
                assert leaf not in {"uuid4", "uuid1", "urandom"}, f"novelty source: {leaf}"
    # 3. No write of any kind: no stores into dicts/attributes, no global state.
    for node in _c4_nodes():
        for sub in ast.walk(node):
            assert not isinstance(sub, (ast.Global, ast.Nonlocal))
            if isinstance(sub, ast.Attribute):
                assert not isinstance(sub.ctx, ast.Store), "attribute store in C4"
            if isinstance(sub, ast.Subscript):
                assert not isinstance(sub.ctx, ast.Store), "subscript store in C4"
    # 4. describe_approval returns its value directly; nothing is registered.
    fn = next(n for n in _c4_nodes() if isinstance(n, ast.FunctionDef))
    returns = [s for s in ast.walk(fn) if isinstance(s, ast.Return)]
    assert returns, "describe_approval must return its artefact"


def test_t9_module_has_no_global_mutable_state_beyond_certified_decl():
    allowed = 0
    for node in _decision_tree().body:
        if isinstance(node, (ast.Import, ast.ImportFrom, ast.ClassDef, ast.FunctionDef)):
            continue
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # module docstring
        if isinstance(node, ast.Assign):
            targets = [t.id for t in node.targets if isinstance(t, ast.Name)]
            if targets == ["__all__"]:
                allowed += 1
                continue
        raise AssertionError(f"unexpected module-level statement: {ast.dump(node)[:80]}")
    assert allowed == 1


def test_t10_no_pause_resume_operation_occurs():
    code = _c4_code_text()
    for token in ("pause", "resume", "halt", "suspend", "transition_state", "break"):
        assert token not in code, f"control-flow token in C4 code: {token!r}"
    for node in _c4_nodes():
        assert not isinstance(node, ast.AsyncFunctionDef), "C4 must be synchronous"
        for sub in ast.walk(node):
            assert not isinstance(sub, ast.Await), "no async wait in C4"
            if isinstance(sub, ast.Call):
                leaf = (
                    sub.func.attr
                    if isinstance(sub.func, ast.Attribute)
                    else getattr(sub.func, "id", "")
                ).lower()
                assert leaf not in {
                    "pause",
                    "resume",
                    "suspend",
                    "halt",
                    "transition",
                    "transition_state",
                    "break_execution",
                }, f"control-flow call in C4: {leaf}"


def test_t11_no_executor_worker_power_engine_or_approval_invocation():
    banned_calls = {
        "execute", "exec", "invoke", "dispatch", "submit", "retry", "rerun",
        "run", "start", "spawn", "apply_async", "delay", "send", "publish",
        "complete", "approve", "reject", "approve_request", "create_approval",
        "call", "predict", "chat", "generate", "openai", "route_model",
        "select_model", "request_approval", "process_decision", "check_timeouts",
    }
    banned_attr_markers = (
        "executor", "worker", "engine", "router", "llm", "client",
        "approval_coordinator", "orchestrator",
    )
    offenders: list[str] = []
    for node in _c4_nodes():
        for sub in ast.walk(node):
            if isinstance(sub, ast.Call):
                target = sub.func
                if isinstance(target, ast.Attribute):
                    leaf = target.attr
                    src = ast.unparse(target).lower()
                    if leaf.lower() in banned_calls:
                        offenders.append(f"call -> {leaf}")
                    if any(marker in src for marker in banned_attr_markers):
                        offenders.append(f"attribute invocation -> {src}")
                elif isinstance(target, ast.Name):
                    if target.id.lower() in banned_calls:
                        offenders.append(f"call -> {target.id}")
    assert offenders == [], f"C4 must not invoke execution infrastructure: {offenders}"


def test_t11_c4_additions_import_nothing_new():
    allowed_modules = {
        "autoforge_composition.execution_outcome",
        "autoforge_composition.lifecycle_taxonomy",
        "pydantic",
        "__future__",
    }
    imported: set[str] = set()
    for node in ast.walk(_decision_tree()):
        if isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name or "" for alias in node.names)
    assert imported <= allowed_modules, f"unexpected imports: {imported - allowed_modules}"


def test_t12_no_model_router_or_llm_invocation():
    code = _c4_code_text()
    for token in (
        "route_model", "select_model", "modelrouter", "openai", "anthropic",
        "completion", "predict", "generate", "llm", "provider",
    ):
        assert token not in code, f"model/LLM token in C4 code: {token!r}"


def test_t13_describe_approval_runs_with_network_disabled(monkeypatch):
    def _blocked(*args, **kwargs):
        raise AssertionError("network must not be used by describe_approval")

    monkeypatch.setattr(socket, "socket", _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)
    for status in OutcomeStatus:
        decision, outcome = _decide(status)
        result = describe_approval(decision, outcome)
        assert result is None or isinstance(result, HumanApprovalRequirement)


def test_t13_c4_source_contains_no_network_or_infra_tokens():
    code = _c4_code_text()
    for token in (
        "socket", "urllib", "urlopen", "httpx", "requests", "aiohttp",
        "http.client", "subprocess", "datetime.now", "time.time", "random",
        "await ",
    ):
        assert token not in code, f"impure/infra token in C4 code: {token!r}"


# ── T14: malformed or contradictory ESCALATE input fails closed ────────────


def test_t14_non_terminal_escalate_decision_is_refused():
    decision = _forged(
        OutcomeStatus.ESCALATE,
        remediation_allowed=False,
        requires_human_approval=True,
        terminal=False,
    )
    with pytest.raises(LifecycleDecisionError):
        describe_approval(decision, _outcome(OutcomeStatus.ESCALATE))


def test_t14_escalate_without_approval_claim_is_refused():
    decision = _forged(
        OutcomeStatus.ESCALATE, requires_human_approval=False, terminal=True
    )
    with pytest.raises(LifecycleDecisionError):
        describe_approval(decision, _outcome(OutcomeStatus.ESCALATE))


def test_t14_escalate_with_remediation_permit_is_refused():
    decision = _forged(
        OutcomeStatus.ESCALATE,
        remediation_allowed=True,
        requires_human_approval=True,
        terminal=True,
    )
    with pytest.raises(LifecycleDecisionError):
        describe_approval(decision, _outcome(OutcomeStatus.ESCALATE))


@pytest.mark.parametrize(
    "contradicting",
    [OutcomeStatus.COMPLETE, OutcomeStatus.REMEDIATE, OutcomeStatus.FAILED],
)
def test_t14_escalate_decision_requires_escalate_evidence(contradicting):
    decision, _ = _decide(OutcomeStatus.ESCALATE)
    with pytest.raises(LifecycleDecisionError):
        describe_approval(decision, _outcome(contradicting))


@pytest.mark.parametrize(
    "claimed",
    [OutcomeStatus.COMPLETE, OutcomeStatus.REMEDIATE, OutcomeStatus.FAILED],
)
def test_t14_approval_claim_without_escalate_decision_is_refused(claimed):
    decision = _forged(claimed, requires_human_approval=True, terminal=True)
    with pytest.raises(LifecycleDecisionError):
        describe_approval(decision, _outcome(claimed))


def test_t14_suppressed_escalate_evidence_is_refused():
    # A forged non-ESCALATE decision (no approval claim) paired with real
    # escalation evidence: the disagreement itself is refused, never dropped.
    decision = _forged(
        OutcomeStatus.COMPLETE, requires_human_approval=False, terminal=True
    )
    with pytest.raises(LifecycleDecisionError):
        describe_approval(decision, _outcome(OutcomeStatus.ESCALATE))


# ── T15-T17: single authority, O-1 quarantine, production-unwired ──────────


def test_t15_no_second_lifecycle_authority_exists():
    # 1. The module defines exactly the certified classes; C4 adds only the
    #    declarative requirement -- no new decision, outcome, or enum type.
    class_defs = [n.name for n in _decision_tree().body if isinstance(n, ast.ClassDef)]
    assert set(class_defs) == {
        "LifecycleDecisionError",
        "RemediationBudget",
        "LifecycleDecision",
        "RemediationRequest",
        "HumanApprovalRequirement",
    }
    # 2. No Enum is defined here: OutcomeStatus stays the sole vocabulary.
    for node in _decision_tree().body:
        if isinstance(node, ast.ClassDef):
            for base in node.bases:
                assert "Enum" not in ast.unparse(base), f"{node.name} subclasses Enum"
    # 3. LifecycleDecision remains the sole decision contract, unchanged.
    assert set(LifecycleDecision.model_fields) == {
        "status",
        "attempt",
        "remediation_allowed",
        "requires_human_approval",
        "terminal",
        "reason",
    }
    assert LifecycleDecision.model_fields["status"].annotation is OutcomeStatus
    # 4. The requirement cannot double as a decision: it carries no status,
    #    no terminality, no permits -- only declarative context.
    assert not {"status", "decision", "terminal", "attempt", "remediation_allowed"} & set(
        HumanApprovalRequirement.model_fields
    )
    # 5. describe_approval can only yield the requirement or nothing.
    fn = next(n for n in _c4_nodes() if isinstance(n, ast.FunctionDef))
    ret = ast.unparse(fn.returns)
    assert "HumanApprovalRequirement" in ret and "None" in ret


def test_t16_o1_remains_quarantined():
    for node in ast.walk(_decision_tree()):
        if isinstance(node, ast.Import):
            names = [a.name or "" for a in node.names]
        elif isinstance(node, ast.ImportFrom):
            names = [node.module or ""]
        else:
            continue
        assert not any("autoforge_orchestration" in n for n in names), (
            "O-1 import found in lifecycle_decision"
        )
    # Runtime proof in a fresh interpreter: importing the contract must not
    # load any O-1 module.
    probe = (
        "import autoforge_composition.lifecycle_decision, sys; "
        "print([m for m in sys.modules if m.startswith('autoforge_orchestration')])"
    )
    proc = subprocess.run(
        [sys.executable, "-c", probe],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(_REPO),
    )
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.strip() == "[]", f"O-1 loaded: {proc.stdout.strip()}"


def test_t17_lifecycle_decision_remains_production_unwired():
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
                    n in {"HumanApprovalRequirement", "describe_approval"} for n in names
                ):
                    offenders.append(str(path.relative_to(_REPO)))
    assert offenders == [], f"C4 capability must stay unwired: {offenders}"


def test_t17_c4_nodes_have_no_loops_and_no_recursion():
    for node in _c4_nodes():
        name = getattr(node, "name", "?")
        for sub in ast.walk(node):
            if isinstance(sub, (ast.For, ast.While, ast.AsyncFor)):
                raise AssertionError(
                    f"{name} contains a loop; approval requirements are data, "
                    "never assembled by iteration"
                )
        # direct self-recursion check: nothing here calls its own node
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for sub in ast.walk(node):
                if isinstance(sub, ast.Call) and isinstance(sub.func, ast.Name):
                    assert sub.func.id != node.name, f"{name} recurses"


# ── T18-T20: regression -- C3 / C2 / B2 remain green ───────────────────────


def _run_contract_suite(relative_path: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_REPO / relative_path),
            "-q",
            "--no-header",
            "-p",
            "no:cacheprovider",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=600,
    )


def test_t18_c3_remediation_contract_remains_green():
    proc = _run_contract_suite("packages/composition/tests/test_remediation_contract.py")
    assert proc.returncode == 0, f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    assert " passed" in proc.stdout


def test_t19_c2_lifecycle_decision_contract_remains_green():
    proc = _run_contract_suite(
        "packages/composition/tests/test_lifecycle_decision_contract.py"
    )
    assert proc.returncode == 0, f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    assert " passed" in proc.stdout


def test_t20_b2_execution_outcome_contract_remains_green():
    proc = _run_contract_suite(
        "packages/composition/tests/test_execution_outcome_contract.py"
    )
    assert proc.returncode == 0, f"{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    assert " passed" in proc.stdout