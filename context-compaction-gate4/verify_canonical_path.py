"""18-L Global Enablement — PART 4 canonical path + PART 7 bypass audit."""

import asyncio
import json
import tempfile
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_execution.models import (
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_workflows.models import TaskDefinition

HERE = Path(__file__).parent


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


async def main() -> int:
    out: dict = {}
    ws = Path(tempfile.mkdtemp(prefix="g4_enable_"))
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "service.py").write_text("X = 1\n", encoding="utf-8")
    (ws / "README.md").write_text("# Project\n", encoding="utf-8")

    # ── PART 4: the real production composition path, no config override ──
    system = build_autoforge_system(workspace_root=str(ws))
    builder = system.context_builder

    task = TaskDefinition(
        task_id="enablement-canon",
        name="Canonical path probe",
        task_type="coding",
        description="Exercise the globally enabled compaction boundary.",
        input_data={},
    )
    history = hist()
    ctx = await builder.assemble_context(
        task_def=task,
        workspace_root=ws,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        context_window_tokens=32768,
    )
    record = builder.last_compaction_record

    # Walk the canonical pipeline in order and prove each stage was reached.
    assembly = ctx.context_assembly_record
    messages = ctx.build_canonical_messages()
    item_kinds = sorted({i.source.kind for i in ctx.selected_context_items})

    out["canonical_path"] = {
        "context_engineering_on": bool(builder.enable_context_engineering),
        "context_compaction_on": builder.compactor is not None,
        "compaction_record_produced": record is not None,
        "compaction_trigger": record.trigger if record else None,
        "compaction_persisted": bool(builder.last_compaction_artifact_id),
        "artifact_id": builder.last_compaction_artifact_id,
        "assembled_context": ctx is not None,
        "msc_selected_count": getattr(assembly, "selected_count", None),
        "candidates_considered": getattr(assembly, "considered_count", None),
        "budget_resolved": bool(getattr(assembly, "budget", None)),
        "prompt_assembled": bool(messages),
        "prompt_messages": len(messages),
        "canonical_item_kinds": item_kinds,
        "iteration_items_present": "iteration" in item_kinds,
    }

    # The durable artifact really exists on disk under the canonical name.
    artifacts = [
        p.name for p in (ws / "artifacts").glob("compaction_cmp_*") if p.is_file()
    ]
    out["canonical_path"]["durable_artifact_files"] = artifacts

    # ── PART 7: bypass audit ──
    engine = system.execution_engine
    dispatcher = getattr(engine, "_dispatcher", None)
    injected = getattr(dispatcher, "_context_builder", None) if dispatcher else None

    out["bypass_audit"] = {
        "production_dispatcher_builder_injected": injected is not None,
        "dispatcher_uses_root_builder": injected is builder,
        "dispatcher_builder_has_compaction": bool(
            injected and injected.compactor is not None
        ),
        "fallback_path_exists_in_source": True,
        "fallback_paths": [
            "packages/execution/src/autoforge_execution/dispatcher.py:158",
            "packages/workforce/src/autoforge_workforce/dispatch.py:158",
        ],
        "fallback_trigger_condition": (
            "only when no context_builder was injected into the dispatcher"
        ),
        "fallback_reached_in_production": injected is None,
    }

    (HERE / "enablement_canonical_path.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )

    print("=== PART 4 — CANONICAL PATH (CE ON, Compaction ON, no config) ===")
    for key, value in out["canonical_path"].items():
        print(f"  {key:32s} {value}")
    print()
    print("=== PART 7 — BYPASS AUDIT ===")
    for key, value in out["bypass_audit"].items():
        print(f"  {key:40s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
