"""Ad-hoc verification of the 19B-3 pipeline components (Gates 2-4)."""

from __future__ import annotations

import uuid

from autoforge_learning.experience import ExperienceCollector
from autoforge_learning.extraction import SignalExtractor
from autoforge_learning.hypothesis import HypothesisGenerator, proposal_kind_for
from autoforge_learning.models import LearningScope, LearningScopeKind
from autoforge_security.ai_guardrails import LEARNABLE_PROPOSAL_KINDS


def main() -> None:
    collector = ExperienceCollector()
    extractor = SignalExtractor()
    generator = HypothesisGenerator()
    project_id = uuid.uuid4()
    scope = LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)

    observations = collector.capture_from_execution(
        project_id=project_id,
        execution_events={
            "validation": {"passed": True},
            "execution_latency": {"duration_ms": 900},
            "resource_behaviour": {"resource_units": 80},
            "execution_failed": {"execution_id": "e1"},
        },
    )
    signals = extractor.extract(
        scope=scope, observations=observations, evidence_for=collector.evidence_for
    )
    print("metrics:", [s.metric for s in signals])

    hypotheses = generator.generate(
        signals=signals,
        scope=scope,
        proposed_change_for={s.metric: "change for " + s.metric for s in signals},
    )
    for h in hypotheses:
        kind = proposal_kind_for(next(s for s in signals if s.metric == h.success_metric))
        print(
            h.success_metric,
            h.success_direction,
            "inert=",
            h.is_inert,
            "competing=",
            len(h.competing_with),
            "kind_ok=",
            kind in LEARNABLE_PROPOSAL_KINDS,
        )


if __name__ == "__main__":
    main()