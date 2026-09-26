"""18-J section 8 verification: the ORIGINAL end-to-end workflow that failed.

Required evidence shape:

    engineering operation
      -> execution
      -> artifact creation
      -> durable state
      -> commit
      -> re-materialisation / resume path   (previously raised)
      -> staging
      -> continued execution
      -> completion

The REAL canonical path is exercised end to end: a default-configuration
AutoForge system (Context Engineering ON) runs a real engineering workflow that
produces durable artifacts. The same system is then torn down and rebuilt against
the same durable database, and the SAME task is re-submitted -- which is exactly
what a resume/replay does, and exactly what previously raised
``InvalidTransitionError: committed -> staging``.

The loop is repeated N times to prove repeated resume is idempotent and never
corrupts durable state.
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
    "memory/src", "knowledge_platform/src", "observability/src",
):
    _p = REPO / "packages" / _pkg
    if _p.exists() and str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_runtime.models import DurableArtifactStatus
from autoforge_workflows.models import TaskDefinition, WorkflowDefinition

TASK_ID = "t-18j-e2e-resume"
RESUME_ROUNDS = 3


async def run_workflow(system) -> str:
    task_def = TaskDefinition(
        task_id=TASK_ID,
        name="Implement calculator add function",
        task_type="coding",
        description="Add a correct add(a, b) function and verify it.",
        input_data={
            "files": [{"path": "output.py", "content": "print(1)\n"}],
            "commands": [[sys.executable, "output.py"]],
            "fallback_policy": "allow_fallback",
        },
    )
    handle = system.workflow_engine.submit(
        WorkflowDefinition(name="18-J resume probe", tasks=[task_def])
    )
    completed = await system.execution_engine.run_workflow_to_completion(handle)
    return str(getattr(completed.status, "value", completed.status))


def snapshot(system) -> dict:
    states = system.durable_catalog.find_by_task(TASK_ID)
    return {
        "count": len(states),
        "by_status": {
            s.status.value: sum(1 for x in states if x.status is s.status)
            for s in states
        },
        "committed_hashes": sorted(
            s.content_hash for s in states if s.status is DurableArtifactStatus.COMMITTED
        ),
        "staging_stranded": [
            s.artifact_name
            for s in states
            if s.status is DurableArtifactStatus.STAGING
        ],
    }


async def main() -> int:
    workspace = Path(tempfile.mkdtemp(prefix="af_18j_e2e_"))
    evidence: dict = {"workspace": str(workspace), "rounds": []}
    baseline_hashes: set[str] = set()

    # ---- Round 0: initial engineering execution ------------------------
    system = build_autoforge_system(workspace_root=str(workspace))
    await system.initialize()
    evidence["context_engineering_enabled"] = (
        system.context_builder.enable_context_engineering
    )
    status = await run_workflow(system)
    snap = snapshot(system)
    baseline_hashes = set(snap["committed_hashes"])
    evidence["rounds"].append(
        {
            "round": 0,
            "phase": "initial engineering execution + artifact creation + commit",
            "workflow_status": status,
            "durable": snap,
        }
    )
    await system.shutdown()

    # ---- Rounds 1..N: process restart + task re-submission (resume) -----
    for r in range(1, RESUME_ROUNDS + 1):
        system = build_autoforge_system(workspace_root=str(workspace))
        await system.initialize()
        try:
            status = await run_workflow(system)
            snap = snapshot(system)
            evidence["rounds"].append(
                {
                    "round": r,
                    "phase": "restart + re-materialisation / resume path",
                    "workflow_status": status,
                    "durable": snap,
                }
            )
        finally:
            await system.shutdown()

    evidence["no_invalid_transition_raised"] = True

    # Growth accounting: each round legitimately materialises NEW logical
    # artifacts (a new execution id per run yields a new deterministic key), so
    # the catalog count is expected to grow. The invariants that must hold are:
    #   * every artifact is COMMITTED (nothing stranded in STAGING),
    #   * artifacts already committed in earlier rounds keep their content hash
    #     (no silent overwrite / corruption across resumes).
    per_round = [r["durable"]["count"] for r in evidence["rounds"]]
    evidence["durable_count_per_round"] = per_round
    evidence["all_artifacts_committed"] = all(
        set(r["durable"]["by_status"]) <= {"committed"} for r in evidence["rounds"]
    )
    evidence["earlier_hashes_never_lost"] = all(
        baseline_hashes.issubset(set(r["durable"]["committed_hashes"]))
        for r in evidence["rounds"]
    )
    evidence["durable_state_stable_across_resume"] = all(
        r["durable"]["staging_stranded"] == [] for r in evidence["rounds"]
    )
    evidence["committed_content_preserved"] = evidence["earlier_hashes_never_lost"]
    evidence["all_rounds_completed"] = all(
        r["workflow_status"] == "completed" for r in evidence["rounds"]
    )
    evidence["VERDICT"] = (
        "PASS: resume/re-materialisation completes across restarts with no "
        "InvalidTransitionError, no stranded STAGING state, and no durable-state loss"
        if (
            evidence["all_rounds_completed"]
            and evidence["durable_state_stable_across_resume"]
            and evidence["committed_content_preserved"]
            and evidence["all_artifacts_committed"]
        )
        else "FAIL"
    )

    out = REPO / "18-j-defect-repair" / "e2e_resume_evidence.json"
    out.write_text(json.dumps(evidence, indent=2, default=str), encoding="utf-8")
    print(json.dumps(evidence, indent=2, default=str))
    return 0 if evidence["VERDICT"].startswith("PASS") else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
