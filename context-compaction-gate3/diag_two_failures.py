"""Diagnose the two failing compaction assumptions."""

import asyncio
import tempfile
from pathlib import Path

from autoforge_execution.compaction import CompactionPolicy, ContextCompactor
from autoforge_execution.context_builder import EngineeringContextBuilder
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition


def make_iteration(i):
    return LoopIterationRecord(
        iteration=i,
        action_plan=f"iteration {i}: adjust backoff",
        changed_files=[f"f{i}.py"],
        passed=False,
        evaluation=EvaluationResult(
            status=EvaluationStatus.FAILED, failures=[f"test {i} FAILED"]
        ),
        diagnosis=DiagnosisReport(
            root_cause=f"rc {i}", failure_mechanism="m",
            affected_files=["a.py"], suggested_fix="fix",
        ),
    )


def task():
    return TaskDefinition(
        task_id="t-diag", name="Repair backoff", task_type="coding",
        description="wrong delay", input_data={},
    )


async def main():
    ws = Path(tempfile.mkdtemp())
    (ws / "s.py").write_text("X=1\n")
    hist = [make_iteration(i) for i in range(1, 8)]

    b = EngineeringContextBuilder(compactor=ContextCompactor(CompactionPolicy(enabled=True)))
    ctx = await b.assemble_context(
        task_def=task(), workspace_root=ws, prior_iterations=hist,
        last_evaluation=hist[-1].evaluation, last_diagnosis=hist[-1].diagnosis,
        context_window_tokens=32768,
    )
    rec = b.last_compaction_record
    print("compaction items:", rec.item_count)
    print("required items in record:", sum(1 for i in rec.items if i.required))
    print()
    print("SELECTED (record is content-free):")
    for e in ctx.context_assembly_record.selected:
        print("   ", e.context_id, "|", e.category, "|", e.provenance_ref)
    print()
    print("selected_context_items (real items):")
    for i in ctx.selected_context_items:
        print("   ", i.source.kind, ":", i.source.ref, "| required:", i.required)


asyncio.run(main())
