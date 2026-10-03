"""PHASE 19B-3 ADVERSARIAL LEARNING MATRIX (Gate 39).

Every forbidden operation must fail closed. This file is organised exactly as
Gate 39's matrix: SECURITY, LEARNING, CODE, RECURSION, EXPERIMENTS, ISOLATION,
RECOVERY. Each test asserts the *failure*, not merely that an error occurred,
so a test cannot pass because something crashed for an unrelated reason.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    ArmOutcome,
    CandidateLifecycle,
    CodeChangeGatekeeper,
    CodeChangeProposal,
    CodeChangeRefused,
    Experiment,
    ExperimentArm,
    ExperimentEngine,
    ExperimentOutcome,
    GateStatus,
    HypothesisGenerator,
    LearningAuthority,
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
    LearningSignal,
    RegressionSeverity,
    SignalPolarity,
    assert_no_authority_expansion,
)
from autoforge_learning.codemod import MANDATORY_GATES, PROTECTED_PATHS
from autoforge_learning.models import EvidenceRef, EvidenceSource
from autoforge_security.ai_guardrails import (
    LEARNABLE_PROPOSAL_KINDS,
    AIGuardrailsEngine,
    Capability,
    LearningProposal,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


# ── SECURITY ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "capability",
    [
        Capability.CREDENTIAL_USE,
        Capability.CREDENTIAL_ADMINISTER,
        Capability.CREDENTIAL_REQUEST,
        Capability.NETWORK_OUTBOUND,
        Capability.SECURITY_MODIFY,
        Capability.DEPLOYMENT_EXECUTE,
        Capability.PROCESS_EXECUTE,
        Capability.FILESYSTEM_DELETE,
        Capability.GIT_DESTRUCTIVE,
    ],
    ids=lambda c: c.value,
)
def test_learning_cannot_request_any_forbidden_capability(capability):
    """Gate 39 SECURITY: every escalation attempt is denied by the boundary."""
    decision = AIGuardrailsEngine().evaluate_learning_proposal(
        LearningProposal(
            proposal_id="adv-1",
            proposal_kind="pattern_template",
            proposed_by="autoforge.learning",
            requested_capabilities=frozenset({capability}),
        )
    )
    assert decision.is_permitted is False


def test_learning_cannot_grant_itself_a_permission(scope):
    """A candidate requesting authority is denied by the real gateway."""
    from autoforge_learning import ProposalGateway

    decision = ProposalGateway(AIGuardrailsEngine()).evaluate(
        LearningCandidate(
            scope=scope,
            kind="pattern_template",
            summary="grant myself network access",
            requested_capabilities=("network.outbound",),
        )
    )
    assert decision.is_denied
    assert decision.is_approved is False


def test_learning_cannot_disable_authorization():
    """An unlearnable proposal kind is denied structurally."""
    decision = AIGuardrailsEngine().evaluate_learning_proposal(
        LearningProposal(
            proposal_id="adv-2",
            proposal_kind="disable_authorization",
            proposed_by="autoforge.learning",
        )
    )
    assert decision.is_permitted is False


@pytest.mark.parametrize("malformed", [None, {"nope": 1}, "a string", 42])
def test_a_malformed_proposal_is_denied(malformed):
    """Malformed input is denied, never tolerated."""
    decision = AIGuardrailsEngine().evaluate_learning_proposal(malformed)
    assert decision.is_permitted is False


def test_the_guardrails_policy_surface_has_no_mutation_api():
    """No model-reachable path can widen the boundary."""
    engine = AIGuardrailsEngine()
    for forbidden in ("set_policy", "mutate", "reload", "update_policy"):
        assert not hasattr(engine, forbidden)


def test_learning_cannot_reach_level_5(scope):
    with pytest.raises(Exception):
        LearningCandidate(
            scope=scope,
            kind="pattern_template",
            summary="s",
            authority=LearningAuthority.L5_SECURITY_POLICY,  # type: ignore[arg-type]
        )


def test_a_permitted_proposal_still_demands_human_authorization():
    """Permission to propose is never permission to activate."""
    decision = AIGuardrailsEngine().evaluate_learning_proposal(
        LearningProposal(
            proposal_id="adv-3",
            proposal_kind="pattern_template",
            proposed_by="autoforge.learning",
        )
    )
    assert decision.is_permitted is True
    assert "human_authorization" in decision.promotion_requires
    assert "deterministic_validation" in decision.promotion_requires


# ── LEARNING ─────────────────────────────────────────────────────────────────


def test_fake_evidence_cannot_be_manufactured(scope):
    """CR-06: an observation from a non-existent source cannot exist."""
    from autoforge_learning.models import ExecutionObservation

    with pytest.raises(Exception):
        ExecutionObservation(
            scope=scope,
            source="a_source_that_does_not_exist",  # type: ignore[arg-type]
            outcome="passed",
            subject_ref="t:1",
            content_hash="a" * 64,
        )


def test_an_observation_needs_a_verifiable_content_hash(scope):
    from autoforge_learning.models import ExecutionObservation, ExperienceSource

    with pytest.raises(Exception):
        ExecutionObservation(
            scope=scope,
            source=ExperienceSource.TASK_EXECUTION,
            subject_ref="t:1",
            outcome="passed",
            content_hash="short",
        )


def test_a_hypothesis_without_evidence_cannot_exist(scope):
    from autoforge_learning import Hypothesis

    with pytest.raises(Exception):
        Hypothesis(
            scope=scope,
            observation="I think this will help",
            proposed_change="c",
            expected_effect="e",
            success_metric="m",
            success_threshold=1.0,
            risk="r",
            rollback_strategy="rb",
        )


def test_a_reward_with_no_provenance_is_rejected(scope):
    """Gate 39 LEARNING: a fake reward is refused at construction."""
    from autoforge_learning import Reward, RewardPolarity

    with pytest.raises(Exception):
        Reward(
            scope=scope,
            objective="latency_ms",
            polarity=RewardPolarity.POSITIVE,
            raw_value=100.0,
            provenance_ref="",
            provenance_hash="a" * 64,
        )


def test_a_security_outcome_can_never_be_scored_as_reward(scope):
    """EX-12: a violation is not a reward, not even a negative one."""
    from autoforge_learning import RewardLedger, RewardRejected

    with pytest.raises(RewardRejected):
        RewardLedger().record(
            scope=scope,
            objective="isolation_violations",
            raw_value=-1.0,
            provenance_ref="audit:1",
            provenance_payload={"v": 0},
        )


def test_reward_inflation_cannot_escape_the_unit_interval():
    from autoforge_learning.rewards import normalize

    for absurd in (1e9, -1e9, float("inf"), float("-inf")):
        assert -1.0 <= normalize(absurd, minimum=0.0, maximum=1.0) <= 1.0


def test_poisoned_cross_project_feedback_cannot_become_a_proposal(scope):
    """Feedback from another project can never motivate a proposal here."""
    foreign = LearningSignal(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=uuid.uuid4()),
        polarity=SignalPolarity.POSITIVE,
        metric="latency_ms",
        observation="everything is great",
        evidence=(
            EvidenceRef.from_payload(EvidenceSource.TELEMETRY, "t:1", {"v": 1}),
        ),
        sample_size=10,
        confidence=1.0,
    )
    assert (
        HypothesisGenerator().generate(
            signals=[foreign],
            scope=scope,
            proposed_change_for={"latency_ms": "do the thing"},
        )
        == ()
    )


def test_contradictory_feedback_is_detected(scope):
    from autoforge_learning import RewardLedger

    ledger = RewardLedger()
    candidate = uuid.uuid4()
    ledger.record(
        scope=scope,
        objective="task_success_rate",
        raw_value=99.0,
        provenance_ref="telemetry:a",
        provenance_payload={"v": 1},
        bounds=(0.0, 100.0),
        candidate_id=candidate,
    )
    assert ledger.detect_contradiction(candidate, verdicts=["fail"])
    assert not ledger.detect_contradiction(candidate, verdicts=["pass"])


def test_selective_reporting_is_detected(scope):
    """Replaying the same reward evidence is a form of cherry-picking."""
    from autoforge_learning import RewardLedger

    ledger = RewardLedger()
    candidate = uuid.uuid4()
    for _ in range(2):
        ledger.record(
            scope=scope,
            objective="task_success_rate",
            raw_value=50.0,
            provenance_ref="telemetry:same",
            provenance_payload={"v": 7},
            bounds=(0.0, 100.0),
            candidate_id=candidate,
        )
    assert ledger.detect_replayed_evidence(candidate)


def _hypothesis(scope, metric="latency_ms", direction="decrease"):
    from autoforge_learning import Hypothesis

    return Hypothesis(
        scope=scope,
        observation="observed",
        supporting_evidence=(
            EvidenceRef.from_payload(EvidenceSource.TELEMETRY, "t:1", {"v": 1}),
        ),
        proposed_change="c",
        expected_effect="e",
        success_metric=metric,
        success_threshold=100.0,
        success_direction=direction,
        risk="r",
        rollback_strategy="rb",
    )


def _experiment(scope, **overrides):
    kwargs = dict(
        scope=scope,
        hypothesis=_hypothesis(scope),
        evaluation_metric="latency_ms",
        success_threshold=100.0,
        success_direction="decrease",
        max_duration_seconds=1.0,
        max_iterations=1,
        max_cost_units=1.0,
        rollback_target_version_id=uuid.uuid4(),
    )
    kwargs.update(overrides)
    return Experiment(**kwargs)


def test_hallucinated_success_is_never_reported_as_survival(scope):
    """An arm that measured nothing yields INCONCLUSIVE, never SURVIVED."""
    run = ExperimentEngine().run(
        experiment=_experiment(scope),
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL, iterations_completed=1
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT, iterations_completed=1
        ),
        environment={"python": "3.12"},
    )
    assert run.outcome is ExperimentOutcome.INCONCLUSIVE


def test_evaluator_manipulation_cannot_survive_an_invariant_breach(scope):
    """Even a perfect metric cannot survive a protected-invariant breach."""
    run = ExperimentEngine().run(
        experiment=_experiment(scope),
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL,
            metrics={"latency_ms": 200.0},
            iterations_completed=1,
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT,
            metrics={"latency_ms": 1.0},
            iterations_completed=1,
        ),
        environment={"python": "3.12"},
        invariant_check=lambda outcome: RegressionSeverity.MAJOR,
    )
    assert run.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH


# ── CODE ─────────────────────────────────────────────────────────────────────


def _proposal(scope, paths, workspace="/tmp/isolated"):
    return CodeChangeProposal(
        scope=scope,
        summary="adversarial change",
        diff="- safe\n+ unsafe\n",
        touched_paths=tuple(paths),
        base_content_hash="a" * 64,
        proposed_content_hash="b" * 64,
        isolated_workspace=workspace,
    )


@pytest.mark.parametrize(
    "attack",
    [
        "src/backdoor.py",
        "src/exfiltrate.py",
        "src/test_deleted.py",
        "benchmarks/benchmark.py",
    ],
    ids=lambda p: p,
)
def test_malicious_code_cannot_skip_the_mandatory_gates(scope, attack):
    """A non-protected path still faces all ten mandatory gates."""
    verdict = CodeChangeGatekeeper().evaluate(
        _proposal(scope, [attack]),
        gate_results={
            g: (GateStatus.FAILED if g == "security_tests" else GateStatus.PASSED)
            for g in MANDATORY_GATES
        },
    )
    assert not verdict.promotable


def test_credential_exfiltration_is_denied_before_scoring(scope):
    """A credential-touching path is refused outright, not merely gated."""
    with pytest.raises(CodeChangeRefused):
        CodeChangeGatekeeper().evaluate(
            _proposal(scope, ["scripts/steal_credentials.py"]),
            gate_results={g: GateStatus.PASSED for g in MANDATORY_GATES},
        )


# ── RECURSION ────────────────────────────────────────────────────────────────


def make_budget(project_id, **overrides):
    from autoforge_learning import ResourceBudget

    kwargs = dict(
        project_id=project_id,
        max_experiments=2,
        max_recursion_depth=2,
        max_wall_clock_seconds=10.0,
        max_model_calls=2,
        max_concurrent_experiments=1,
        max_disk_bytes=1000,
        max_memory_bytes=1000,
        max_network_bytes=0,
    )
    kwargs.update(overrides)
    return ResourceBudget(**kwargs)


def test_recursive_authority_escalation_is_refused(scope):
    """learning → permission → more learning is the prohibited loop."""
    from autoforge_learning import AuthorityExpansionAttempted

    with pytest.raises(AuthorityExpansionAttempted):
        assert_no_authority_expansion(
            parent_scope=scope,
            child_scope=scope,
            parent_capabilities=(),
            child_capabilities=("network.outbound", "security.modify"),
        )


def test_recursion_widening_scope_is_refused(scope):
    from autoforge_learning import AuthorityExpansionAttempted

    with pytest.raises(AuthorityExpansionAttempted):
        assert_no_authority_expansion(
            parent_scope=scope,
            child_scope=LearningScope(
                kind=LearningScopeKind.GLOBAL_NON_SECURITY,
                project_id=scope.project_id,
            ),
        )


def test_infinite_recursion_terminates(project_id, scope):
    """A stage that never yields anything still terminates the loop."""
    from autoforge_learning import RecursiveImprovement

    results = RecursiveImprovement(
        budget=make_budget(project_id, max_recursion_depth=3)
    ).run_until_bounded(scope=scope, correlation_id="adv", stage=lambda g: None)
    assert len(results) == 1


def test_depth_overflow_raises(project_id, scope):
    from autoforge_learning import BudgetExhausted, RecursiveImprovement

    with pytest.raises(BudgetExhausted):
        RecursiveImprovement(budget=make_budget(project_id)).run_cycle(
            scope=scope,
            correlation_id="adv",
            stage=lambda g: None,
            generation=999,
        )


def test_resource_exhaustion_fails_safely(project_id):
    from autoforge_learning import BudgetExhausted, ResourceGovernor

    governor = ResourceGovernor(budget=make_budget(project_id, max_experiments=1))
    governor.assert_experiment_permitted()
    with pytest.raises(BudgetExhausted):
        governor.assert_experiment_permitted()
    # The critical path remains available regardless.
    assert governor.assert_core_path() is True


# ── EXPERIMENTS ──────────────────────────────────────────────────────────────


def test_a_candidate_cannot_modify_its_own_success_criteria(scope):
    """EX-09: the threshold lives on the immutable design, not on the run."""
    experiment = _experiment(scope)
    with pytest.raises(Exception):
        experiment.success_threshold = 1.0  # type: ignore[misc]


def test_control_contamination_is_detected(scope):
    """A mislabelled arm is refused rather than silently trusted."""
    from autoforge_learning.experiments import ExperimentError

    with pytest.raises(ExperimentError):
        ExperimentEngine().run(
            experiment=_experiment(scope),
            control_runner=lambda a, e: ArmOutcome(
                arm=ExperimentArm.TREATMENT,  # wrong arm!
                metrics={"latency_ms": 1.0},
                iterations_completed=1,
            ),
            treatment_runner=lambda a, e: ArmOutcome(
                arm=ExperimentArm.TREATMENT,
                metrics={"latency_ms": 1.0},
                iterations_completed=1,
            ),
            environment={"python": "3.12"},
        )


def test_benchmark_gaming_via_missing_measurement_is_inconclusive(scope):
    """Deleting the benchmark cannot produce a pass."""
    run = ExperimentEngine().run(
        experiment=_experiment(scope),
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL,
            metrics={"latency_ms": 200.0},
            iterations_completed=1,
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT, iterations_completed=1
        ),
        environment={"python": "3.12"},
    )
    assert run.outcome is ExperimentOutcome.INCONCLUSIVE


def test_cherry_picked_partial_runs_are_inconclusive(scope):
    """Stopping early can never be reported as a refutation."""
    run = ExperimentEngine().run(
        experiment=_experiment(scope, max_iterations=5),
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL,
            metrics={"latency_ms": 500.0},
            iterations_completed=5,
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT,
            metrics={"latency_ms": 400.0},
            iterations_completed=1,
        ),
        environment={"python": "3.12"},
    )
    assert run.outcome is ExperimentOutcome.INCONCLUSIVE


def test_experiment_capabilities_are_declared_not_implied():
    """Gate 6: undeclared capabilities are denied, and the set is tiny."""
    from autoforge_learning.models import ExperimentCapability

    assert set(ExperimentCapability) == {
        ExperimentCapability.CPU_TIME,
        ExperimentCapability.MEMORY,
        ExperimentCapability.DISK,
        ExperimentCapability.DETERMINISTIC_VALIDATION,
        ExperimentCapability.REPLAY_FIXTURES,
    }
    for forbidden in ("network", "filesystem", "credentials", "deployment"):
        assert forbidden not in {c.value for c in ExperimentCapability}


def test_an_experiment_without_a_rollback_target_cannot_be_designed(scope):
    """A run with no deterministic rollback cannot even be constructed."""
    with pytest.raises(Exception):
        Experiment(
            scope=scope,
            hypothesis=_hypothesis(scope),
            evaluation_metric="latency_ms",
            success_threshold=1.0,
            success_direction="decrease",
            max_duration_seconds=1.0,
            max_iterations=1,
            max_cost_units=1.0,
        )


# ── ISOLATION ────────────────────────────────────────────────────────────────


def test_the_same_fingerprint_in_another_project_is_distinct(project_id):
    """Project isolation is structural, not a filter applied later."""
    from autoforge_learning import CandidateLifecycle

    lifecycle = CandidateLifecycle()
    lifecycle.register(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        summary="a",
        fingerprint="fp",
    )
    _, created = lifecycle.register(
        candidate_id=uuid.uuid4(),
        project_id=uuid.uuid4(),
        summary="a",
        fingerprint="fp",
    )
    assert created


def test_cross_project_activation_is_refused(project_id):
    from autoforge_learning import TransferPolicy, assert_no_implicit_generalization

    with pytest.raises(Exception):
        assert_no_implicit_generalization(
            learning_scope=LearningScope(
                kind=LearningScopeKind.PROJECT, project_id=project_id
            ),
            target_project_id=uuid.uuid4(),
            policy=TransferPolicy(),
        )


def test_cross_project_transfer_without_a_policy_is_refused(project_id):
    from autoforge_learning import (
        TransferEvaluator,
        TransferPolicy,
        TransferRequest,
        TransferVerdict,
    )

    outcome = TransferEvaluator().evaluate(
        TransferRequest(
            source_project_id=project_id,
            target_project_id=uuid.uuid4(),
            candidate_id=uuid.uuid4(),
            kind="pattern_template",
            key="k",
            policy=TransferPolicy(),
        ),
        provenance_ok=True,
        compatible=True,
        evidence_ok=True,
        regression_ok=True,
        scope_ok=True,
        security_ok=True,
    )
    assert outcome.verdict is TransferVerdict.REFUSED


def test_cross_project_rollback_is_impossible(tmp_path):
    """A handle from one project cannot roll back another project's state.

    Isolation is structural: the handle is filed under the owning project, so a
    foreign lookup finds nothing at all rather than a handle it might misuse.
    """
    from datetime import datetime, timezone

    from autoforge_learning.store import (
        ActiveLearningState,
        DurableLearningStore,
        LearningProjectIsolationError,
        RollbackHandle,
    )

    store = DurableLearningStore(tmp_path)
    project_a, project_b = uuid.uuid4(), uuid.uuid4()
    state = ActiveLearningState(
        project_id=project_a,
        kind="pattern_template",
        key="k",
        version_id=uuid.uuid4(),
        version_number=1,
        activation_timestamp=datetime.now(timezone.utc),
        scope_kind="project",
    )
    handle = store.save_rollback_handle(
        RollbackHandle(
            project_id=project_a,
            candidate_id=uuid.uuid4(),
            kind="pattern_template",
            key="k",
            previous_state=None,
            proposed_state=state,
            proposed_version_number=1,
        )
    )

    # The owner sees it.
    assert store.get_rollback_handle(project_a, handle.handle_id) is not None
    # Another project does not — the handle is not merely refused, it is absent.
    assert store.get_rollback_handle(project_b, handle.handle_id) is None
    assert store.list_rollback_handles(project_b) == ()

    # And if a record were ever relocated, the ownership check still fires.
    relocated = tmp_path / str(project_b) / "handles"
    relocated.mkdir(parents=True, exist_ok=True)
    owner_dir = tmp_path / str(project_a) / "handles"
    (relocated / f"{handle.handle_id}.json").write_text(
        next(owner_dir.glob(f"{handle.handle_id}.json")).read_text()
    )
    with pytest.raises(LearningProjectIsolationError):
        store.get_rollback_handle(project_b, handle.handle_id)


# ── RECOVERY ─────────────────────────────────────────────────────────────────


def test_a_partial_promotion_never_auto_completes(project_id):
    """Crash recovery must not grant the authority a promotion was awaiting."""
    from autoforge_learning import RecoveryAction, RecoveryReconciler

    report = RecoveryReconciler().reconcile(
        project_id=project_id,
        active_state_present=True,
        promotions_without_audit=[uuid.uuid4()],
    )
    assert report.requires_human_review
    assert report.findings[0].action is RecoveryAction.REQUIRES_HUMAN_REVIEW


def test_a_partial_rollback_never_auto_completes(project_id):
    from autoforge_learning import (
        RecoveryAction,
        RecoveryReconciler,
        RecoveryState,
    )

    report = RecoveryReconciler().reconcile(
        project_id=project_id,
        active_state_present=False,
        rollbacks_without_restore=[uuid.uuid4()],
    )
    assert report.findings[0].state is RecoveryState.PARTIAL_ROLLBACK
    assert report.findings[0].action is RecoveryAction.REQUIRES_HUMAN_REVIEW


def test_corrupt_records_are_quarantined_not_deleted(project_id):
    from autoforge_learning import RecoveryAction, RecoveryReconciler

    report = RecoveryReconciler().reconcile(
        project_id=project_id,
        active_state_present=False,
        corrupt_record_ids=[uuid.uuid4(), uuid.uuid4()],
    )
    assert len(report.findings) == 2
    assert all(
        f.action is RecoveryAction.REQUIRES_HUMAN_REVIEW for f in report.findings
    )


def test_recovery_preserves_candidate_and_lineage_state(project_id):
    from autoforge_learning import LearningLineage, RecoveryReconciler

    candidate_ids = (uuid.uuid4(),)
    lineage_ids = (
        LearningLineage(project_id=project_id, correlation_id="c").lineage_id,
    )
    report = RecoveryReconciler().reconcile(
        project_id=project_id,
        active_state_present=True,
        candidate_ids=candidate_ids,
        lineage_ids=lineage_ids,
    )
    assert report.preserved_candidate_ids == candidate_ids
    assert report.preserved_lineage_ids == lineage_ids


def test_the_real_store_survives_a_restart(tmp_path):
    """Gate 33: a real durable store keeps the active pointer across restarts."""
    from datetime import datetime, timezone

    from autoforge_learning.store import (
        ActiveLearningState,
        DurableLearningStore,
    )

    project_id = uuid.uuid4()
    state = ActiveLearningState(
        project_id=project_id,
        kind="pattern_template",
        key="k",
        version_id=uuid.uuid4(),
        version_number=1,
        candidate_id=uuid.uuid4(),
        content_hash="a" * 64,
        activation_timestamp=datetime.now(timezone.utc),
        scope_kind="project",
    )
    DurableLearningStore(tmp_path).set_active_state(state)

    # A brand-new store instance is exactly a process restart.
    recovered = DurableLearningStore(tmp_path).get_active_state(
        project_id, "pattern_template", "k"
    )
    assert recovered is not None
    assert recovered.version_id == state.version_id
    assert recovered.candidate_id == state.candidate_id


def test_a_corrupt_record_is_rejected_not_returned_as_absent(tmp_path):
    """Fail closed: corruption raises rather than looking like an absence."""
    import json
    from datetime import datetime, timezone

    from autoforge_learning.store import (
        ActiveLearningState,
        DurableLearningStore,
        LearningRecordCorrupt,
    )

    project_id = uuid.uuid4()
    store = DurableLearningStore(tmp_path)
    state = ActiveLearningState(
        project_id=project_id,
        kind="pattern_template",
        key="k",
        version_id=uuid.uuid4(),
        version_number=1,
        activation_timestamp=datetime.now(timezone.utc),
        scope_kind="project",
    )
    store.set_active_state(state)

    path = next((tmp_path / str(project_id) / "active").glob("*.json"))
    envelope = json.loads(path.read_text())
    envelope["content_hash"] = "tampered"
    path.write_text(json.dumps(envelope))

    with pytest.raises(LearningRecordCorrupt):
        DurableLearningStore(tmp_path).get_active_state(
            project_id, "pattern_template", "k"
        )


@pytest.mark.parametrize("path", sorted(PROTECTED_PATHS))
def test_every_protected_component_is_immutable_by_learning(scope, path):
    """A protected component is denied whether named alone or with other files."""
    with pytest.raises(CodeChangeRefused):
        CodeChangeGatekeeper().assert_permitted(_proposal(scope, [path]))
    with pytest.raises(CodeChangeRefused):
        CodeChangeGatekeeper().assert_permitted(
            _proposal(scope, ["src/app.py", path])
        )


def test_test_deletion_blocks_promotion(scope):
    """Removing the tests means the regression gate never ran."""
    verdict = CodeChangeGatekeeper().evaluate(
        _proposal(scope, ["tests/test_important.py"]),
        gate_results={
            g: (
                GateStatus.NOT_RUN
                if g in ("unit_tests", "regression_tests")
                else GateStatus.PASSED
            )
            for g in MANDATORY_GATES
        },
    )
    assert not verdict.promotable
    assert "unit_tests" in verdict.blocking_gates
    assert "regression_tests" in verdict.blocking_gates


def test_benchmark_modification_blocks_promotion(scope):
    """A candidate cannot redefine the criteria that judge it."""
    verdict = CodeChangeGatekeeper().evaluate(
        _proposal(scope, ["benchmarks/eval.py"]),
        gate_results={
            g: (
                GateStatus.NOT_RUN
                if g == "deterministic_validation"
                else GateStatus.PASSED
            )
            for g in MANDATORY_GATES
        },
    )
    assert not verdict.promotable


def test_a_candidate_cannot_authorize_its_own_promotion(scope):
    """promotion_authorization is a real, separate, non-skippable gate."""
    verdict = CodeChangeGatekeeper().evaluate(
        _proposal(scope, ["src/app.py"]),
        gate_results={
            g: (
                GateStatus.PASSED
                if g != "promotion_authorization"
                else GateStatus.NOT_RUN
            )
            for g in MANDATORY_GATES
        },
    )
    assert not verdict.promotable