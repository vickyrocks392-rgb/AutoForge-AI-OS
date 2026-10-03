"""Phase 19B-3 — Gates 11-12, 26: safe source-code self-modification."""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    CodeChangeGatekeeper,
    CodeChangeProposal,
    CodeChangeRefused,
    GateStatus,
    LearningScope,
    LearningScopeKind,
)
from autoforge_learning.codemod import (
    MANDATORY_GATES,
    PROTECTED_PATHS,
    parses_as_python,
    verify_diff_is_reversible,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


def make_proposal(scope: LearningScope, paths=("src/app.py",), workspace="/tmp/ws"):
    return CodeChangeProposal(
        scope=scope,
        summary="cache the parsed template",
        diff="--- a/src/app.py\n+++ b/src/app.py\n@@\n+cache = {}\n",
        touched_paths=tuple(paths),
        base_content_hash="a" * 64,
        proposed_content_hash="b" * 64,
        isolated_workspace=workspace,
    )


def all_passed() -> dict[str, GateStatus]:
    return {g: GateStatus.PASSED for g in MANDATORY_GATES}


# ── Gate 11: versioned, diffable, attributable, reversible ────────────────────


def test_ten_mandatory_gates_are_declared():
    """Gate 12 enumerates exactly ten gates, in order."""
    assert len(MANDATORY_GATES) == 10
    assert MANDATORY_GATES[0] == "syntax_parse"
    assert MANDATORY_GATES[-1] == "promotion_authorization"
    for expected in (
        "compilation",
        "unit_tests",
        "integration_tests",
        "deterministic_validation",
        "security_tests",
        "regression_tests",
        "protected_system_tests",
        "review",
    ):
        assert expected in MANDATORY_GATES


def test_a_proposal_records_its_diff_and_reversibility(scope):
    proposal = make_proposal(scope)
    assert proposal.diff
    assert proposal.base_content_hash != proposal.proposed_content_hash
    assert proposal.isolated_workspace
    assert proposal.proposed_by


def test_reversibility_is_asserted_against_content_not_memory(scope):
    """If the tree moved since the diff, the proposal is stale and refused."""
    import hashlib

    base = "def main():\n    return 1\n"
    proposal = CodeChangeProposal(
        scope=scope,
        summary="s",
        diff="d",
        touched_paths=("src/app.py",),
        base_content_hash=hashlib.sha256(base.encode()).hexdigest(),
        proposed_content_hash="b" * 64,
        isolated_workspace="/tmp/ws",
    )
    assert verify_diff_is_reversible(proposal, base)
    assert not verify_diff_is_reversible(proposal, "the tree moved on")


def test_a_direct_write_to_production_is_refused(scope):
    """There is no path to production source that skips an isolated workspace."""
    with pytest.raises(CodeChangeRefused, match="isolated workspace"):
        CodeChangeGatekeeper().assert_permitted(make_proposal(scope, workspace=""))


def test_a_proposal_without_a_workspace_is_denied_before_scoring(scope):
    """The isolation check runs before any gate is scored."""
    with pytest.raises(CodeChangeRefused):
        CodeChangeGatekeeper().evaluate(
            make_proposal(scope, workspace=""), gate_results=all_passed()
        )


def test_the_syntax_gate_rejects_unparseable_source():
    """Gate 1 of Gate 12: the proposed content must actually parse."""
    assert parses_as_python("def f():\n    return 1\n")
    assert not parses_as_python("def f(:\n")


# ── Gate 12: any mandatory gate failure means NO PROMOTION ───────────────────


def test_all_ten_gates_passing_is_promotable(scope):
    verdict = CodeChangeGatekeeper().evaluate(
        make_proposal(scope), gate_results=all_passed()
    )
    assert verdict.promotable
    assert verdict.blocking_gates == ()


@pytest.mark.parametrize("failing_gate", MANDATORY_GATES)
def test_one_failed_gate_blocks_promotion(scope, failing_gate):
    verdict = CodeChangeGatekeeper().evaluate(
        make_proposal(scope),
        gate_results={
            g: (GateStatus.FAILED if g == failing_gate else GateStatus.PASSED)
            for g in MANDATORY_GATES
        },
    )
    assert not verdict.promotable, f"{failing_gate} failure must block promotion"
    assert verdict.blocking_gates == (failing_gate,)
    assert failing_gate in verdict.denied_reason


def test_a_gate_that_did_not_run_blocks(scope):
    """Absence of evidence is never a pass."""
    verdict = CodeChangeGatekeeper().evaluate(
        make_proposal(scope),
        gate_results={g: GateStatus.PASSED for g in MANDATORY_GATES[:-1]},
    )
    assert not verdict.promotable
    assert verdict.blocking_gates == ("promotion_authorization",)


# ── Gate 26: the self-modification boundary ──────────────────────────────────


@pytest.mark.parametrize("path", sorted(PROTECTED_PATHS))
def test_every_protected_path_is_denied(scope, path):
    """AUTOMATIC LEARNING PROMOTION = DENIED for every protected component."""
    proposal = make_proposal(scope, paths=("src/app.py", path))
    assert proposal.touches_protected_path
    with pytest.raises(CodeChangeRefused, match="DENIED"):
        CodeChangeGatekeeper().assert_permitted(proposal)


def test_a_security_file_change_is_denied(scope):
    proposal = make_proposal(
        scope, paths=("packages/security/src/autoforge_security/ai_guardrails.py",)
    )
    with pytest.raises(CodeChangeRefused):
        CodeChangeGatekeeper().assert_permitted(proposal)


def test_the_learning_authority_model_is_protected(scope):
    """Learning cannot rewrite its own authority model."""
    for path in (
        "packages/learning/src/autoforge_learning/gateway.py",
        "packages/learning/src/autoforge_learning/promotion.py",
        "packages/learning/src/autoforge_learning/approval.py",
        "packages/learning/src/autoforge_learning/invariants.py",
    ):
        with pytest.raises(CodeChangeRefused):
            CodeChangeGatekeeper().assert_permitted(
                make_proposal(scope, paths=(path,))
            )


def test_protected_paths_are_denied_even_when_every_gate_would_pass(scope):
    """The boundary is evaluated before scoring, so it cannot be outvoted."""
    proposal = make_proposal(scope, paths=("packages/security/src/x.py",))
    with pytest.raises(CodeChangeRefused):
        CodeChangeGatekeeper().evaluate(proposal, gate_results=all_passed())


def test_an_ordinary_path_is_permitted(scope):
    CodeChangeGatekeeper().assert_permitted(
        make_proposal(scope, paths=("src/util.py",))
    )


def test_a_proposal_cannot_reclassify_its_own_paths(scope):
    """There is no parameter through which a proposal hides a protected path."""
    with pytest.raises(Exception):
        CodeChangeProposal(
            scope=scope,
            summary="s",
            diff="d",
            touched_paths=("packages/security/src/x.py",),
            base_content_hash="a" * 64,
            proposed_content_hash="b" * 64,
            isolated_workspace="/tmp/ws",
            touches_protected_path=False,  # type: ignore[call-arg]
        )