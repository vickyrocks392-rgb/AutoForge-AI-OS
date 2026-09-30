"""
18-LR LAYER-B :: CANONICAL ARCHITECTURE INVOCATION OF THE FIVE ENGINES.

For each of the five Commercial Power Engines this asks a single question of
the REAL production path, with no mocks and no bypasses:

    Request -> Kernel.submit_request -> Intent -> Strategic Engine
        -> Executable Workflow -> O-2 (DefaultOrchestrationEngine)
        -> ??? Commercial Power Engine

The answer for every engine is recorded as an explicit, inspectable result.
The probe drives the genuine composed system and observes, at the O-2 loop
dispatch seam, WHICH component actually executes each loop.

This is a diagnostic. It does not assert an engine is broken: it records
whether the canonical architecture reaches it at all, so the report can
distinguish ENGINE IMPLEMENTATION from CANONICAL INTEGRATION.
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
_EVIDENCE = _REPO / "18LR-defect-repair" / "evidence"
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

ENGINES = {
    "rag_knowledge": "RAGKnowledgePowerEngine",
    "custom_ai_agent": "CustomAIAgentPowerEngine",
    "ai_automation": "AIAutomationPowerEngine",
    "code_migration": "CodeMigrationPowerEngine",
    "legacy_modernization": "ModernizationPipeline",
}

REQUEST_TEXTS = {
    "rag_knowledge": (
        "Build a customer knowledge assistant that ingests our PDF and Markdown "
        "documents, embeds them, retrieves relevant passages and answers questions "
        "with grounded source citations."
    ),
    "custom_ai_agent": (
        "Build a custom AI customer-support agent that can read order files, use "
        "the calculator and current_time tools, and answer within a bounded loop."
    ),
    "ai_automation": (
        "Build an AI automation that watches a drop folder, triggers on new files, "
        "runs a multi-step workflow with conditions and error handling, and records "
        "state transitions and outputs."
    ),
    "code_migration": (
        "Migrate the existing Python 2 order-processing module to modern typed "
        "Python 3, transforming the real source files and verifying the result."
    ),
    "legacy_modernization": (
        "Modernize the legacy COBOL batch ledger and its JCL job into a modern "
        "Java service, consuming the actual repository source."
    ),
}

async def _probe_engine(key: str) -> dict[str, Any]:
    """Drive the real canonical path for one engine and record what executed."""
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    request_text = REQUEST_TEXTS[key]
    workspace = Path(tempfile.mkdtemp(prefix=f"18LR_{key}_ws_"))
    system = build_autoforge_system(workspace_root=str(workspace))
    await system.initialize()

    # Record which component actually executes each O-2 loop.
    executed_by: list[dict[str, Any]] = []
    adapter = system.kernel.execution_engine
    original_execute_loop = adapter.execute_loop

    async def _spy(loop_type, loop_input, context):  # noqa: ANN001
        result = await original_execute_loop(loop_type, loop_input, context)
        executed_by.append({
            "loop_type": loop_type,
            "executor": type(adapter).__name__,
            "concrete_engine": type(adapter.concrete_engine).__name__,
            "status": result.get("status"),
        })
        return result

    adapter.execute_loop = _spy

    record: dict[str, Any] = {
        "engine": ENGINES[key],
        "request_text": request_text,
        "canonical_path_steps": [],
        "loops_executed": executed_by,
        "reached_commercial_engine": False,
        "engine_invoked": None,
    }

    try:
        o2 = system.kernel.orchestration_engine
        record["orchestration_engine"] = type(o2).__name__
        record["canonical_path_steps"] = [
            "Kernel.submit_request",
            "IntentAnalysis (DefaultIntentAnalyzer)",
            "StrategicEngine (DefaultStrategicEngine)",
            "PlanningCoordinator -> ExecutableWorkflow",
            "O-2 DefaultOrchestrationEngine.orchestrate",
            "LoopOrchestrator.orchestrate_loop",
            "KernelExecutionEngineAdapter.execute_loop",
        ]

        submitted = await system.kernel.submit_request(
            Request(
                user_id=uuid.uuid4(),
                request_text=request_text,
                configuration={"environment": "production", "execute": False},
            )
        )
        project_id = submitted["project_id"]
        record["project_id"] = str(project_id)

        state = await system.runtime_facade.get_project_state(project_id)
        record["intent"] = {
            "status": str(getattr(state.get("status"), "value", state.get("status"))).lower(),
            "acceptance_criteria": state.get("acceptance_criteria"),
            "task_count": state.get("task_count"),
        }
        wf = system.kernel.completion_module._project_workflow_id(state)
        record["workflow_id"] = str(wf) if wf else None

        await system.kernel.execute_project(project_id)

        # Which component actually ran the work?
        executors = {e["concrete_engine"] for e in executed_by}
        record["distinct_executors"] = sorted(executors)
        record["reached_commercial_engine"] = any(
            "PowerEngine" in e for e in executors
        )
        record["engine_invoked"] = sorted(executors)
    except Exception as exc:  # pragma: no cover - diagnostic
        record["error"] = f"{type(exc).__name__}: {exc}"
    finally:
        await system.shutdown()
    return record


async def main() -> int:
    out: dict[str, Any] = {
        "phase": "18-LR Layer-B canonical architecture invocation",
        "method": (
            "The REAL composed system is driven end to end for each engine. "
            "The O-2 loop dispatch seam is instrumented to record which "
            "concrete component actually executed each loop."
        ),
        "results": {},
    }
    for key in ENGINES:
        out["results"][key] = await _probe_engine(key)
        r = out["results"][key]
        print(
            f"{key:24s} reached={r['reached_commercial_engine']!s:5s} "
            f"executors={r.get('distinct_executors')} "
            f"loops={len(r['loops_executed'])}"
        )

    reached = [k for k, v in out["results"].items() if v["reached_commercial_engine"]]
    out["summary"] = {
        "engines_tested": len(ENGINES),
        "engines_reached_by_canonical_path": reached,
        "canonical_integration_pass": len(reached) == len(ENGINES),
    }
    print(json.dumps(out["summary"], indent=2))
    (_EVIDENCE / "layer_b_canonical_engines.json").write_text(
        json.dumps(out, indent=2, default=str), encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
