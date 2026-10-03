"""Phase 19B-3 — Gates 14-18: activation, shadow, monitoring, rollback."""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    ActivationMode,
    ActivationState,
    LearningOverlay,
    RegressionReport,
    RegressionSeverity,
)
from autoforge_learning.activation import ActivationError, ActivationService
from autoforge_learning.monitoring import (
    CATASTROPHIC_CONDITIONS,
    RegressionMonitor,
    RegressionPolicy,
    enforce,
)


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def activate(service, project_id, mode, candidate=None, key="k"):
    return service.activate(
        candidate_id=candidate or uuid.uuid4(),
        project_id=project_id,
        kind="pattern_template",
        key=key,
        mode=mode,
    )


# ── Gate 14: activation is separate from promotion ────────────────────────────


def test_promoted_and_active_are_separate_states():
    """A promoted candidate may legitimately be inactive during a rollout."""
    assert ActivationState.INACTIVE is not ActivationState.FULL
    assert set(ActivationState) == {
        ActivationState.INACTIVE,
        ActivationState.SHADOW,
        ActivationState.CANARY,
        ActivationState.LIMITED,
        ActivationState.FULL,
        ActivationState.DEACTIVATED,
        ActivationState.ROLLED_BACK,
    }


def test_shadow_activation_receives_no_traffic(project_id):
    transition = activate(ActivationService(), project_id, ActivationMode.SHADOW)
    assert transition.record.state is ActivationState.SHADOW
    assert transition.record.traffic_fraction == 0.0
    assert transition.record.affects_behaviour is False


def test_traffic_increases_monotonically_across_the_rollout(project_id):
    service = ActivationService()
    fractions = [
        activate(service, project_id, mode).record.traffic_fraction
        for mode in (
            ActivationMode.SHADOW,
            ActivationMode.CANARY,
            ActivationMode.LIMITED,
            ActivationMode.FULL,
        )
    ]
    assert fractions == sorted(fractions)
    assert fractions[0] == 0.0
    assert fractions[-1] == 1.0
    assert len(service.history) == 4


def test_demoting_live_traffic_is_refused(project_id):
    """Changing behaviour under running executions is never silent."""
    service = ActivationService()
    candidate = uuid.uuid4()
    activate(service, project_id, ActivationMode.FULL, candidate=candidate)
    with pytest.raises(ActivationError, match="deactivate"):
        activate(service, project_id, ActivationMode.SHADOW, candidate=candidate)


def test_deactivation_stops_behaviour_and_keeps_history(project_id):
    service = ActivationService()
    candidate = uuid.uuid4()
    activate(service, project_id, ActivationMode.FULL, candidate=candidate)
    transition = service.deactivate(
        candidate_id=candidate,
        project_id=project_id,
        kind="pattern_template",
        key="k",
        reason="regression",
    )
    assert transition.record.state is ActivationState.DEACTIVATED
    assert transition.record.affects_behaviour is False
    assert len(service.history) == 2, "deactivation must not erase history"


def test_activation_is_project_scoped(project_id):
    service = ActivationService()
    candidate = uuid.uuid4()
    activate(service, project_id, ActivationMode.FULL, candidate=candidate)
    assert (
        service.current(
            candidate_id=candidate,
            project_id=uuid.uuid4(),
            kind="pattern_template",
            key="k",
        )
        is None
    )


# ── Gate 15: shadow evaluation ────────────────────────────────────────────────


def test_shadow_never_becomes_the_authoritative_outcome():
    comparison = ActivationService().shadow_compare(
        execution_id=uuid.uuid4(),
        baseline_outcome="baseline-correct",
        shadow_runner=lambda: "candidate-different",
    )
    assert comparison.baseline_outcome == "baseline-correct"
    assert comparison.authoritative_source == "baseline"
    assert not comparison.agreed


def test_a_shadow_failure_does_not_break_the_execution():
    def broken():
        raise RuntimeError("shadow exploded")

    comparison = ActivationService().shadow_compare(
        execution_id=uuid.uuid4(), baseline_outcome="ok", shadow_runner=broken
    )
    assert comparison.baseline_outcome == "ok"
    assert "shadow_error" in comparison.shadow_outcome


# ── Gate 16: deterministic regression detection ──────────────────────────────


def make_policy(**overrides) -> RegressionPolicy:
    kwargs = dict(
        thresholds={"latency_ms": (200.0, True)},
        tracked_invariants=("PI-5",),
        min_sample_size=1,
    )
    kwargs.update(overrides)
    return RegressionPolicy(**kwargs)


def monitor(project_id, **overrides):
    kwargs = dict(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        kind="pattern_template",
        key="k",
        policy=make_policy(),
        measurements={"latency_ms": 100.0},
        invariant_verdicts={"PI-5": "pass"},
        sample_size=5,
    )
    kwargs.update(overrides)
    return RegressionMonitor().evaluate(**kwargs)


def test_measurements_within_threshold_report_no_regression(project_id):
    report = monitor(project_id)
    assert report.severity is RegressionSeverity.NONE
    assert not report.is_regression
    assert not report.auto_rollback_permitted


def test_a_breached_threshold_is_a_minor_regression(project_id):
    report = monitor(project_id, measurements={"latency_ms": 500.0})
    assert report.severity is RegressionSeverity.MINOR
    assert report.tripped_metrics


def test_a_failed_invariant_is_a_major_regression(project_id):
    report = monitor(project_id, invariant_verdicts={"PI-5": "fail"})
    assert report.severity is RegressionSeverity.MAJOR
    assert report.tripped_invariants


def test_an_unmeasured_metric_is_not_a_passing_metric(project_id):
    report = monitor(project_id, measurements={})
    assert "latency_ms:unmeasured" in report.tripped_metrics


def test_an_unmeasured_invariant_is_not_a_passing_invariant(project_id):
    report = monitor(project_id, invariant_verdicts={})
    assert "PI-5:unmeasured" in report.tripped_invariants


def test_the_policy_is_pinned_and_tamper_detectable():
    """A goalpost moved after the fact is detected, not silently applied."""
    policy = make_policy()
    pinned = policy.policy_hash
    assert policy.assert_unchanged(pinned)
    moved = make_policy(thresholds={"latency_ms": (9999.0, True)})
    assert not moved.assert_unchanged(pinned)


def test_shadow_gains_no_extra_authority(project_id):
    """Shadow observes; it never affects behaviour, by construction."""
    record = activate(ActivationService(), project_id, ActivationMode.SHADOW).record
    assert record.affects_behaviour is False
    assert record.traffic_fraction == 0.0


# ── Gate 18: catastrophic protection ─────────────────────────────────────────


@pytest.mark.parametrize("condition", CATASTROPHIC_CONDITIONS)
def test_a_catastrophic_condition_trips_immediately(project_id, condition):
    """Gate 18: do not wait for accumulated reward or sample size."""
    report = monitor(project_id, catastrophic_conditions=[condition], sample_size=0)
    assert report.severity is RegressionSeverity.CATASTROPHIC
    assert report.is_catastrophic
    assert condition in report.catastrophic_reasons


def test_a_catastrophic_condition_outranks_a_passing_metric(project_id):
    report = monitor(
        project_id,
        measurements={"latency_ms": 1.0},
        catastrophic_conditions=["security_violation"],
    )
    assert report.severity is RegressionSeverity.CATASTROPHIC


# ── Gate 17: automatic rollback ───────────────────────────────────────────────


def make_report(project_id, severity, permitted=True, handle=True):
    return RegressionReport(
        candidate_id=uuid.uuid4(),
        project_id=project_id,
        kind="pattern_template",
        key="k",
        severity=severity,
        sample_size=5,
        auto_rollback_permitted=permitted and handle,
        rollback_handle_id=uuid.uuid4() if handle else None,
    )


def response(report, rollback=None):
    return enforce(
        report=report,
        freeze_promotion=lambda: True,
        deterministic_rollback=rollback or (lambda h: uuid.uuid4()),
        emit_audit=lambda r: True,
        generate_signal=lambda r: True,
        create_follow_up_candidate=lambda r: True,
    )


def test_no_regression_means_no_action(project_id):
    outcome = response(make_report(project_id, RegressionSeverity.NONE))
    assert not outcome.rollback_performed
    assert not outcome.promotion_frozen


def test_a_verified_regression_rolls_back_deterministically(project_id):
    rolled_back: list[uuid.UUID] = []
    outcome = response(
        make_report(project_id, RegressionSeverity.MAJOR),
        rollback=lambda h: rolled_back.append(h) or uuid.uuid4(),
    )
    assert outcome.rollback_performed
    assert len(rolled_back) == 1
    assert outcome.promotion_frozen
    assert outcome.audit_emitted
    assert outcome.signal_generated


def test_rollback_is_refused_without_evidence_verification(project_id):
    """Gate 17 step 2: verify the evidence before acting on it."""
    outcome = response(
        make_report(project_id, RegressionSeverity.MAJOR, permitted=False)
    )
    assert not outcome.rollback_performed
    assert any("not permitted" in step for step in outcome.steps)


def test_rollback_is_refused_without_a_handle(project_id):
    outcome = response(
        make_report(project_id, RegressionSeverity.MAJOR, handle=False)
    )
    assert not outcome.rollback_performed
    assert any("no rollback handle" in step for step in outcome.steps)


def test_a_catastrophic_regression_creates_a_follow_up_candidate(project_id):
    outcome = response(make_report(project_id, RegressionSeverity.CATASTROPHIC))
    assert outcome.follow_up_candidate_created
    assert outcome.rollback_performed


def test_rollback_requires_no_model():
    """The rollback path is a pointer restore, never a reasoned decision."""
    import ast
    import inspect
    from pathlib import Path

    from autoforge_learning import promotion

    tree = ast.parse(Path(inspect.getfile(promotion)).read_text())
    rollback_fn = next(
        node
        for node in ast.walk(tree)
        if isinstance(node, ast.FunctionDef) and node.name == "_rollback_locked"
    )
    called = {
        getattr(n.func, "attr", None) or getattr(n.func, "id", None)
        for n in ast.walk(rollback_fn)
        if isinstance(n, ast.Call)
    }
    for forbidden in ("requests", "httpx", "urlopen", "generate", "complete"):
        assert forbidden not in called


# ── Gate 13 / 32: the execution overlay ───────────────────────────────────────


class _State:
    def __init__(self, project_id, content_hash="a" * 64, deactivated=False):
        self.project_id = project_id
        self.content_hash = content_hash
        self.deactivation_timestamp = "now" if deactivated else None
        self.candidate_id = uuid.uuid4()
        self.version_id = uuid.uuid4()
        self.scope_kind = "project"


class _Store:
    def __init__(self, state):
        self._state = state

    def get_active_state(self, project_id, kind, key):
        return self._state


def test_absent_learning_is_identical_to_baseline(project_id):
    """Gate 13: a backward-compatible overlay changes nothing when inactive."""
    overlay = LearningOverlay(store=_Store(None))
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is None
    assert not resolution.degraded
    defaults = {"template": "baseline", "depth": 2}
    assert overlay.parameters_for(resolution, defaults) == defaults


def test_a_corrupt_store_degrades_to_baseline(project_id):
    """Gate 32: learning may never break the critical path."""

    class Exploding:
        def get_active_state(self, *_args, **_kwargs):
            raise RuntimeError("store is corrupt")

    overlay = LearningOverlay(store=Exploding())
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is None
    assert resolution.degraded
    assert overlay.degradations


def test_an_unverifiable_state_is_not_applied(project_id):
    overlay = LearningOverlay(store=_Store(_State(project_id, content_hash="")))
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is None
    assert resolution.degraded


def test_a_cross_project_pointer_is_not_applied(project_id):
    overlay = LearningOverlay(store=_Store(_State(uuid.uuid4())))
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is None
    assert resolution.degraded


def test_a_deactivated_candidate_is_not_applied(project_id):
    overlay = LearningOverlay(store=_Store(_State(project_id, deactivated=True)))
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is None
    assert not resolution.degraded


def test_a_verified_candidate_is_applied(project_id):
    overlay = LearningOverlay(
        store=_Store(_State(project_id)),
        parameters_for=lambda s: {"template": "new"},
    )
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is not None
    assert resolution.applied.integrity_verified
    assert overlay.parameters_for(resolution, {"template": "old", "d": 1}) == {
        "template": "new",
        "d": 1,
    }


def test_a_denying_authorizer_blocks_application(project_id):
    overlay = LearningOverlay(
        store=_Store(_State(project_id)), authorize=lambda state, pid: False
    )
    resolution = overlay.apply(project_id=project_id, kind="k", key="k")
    assert resolution.applied is None
    assert resolution.degraded


def test_the_overlay_holds_no_write_handle():
    """Wiring learning into an engine must add no authority."""
    overlay = LearningOverlay(store=None)
    for forbidden in (
        "promote",
        "activate",
        "rollback",
        "approve",
        "grant",
        "authorize",
        "set_active_state",
        "save_candidate",
    ):
        assert not hasattr(overlay, forbidden)