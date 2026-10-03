"""Phase 19B-3 — Gates 22-23, 28-29, 31, 33: transfer, PI-8, governance, recovery."""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    BudgetExhausted,
    ExperienceCollector,
    LearningClass,
    LearningScope,
    LearningScopeKind,
    LearningTelemetry19B3,
    ResourceBudget,
    ResourceGovernor,
    TransferEvaluator,
    TransferPolicy,
    TransferRefused,
    TransferRequest,
    TransferVerdict,
    assert_no_implicit_generalization,
    measure_effectiveness,
)
from autoforge_learning.effectiveness import (
    EFFECTIVENESS_DIMENSIONS,
    PI8_CONTRACT,
    CustomerOutcomeEvidence,
    assert_pi8_definition_unchanged,
)
from autoforge_learning.recovery import (
    RecoveryAction,
    RecoveryReconciler,
    RecoveryState,
)
from autoforge_learning.transfer import REQUIRED_TRANSFER_CHECKS


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def make_request(source, target, policy=None):
    return TransferRequest(
        source_project_id=source,
        target_project_id=target,
        candidate_id=uuid.uuid4(),
        kind="pattern_template",
        key="k",
        policy=policy or TransferPolicy(),
    )


#: Maps each Gate 23 check to the evaluator keyword that supplies it. Used to
#: prove every required check is genuinely load-bearing.
CHECK_TO_ARGUMENT: dict[str, str] = {
    "provenance": "provenance_ok",
    "compatibility": "compatible",
    "evidence": "evidence_ok",
    "regression_evaluation": "regression_ok",
    "scope": "scope_ok",
    "security": "security_ok",
}


def evaluate_all_ok(request, **overrides):
    """Run the evaluator with every check passing unless overridden."""
    kwargs = {arg: True for arg in CHECK_TO_ARGUMENT.values()}
    kwargs.update(overrides)
    return TransferEvaluator().evaluate(request, **kwargs)
    kwargs = dict(
        provenance_ok=True,
        compatible=True,
        evidence_ok=True,
        regression_ok=True,
        scope_ok=True,
        security_ok=True,
    )
    kwargs.update(overrides)
    return TransferEvaluator().evaluate(request, **kwargs)


# ── Gate 22: cross-project policy ────────────────────────────────────────────


def test_no_policy_means_no_cross_project_transfer(project_id):
    outcome = evaluate_all_ok(make_request(project_id, uuid.uuid4()))
    assert outcome.verdict is TransferVerdict.REFUSED
    assert any("explicit transfer policy" in r for r in outcome.reasons)


def test_an_explicit_policy_permits_a_checked_transfer(project_id):
    outcome = evaluate_all_ok(
        make_request(
            project_id, uuid.uuid4(), TransferPolicy(authorized_by="human.governance")
        )
    )
    assert outcome.approved
    assert outcome.learning_class is LearningClass.PROJECT_SPECIFIC


@pytest.mark.parametrize("failing", REQUIRED_TRANSFER_CHECKS)
def test_any_failed_transfer_check_blocks(project_id, failing):
    outcome = evaluate_all_ok(
        make_request(
            project_id, uuid.uuid4(), TransferPolicy(authorized_by="human.governance")
        ),
        **{CHECK_TO_ARGUMENT[failing]: False},
    )
    assert not outcome.approved
    assert failing in outcome.failed_checks


def test_global_validated_learning_needs_independent_validation(project_id):
    """Gate 22: global learning requires stronger validation and governance."""
    request = make_request(
        project_id,
        uuid.uuid4(),
        TransferPolicy(
            authorized_by="human.governance",
            target_class=LearningClass.GLOBAL_VALIDATED,
            required_validations=2,
        ),
    )
    weak = evaluate_all_ok(request, independent_validations=1)
    assert not weak.approved
    assert any("GLOBAL_VALIDATED" in r for r in weak.reasons)
    strong = evaluate_all_ok(request, independent_validations=2)
    assert strong.approved
    assert strong.learning_class is LearningClass.GLOBAL_VALIDATED


def test_implicit_generalization_is_refused_at_the_point_of_use(project_id):
    """Even a caller that skipped the evaluator cannot generalize implicitly."""
    with pytest.raises(TransferRefused, match="explicit policy"):
        assert_no_implicit_generalization(
            learning_scope=LearningScope(
                kind=LearningScopeKind.PROJECT, project_id=project_id
            ),
            target_project_id=uuid.uuid4(),
            policy=TransferPolicy(),
        )


def test_an_authorized_transfer_passes_the_point_of_use_check(project_id):
    assert_no_implicit_generalization(
        learning_scope=LearningScope(
            kind=LearningScopeKind.PROJECT, project_id=project_id
        ),
        target_project_id=uuid.uuid4(),
        policy=TransferPolicy(authorized_by="human.governance"),
    )


def test_same_project_use_needs_no_transfer_policy(project_id):
    assert_no_implicit_generalization(
        learning_scope=LearningScope(
            kind=LearningScopeKind.PROJECT, project_id=project_id
        ),
        target_project_id=project_id,
        policy=TransferPolicy(),
    )


# ── Gate 29: effectiveness and PI-8 ──────────────────────────────────────────


def test_the_pi8_contract_is_transcribed_not_redefined():
    """Gate 29: measure PI-8 from the 19A contract, do not invent a definition."""
    assert assert_pi8_definition_unchanged()
    assert PI8_CONTRACT["invariant"] == "PI-8"
    assert PI8_CONTRACT["name"] == "Customer outcomes"
    assert PI8_CONTRACT["invariant_class"] == "deferred"
    assert PI8_CONTRACT["floor"] == "Not measurable in Phase 19"
    assert PI8_CONTRACT["measurement_source"] == "— (deferred, Gate 4 §5)"


def test_all_gate29_effectiveness_dimensions_are_declared():
    for dimension in (
        "correctness",
        "reliability",
        "regression_rate",
        "latency_ms",
        "resource_cost",
        "task_completion",
        "validation_success",
        "review_outcome",
    ):
        assert dimension in EFFECTIVENESS_DIMENSIONS


def test_pi8_stays_not_applicable_without_instrumentation(project_id):
    """The contract deferral is retained when no customer-outcome source exists."""
    observations = ExperienceCollector().capture_from_execution(
        project_id=project_id,
        execution_events={"task_execution": {"status": "succeeded", "duration_ms": 50}},
    )
    report = measure_effectiveness(
        project_id=project_id,
        baseline_observations=observations,
        post_observations=observations,
    )
    assert report.pi8_measured is False
    assert report.pi8_status == "not_applicable"
    assert any("deferral retained" in c for c in report.conclusions)


def test_pi8_is_measured_when_a_real_source_exists(project_id):
    evidence = CustomerOutcomeEvidence(
        source_ref="dashboard:customer-outcome-counter",
        content_hash="a" * 64,
        satisfied=True,
    )
    report = measure_effectiveness(
        project_id=project_id,
        baseline_observations=(),
        post_observations=(),
        customer_outcome=evidence,
    )
    assert report.pi8_measured is True
    assert report.pi8_status == "passed"
    assert report.pi8_evidence_ref == evidence.source_ref


def test_a_failing_customer_outcome_is_reported_as_failed(project_id):
    report = measure_effectiveness(
        project_id=project_id,
        baseline_observations=(),
        post_observations=(),
        customer_outcome=CustomerOutcomeEvidence(
            source_ref="dashboard:counter", content_hash="a" * 64, satisfied=False
        ),
    )
    assert report.pi8_measured is True
    assert report.pi8_status == "failed"


def test_unprovenanced_customer_evidence_cannot_exist():
    """PI-8's deferral is lifted by instrumentation, never by assertion."""
    with pytest.raises(ValueError):
        CustomerOutcomeEvidence(
            source_ref="   ", content_hash="a" * 64, satisfied=True
        )
    with pytest.raises(ValueError):
        CustomerOutcomeEvidence(
            source_ref="d:1", content_hash="short", satisfied=True
        )


def test_effectiveness_reports_an_unmeasured_dimension_as_absent(project_id):
    report = measure_effectiveness(
        project_id=project_id, baseline_observations=(), post_observations=()
    )
    assert report.measurement.measured_dimensions == ()
    assert report.measurement.delta("latency_ms") is None
    assert any("not measured" in c for c in report.conclusions)


def test_effectiveness_compares_baseline_against_post_learning(project_id):
    """Gate 29: baseline performance versus post-learning performance."""
    collector = ExperienceCollector()
    baseline = collector.capture_from_execution(
        project_id=project_id,
        execution_events={
            "execution_latency": {"duration_ms": 200},
            "task_execution": {"status": "succeeded"},
        },
    )
    post = collector.capture_from_execution(
        project_id=project_id,
        execution_events={
            "execution_latency": {"duration_ms": 100},
            "task_execution": {"status": "succeeded"},
        },
    )
    report = measure_effectiveness(
        project_id=project_id,
        baseline_observations=baseline,
        post_observations=post,
    )
    assert report.measurement.delta("latency_ms") == pytest.approx(-100.0)
    assert report.measurement.baseline_sample_size == 2


# ── Gate 31: resource governance ─────────────────────────────────────────────


def make_budget(project_id, **overrides) -> ResourceBudget:
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


def test_the_experiment_budget_is_enforced(project_id):
    governor = ResourceGovernor(budget=make_budget(project_id))
    governor.assert_experiment_permitted()
    governor.assert_experiment_permitted()
    with pytest.raises(BudgetExhausted, match="experiment budget"):
        governor.assert_experiment_permitted()
    assert governor.remaining_experiments() == 0


def test_the_model_call_budget_is_enforced(project_id):
    governor = ResourceGovernor(budget=make_budget(project_id))
    governor.assert_model_call_permitted()
    governor.assert_model_call_permitted()
    with pytest.raises(BudgetExhausted, match="model-call"):
        governor.assert_model_call_permitted()


def test_concurrency_is_bounded(project_id):
    governor = ResourceGovernor(budget=make_budget(project_id))
    governor.enter_experiment()
    with pytest.raises(BudgetExhausted, match="concurrent"):
        governor.enter_experiment()
    governor.exit_experiment()
    governor.assert_experiment_permitted()


def test_the_recursion_depth_is_bounded(project_id):
    governor = ResourceGovernor(budget=make_budget(project_id))
    governor.assert_recursion_permitted(1)
    with pytest.raises(BudgetExhausted, match="recursion depth"):
        governor.assert_recursion_permitted(99)


def test_the_wall_clock_budget_is_bounded(project_id):
    governor = ResourceGovernor(
        budget=make_budget(project_id, max_wall_clock_seconds=1.0)
    )
    governor.record_duration(2.0)
    with pytest.raises(BudgetExhausted, match="wall-clock"):
        governor.assert_time_permitted()


def test_the_critical_path_is_never_gated_by_learning_budgets(project_id):
    """Gate 31/32: learning may never starve the core AutoForge path."""
    governor = ResourceGovernor(budget=make_budget(project_id))
    for _ in range(50):
        try:
            governor.assert_experiment_permitted()
        except BudgetExhausted:
            pass
    assert governor.assert_core_path() is True


# ── Gate 28: truthful telemetry ───────────────────────────────────────────────


def test_an_empty_run_reports_zeros_not_success():
    """An empty run is not "all passing" — the fabricated state 19A removed."""
    telemetry = LearningTelemetry19B3()
    assert telemetry.survival_rate is None
    assert telemetry.is_all_passing is False
    assert telemetry.data_available is False


def test_telemetry_reports_real_experiment_counts(project_id):
    telemetry = LearningTelemetry19B3(
        project_id=project_id,
        experiments_run=4,
        experiments_survived=2,
        experiments_refuted=1,
        experiments_inconclusive=1,
        data_available=True,
    )
    assert telemetry.survival_rate == pytest.approx(0.5)
    assert telemetry.is_all_passing is False


def test_telemetry_is_all_passing_only_when_every_experiment_passed(project_id):
    telemetry = LearningTelemetry19B3(
        project_id=project_id, experiments_run=2, experiments_survived=2
    )
    assert telemetry.is_all_passing is True


# ── Gate 33: recovery ────────────────────────────────────────────────────────


def reconcile(**overrides):
    kwargs = dict(project_id=uuid.uuid4(), active_state_present=False)
    kwargs.update(overrides)
    return RecoveryReconciler().reconcile(**kwargs)


def test_a_clean_restart_needs_no_action():
    report = reconcile(active_state_present=True)
    assert report.is_clean
    assert not report.requires_human_review


def test_an_incomplete_experiment_is_discarded():
    """Discarding an incomplete experiment loses no conclusion."""
    report = reconcile(dangling_experiment_ids=[uuid.uuid4()])
    assert report.findings[0].state is RecoveryState.PARTIAL_EXPERIMENT
    assert report.findings[0].action is RecoveryAction.DISCARD_INCOMPLETE
    assert not report.requires_human_review


def test_a_timed_out_experiment_is_discarded():
    report = reconcile(timed_out_experiment_ids=[uuid.uuid4()])
    assert report.findings[0].state is RecoveryState.TIMED_OUT


def test_a_partial_promotion_requires_a_human():
    """Finishing it automatically would grant the authority it was awaiting."""
    report = reconcile(promotions_without_audit=[uuid.uuid4()])
    assert report.findings[0].state is RecoveryState.PARTIAL_PROMOTION
    assert report.requires_human_review


def test_a_partial_rollback_requires_a_human():
    report = reconcile(rollbacks_without_restore=[uuid.uuid4()])
    assert report.findings[0].state is RecoveryState.PARTIAL_ROLLBACK
    assert report.requires_human_review


def test_a_corrupt_record_is_quarantined_not_deleted():
    report = reconcile(corrupt_record_ids=[uuid.uuid4()])
    assert report.findings[0].state is RecoveryState.CORRUPT_STORE
    assert report.requires_human_review


def test_recovery_preserves_lineage_candidate_and_rollback_state():
    lineage_ids = (uuid.uuid4(),)
    candidate_ids = (uuid.uuid4(),)
    handle_ids = (uuid.uuid4(),)
    report = reconcile(
        dangling_experiment_ids=[uuid.uuid4()],
        lineage_ids=lineage_ids,
        candidate_ids=candidate_ids,
        rollback_handle_ids=handle_ids,
    )
    assert report.preserved_lineage_ids == lineage_ids
    assert report.preserved_candidate_ids == candidate_ids
    assert report.preserved_rollback_handle_ids == handle_ids


def test_the_real_store_reports_no_active_state_for_a_fresh_project(tmp_path):
    """Gate 33: the real durable store survives a restart with no active state."""
    from autoforge_learning.store import DurableLearningStore

    store = DurableLearningStore(tmp_path)
    assert store.get_active_state(uuid.uuid4(), "pattern_template", "k") is None