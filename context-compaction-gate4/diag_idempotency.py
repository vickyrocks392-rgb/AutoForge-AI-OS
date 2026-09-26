"""Investigate the 'different_source_distinct_id' idempotency finding."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from corpus import build_corpus  # noqa: E402

from autoforge_execution.compaction import (  # noqa: E402
    CompactionPolicy,
    ContextCompactor,
)

ENABLED = CompactionPolicy(enabled=True)
case = build_corpus()[0]

full = ContextCompactor(ENABLED).compact(
    task_id=case.task.task_id, prior_iterations=case.history
)
# Case A has 2 iterations; retention window is 3, so history[:2] == history.
fewer = ContextCompactor(ENABLED).compact(
    task_id=case.task.task_id, prior_iterations=case.history[:2]
)
print("case:", case.name, "iterations:", len(case.history))
print("full  id:", full.compaction_id, "items:", full.item_count)
print("fewer id:", fewer.compaction_id, "items:", fewer.item_count)
print("ids equal:", full.compaction_id == fewer.compaction_id)
print("fingerprints equal:", full.request_fingerprint == fewer.request_fingerprint)
print()
print("source_context_ids (full ):", full.provenance.source_context_ids)
print("source_context_ids (fewer):", fewer.provenance.source_context_ids)
print()
print("ISSUES:")
print("  case A history[:2] is the same list as history (2 iters < retention 3)")
print("  => the 'different source' probe was not actually different for A-H")
print("  => for I (12 iters) and J (8 iters) it IS genuinely different")
print("  I id:", ContextCompactor(ENABLED).compact(task_id='t-I', prior_iterations=build_corpus()[8].history).compaction_id)
print("  I[:2] id:", ContextCompactor(ENABLED).compact(task_id='t-I', prior_iterations=build_corpus()[8].history[:2]).compaction_id)
