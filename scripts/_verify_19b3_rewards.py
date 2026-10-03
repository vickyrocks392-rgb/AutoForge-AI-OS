"""Ad-hoc verification of the 19B-3 reward layer (Gates 8 and 25)."""

from __future__ import annotations

import uuid

from autoforge_learning.models import LearningScope, LearningScopeKind, RewardPolarity
from autoforge_learning.rewards import RewardLedger, RewardRejected


def main() -> None:
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=uuid.uuid4())
    ledger = RewardLedger()
    candidate = uuid.uuid4()

    # A legitimate, well-provenanced reward. Bounds (0,100) with 95 maps to +0.9.
    good = ledger.record(
        scope=scope,
        objective="task_success_rate",
        raw_value=95.0,
        provenance_ref="telemetry:run-1",
        provenance_payload={"success_rate": 0.95},
        bounds=(0.0, 100.0),
        candidate_id=candidate,
        confidence=1.0,
    )
    print("normalized:", good.normalized_value)

    # Fabricated reward: no provenance reference.
    try:
        ledger.record(
            scope=scope,
            objective="task_success_rate",
            raw_value=1000.0,
            provenance_ref="   ",
            provenance_payload={"x": 1},
        )
    except RewardRejected as exc:
        print("fabricated ->", exc)

    # Adversarial: score a security outcome.
    try:
        ledger.record(
            scope=scope,
            objective="security_violations",
            raw_value=-5.0,
            provenance_ref="audit:1",
            provenance_payload={"v": 0},
        )
    except RewardRejected as exc:
        print("protected objective ->", exc)

    # Deterministic validation must outrank a large positive reward.
    window = ledger.aggregate([good], deterministic_verdicts=["fail"])
    print(
        "high reward + failing validation ->",
        window.aggregate,
        "clamped:",
        window.clamped_by_determinism,
    )

    clean = ledger.aggregate([good], deterministic_verdicts=["pass"])
    print("high reward + passing validation ->", clean.aggregate)

    # Anti-hacking detectors.
    print("inflation:", ledger.detect_inflation(candidate, ceiling=0.5))
    print("contradiction:", ledger.detect_contradiction(candidate, verdicts=["fail"]))
    ledger.record(
        scope=scope,
        objective="task_success_rate",
        raw_value=10.0,
        provenance_ref="telemetry:run-1",
        provenance_payload={"success_rate": 0.95},
        bounds=(0.0, 100.0),
        candidate_id=candidate,
    )
    print("replay:", ledger.detect_replayed_evidence(candidate))
    print("rejections:", len(ledger.rejections))


if __name__ == "__main__":
    main()