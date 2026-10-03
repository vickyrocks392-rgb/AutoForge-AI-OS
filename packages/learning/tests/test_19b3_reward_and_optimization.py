"""Phase 19B-3 — Gates 8, 9, 10, 25: reward, optimization, recursion."""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    BudgetExhausted,
    LearningScope,
    LearningScopeKind,
    ResourceBudget,
    Reward,
    RewardLedger,
    RewardRejected,
    RewardPolarity,
)
from autoforge_learning.optimization import (
    NEVER_OPTIMIZABLE,
    OPTIMIZABLE_TARGETS,
    BoundedOptimizer,
    OptimizationRefused,
    OptimizationStep,
    OptimizationTrace,
)
from autoforge_learning.recursion import (
    AuthorityExpansionAttempted,
    RecursiveImprovement,
    assert_no_authority_expansion,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


def make_budget(project_id: uuid.UUID, **overrides) -> ResourceBudget:
    kwargs = dict(
        project_id=project_id,
        max_experiments=5,
        max_recursion_depth=2,
        max_wall_clock_seconds=60.0,
        max_model_calls=5,
        max_concurrent_experiments=1,
        max_disk_bytes=1000,
        max_memory_bytes=1000,
        max_network_bytes=0,
    )
    kwargs.update(overrides)
    return ResourceBudget(**kwargs)


# ── Gate 8: deterministic validation outranks reward ──────────────────────────


def test_a_high_reward_does_not_override_a_validation_failure(scope):
    ledger = RewardLedger()
    reward = ledger.record(
        scope=scope,
        objective="task_success_rate",
        raw_value=95.0,
        provenance_ref="telemetry:run-1",
        provenance_payload={"success_rate": 0.95},
        bounds=(0.0, 100.0),
        confidence=1.0,
    )
    assert reward.normalized_value > 0
    clamped = ledger.aggregate([reward], deterministic_verdicts=["fail"])
    assert clamped.aggregate == 0.0
    assert clamped.clamped_by_determinism
    clean = ledger.aggregate([reward], deterministic_verdicts=["pass"])
    assert clean.aggregate == pytest.approx(reward.normalized_value)


def test_a_fabricated_reward_is_rejected(scope):
    with pytest.raises(RewardRejected, match="provenance"):
        RewardLedger().record(
            scope=scope,
            objective="latency_ms",
            raw_value=1.0,
            provenance_ref="   ",
            provenance_payload={"v": 1},
        )


def test_a_security_outcome_is_never_scored(scope):
    with pytest.raises(RewardRejected, match="protected"):
        RewardLedger().record(
            scope=scope,
            objective="security_violations",
            raw_value=-1.0,
            provenance_ref="audit:1",
            provenance_payload={"v": 0},
        )


def test_reward_carries_no_authority_field(scope):
    """Reward is not authority, structurally: there is nothing to exchange."""
    reward = Reward(
        scope=scope,
        objective="latency_ms",
        polarity=RewardPolarity.POSITIVE,
        raw_value=1.0,
        provenance_ref="t:1",
        provenance_hash="a" * 64,
    )
    forbidden = {
        "permission", "capability", "authority", "grant", "approve",
        "scope_kind", "trust_level",
    }
    assert not (forbidden & set(type(reward).model_fields))


def test_extra_authority_fields_are_rejected_at_parse_time(scope):
    """ISO-10: an artifact carrying unexpected authority fails validation."""
    with pytest.raises(Exception):
        Reward(
            scope=scope,
            objective="latency_ms",
            polarity=RewardPolarity.POSITIVE,
            raw_value=1.0,
            provenance_ref="t:1",
            provenance_hash="a" * 64,
            bypass_validation=True,  # type: ignore[call-arg]
        )


def test_inflation_is_detected(scope):
    ledger = RewardLedger()
    candidate = uuid.uuid4()
    for _ in range(3):
        ledger.record(
            scope=scope,
            objective="task_success_rate",
            raw_value=99.0,
            provenance_ref="telemetry:x",
            provenance_payload={"v": 1},
            bounds=(0.0, 100.0),
            candidate_id=candidate,
        )
    assert ledger.detect_inflation(candidate, ceiling=1.0)
    assert not ledger.detect_inflation(candidate, ceiling=100.0)


def test_contradiction_is_detected(scope):
    ledger = RewardLedger()
    candidate = uuid.uuid4()
    ledger.record(
        scope=scope,
        objective="task_success_rate",
        raw_value=99.0,
        provenance_ref="telemetry:x",
        provenance_payload={"v": 1},
        bounds=(0.0, 100.0),
        candidate_id=candidate,
    )
    assert ledger.detect_contradiction(candidate, verdicts=["fail"])
    assert not ledger.detect_contradiction(candidate, verdicts=["pass"])


def test_replayed_evidence_is_detected(scope):
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


def test_normalization_cannot_exceed_the_unit_interval():
    """An inflated input cannot produce an inflated *normalized* reward."""
    from autoforge_learning.rewards import normalize

    assert normalize(1e9, minimum=0.0, maximum=1.0) <= 1.0
    assert normalize(-1e9, minimum=0.0, maximum=1.0) >= -1.0
    assert normalize(5.0, minimum=5.0, maximum=5.0) == 0.0


def test_a_protected_metric_is_rejected_at_aggregation(scope):
    ledger = RewardLedger()
    forbidden = Reward(
        scope=scope,
        objective="security_violations",
        polarity=RewardPolarity.NEGATIVE,
        raw_value=-1.0,
        provenance_ref="audit:1",
        provenance_hash="a" * 64,
    )
    window = ledger.aggregate([forbidden])
    assert window.rewards == ()
    assert window.aggregate == 0.0
    assert window.rejections


def test_a_low_confidence_reward_is_excluded(scope):
    ledger = RewardLedger()
    weak = ledger.record(
        scope=scope,
        objective="task_success_rate",
        raw_value=99.0,
        provenance_ref="telemetry:x",
        provenance_payload={"v": 1},
        bounds=(0.0, 100.0),
        confidence=0.1,
    )
    window = ledger.aggregate([weak])
    assert window.rewards == ()
    assert window.rejections


# ── Gate 9: bounded optimization ──────────────────────────────────────────────


@pytest.mark.parametrize("target", sorted(NEVER_OPTIMIZABLE))
def test_every_permanently_forbidden_domain_is_refused(project_id, target):
    optimizer = BoundedOptimizer(
        budget=make_budget(project_id), project_id=project_id
    )
    with pytest.raises(OptimizationRefused, match="permanently"):
        optimizer.assert_optimizable(target)


def test_allow_list_and_deny_list_do_not_overlap():
    assert not (OPTIMIZABLE_TARGETS & NEVER_OPTIMIZABLE)


def test_an_unknown_domain_is_refused(project_id):
    optimizer = BoundedOptimizer(
        budget=make_budget(project_id), project_id=project_id
    )
    with pytest.raises(OptimizationRefused, match="not an approved"):
        optimizer.assert_optimizable("something_new")


def test_optimizer_only_accepts_a_measured_improvement(project_id):
    optimizer = BoundedOptimizer(
        budget=make_budget(project_id), project_id=project_id
    )
    trace = optimizer.optimize(
        target="prompt_strategy",
        current_value="a",
        candidates=["b", "c", "d"],
        score=lambda v: {"a": 0.1, "b": 0.5, "c": None, "d": 0.3}[v],
    )
    assert trace.best_value == "b"
    assert len(trace.steps) == 3
    assert [s.accepted for s in trace.steps] == [True, False, False]
    unmeasured = [s for s in trace.steps if s.to_value == "c"]
    assert unmeasured and not unmeasured[0].accepted


def test_optimizer_enforces_depth_and_experiment_budgets(project_id):
    optimizer = BoundedOptimizer(
        budget=make_budget(project_id), project_id=project_id
    )
    with pytest.raises(OptimizationRefused, match="recursion depth"):
        optimizer.optimize(
            target="prompt_strategy",
            current_value="a",
            candidates=["b"],
            score=lambda v: 1.0,
            generation=99,
        )
    with pytest.raises(OptimizationRefused, match="experiment budget"):
        optimizer.optimize(
            target="prompt_strategy",
            current_value="a",
            candidates=list("bcdefg"),
            score=lambda v: 1.0,
        )
# ── Gate 10: bounded recursion ───────────────────────────────────────────────


def make_trace(project_id: uuid.UUID, accepted: bool, generation: int):
    return OptimizationTrace(
        trace_id=uuid.uuid4(),
        project_id=project_id,
        target="prompt_strategy",
        steps=(
            OptimizationStep(
                step_id=uuid.uuid4(),
                generation=generation,
                target="prompt_strategy",
                from_value="a",
                to_value="b",
                accepted=accepted,
                reason="improved",
                measured_delta=0.1,
            ),
        ),
        best_value="b" if accepted else "a",
        best_score=0.5 if accepted else 0.1,
        generations_completed=generation + 1,
        terminated_because="candidate set exhausted",
    )


def test_recursion_terminates_at_the_declared_ceiling(project_id, scope):
    """A depth budget of N permits exactly N cycles, then stops."""
    budget = make_budget(project_id, max_recursion_depth=2)
    results = RecursiveImprovement(budget=budget).run_until_bounded(
        scope=scope, correlation_id="c1",
        stage=lambda g: make_trace(project_id, True, g),
    )
    assert [r.generation for r in results] == [0, 1]
    assert len(results) == budget.max_recursion_depth


def test_recursion_stops_when_nothing_improves(project_id, scope):
    engine = RecursiveImprovement(budget=make_budget(project_id))
    results = engine.run_until_bounded(
        scope=scope, correlation_id="c2",
        stage=lambda g: make_trace(project_id, False, g),
    )
    assert len(results) == 1


def test_recursion_stops_when_the_stage_yields_nothing(project_id, scope):
    engine = RecursiveImprovement(budget=make_budget(project_id))
    results = engine.run_until_bounded(
        scope=scope, correlation_id="c3", stage=lambda g: None
    )
    assert len(results) == 1


def test_exceeding_the_depth_budget_raises(project_id, scope):
    with pytest.raises(BudgetExhausted):
        RecursiveImprovement(budget=make_budget(project_id)).run_cycle(
            scope=scope,
            correlation_id="c4",
            stage=lambda g: make_trace(project_id, True, g),
            generation=99,
        )


def test_the_experiment_budget_bounds_the_loop(project_id, scope):
    engine = RecursiveImprovement(
        budget=make_budget(project_id, max_experiments=1, max_recursion_depth=5)
    )
    results = engine.run_until_bounded(
        scope=scope, correlation_id="c5",
        stage=lambda g: make_trace(project_id, True, g),
    )
    assert len(results) == 1


def test_recursion_records_lineage_between_generations(project_id, scope):
    engine = RecursiveImprovement(budget=make_budget(project_id))
    results = engine.run_until_bounded(
        scope=scope, correlation_id="c6",
        stage=lambda g: make_trace(project_id, True, g),
    )
    assert results[0].lineage.parent_lineage_id is None
    for previous, current in zip(results, results[1:]):
        assert current.lineage.parent_lineage_id == previous.lineage.lineage_id
        assert current.lineage.generation == previous.lineage.generation + 1


def test_scope_widening_is_refused(project_id):
    with pytest.raises(AuthorityExpansionAttempted, match="scope kind"):
        assert_no_authority_expansion(
            parent_scope=LearningScope(
                kind=LearningScopeKind.PROJECT, project_id=project_id
            ),
            child_scope=LearningScope(
                kind=LearningScopeKind.GLOBAL_NON_SECURITY, project_id=project_id
            ),
        )


def test_capability_gain_is_refused(project_id):
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    with pytest.raises(AuthorityExpansionAttempted, match="capabilities"):
        assert_no_authority_expansion(
            parent_scope=scope,
            child_scope=scope,
            child_capabilities=("network.outbound",),
        )


def test_cross_project_recursion_is_refused(project_id):
    with pytest.raises(AuthorityExpansionAttempted, match="project scope"):
        assert_no_authority_expansion(
            parent_scope=LearningScope(
                kind=LearningScopeKind.PROJECT, project_id=project_id
            ),
            child_scope=LearningScope(
                kind=LearningScopeKind.PROJECT, project_id=uuid.uuid4()
            ),
        )