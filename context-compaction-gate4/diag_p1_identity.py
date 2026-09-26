"""Quick check of logical_identity semantics before wiring the store."""

from autoforge_execution.compaction import CompactionPolicy, ContextCompactor
from autoforge_execution.models import (
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)


def hist(n: int = 8):
    return [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"iter {i} plan",
            changed_files=[],
            passed=False,
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED, failures=[f"f{i}"]
            ),
        )
        for i in range(1, n + 1)
    ]


c = ContextCompactor(CompactionPolicy(enabled=True))
h = hist()
a = c.compact(task_id="t", prior_iterations=h)
b = c.compact(task_id="t", prior_iterations=h)

print("baseline identity equal      :", a.logical_identity() == b.logical_identity())

a.duration_ms = 0.400
b.duration_ms = 0.900
print("duration differs -> equal    :", a.logical_identity() == b.logical_identity())
print("content_digest still equal   :", a.content_digest() == b.content_digest())
print("as_dict carries identity    :", "logical_identity" in a.as_dict())

other_task = c.compact(task_id="t2", prior_iterations=h)
print("different task -> differ     :", a.logical_identity() != other_task.logical_identity())

changed = c.compact(task_id="t", prior_iterations=h[:6])
print("different content -> differ  :", a.logical_identity() != changed.logical_identity())

# The identity must be self-consistent (not self-referential).
print("identity stable on recompute :", a.logical_identity() == a.logical_identity())
print("payload identity == method   :",
      a.as_dict()["logical_identity"] == a.logical_identity())
