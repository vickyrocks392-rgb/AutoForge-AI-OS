"""Smoke test for the Gate 3 compaction package (design verified, not Gate 4)."""

from autoforge_execution.compaction import (
    CompactionPolicy,
    ContextCompactor,
    apply_validation,
)
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)

policy = CompactionPolicy(enabled=True)
print("default enabled (must be False):", CompactionPolicy().enabled)
print(
    "trigger @4 iters:",
    policy.should_compact(
        iteration_count=4, candidate_count=4, remaining_budget_tokens=30000
    ),
)
print(
    "trigger @2 iters:",
    policy.should_compact(
        iteration_count=2, candidate_count=4, remaining_budget_tokens=30000
    ),
)

hist = [
    LoopIterationRecord(
        iteration=i,
        action_plan=f"plan {i}",
        changed_files=[f"f{i}.py"],
        passed=(i % 3 == 0),
        evaluation=EvaluationResult(
            status=EvaluationStatus.FAILED, failures=[f"test_{i} FAILED"]
        ),
        diagnosis=DiagnosisReport(
            root_cause=f"rc {i}",
            failure_mechanism="m",
            affected_files=["a.py"],
            suggested_fix="fix",
        ),
    )
    for i in range(1, 7)
]

compactor = ContextCompactor(policy)
rec = compactor.compact(task_id="t1", prior_iterations=hist)
print(
    "items:", rec.item_count,
    "| reduction:", rec.reduction_ratio,
    "| source_tokens:", rec.source_estimated_tokens,
    "| record_tokens:", rec.estimated_tokens,
)
print("valid:", apply_validation(rec, policy=policy), "| status:", rec.validation_status)
for item in rec.items:
    print("  ", item.source.ref, "| required:", item.required, "| depends_on:", item.depends_on)

# Determinism: same inputs -> identical record content digest.
rec2 = ContextCompactor(policy).compact(task_id="t1", prior_iterations=hist)
print("deterministic digest:", rec.content_digest() == rec2.content_digest())
print("deterministic id:", rec.compaction_id == rec2.compaction_id)
