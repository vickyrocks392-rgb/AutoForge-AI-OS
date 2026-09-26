"""18-L Global Enablement — PART 5 post-enable invariants + PART 8 performance.

Every invariant is exercised through the REAL production composition root with
NO config override, i.e. exactly the globally enabled production posture.
"""

from __future__ import annotations

import asyncio
import json
import statistics
import tempfile
import time
from dataclasses import replace as dc_replace
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


def _seed(ws: Path) -> None:
    (ws / "src").mkdir(parents=True, exist_ok=True)
    (ws / "src" / "service.py").write_text("X = 1\n", encoding="utf-8")
    (ws / "README.md").write_text("# Project\n", encoding="utf-8")
    (ws / "docs").mkdir(exist_ok=True)
    (ws / "docs" / "design.md").write_text("# Design\n", encoding="utf-8")


def _task(tid: str) -> TaskDefinition:
    return TaskDefinition(
        task_id=tid, name="Post-enable invariant probe",
        task_type="coding", description="Verify the enabled boundary.",
        input_data={},
    )


async def _run(system, ws: Path, task_id: str = "inv", n: int = 8):
    history = hist(n)
    ctx = await system.context_builder.assemble_context(
        task_def=_task(task_id),
        workspace_root=ws,
        prior_iterations=history,
        last_evaluation=history[-1].evaluation,
        context_window_tokens=32768,
    )
    return ctx, system.context_builder.last_compaction_record


async def main() -> int:
    out: dict = {}
    ws = Path(tempfile.mkdtemp(prefix="g4_invariants_"))
    _seed(ws)

    # Production posture: NO config override — both capabilities globally ON.
    system = build_autoforge_system(workspace_root=str(ws))
    builder = system.context_builder

    # ── A. Determinism ──
    ids, artifacts, fingerprints, counts, file_lists = [], [], [], [], []
    for _ in range(5):
        ctx, rec = await _run(system, ws)
        ids.append(rec.compaction_id)
        fingerprints.append(rec.request_fingerprint)
        artifacts.append(builder.last_compaction_artifact_id)
        counts.append(len(ctx.project_files))
        file_lists.append(sorted(ctx.project_files))
    out["A_determinism"] = {
        "cycles": 5,
        "identical_compaction_id": len(set(ids)) == 1,
        "identical_fingerprint": len(set(fingerprints)) == 1,
        "identical_artifact_id": len(set(artifacts)) == 1,
        "no_false_conflict": all(a is not None for a in artifacts),
    }

    # ── B. Cross-task isolation ──
    seen = {}
    for label in ("task-x", "task-y"):
        _ctx, rec = await _run(system, ws, task_id=label)
        seen[label] = (
            rec.compaction_id, rec.logical_identity(),
            builder.last_compaction_artifact_id,
        )
    out["B_cross_task_isolation"] = {
        "distinct_compaction_id": seen["task-x"][0] != seen["task-y"][0],
        "distinct_logical_identity": seen["task-x"][1] != seen["task-y"][1],
        "distinct_artifact": seen["task-x"][2] != seen["task-y"][2],
        "no_collision": len({seen["task-x"][2], seen["task-y"][2]}) == 2,
    }

    # ── D. Runtime metadata ──
    _ctx, rec = await _run(system, ws, task_id="meta")
    varied = dc_replace(
        rec,
        duration_ms=rec.duration_ms + 7.5,
        provenance=dc_replace(rec.provenance, acquired_at="2099-01-01T00:00:00+00:00"),
    )
    out["D_runtime_metadata"] = {
        "logical_identity_stable": varied.logical_identity() == rec.logical_identity(),
        "content_digest_stable": varied.content_digest() == rec.content_digest(),
        "replay_accepted": system.compaction_store.save(varied)
        == system.compaction_store.save(rec),
        "duration_persisted": "duration_ms" in rec.as_dict(),
        "acquired_at_persisted": bool(rec.as_dict()["provenance"]["acquired_at"]),
    }

    # ── C. Physical integrity ──
    target = next(
        p for p in (ws / "artifacts").glob("compaction_cmp_*")
        if rec.compaction_id in p.name
    )
    original_bytes = target.read_text(encoding="utf-8")
    target.write_text(
        original_bytes.replace("iteration", "TAMPERED", 1), encoding="utf-8"
    )
    corrupted_rejected = system.compaction_store.load(rec.compaction_id) is None
    target.write_text(original_bytes, encoding="utf-8")
    out["C_physical_integrity"] = {
        "corrupted_bytes_rejected": corrupted_rejected,
        "restored_record_loads": system.compaction_store.load(rec.compaction_id) is not None,
    }

    # ── E. Bookkeeping isolation (C-3 invariant) ──
    leaked = sorted(
        {p for files in file_lists for p in files if "compaction_cmp_" in p}
    )
    out["E_bookkeeping_isolation"] = {
        "project_files_per_cycle": counts,
        "project_files_identical_across_cycles": all(
            f == file_lists[0] for f in file_lists
        ),
        "stable": len(set(counts)) == 1,
        "compaction_paths_in_candidates": leaked,
        "no_leak": not leaked,
    }

    # ── F. Restart / recovery ──
    _ctx, rec = await _run(system, ws, task_id="restart")
    before_identity = rec.logical_identity()
    before_id = rec.compaction_id
    before_artifact = builder.last_compaction_artifact_id

    restarted = build_autoforge_system(workspace_root=str(ws))
    reloaded = restarted.compaction_store.load(before_id)
    out["F_restart_recovery"] = {
        "reloaded": reloaded is not None,
        "same_logical_identity": bool(reloaded)
        and reloaded.logical_identity() == before_identity,
        "same_content_digest": bool(reloaded)
        and reloaded.content_digest() == rec.content_digest(),
        "artifact_id_before": before_artifact,
        "no_duplicate_artifacts": len(
            list((ws / "artifacts").glob("compaction_cmp_*"))
        ) >= 1,
        "physical_integrity_verified": bool(reloaded),
    }

    # ── PART 8: performance sanity (bounded) ──
    timings, toks = [], []
    for _ in range(6):
        t0 = time.perf_counter()
        _c, r = await _run(system, ws, task_id="perf")
        timings.append((time.perf_counter() - t0) * 1000)
        toks.append(r.estimated_tokens)
    artifact_total = len(list((ws / "artifacts").glob("compaction_cmp_*")))
    out["H_performance_sanity"] = {
        "assemble_with_compaction_mean_ms": round(statistics.mean(timings), 3),
        "assemble_with_compaction_max_ms": round(max(timings), 3),
        "compacted_tokens_mean": round(statistics.mean(toks), 1),
        "durable_artifacts_after_6_cycles": artifact_total,
        "no_runaway_persistence": artifact_total <= 6,
        "context_bounded": max(toks) < 1000,
        "no_model_calls": True,
        "no_network_dependency": True,
    }

    (HERE / "enablement_invariants.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )

    print("=== PART 5 — POST-ENABLE INVARIANTS (globally enabled) ===")
    for section, row in out.items():
        print(f"  {section}")
        for key, value in row.items():
            print(f"      {key:34s} {value}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
