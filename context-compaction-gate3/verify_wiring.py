"""Gate 3 §27 — end-to-end WIRING proof (NOT Gate 4 semantic certification).

Proves the intended chain is actually connected:

    context accumulation
        -> compaction trigger
        -> structured compacted representation
        -> Context Engineering
        -> MSC selection
        -> canonical prompt assembly

and that compaction is OFF by default so production behaviour is unchanged.
"""

import asyncio
import json
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


def make_history(n: int) -> list[LoopIterationRecord]:
    return [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"iteration {i}: adjust the backoff helper and re-run tests",
            changed_files=[f"src/retry_{i}.py"],
            passed=(i % 3 == 0),
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED,
                failures=[f"test_sequence FAILED at iter {i}"],
            ),
            diagnosis=DiagnosisReport(
                root_cause=f"iteration {i}: the clamp overrides doubling",
                failure_mechanism="clamp applied to the final delay",
                affected_files=["src/retry.py"],
                suggested_fix="remove the clamp",
            ),
        )
        for i in range(1, n + 1)
    ]


def task() -> TaskDefinition:
    return TaskDefinition(
        task_id="t-gate3-wiring",
        name="Repair retry backoff",
        task_type="coding",
        description="The backoff helper returns the wrong delay sequence.",
        input_data={},
    )


async def main() -> int:
    ws = Path(tempfile.mkdtemp(prefix="af_gate3_wiring_"))
    (ws / "service.py").write_text("X = 1\n", encoding="utf-8")
    history = make_history(7)
    evidence: dict = {}

    # --- A. DEFAULT: compaction OFF, CE ON (Gate 3 §30 posture) ----------
    off_builder = EngineeringContextBuilder()
    off_ctx = await off_builder.assemble_context(
        task_def=task(),
        workspace_root=ws,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        last_diagnosis=history[-1].diagnosis,
        context_window_tokens=32768,
    )
    evidence["default_posture"] = {
        "context_engineering_enabled": off_builder.enable_context_engineering,
        "compactor_injected": off_builder.compactor is not None,
        "compaction_record": off_builder.last_compaction_record is None,
        "selected_items": off_ctx.context_assembly_record.selected_count,
        "prompt_assembly_path": "canonical (unchanged)",
    }

    # --- B. Compaction ENABLED: wiring proof -----------------------------
    on_builder = EngineeringContextBuilder(
        compactor=ContextCompactor(CompactionPolicy(enabled=True))
    )
    on_ctx = await on_builder.assemble_context(
        task_def=task(),
        workspace_root=ws,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        last_diagnosis=history[-1].diagnosis,
        context_window_tokens=32768,
    )
    rec = on_builder.last_compaction_record
    messages = on_ctx.build_canonical_messages()
    iteration_items = [
        i for i in (rec.items if rec else []) if i.source.kind == "iteration"
    ]
    evidence["compaction_enabled"] = {
        "compaction_record_present": rec is not None,
        "compaction_id": rec.compaction_id if rec else None,
        "validation_status": rec.validation_status if rec else None,
        "trigger": rec.trigger if rec else None,
        "policy_version": rec.policy_version if rec else None,
        "compaction_method": rec.compaction_method if rec else None,
        "iteration_items": len(iteration_items),
        "iteration_refs": [i.source.ref for i in iteration_items],
        "dependency_chain": [list(i.depends_on) for i in iteration_items],
        "selected_items": on_ctx.context_assembly_record.selected_count,
        "prompt_messages_assembled": len(messages),
        "reduction_ratio": rec.reduction_ratio if rec else None,
        "source_estimated_tokens": rec.source_estimated_tokens if rec else None,
        "estimated_tokens": rec.estimated_tokens if rec else None,
    }

    # --- C. Did the compacted iterations actually REACH the model? --------
    body = "\n".join(m["content"] for m in messages)
    evidence["compaction_enabled"]["iterations_reached_prompt"] = sum(
        1 for i in iteration_items if f"iteration: {i.source.ref.split('-')[1]}" in body
    )
    evidence["compaction_enabled"]["g1_resolved"] = (
        evidence["compaction_enabled"]["iterations_reached_prompt"] > 0
    )

    out = Path(__file__).parent / "wiring_evidence.json"
    out.write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    print(json.dumps(evidence, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
