"""
C-3 §4 — reproduce the workspace/compaction feedback path BEFORE any fix.

Establishes, from source rather than from report prose, whether a durable
CompactionRecordStore artifact actually enters the ordinary Context Engineering
candidate set, and exactly how it perturbs the candidate inputs.
"""

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

OUT = Path(__file__).parent / "c3_candidate_inventory.json"


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


def make_task(tid: str) -> TaskDefinition:
    return TaskDefinition(
        task_id=tid, name="C-3 probe", task_type="coding",
        description="Workspace boundary probe.", input_data={},
    )


def workspace_item(ctx):
    for item in getattr(ctx, "selected_context_items", []) or []:
        if item.source.kind == "workspace":
            return item
    return None


async def cycle(ws: Path, label: str, evidence: list) -> dict:
    system = build_autoforge_system(
        workspace_root=str(ws), config={"enable_context_compaction": True}
    )
    task = make_task("c3-repro")
    h = hist()
    ctx = await system.context_builder.assemble_context(
        task_def=task,
        workspace_root=ws,
        prior_iterations=h,
        last_evaluation=h[-1].evaluation,
        context_window_tokens=32768,
    )
    rec = system.context_builder.last_compaction_record
    witem = workspace_item(ctx)
    row = {
        "cycle": label,
        "candidate_count": len(getattr(ctx, "selected_context_items", []) or []),
        "project_files": sorted(ctx.project_files or []),
        "workspace_item_context_id": witem.context_id if witem else None,
        "compaction_id": rec.compaction_id if rec else None,
        "fingerprint": rec.request_fingerprint if rec else None,
        "items": rec.item_count if rec else None,
        "persisted": system.context_builder.last_compaction_artifact_id,
    }
    evidence.append(row)
    return row


async def main() -> None:
    ws = Path(tempfile.mkdtemp(prefix="c3_repro_"))

    # Representative ORDINARY engineering artifacts, present from the start.
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "service.py").write_text("X = 1\n", encoding="utf-8")
    (ws / "README.md").write_text("# Project\n", encoding="utf-8")
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "design.md").write_text("# Design\n", encoding="utf-8")
    (ws / "tests").mkdir(exist_ok=True)
    (ws / "tests" / "evidence.json").write_text('{"result": "pass"}\n', encoding="utf-8")

    evidence: list[dict] = []
    rows = [await cycle(ws, f"cycle_{i}", evidence) for i in range(1, 5)]

    print(f"{'cycle':>8} {'cands':>6} {'projfiles':>10} {'items':>6}  compaction_id")
    for r in rows:
        print(f"{r['cycle']:>8} {r['candidate_count']:>6} "
              f"{len(r['project_files']):>10} {r['items']:>6}  {r['compaction_id']}")

    compaction_paths = sorted(
        p for p in rows[-1]["project_files"] if "compaction_cmp_" in p
    )
    first, second = rows[0], rows[1]
    new_ids = sorted(set(second["project_files"]) - set(first["project_files"]))

    print()
    print("LEAK CONFIRMED:" if compaction_paths else "NO LEAK")
    print(f"  compaction artifacts inside CE project_files: {compaction_paths}")
    print(f"  new project_files after first persist        : {new_ids}")
    print(f"  workspace item context_id cycle1 -> cycle2   : "
          f"{first['workspace_item_context_id']} -> "
          f"{second['workspace_item_context_id']}")
    print(f"  fingerprint changed cycle1 -> cycle2        : "
          f"{first['fingerprint'] != second['fingerprint']}")
    print()
    print("ordinary artifacts still discovered:",
          [p for p in rows[-1]["project_files"] if not p.startswith("artifacts/")][:8])

    OUT.write_text(
        json.dumps({
            "reproduced": bool(compaction_paths),
            "compaction_paths_in_candidates": compaction_paths,
            "new_project_files_after_persist": new_ids,
            "cycles": evidence,
        }, indent=2),
        encoding="utf-8",
    )
    print(f"wrote {OUT.name}")


asyncio.run(main())
