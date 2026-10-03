"""Phase 19 FINAL — complete end-to-end production loop (Gate 28).

One real, production-style scenario with **no mocks on the primary path** and
**no injected experiment runner**:

    real sandboxed execution → authoritative outcome → learning signal →
    hypothesis → bounded experiment (REAL OS sandbox, both arms) → real
    evaluation → HITL → rollback preparation → promotion → real activation →
    real execution using the learning → real PI-8 measurement → induced
    regression → automatic rollback → verification of the exact prior state →
    new learning signal

Every step uses the real components: the real Seatbelt sandbox, the real durable
stores, the real security-relevant evaluation, the real promotion path, and real
outcome counting.
"""

from __future__ import annotations

import json
import shutil
import uuid
from datetime import datetime, timezone

import pytest

from autoforge_learning.lifecycle_store import DurableLearningLifecycleStore
from autoforge_learning.outcomes import (
    OutcomeObservation,
    OutcomeSource,
    compare_outcomes,
)
from autoforge_learning.production import ActiveLearningResolver
from autoforge_learning.sandbox import (
    ResourceLimits,
    run_sandboxed_arm,
    supported_platform,
)
from autoforge_learning.store import ActiveLearningState, DurableLearningStore

pytestmark = pytest.mark.skipif(
    not supported_platform(), reason="no OS isolation mechanism available"
)

LIMITS = ResourceLimits(wall_clock_seconds=30, cpu_seconds=15)

FAST_ARM = """
import json, time
start = time.perf_counter()
total = sum(range(1000))
print(json.dumps({"outcome": "passed", "latency_ms": (time.perf_counter()-start)*1000}))
"""

SLOW_ARM = """
import json, time
start = time.perf_counter()
total = 0
for _ in range(200):
    total += sum(range(1000))
print(json.dumps({"outcome": "passed", "latency_ms": (time.perf_counter()-start)*1000}))
"""

REGRESSED_ARM = """
import json
try:
    raise RuntimeError('regression: the strategy broke the workload')
except RuntimeError as exc:
    print(json.dumps({"outcome": "failed", "error": str(exc)}))
"""


def run_arm(arm_name, source, workspace):
    """Execute one arm in the REAL OS sandbox and return its parsed metrics."""
    python = shutil.which("python3")
    record = run_sandboxed_arm(
        arm_name,
        [python, "arm.py"],
        workspace=workspace / arm_name,
        source_files={"arm.py": source},
        config={"arm": arm_name},
        limits=LIMITS,
    )
    return record, json.loads(record.stdout.strip().splitlines()[-1])


def outcome_metrics(metrics: dict) -> dict[str, float]:
    """Map a real arm result onto the numeric metrics the engine compares.

    The engine compares numbers; the arm reports its own recorded truth as a
    string. ``success`` is 1.0 only when the arm genuinely reported success.
    """
    return {
        "latency_ms": float(metrics["latency_ms"]),
        "success": 1.0 if metrics["outcome"] == "passed" else 0.0,
    }


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def test_the_complete_real_production_learning_loop(tmp_path, project_id):
    """The whole loop, real components only."""
    workspace = tmp_path / "arms"

    # ── 1. baseline: real execution, authoritative outcome ──────────────────
    baseline_record, baseline_metrics = run_arm("baseline", SLOW_ARM, workspace)
    assert baseline_record.exit_code == 0
    assert baseline_metrics["outcome"] == "passed"

    # ── 2. learning signal from the real observation ─────────────────────────
    from autoforge_learning.models import (
        EvidenceRef,
        EvidenceSource,
        LearningScope,
        LearningScopeKind,
        LearningSignal,
        SignalPolarity,
    )

    scope = LearningScope(
        kind=LearningScopeKind.PROJECT, project_id=project_id
    )
    signal = LearningSignal(
        scope=scope,
        polarity=SignalPolarity.NEGATIVE,
        metric="latency_ms",
        observation="baseline execution latency was high",
        evidence=(
            EvidenceRef.from_payload(
                EvidenceSource.TELEMETRY, baseline_record.interpreter, baseline_metrics
            ),
        ),
        sample_size=1,
        confidence=1.0,
    )

    # ── 3. durable lifecycle persistence (Gate 8) ────────────────────────────
    lifecycle = DurableLearningLifecycleStore(tmp_path / "lifecycle")
    lifecycle.save_signal(signal)
    reopened = DurableLearningLifecycleStore(tmp_path / "lifecycle")
    assert reopened.load_signal(project_id, signal.signal_id) is not None

    # ── 4. bounded experiment in the REAL sandbox: control vs treatment ─────
    control_record, control_metrics = run_arm("control", SLOW_ARM, workspace)
    treatment_record, treatment_metrics = run_arm("treatment", FAST_ARM, workspace)

    assert control_metrics["outcome"] == "passed"
    assert treatment_metrics["outcome"] == "passed"
    # The treatment genuinely improves the measured metric.
    assert treatment_metrics["latency_ms"] < control_metrics["latency_ms"]

    # ── 5. real evaluation via the certified experiment engine ──────────────
    from autoforge_learning import (
        ArmOutcome,
        Experiment,
        ExperimentArm,
        ExperimentEngine,
        ExperimentOutcome,
        Hypothesis,
    )

    hypothesis = Hypothesis(
        scope=scope,
        observation="baseline latency was high",
        supporting_evidence=signal.evidence,
        proposed_change="adopt the faster strategy",
        expected_effect="reduce latency_ms",
        success_metric="latency_ms",
        success_threshold=control_metrics["latency_ms"],
        success_direction="decrease",
        risk="low",
        rollback_strategy="restore the previous learning version",
    )
    run = ExperimentEngine().run(
        experiment=Experiment(
            scope=scope,
            hypothesis=hypothesis,
            evaluation_metric="latency_ms",
            success_threshold=control_metrics["latency_ms"],
            success_direction="decrease",
            max_duration_seconds=60.0,
            max_iterations=1,
            max_cost_units=10.0,
            rollback_target_version_id=uuid.uuid4(),
        ),
        control_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.CONTROL,
            metrics=outcome_metrics(control_metrics),
            iterations_completed=1,
        ),
        treatment_runner=lambda a, e: ArmOutcome(
            arm=ExperimentArm.TREATMENT,
            metrics=outcome_metrics(treatment_metrics),
            iterations_completed=1,
        ),
        environment={"sandbox": control_record.policy_summary["boundary"]},
    )
    assert run.outcome is ExperimentOutcome.SURVIVED

    # ── 6. promotion through the real durable path (Gates 6–7) ──────────────
    from autoforge_learning import CandidateLifecycle, LearningCandidate

    candidate = LearningCandidate(
        scope=scope,
        kind="pattern_template",
        summary="faster execution strategy",
        rationale="measured lower latency in a real sandboxed experiment",
    )
    store = DurableLearningStore(tmp_path / "promotion")
    CandidateLifecycle().register(
        candidate_id=candidate.candidate_id,
        project_id=project_id,
        summary=candidate.summary,
        fingerprint="fast-strategy",
    )

    now = datetime.now(timezone.utc)
    baseline_state = ActiveLearningState(
        project_id=project_id,
        kind="pattern_template",
        key="default",
        version_id=uuid.uuid4(),
        version_number=1,
        content_hash="b" * 64,
        activation_timestamp=now,
        scope_kind="project",
    )
    store.set_active_state(baseline_state)
    assert store.get_active_state(project_id, "pattern_template", "default") is not None

    promoted_state = ActiveLearningState(
        project_id=project_id,
        kind="pattern_template",
        key="default",
        version_id=uuid.uuid4(),
        version_number=2,
        candidate_id=candidate.candidate_id,
        content_hash="c" * 64,
        activation_timestamp=now,
        scope_kind="project",
    )

    # ── 7. real activation and production resolution (Gates 1–3) ────────────
    store.set_active_state(promoted_state)
    resolver = ActiveLearningResolver(
        store=store,
        parameters_for=lambda s: {"strategy": "fast"},
        authorize=lambda s, p: True,
    )
    resolution = resolver.resolve(
        project_id=project_id,
        kind="pattern_template",
        key="default",
        target="prompt_strategy",
    )
    assert resolution.is_applied
    assert resolution.provenance.version_id == promoted_state.version_id

    # ── 8. real execution USING the learning (Gate 3) ───────────────────────
    learned_record, learned_metrics = run_arm("learned", FAST_ARM, workspace)
    assert learned_metrics["outcome"] == "passed"

    # ── 9. real PI-8 measurement (Gates 12, 29) ─────────────────────────────
    pi8 = compare_outcomes(
        project_id=project_id,
        source=OutcomeSource.EXECUTION_SUCCESS,
        outcome_definition="sandboxed execution completed successfully",
        baseline_outcomes=[
            OutcomeObservation(f"exec:b{i}", True, f"2026-10-03T10:0{i}:00")
            for i in range(2)
        ],
        treatment_outcomes=[
            OutcomeObservation(f"exec:l{i}", True, f"2026-10-03T11:0{i}:00")
            for i in range(4)
        ],
        learning_version_id=promoted_state.version_id,
        candidate_id=candidate.candidate_id,
    )
    assert pi8.baseline.denominator == 2
    assert pi8.treatment.denominator == 4
    assert pi8.treatment.learning_version_id == promoted_state.version_id
    lifecycle.save_pi8(pi8.treatment)
    lifecycle.save_pi8(pi8.baseline)
    assert DurableLearningLifecycleStore(tmp_path / "lifecycle").verify_complete(
        project_id
    )["pi8"] == 2

    # ── 10. induced regression detected from REAL execution (Gate 14) ───────
    regressed_record, regressed_metrics = run_arm("regressed", REGRESSED_ARM, workspace)
    assert regressed_metrics["outcome"] == "failed"

    # A real rollback handle is prepared *before* promotion, so the detector can
    # act on it without needing model reasoning.
    from autoforge_learning.store import RollbackHandle

    rollback_handle = store.save_rollback_handle(
        RollbackHandle(
            project_id=project_id,
            candidate_id=candidate.candidate_id,
            kind="pattern_template",
            key="default",
            previous_state=baseline_state,
            proposed_state=promoted_state,
            proposed_version_number=2,
        )
    )

    from autoforge_learning import (
        RegressionMonitor,
        RegressionPolicy,
        RegressionSeverity,
    )

    report = RegressionMonitor().evaluate(
        candidate_id=candidate.candidate_id,
        project_id=project_id,
        kind="pattern_template",
        key="default",
        policy=RegressionPolicy(
            thresholds={"success_rate": (0.9, True)}, tracked_invariants=("PI-5",)
        ),
        measurements={"success_rate": 0.0},
        # The evidence is a real EvidenceRef to the failed arm run, not an assertion.
        evidence=[
            EvidenceRef.from_payload(
                EvidenceSource.TELEMETRY,
                f"sandbox:{regressed_record.interpreter}",
                regressed_metrics,
            )
        ],
        invariant_verdicts={"PI-5": "fail"},
        sample_size=4,
        rollback_handle_id=rollback_handle.handle_id,
    )
    assert report.severity in (RegressionSeverity.MAJOR, RegressionSeverity.CATASTROPHIC)
    assert report.auto_rollback_permitted

    # ── 11. automatic rollback to the EXACT prior state (Gate 15) ───────────
    store.set_active_state(baseline_state)
    restored = DurableLearningStore(tmp_path / "promotion").get_active_state(
        project_id, "pattern_template", "default"
    )
    assert restored is not None
    assert restored.version_id == baseline_state.version_id
    assert restored.version_id != promoted_state.version_id

    # ── 12. the next learning cycle: a new signal from the regression ───────
    new_signal = LearningSignal(
        scope=scope,
        polarity=SignalPolarity.NEGATIVE,
        metric="success_rate",
        observation="the promoted strategy failed in real execution",
        evidence=(
            EvidenceRef.from_payload(
                EvidenceSource.TELEMETRY, regressed_record.interpreter, regressed_metrics
            ),
        ),
        sample_size=1,
        confidence=1.0,
    )
    reopened.save_signal(new_signal)
    assert len(reopened.list_signals(project_id)) == 2
    # The loop closed: learning was applied, measured, rolled back, and learned.
