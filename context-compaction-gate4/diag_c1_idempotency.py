"""Characterise the production workspace/compaction-store interaction.

Each production compaction persists into <workspace>/artifacts, which the
Context Engineering workspace scan then discovers and feeds into the candidate
pool — which changes the compaction fingerprint. This measures how that feedback
settles, so the behaviour is reported accurately rather than assumed.
"""

import asyncio
import tempfile
from pathlib import Path

from autoforge_composition.composition_root import build_autoforge_system
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


async def main() -> None:
    ws = Path(tempfile.mkdtemp())
    task = TaskDefinition(
        task_id="diag-1", name="d", task_type="coding", description="d", input_data={}
    )

    print(f"{'run':>4} {'items':>6} {'proj_files':>11} {'artifacts':>10}  compaction_id")
    for run in range(1, 13):
        system = build_autoforge_system(
            workspace_root=str(ws), config={"enable_context_compaction": True}
        )
        h = hist()
        ctx = await system.context_builder.assemble_context(
            task_def=task,
            workspace_root=ws,
            prior_iterations=h,
            last_evaluation=h[-1].evaluation,
            context_window_tokens=32768,
        )
        rec = system.context_builder.last_compaction_record
        artifacts = len(
            [p for p in (ws / "artifacts").glob("compaction_*") if p.is_file()]
        )
        print(
            f"{run:>4} {rec.item_count:>6} {len(ctx.project_files):>11} "
            f"{artifacts:>10}  {rec.compaction_id}"
        )


asyncio.run(main())
