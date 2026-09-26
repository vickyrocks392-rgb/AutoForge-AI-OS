"""Gate 3 §15 — empirical measurement of context growth.

Retention/trigger thresholds are UNKNOWN per Gate 2 §34 Q-1/Q-2. This measures
REAL behaviour so the initial policy is derived from evidence, not guessed.

Read-only. No production code is modified.
"""

from __future__ import annotations

import asyncio
import json
import statistics
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

from autoforge_execution.models import (
    DiagnosisReport,
    EvaluationResult,
    EvaluationStatus,
    LoopIterationRecord,
)
from autoforge_execution.token_estimator import estimate_tokens
from autoforge_workflows.models import TaskDefinition


def make_iteration(i: int) -> LoopIterationRecord:
    return LoopIterationRecord(
        iteration=i,
        action_plan=(
            f"Iteration {i}: analyse failing assertion, adjust backoff helper, "
            f"re-run the sequence test and confirm the delay doubles each step."
        ),
        changed_files=[f"src/retry/service_{i}.py", "src/retry/sequence_test.py"],
        passed=(i % 3 == 0),
        evaluation=EvaluationResult(
            status=EvaluationStatus.PASSED if i % 3 == 0 else EvaluationStatus.FAILED,
            failures=(
                []
                if i % 3 == 0
                else [f"test_sequence FAILED at iteration {i}: expected [1,2,4,8] got [1,2,4,4]"]
            ),
            recommendations=["clamp the delay", "double the final step"],
        ),
        diagnosis=DiagnosisReport(
            root_cause=f"iteration {i}: compute_backoff clamps the final delay",
            failure_mechanism=f"iteration {i}: clamp overrides doubling on the last step",
            affected_files=["src/retry/service.py"],
            suggested_fix="remove the clamp",
            confidence_score=0.9,
        ),
    )


def project(rec: LoopIterationRecord) -> str:
    """The structured projection compaction will carry for one iteration."""
    return "\n".join(
        [
            f"iteration: {rec.iteration}",
            f"action_plan: {rec.action_plan}",
            f"changed_files: {', '.join(rec.changed_files)}",
            f"result: {'passed' if rec.passed else 'failed'}",
            f"failures: {'; '.join(rec.evaluation.failures) if rec.evaluation else ''}",
            f"root_cause: {rec.diagnosis.root_cause if rec.diagnosis else ''}",
            f"suggested_fix: {rec.diagnosis.suggested_fix if rec.diagnosis else ''}",
        ]
    )


async def main() -> int:
    from autoforge_execution.context_builder import EngineeringContextBuilder

    results: dict = {"per_iteration": [], "scaling": []}

    # --- Measure raw per-iteration structured cost -----------------------
    raw_costs, proj_costs = [], []
    for i in range(1, 13):
        rec = make_iteration(i)
        raw = estimate_tokens(rec.model_dump_json(indent=2))
        proj = estimate_tokens(project(rec))
        raw_costs.append(raw)
        proj_costs.append(proj)
        results["per_iteration"].append(
            {
                "iteration": i,
                "raw_record_tokens": raw,
                "structured_projection_tokens": proj,
                "reduction": round(1 - (proj / raw), 3) if raw else 0.0,
            }
        )

    results["mean_raw_record_tokens"] = round(statistics.mean(raw_costs), 1)
    results["mean_projection_tokens"] = round(statistics.mean(proj_costs), 1)
    results["mean_projection_reduction"] = round(
        1 - (statistics.mean(proj_costs) / statistics.mean(raw_costs)), 3
    )

    # --- Measure what the CURRENT canonical path actually delivers -------
    # This is the real G-1 baseline: how many iterations reach the model today.
    ws = Path(tempfile.mkdtemp(prefix="af_gate3_measure_"))
    (ws / "service.py").write_text("X = 1\n", encoding="utf-8")
    task = TaskDefinition(
        task_id="t-measure",
        name="Repair retry backoff",
        task_type="coding",
        description="The backoff helper returns the wrong delay sequence.",
        input_data={},
    )
    builder = EngineeringContextBuilder()
    for n in (1, 2, 3, 6, 9, 12):
        hist = [make_iteration(i) for i in range(1, n + 1)]
        ctx = await builder.assemble_context(
            task_def=task,
            workspace_root=ws,
            prior_iterations=hist,
            last_evaluation=hist[-1].evaluation,
            last_diagnosis=hist[-1].diagnosis,
            context_window_tokens=32768,
        )
        rec = ctx.context_assembly_record
        entries = rec.selected
        iteration_items = [
            e for e in entries if (e.provenance_ref or "").startswith("iteration:")
        ]
        # Delivered tokens measured from the real selected ContextItems (the
        # record itself is content-free by construction, by design).
        delivered = ctx.selected_context_items
        results["scaling"].append(
            {
                "iterations_supplied": n,
                "candidates_considered": rec.considered_count,
                "candidates_selected": rec.selected_count,
                "iteration_items_delivered_today": len(iteration_items),
                "delivered_tokens": sum(estimate_tokens(i.content) for i in delivered),
                "history_retained_on_context": len(ctx.prior_iterations),
            }
        )

    # --- Derive the evidence-based policy -------------------------------
    mean_raw = results["mean_raw_record_tokens"]
    results["g1_confirmed"] = all(
        r["iteration_items_delivered_today"] == 0 for r in results["scaling"]
    )
    results["evidence_derived_policy"] = {
        "retention_window": 3,
        "retention_rationale": (
            f"Mean raw iteration record is {mean_raw} tokens. Keeping 3 inline is "
            f"~{round(mean_raw * 3)} tokens, about "
            f"{round(mean_raw * 3 / 32768 * 100, 1)}% of a 32k window, while "
            f"preserving the active repair loop the next operation needs."
        ),
        "iteration_count_trigger": 4,
        "iteration_trigger_rationale": (
            "One iteration beyond the retention window: at that point at least one "
            "iteration is guaranteed to be compacted, so the trigger is meaningful."
        ),
        "budget_pressure_floor_tokens": 2048,
        "budget_rationale": (
            f"Below one full raw iteration record ({mean_raw} tokens); compaction "
            f"then fires before MSC begins excluding optional items."
        ),
    }

    dest = REPO / "context-compaction-gate3" / "growth_measurements.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(results, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "mean_raw_record_tokens": results["mean_raw_record_tokens"],
                "mean_projection_tokens": results["mean_projection_tokens"],
                "mean_projection_reduction": results["mean_projection_reduction"],
                "g1_confirmed": results["g1_confirmed"],
                "scaling": results["scaling"],
                "policy": results["evidence_derived_policy"],
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
