"""Gate 1 evidence: how context actually accumulates, and where the gaps are.

Read-only probes. No production code is modified.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
for _pkg in (
    "execution/src", "composition/src", "workflows/src", "ai_infrastructure/src",
    "runtime/src", "events/src", "event_platform/src", "kernel/src",
    "artifacts/src", "security/src", "models/src", "connectors/src",
    "knowledge_platform/src", "observability/src",
):
    _p = REPO / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition


def task() -> TaskDefinition:
    return TaskDefinition(
        task_id="t-cc-gate1",
        name="Repair retry backoff",
        task_type="coding",
        description="The backoff helper returns the wrong delay sequence.",
        input_data={},
    )


def iterations(n: int) -> list[LoopIterationRecord]:
    return [
        LoopIterationRecord(
            iteration=i,
            action_plan=f"attempt plan {i}",
            changed_files=[f"src/mod_{i}.py"],
            passed=(i % 2 == 0),
            evaluation=EvaluationResult(
                status=EvaluationStatus.FAILED,
                failures=[f"test_{i}::FAILED expected [1,2,4,8] got [1,2,4,4]"],
            ),
            diagnosis=DiagnosisReport(
                root_cause=f"root cause {i}",
                failure_mechanism=f"mechanism {i}",
                affected_files=[f"src/mod_{i}.py"],
                suggested_fix=f"fix {i}",
            ),
        )
        for i in range(1, n + 1)
    ]


async def main() -> int:
    ws = Path(tempfile.mkdtemp(prefix="af_cc_gate1_"))
    (ws / "svc.py").write_text("X = 1\n", encoding="utf-8")
    system = build_autoforge_system(workspace_root=str(ws))
    out: dict = {
        "context_engineering_enabled": system.context_builder.enable_context_engineering
    }

    # --- Probe 1: does the CE pipeline surface ALL prior iterations? --------
    hist = iterations(6)
    ctx = await system.context_builder.assemble_context(
        task_def=task(),
        workspace_root=ws,
        prior_iterations=hist,
        last_evaluation=hist[-1].evaluation,
        last_diagnosis=hist[-1].diagnosis,
        context_window_tokens=32768,
    )
    rec = ctx.context_assembly_record
    out["probe_prior_iterations"] = {
        "iterations_supplied": len(hist),
        "iterations_retained_on_context": len(ctx.prior_iterations),
        "context_items_selected": rec.selected_count,
        "selected_categories": sorted({e.category for e in rec.selected}),
        "selected_ids": [e.context_id for e in rec.selected],
        "distinct_iterations_represented": sum(
            1
            for e in rec.selected
            if any(f"iteration {i}" in (e.context_id or "") for i in range(1, 7))
        ),
        "note": "Only the LAST evaluation/diagnosis become items; intermediate "
                "iterations are carried on ExecutionContext but not projected "
                "into the MSC candidate set.",
    }

    # --- Probe 2: what does the legacy prompt do with history? -------------
    payload = ctx.format_reasoning_prompt(7)
    out["probe_legacy_payload"] = {
        "keys": sorted(payload.keys()),
        "prior_attempts_count": len(payload.get("prior_attempts", [])),
        "note": "The legacy payload enumerates every prior attempt in full, "
                "with no budget applied. This is the unbounded growth path.",
    }

    # --- Probe 3: is accumulated history durable across restart? ------------
    out["probe_durability"] = {
        "memory_engine": "KernelMemoryEngineAdapter._local_memories "
                         "(in-process dict; not durable, lost on restart)",
        "loop_iterations": "held in-process on EngineeringLoop._iterations and "
                           "ExecutionContext.prior_iterations",
        "durable_anchors": [
            "DurableExecutionStore (18-J): execution/attempt/checkpoint state",
            "DurableArtifactCatalog (18-K): committed artifacts + content hashes",
            "CheckpointManager: named state snapshots",
            "Event Platform: canonical events",
        ],
    }

    # --- Probe 4: does any component already compact/summarise? -----------
    out["probe_existing_compaction"] = {
        "found": "none on the canonical engineering path",
        "adjacent": [
            "research_brief_generator (knowledge_platform) — a different concern",
            "assemble_evidence() — string formatting, not compaction",
            "ContextWindowBudget — budget enforcement, not compaction",
        ],
        "note": "Budgeting already DROPS items when over budget "
                "(exclusion reason 'budget_exhausted'), which silently loses "
                "history rather than compacting it.",
    }

    dest = REPO / "context-compaction-gate1" / "gate1_probe_evidence.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out, indent=2, default=str), encoding="utf-8")
    print(json.dumps(out, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
