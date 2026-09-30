"""
18-L-D :: VACUOUS-APPROVAL FAIL-OPEN PROBE (definitive)
======================================================

The failure-path suite showed that a project with NO reviewable deliverable
reaches ``finished``. This probe isolates WHY, with no mocks and no ambiguity,
so the finding is reported as evidence rather than as a hypothesis.

Claim under test:
    When the final review is handed an EMPTY evidence set, the Review Engine
    returns an explicit ``approved`` verdict via its documented ``no_target``
    branch, the Completion Module evaluates that approval as a real approval,
    and the project transitions to ``Finished`` -- despite having produced
    nothing at all.

This is exactly the condition the 18-L acceptance gate names:
    "Missing evidence blocks completion where review is mandatory."

Nothing here fabricates a verdict or forces a state. It only observes the real
ReviewEngine and the real DefaultCompletionModule.
"""

from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_EVIDENCE = _REPO / "18L-autonomous-certification" / "evidence"
_EVIDENCE.mkdir(parents=True, exist_ok=True)

for _pkg in [
    "events", "event_platform", "runtime", "models", "ai_infrastructure",
    "workflows", "execution", "artifacts", "review", "security", "connectors",
    "orchestration", "kernel", "composition", "workforce", "power_engines",
    "modernization", "observability", "persistence", "knowledge_platform",
]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))


async def main() -> int:
    from autoforge_review.models import ReviewRequest, ReviewEvidence
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    out: dict[str, Any] = {}

    # ── Part 1: what does the REAL ReviewEngine do with empty evidence? ─────
    from autoforge_review.engine import ReviewEngine
    engine = ReviewEngine()
    res = await engine.review(ReviewRequest(project_id=None, evidence=ReviewEvidence()))
    out["review_engine_empty_evidence"] = {
        "approved": getattr(res, "approved", None),
        "decision": str(getattr(res.decision, "value", res.decision)),
        "findings": [f.model_dump(mode="json") for f in res.findings],
    }
    print("REAL ReviewEngine on EMPTY evidence:",
          json.dumps(out["review_engine_empty_evidence"], indent=2)[:600])

    # ── Part 2: does a real project with no deliverable reach Finished? ────
    ws = Path(tempfile.mkdtemp(prefix="18L_vacuous_ws_"))
    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    try:
        res_in = await system.kernel.submit_request(
            Request(
                user_id=uuid.uuid4(),
                request_text="Build a validated service with tests",
                configuration={"environment": "production", "execute": False},
            )
        )
        pid = res_in["project_id"]

        # Produce NOTHING: the model is declared-unavailable.
        ai = system.execution_engine._ai

        async def _dead(*_a, **_k):
            from autoforge_ai_infrastructure.errors import ModelUnavailableError
            raise ModelUnavailableError("m6 runtime unreachable")

        ai.generate_plan = _dead
        ai.generate_implementation = _dead

        exec_res = await system.kernel.execute_project(pid)
        state = await system.runtime_facade.get_project_state(pid)
        raw = state.get("status")
        status = str(getattr(raw, "value", raw)).lower()

        gate = await system.kernel.completion_module._run_final_review(pid)
        out["platform_behaviour"] = {
            "execute_status": exec_res.get("status"),
            "final_project_status": status,
            "gate_approved": gate.get("approved"),
            "gate_reason": gate.get("reason"),
            "evidence_files": gate.get("evidence_files"),
            "reached_finished": status == "finished",
        }
        print("\nPLATFORM with NO deliverable:",
              json.dumps(out["platform_behaviour"], indent=2)[:800])
    finally:
        await system.shutdown()

    out["verdict"] = (
        "FAIL-OPEN CONFIRMED: empty evidence produced an explicit approval and "
        "the project reached Finished with no deliverable"
        if out["platform_behaviour"]["reached_finished"]
        else "no fail-open observed"
    )
    print("\nVERDICT:", out["verdict"])
    (_EVIDENCE / "vacuous_approval_probe.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
