"""Why does a STABLE compaction_id still produce differing persisted content?

C-3 makes the fingerprint stable, so retries now land on the same artifact key
(18-J idempotent replay). The store then reports differing content. This isolates
exactly which serialized field varies between two otherwise-identical compactions.
"""

import json
import tempfile
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.compaction import CompactionPolicy, ContextCompactor
from autoforge_execution.models import (
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition


def hist(n: int = 8):
    return [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"iteration {i}: investigate the connection pool timeout",
            changed_files=[f"src/pool_{i}.py"],
            passed=False,
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED,
                failures=[f"test_pool_timeout::FAILED at iteration {i}"],
            ),
        )
        for i in range(1, n + 1)
    ]


def flatten(obj, prefix=""):
    out = {}
    if isinstance(obj, dict):
        for k, v in obj.items():
            out.update(flatten(v, f"{prefix}.{k}" if prefix else str(k)))
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            out.update(flatten(v, f"{prefix}[{i}]"))
    else:
        out[prefix] = obj
    return out


def main() -> None:
    ws = Path(tempfile.mkdtemp(prefix="c3_diff_"))
    c = ContextCompactor(CompactionPolicy(enabled=True))
    a = c.compact(task_id="t-diff", prior_iterations=hist())
    b = c.compact(task_id="t-diff", prior_iterations=hist())

    print("same compaction_id   :", a.compaction_id == b.compaction_id)
    print("same fingerprint     :", a.request_fingerprint == b.request_fingerprint)
    print("same content_digest  :", a.content_digest() == b.content_digest())
    print()

    fa, fb = flatten(a.as_dict()), flatten(b.as_dict())
    differing = [k for k in set(fa) | set(fb) if fa.get(k) != fb.get(k)]
    print(f"SERIALIZED FIELDS THAT DIFFER ({len(differing)}):")
    for k in sorted(differing):
        print(f"  {k}: {fa.get(k)!r}  ->  {fb.get(k)!r}")
    print()
    print("fields present in the PERSISTED payload:", len(fa))


main()
