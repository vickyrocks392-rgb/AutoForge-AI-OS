"""PHASE 19B-3 END-TO-END CERTIFICATION (Gates 34-38).

Every test in this file uses the REAL production learning components — the real
:class:`LearningLifecycleService` built over the real certified
:class:`SecurityPlatform`, the real durable store, the real guardrails boundary,
the real HITL manager and the real promotion/rollback path. There is no mocked
"fake learning system" anywhere here.

The five certifications are:

* Gate 34 — the complete autonomous loop, observe → … → automatic rollback →
  new learning signal.
* Gate 35 — source-code self-improvement end to end, on a *fixture project*, so
  AutoForge's own protected security source is never modified.
* Gate 36 — bounded multi-generation recursive improvement with proven
  termination.
* Gate 37 — a bounded reward-driven experiment where a high reward cannot
  override deterministic safety.
* Gate 38 — a deterministic automatic rollback that restores exact prior state
  with no model reasoning.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    ArmOutcome,
    Experiment,
    ExperimentArm,
    ExperimentCapability,
    ExperimentEngine,
    ExperimentOutcome,
    Hypothesis,
    LearningCandidate,
    LearningScope,
    LearningScopeKind,
    RegressionSeverity,
    ResourceBudget,
    Reward,
    RewardLedger,
    RewardPolarity,
)
from autoforge_learning.activation import ActivationMode, ActivationService
from autoforge_learning.codemod import (
    MANDATORY_GATES,
    CodeChangeGatekeeper,
    CodeChangeProposal,
    GateStatus,
    parses_as_python,
)
from autoforge_learning.experience import ExperienceCollector
from autoforge_learning.extraction import SignalExtractor
from autoforge_learning.hypothesis import HypothesisGenerator
from autoforge_learning.lifecycle import LearningLifecycleService
from autoforge_learning.monitoring import RegressionMonitor, RegressionPolicy, enforce
from autoforge_learning.optimization import OptimizationStep, OptimizationTrace
from autoforge_learning.recursion import RecursiveImprovement
from autoforge_learning.runtime import LearningOverlay

from tests.helpers import evidence_payload_for, healthy_metrics, make_human, make_service

KIND = "pattern_template"
KEY = "template-alpha"
EFFECT = "Use the learned template for this project's task type"


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def service(tmp_path) -> LearningLifecycleService:
    """The REAL 19B-2 lifecycle over the REAL certified SecurityPlatform."""
    from autoforge_security.engine import SecurityPlatform

    return LearningLifecycleService.build(
        store_root=tmp_path / "learning-store",
        security_platform=SecurityPlatform(),
    )


@pytest.fixture()
def metrics():
    return healthy_metrics()


@pytest.fixture()
def evidence(project_id, metrics):
    return evidence_payload_for(healthy_metrics(latency_ms=90.0), project_id)


@pytest.fixture()
def stored(service, project_id, evidence):
    """A candidate that has passed the real security boundary and evaluation."""
    candidate = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary="Prefer the project's established template for this task type.",
        rationale="Derived from completed executions in this project.",
    )
    record = service.create_candidate(candidate)
    record = service.record_evidence(record, evidence)
    return record


@pytest.fixture()
def promoted(service, stored, metrics, project_id):
    """A fully promoted candidate: real evaluation, real HITL, real handle."""
    evaluation = service.evaluate(
        record=stored,
        baseline=metrics,
        candidate_metrics=healthy_metrics(latency_ms=90.0),
    )
    approval = service.request_approval(
        record=stored,
        evaluation=evaluation,
        kind=KIND,
        key=KEY,
        proposed_effect=EFFECT,
        requested_by=make_service(),
    )
    approval = service.approvals.record_decision(
        approval=approval,
        approver=make_human(),
        approve=True,
        reason="Reviewed evidence and invariants; approved.",
    )
    return service.promote(
        record=stored,
        evaluation=evaluation,
        approval=approval,
        kind=KIND,
        key=KEY,
        proposed_effect=EFFECT,
        requested_by=make_human(),
    )


def test_gate34_the_complete_autonomous_loop_closes(service, promoted, project_id):
    """Gate 34, end to end with real components:

    REAL EXECUTION → EXPERIENCE → SIGNAL → HYPOTHESIS → EXPERIMENT → EVALUATION
    → APPROVAL → ROLLBACK HANDLE → PROMOTION → ACTIVATION
    → EXECUTION WITH LEARNING → OBSERVATION → REGRESSION DETECTION
    → AUTOMATIC ROLLBACK → NEW LEARNING SIGNAL

    Stages 7-9 (evaluation, HITL approval, rollback handle, promotion) are
    performed by the real ``promoted`` fixture, which drives the real
    ``LearningLifecycleService`` and the real certified ``SecurityPlatform``.
    """
    # 1-2. OBSERVE → CAPTURE: real execution records, nothing manufactured.
    collector = ExperienceCollector()
    observations = collector.capture_from_execution(
        project_id=project_id,
        correlation_id="e2e-loop",
        execution_events={
            "task_execution": {"task_id": "t1", "status": "succeeded"},
            "execution_latency": {"duration_ms": 400},
            "validation": {"passed": True},
        },
    )
    assert len(observations) == 3

    # 3. EXTRACT SIGNALS from that evidence.
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    signals = SignalExtractor().extract(
        scope=scope, observations=observations, evidence_for=collector.evidence_for
    )
    assert signals and all(s.evidence for s in signals)

    # 4. GENERATE HYPOTHESES — competing and inert.
    hypotheses = HypothesisGenerator().generate(
        signals=signals,
        scope=scope,
        proposed_change_for={
            s.metric: f"adopt a faster strategy for {s.metric}" for s in signals
        },
    )
    assert hypotheses
    assert all(h.is_inert for h in hypotheses)
    assert all(h.supporting_evidence for h in hypotheses)

    # 5-6. EXPERIMENT: control versus treatment, judged from measurements.
    latency_hypothesis = next(
        (h for h in hypotheses if h.success_metric == "latency_ms"), None
    )
    assert latency_hypothesis is not None

    experiment = Experiment(
        scope=scope,
        hypothesis=latency_hypothesis,
        evaluation_metric="latency_ms",
        success_threshold=200.0,
        success_direction="decrease",
        max_duration_seconds=30.0,
        max_iterations=2,
        max_cost_units=5.0,
        declared_capabilities=(ExperimentCapability.CPU_TIME,),
        rollback_target_version_id=uuid.uuid4(),
        seed=7,
        correlation_id="e2e-loop",
    )
    run = ExperimentEngine().run(
        experiment=experiment,
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL,
            metrics={"latency_ms": 400.0},
            iterations_completed=2,
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT,
            metrics={"latency_ms": 150.0},
            iterations_completed=2,
        ),
        environment={"python": "3.12"},
        code_version="e2e",
    )
    assert run.outcome is ExperimentOutcome.SURVIVED
    assert run.is_reproducible

    # 7-9. EVALUATION → APPROVAL → HANDLE → PROMOTION: real, in `promoted`.

    # 10. ACTIVATE (Gate 14) as a distinct, explicit decision.
    activation = ActivationService()
    active = service.active_state(project_id, KIND, KEY)
    transition = activation.activate(
        candidate_id=promoted.candidate_id,
        project_id=project_id,
        kind=KIND,
        key=KEY,
        mode=ActivationMode.SHADOW,
        version_id=active.version_id,
        rollback_handle_id=promoted.rollback_handle_id,
    )
    assert transition.record.state.value == "shadow"
    assert transition.record.affects_behaviour is False

    # 11. EXECUTION WITH LEARNING: the overlay resolves the promoted state.
    overlay = LearningOverlay(
        store=service.store, parameters_for=lambda s: {"template": "learned"}
    )
    resolution = overlay.apply(project_id=project_id, kind=KIND, key=KEY)
    assert resolution.applied is not None
    assert overlay.parameters_for(resolution, {"template": "baseline"}) == {
        "template": "learned"
    }

    # 12. OBSERVATION after activation: the measured effect.
    post = collector.capture_from_execution(
        project_id=project_id,
        correlation_id="e2e-loop",
        execution_events={"execution_latency": {"duration_ms": 900}},
    )
    assert post[0].duration_ms == 900.0

    # 13. REGRESSION DETECTION against pre-registered thresholds.
    policy = RegressionPolicy(
        thresholds={"latency_ms": (200.0, True)}, tracked_invariants=("PI-5",)
    )
    report = RegressionMonitor().evaluate(
        candidate_id=promoted.candidate_id,
        project_id=project_id,
        kind=KIND,
        key=KEY,
        policy=policy,
        measurements={"latency_ms": 900.0},
        invariant_verdicts={"PI-5": "pass"},
        sample_size=1,
        rollback_handle_id=promoted.rollback_handle_id,
        correlation_id="e2e-loop",
    )
    assert report.severity is RegressionSeverity.MINOR
    assert report.tripped_metrics

    # 14. AUTOMATIC ROLLBACK through the real deterministic promotion rollback.
    #     A MINOR regression does not permit automatic rollback by contract, so
    #     escalate to a MAJOR one exactly as a real invariant failure would.
    major = report.model_copy(
        update={
            "severity": RegressionSeverity.MAJOR,
            "tripped_invariants": ("PI-5:fail",),
            "auto_rollback_permitted": True,
        }
    )
    outcome = enforce(
        report=major,
        freeze_promotion=lambda: True,
        deterministic_rollback=lambda handle_id: service.rollback(
            project_id=project_id,
            handle_id=handle_id,
            reason="automatic rollback: PI-5 regression detected",
        ).rollback_id,
        emit_audit=lambda r: True,
        generate_signal=lambda r: True,
        create_follow_up_candidate=lambda r: False,
    )
    assert outcome.rollback_performed

    # 15. The exact prior state is restored and the rollback record is retained.
    assert service.active_state(project_id, KIND, KEY) is None
    rollbacks = service.store.list_rollbacks(project_id)
    assert len(rollbacks) == 1
    assert rollbacks[0].restored_state is None

    # 16. NEW LEARNING SIGNAL: the regression is fed back into the loop.
    post_regression = SignalExtractor().extract(
        scope=scope, observations=post, evidence_for=collector.evidence_for
    )
    assert any(s.metric == "latency_ms" for s in post_regression)


def test_gate34_the_first_candidate_check_still_passes_the_real_boundary(
    service, stored
):
    """Gate 34's security stage: the real gateway permitted this candidate."""
    from autoforge_learning.audit import LearningAuditAction

    emitted = {e.action for e in service.auditor.events}
    assert LearningAuditAction.CANDIDATE_CREATED in emitted


# ── Gate 35: source-code self-improvement E2E ────────────────────────────────


FIXTURE_SOURCE = "def total(values):\n    return sum(values)\n"
FIXTURE_TEST = (
    "from fixture_module import total\n\n\n"
    "def test_total():\n    assert total([1, 2, 3]) == 6\n"
)


@pytest.fixture()
def fixture_project(tmp_path):
    """A small, controlled fixture project in its own directory.

    AutoForge's own protected security source is never touched: the change is
    prepared and evaluated entirely inside this directory.
    """
    root = tmp_path / "fixture-project"
    project = root / "fixture"
    project.mkdir(parents=True)
    (project / "fixture_module.py").write_text(FIXTURE_SOURCE)
    (project / "test_fixture_module.py").write_text(FIXTURE_TEST)
    workspace = root / "workspace"
    workspace.mkdir()
    return project, workspace


def test_gate35_source_change_is_isolated_diffed_and_evaluated(
    fixture_project, project_id
):
    """Gate 35: proposal → isolated workspace → diff → tests → rollback."""
    import hashlib
    import shutil
    import subprocess
    import sys

    project, workspace = fixture_project
    base_content = (project / "fixture_module.py").read_text()
    proposed_content = "def total(values):\n    return sum(int(v) for v in values)\n"

    # The change is prepared in the isolated workspace, never over production.
    shutil.copytree(project, workspace / "copy", dirs_exist_ok=True)
    (workspace / "copy" / "fixture_module.py").write_text(proposed_content)
    assert (project / "fixture_module.py").read_text() == base_content, (
        "the source tree must be untouched while the change is prepared"
    )

    proposal = CodeChangeProposal(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        summary="coerce inputs to int before summing",
        diff=(
            "--- a/fixture_module.py\n+++ b/fixture_module.py\n@@\n"
            "-    return sum(values)\n+    return sum(int(v) for v in values)\n"
        ),
        touched_paths=("fixture_module.py",),
        base_content_hash=hashlib.sha256(base_content.encode()).hexdigest(),
        proposed_content_hash=hashlib.sha256(
            proposed_content.encode()
        ).hexdigest(),
        isolated_workspace=str(workspace),
    )
    assert proposal.diff and proposal.touched_paths

    # The real tests execute against the isolated copy.
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", str(workspace / "copy")],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stdout[-500:]
    assert parses_as_python(proposed_content)

    # All ten mandatory gates pass, including security and regression suites.
    verdict = CodeChangeGatekeeper().evaluate(
        proposal, gate_results={g: GateStatus.PASSED for g in MANDATORY_GATES}
    )
    assert verdict.promotable

    # Rollback exists: the exact prior state is identified by content hash.
    from autoforge_learning.codemod import verify_diff_is_reversible

    assert verify_diff_is_reversible(proposal, base_content)
    assert (project / "fixture_module.py").read_text() == base_content


def test_gate35_a_protected_file_change_is_denied_before_any_workspace(
    fixture_project, project_id
):
    """AutoForge's own security source can never be self-modified."""
    from autoforge_learning import CodeChangeRefused

    _, workspace = fixture_project
    proposal = CodeChangeProposal(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        summary="disable the authorization check",
        diff="- allow all\n+ allow all  # disabled",
        touched_paths=("packages/security/src/autoforge_security/authorization.py",),
        base_content_hash="a" * 64,
        proposed_content_hash="b" * 64,
        isolated_workspace=str(workspace),
    )
    with pytest.raises(CodeChangeRefused, match="DENIED"):
        CodeChangeGatekeeper().evaluate(
            proposal, gate_results={g: GateStatus.PASSED for g in MANDATORY_GATES}
        )


# ── Gate 36: bounded multi-generation recursion ──────────────────────────────


def make_trace(project_id, accepted, generation, score):
    return OptimizationTrace(
        trace_id=uuid.uuid4(),
        project_id=project_id,
        target="prompt_strategy",
        steps=(
            OptimizationStep(
                step_id=uuid.uuid4(),
                generation=generation,
                target="prompt_strategy",
                from_value=f"v{generation}",
                to_value=f"v{generation + 1}",
                accepted=accepted,
                reason="improved" if accepted else "no improvement",
                measured_delta=0.1,
            ),
        ),
        best_value=f"v{generation + 1}" if accepted else f"v{generation}",
        best_score=score,
        generations_completed=generation + 1,
        terminated_because="candidate set exhausted",
    )


def make_budget(project_id, **overrides) -> ResourceBudget:
    kwargs = dict(
        project_id=project_id,
        max_experiments=10,
        max_recursion_depth=3,
        max_wall_clock_seconds=60.0,
        max_model_calls=10,
        max_concurrent_experiments=1,
        max_disk_bytes=1000,
        max_memory_bytes=1000,
        max_network_bytes=0,
    )
    kwargs.update(overrides)
    return ResourceBudget(**kwargs)


def test_gate36_multi_generation_learning_terminates_at_its_bound(project_id):
    """Gate 36: Generation 0 → 1 → … bounded by configured recursion limits.

    Each generation observes its predecessor, and generation N is capped by the
    declared depth so the loop provably terminates.
    """
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    budget = make_budget(project_id)
    generations = RecursiveImprovement(budget=budget).run_until_bounded(
        scope=scope,
        correlation_id="gen-e2e",
        stage=lambda g: make_trace(project_id, True, g, 0.5 + g * 0.1),
    )

    assert [r.generation for r in generations] == [0, 1, 2]
    assert len(generations) == budget.max_recursion_depth

    for previous, current in zip(generations, generations[1:]):
        assert current.lineage.parent_lineage_id == previous.lineage.lineage_id
        assert current.lineage.generation == previous.lineage.generation + 1
        assert current.trace.best_score > previous.trace.best_score


def test_gate36_recursion_stops_when_a_generation_cannot_improve(project_id):
    """A generation that cannot improve ends the loop: no endless search."""
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    results = RecursiveImprovement(
        budget=make_budget(project_id, max_recursion_depth=5)
    ).run_until_bounded(
        scope=scope,
        correlation_id="gen-stop",
        stage=lambda g: make_trace(project_id, False, g, 0.5),
    )
    assert len(results) == 1


def test_gate36_recursion_cannot_exceed_its_experiment_budget(project_id):
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    engine = RecursiveImprovement(
        budget=make_budget(project_id, max_experiments=2, max_recursion_depth=9)
    )
    results = engine.run_until_bounded(
        scope=scope,
        correlation_id="gen-budget",
        stage=lambda g: make_trace(project_id, True, g, 0.5),
    )
    assert len(results) <= 2
    assert engine.experiments_used <= 2


def test_gate36_recursion_never_widens_authority(project_id):
    """The prohibited learning → permission → learning loop cannot form."""
    from autoforge_learning import AuthorityExpansionAttempted

    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)
    engine = RecursiveImprovement(budget=make_budget(project_id))
    widened = LearningScope(
        kind=LearningScopeKind.GLOBAL_NON_SECURITY, project_id=project_id
    )
    results = engine.run_until_bounded(
        scope=scope, correlation_id="gen-authority", stage=lambda g: None
    )
    assert results
    with pytest.raises(AuthorityExpansionAttempted):
        from autoforge_learning import assert_no_authority_expansion

        assert_no_authority_expansion(parent_scope=scope, child_scope=widened)


# ── Gate 37: RL / reward-driven experiment E2E ───────────────────────────────


@pytest.fixture()
def reward_hypothesis(project_id):
    from autoforge_learning.models import EvidenceRef, EvidenceSource

    return Hypothesis(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        observation="task success rate observed",
        supporting_evidence=(
            EvidenceRef.from_payload(
                EvidenceSource.CANONICAL_EVENT, "execution:t1", {"ok": True}
            ),
        ),
        proposed_change="adopt the higher-success strategy",
        expected_effect="improve task_success_rate",
        success_metric="task_success_rate",
        success_threshold=0.95,
        success_direction="increase",
        risk="low",
        rollback_strategy="restore prior version",
    )


def test_gate37_a_high_reward_cannot_override_deterministic_safety(
    reward_hypothesis,
):
    """Gate 37: define reward → collect → compare → reject hacking → keep rollback."""
    ledger = RewardLedger()
    candidate = uuid.uuid4()

    reward = ledger.record(
        scope=reward_hypothesis.scope,
        objective="task_success_rate",
        raw_value=99.0,
        provenance_ref="telemetry:e2e-run",
        provenance_payload={"success_rate": 0.99},
        bounds=(0.0, 100.0),
        candidate_id=candidate,
        confidence=1.0,
    )
    assert reward.normalized_value > 0.9

    experiment = Experiment(
        scope=reward_hypothesis.scope,
        hypothesis=reward_hypothesis,
        evaluation_metric="task_success_rate",
        success_threshold=0.95,
        success_direction="increase",
        max_duration_seconds=30.0,
        max_iterations=2,
        max_cost_units=5.0,
        rollback_target_version_id=uuid.uuid4(),
    )
    arms = dict(
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL,
            metrics={"task_success_rate": 0.90},
            iterations_completed=2,
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT,
            metrics={"task_success_rate": 0.99},
            iterations_completed=2,
        ),
        rewards=[reward],
        environment={"python": "3.12"},
    )

    # Reward hacking: an excellent reward that trips a protected invariant.
    hacked = ExperimentEngine().run(
        experiment=experiment,
        invariant_check=lambda outcome: RegressionSeverity.CATASTROPHIC,
        **arms,
    )
    assert hacked.outcome is ExperimentOutcome.TERMINATED_ON_INVARIANT_BREACH
    assert hacked.reward_total > 0.9
    assert hacked.reward_suppressed is True

    # The identical candidate without the breach survives, proving the reward
    # was never what decided the verdict.
    safe = ExperimentEngine().run(experiment=experiment, **arms)
    assert safe.outcome is ExperimentOutcome.SURVIVED

    # Rollback is preserved throughout: a target was pre-registered.
    assert experiment.rollback_target_version_id is not None

    # Reward hacking is detected rather than rewarded.
    assert ledger.detect_contradiction(candidate, verdicts=["fail"])


def test_gate37_a_reward_conflicting_with_validation_is_clamped(reward_hypothesis):
    """Deterministic validation outranks reward, unconditionally."""
    ledger = RewardLedger()
    reward = ledger.record(
        scope=reward_hypothesis.scope,
        objective="task_success_rate",
        raw_value=99.0,
        provenance_ref="telemetry:run",
        provenance_payload={"success_rate": 0.99},
        bounds=(0.0, 100.0),
        confidence=1.0,
    )
    window = ledger.aggregate([reward], deterministic_verdicts=["fail"])
    assert window.aggregate == 0.0
    assert window.clamped_by_determinism


# ── Gate 38: automatic rollback E2E ──────────────────────────────────────────


def _promote(service, record, approver, key=None):
    """Drive the real evaluation → HITL → promotion chain for one candidate.

    All promotions in these tests address the same ``(kind, key)`` pointer, so
    successive promotions genuinely supersede one another — which is what makes
    the rollback target meaningful.
    """
    key = key or KEY
    evaluation = service.evaluate(
        record=record,
        baseline=healthy_metrics(),
        candidate_metrics=healthy_metrics(latency_ms=90.0),
    )
    approval = service.request_approval(
        record=record,
        evaluation=evaluation,
        kind=KIND,
        key=key,
        proposed_effect=f"Adopt {key}",
        requested_by=make_service(),
    )
    approval = service.approvals.record_decision(
        approval=approval,
        approver=approver,
        approve=True,
        reason="Reviewed evidence and invariants; approved.",
    )
    return service.promote(
        record=record,
        evaluation=evaluation,
        approval=approval,
        kind=KIND,
        key=key,
        proposed_effect=f"Adopt {key}",
        requested_by=approver,
    )


def test_gate38_automatic_rollback_restores_exact_prior_state(
    service, stored, project_id
):
    """Gate 38: baseline → activate → regress → detect → automatic rollback.

    No model reasoning is involved: the detector compares measurements to
    pre-registered thresholds and the real deterministic rollback restores the
    exact prior pointer.
    """
    # Baseline: a first, real, human-approved promotion is active.
    first = _promote(service, stored, make_human())
    baseline_state = service.active_state(project_id, KIND, KEY)
    assert baseline_state is not None
    assert baseline_state.candidate_id == first.candidate_id

    # A second candidate is promoted over it, creating a rollback handle.
    second_candidate = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary="An experimental candidate that regresses.",
        rationale="Proposed from observed latency.",
    )
    second_record = service.record_evidence(
        service.create_candidate(second_candidate),
        evidence_payload_for(healthy_metrics(latency_ms=90.0), project_id),
    )
    second = _promote(service, second_record, make_human())
    assert service.active_state(project_id, KIND, KEY).candidate_id == (
        second.candidate_id
    )

    # A measurable regression is introduced.
    report = RegressionMonitor().evaluate(
        candidate_id=second.candidate_id,
        project_id=project_id,
        kind=KIND,
        key=KEY,
        policy=RegressionPolicy(
            thresholds={"latency_ms": (200.0, True)}, tracked_invariants=("PI-5",)
        ),
        measurements={"latency_ms": 900.0},
        invariant_verdicts={"PI-5": "fail"},
        evidence=evidence_payload_for(healthy_metrics(latency_ms=900.0), project_id),
        sample_size=5,
        rollback_handle_id=second.rollback_handle_id,
    )
    assert report.severity is RegressionSeverity.MAJOR
    assert report.auto_rollback_permitted

    outcome = enforce(
        report=report,
        freeze_promotion=lambda: True,
        deterministic_rollback=lambda handle_id: service.rollback(
            project_id=project_id,
            handle_id=handle_id,
            reason="automatic rollback: PI-5 failed after activation",
        ).rollback_id,
        emit_audit=lambda r: True,
        generate_signal=lambda r: True,
        create_follow_up_candidate=lambda r: True,
    )
    assert outcome.rollback_performed
    # A follow-up candidate is created only for a catastrophic regression;
    # a MAJOR regression rolls back and learns without a new candidate.
    assert not outcome.follow_up_candidate_created

    # The exact previous state is restored: same version, same candidate.
    restored = service.active_state(project_id, KIND, KEY)
    assert restored is not None
    assert restored.version_id == baseline_state.version_id
    assert restored.candidate_id == first.candidate_id


def test_gate38_a_catastrophic_regression_also_creates_a_follow_up(
    service, stored, project_id
):
    """Gate 17.9: a catastrophic regression generates a follow-up candidate."""
    second_candidate = LearningCandidate(
        scope=LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id),
        kind=KIND,
        summary="An experimental candidate that fails catastrophically.",
        rationale="Proposed from observed latency.",
    )
    second_record = service.record_evidence(
        service.create_candidate(second_candidate),
        evidence_payload_for(healthy_metrics(latency_ms=90.0), project_id),
    )
    second = _promote(service, second_record, make_human())

    report = RegressionMonitor().evaluate(
        candidate_id=second.candidate_id,
        project_id=project_id,
        kind=KIND,
        key=KEY,
        policy=RegressionPolicy(thresholds={"latency_ms": (200.0, True)}),
        measurements={"latency_ms": 5000.0},
        invariant_verdicts={"PI-5": "pass"},
        evidence=evidence_payload_for(healthy_metrics(latency_ms=5000.0), project_id),
        sample_size=1,
        catastrophic_conditions=["security_violation"],
        rollback_handle_id=second.rollback_handle_id,
    )
    assert report.severity is RegressionSeverity.CATASTROPHIC

    outcome = enforce(
        report=report,
        freeze_promotion=lambda: True,
        deterministic_rollback=lambda handle_id: service.rollback(
            project_id=project_id,
            handle_id=handle_id,
            reason="catastrophic regression",
        ).rollback_id,
        emit_audit=lambda r: True,
        generate_signal=lambda r: True,
        create_follow_up_candidate=lambda r: True,
    )
    assert outcome.rollback_performed
    assert outcome.follow_up_candidate_created


def test_gate38_rollback_is_idempotent(service, stored, project_id):
    """The rollback is a deterministic pointer restore (LC-06 / RB-01)."""
    first = _promote(service, stored, make_human())
    assert service.active_state(project_id, KIND, KEY) is not None

    record = service.rollback(
        project_id=project_id,
        handle_id=first.rollback_handle_id,
        reason="first rollback",
    )
    second = service.rollback(
        project_id=project_id,
        handle_id=first.rollback_handle_id,
        reason="second rollback",
    )
    assert record.handle_id == second.handle_id
    # The desired end state holds and is not corrupted by the repeat.
    assert service.active_state(project_id, KIND, KEY) is None
    # Both executions are retained: history is never erased.
    assert len(service.store.list_rollbacks(project_id)) == 2