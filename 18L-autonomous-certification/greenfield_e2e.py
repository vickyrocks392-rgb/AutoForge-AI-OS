"""
PHASE 18-L-B :: GREENFIELD AUTONOMOUS ENGINEERING CERTIFICATION
============================================================

M6-ONLY. This harness drives the REAL production path end to end:

    user request
      -> Kernel.submit_request            (intent + strategic planning + workflow)
      -> Kernel.execute_project           (O-2 DefaultOrchestrationEngine)
      -> KernelExecutionEngineAdapter     (workforce dispatcher -> EngineeringLoop)
      -> AIInfrastructureAdapter          (Model Router -> LocalRuntimeProviderAdapter -> MLX)
      -> M6 Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2   <-- REAL INFERENCE
      -> workspace filesystem writes      (REAL source modification)
      -> ArtifactPipeline                 (18-K durable registration)
      -> DurableArtifactCatalog + PhysicalArtifactStore  (COMMITTED)
      -> completion validation
      -> FinalReviewEvidenceCollector     (real COMMITTED artifacts)
      -> KernelReviewEngineAdapter        (real ReviewEngine)
      -> explicit APPROVED
      -> Finished
      -> export / recovery

WHAT THIS HARNESS DOES *NOT* DO (18-L-I autonomity integrity):

  * It does not write any source file of the greenfield project.
  * It does not fix, edit, or correct any generated source.
  * It does not create or register any artifact of the project.
  * It does not invoke, stub, or influence the Review Engine's decision.
  * It does not transition any project state by hand.

It creates ONLY: the empty project workspace, the user request text, the
acceptance criteria, and the verification/test command. Every byte of the
deliverable comes from the M6 model through the canonical AI path.

HARDWARE SCOPE: M6 Mac mini only. The Model Router resolves the local
OpenAI-compatible runtime at AUTOFORGE_LOCAL_RUNTIME_URL (127.0.0.1:8080).
No M1, no HP, no distributed inference, no topology change.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parents[1]
_HERE = Path(__file__).resolve().parent
_EVIDENCE = _HERE / "evidence"
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


MODEL_ID = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
RUNTIME_URL = os.environ.get("AUTOFORGE_LOCAL_RUNTIME_URL", "http://127.0.0.1:8080/v1")


# ---------------------------------------------------------------------------
# The greenfield project specification.
#
# SMALL but COMPLETE: a text-token counting library with a CLI, multiple source
# files, a test suite, a README and a deterministic verification command.
# It is deliberately NOT "hello world" (4 modules, a CLI, edge cases, a
# documented public API) and deliberately NOT a large application.
#
# The harness supplies ONLY the specification and the acceptance criteria. It
# supplies no source code, no stub, no template and no partial implementation.
# ---------------------------------------------------------------------------

REQUEST_TEXT = (
    "Build a greenfield Python package named 'tokenizer_lite'. It is a small, "
    "self-contained text token-counting library with a CLI. Create exactly these "
    "four files:\n"
    "1. 'tokenizer_lite/__init__.py' - exports TokenizerLite and count_tokens.\n"
    "2. 'tokenizer_lite/core.py' - defines class TokenizerLite with methods "
    "count(text), count_words(text), and a module-level function count_tokens(text) "
    "that returns a dict with keys 'tokens', 'characters' and 'words'. Splitting "
    "must be whitespace based, must treat consecutive whitespace as one "
    "separator, and must return zeros for empty or whitespace-only input.\n"
    "3. 'tokenizer_lite/cli.py' - a 'main()' function with an argparse parser "
    "accepting one positional 'text' argument, printing 'tokens=<n> characters=<n> "
    "words=<n>' and returning exit code 0.\n"
    "4. 'test_tokenizer_lite.py' - pytest tests covering: empty string, "
    "whitespace-only string, single word, multiple words, and character count.\n"
    "Also create 'README.md' with a title line, an Overview section and a Usage "
    "section. All code must be plain Python 3 with no third-party dependencies "
    "except pytest for the tests."
)

# The verification command AutoForge runs to validate the generated project.
# Absolute paths: the command runs with cwd=<project workspace>, so a relative
# .venv path would not resolve. This is harness plumbing, not project content.
_PY = str(_REPO / ".venv" / "bin" / "python")
VERIFY_COMMAND = [_PY, "-m", "pytest", "test_tokenizer_lite.py", "-q"]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _write(name: str, payload: Any) -> Path:
    p = _EVIDENCE / name
    p.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    return p


def _sha256_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def _status_value(state: dict[str, Any]) -> str:
    raw = state.get("status")
    return str(getattr(raw, "value", raw)).lower()


async def run() -> int:
    from autoforge_composition.composition_root import build_autoforge_system
    from autoforge_kernel.interfaces import Request

    timeline: list[dict[str, Any]] = []
    t_start = time.perf_counter()

    def mark(phase: str, **kw: Any) -> None:
        timeline.append({
            "phase": phase,
            "at": _now(),
            "t_sec": round(time.perf_counter() - t_start, 2),
            **kw,
        })

    # -- Infrastructure: a clean, EMPTY greenfield project directory. --------
    # The harness creates the directory and nothing else. No project source.
    ws = Path(tempfile.mkdtemp(prefix="18L_greenfield_ws_"))
    mark("workspace_created", workspace=str(ws))
    pre_existing = sorted(p.relative_to(ws).as_posix() for p in ws.rglob("*"))
    mark("workspace_pre_existing_files", files=pre_existing)

    # -- M6 runtime preflight (observability, not a bypass) -------------------
    preflight: dict[str, Any] = {"runtime_url": RUNTIME_URL, "model": MODEL_ID}
    try:
        r = await asyncio.to_thread(
            subprocess.run,
            ["curl", "-s", "-o", "/dev/null", "-w", "%{http_code}", "--max-time", "25",
             f"{RUNTIME_URL}/models"],
            capture_output=True, text=True, timeout=60,
        )
        preflight["models_endpoint_http"] = r.stdout.strip()
    except Exception as exc:
        preflight["models_endpoint_error"] = f"{type(exc).__name__}: {exc}"
    mark("m6_runtime_preflight", **preflight)

    system = build_autoforge_system(workspace_root=str(ws))
    await system.initialize()
    mark("system_initialized", o2_type=type(system.kernel.orchestration_engine).__name__)

    # -----------------------------------------------------------------------
    # M6 DEPLOYMENT BINDING (18-L-J, configuration only -- NO source change).
    #
    # The production Model Router catalog registers local model IDs for the
    # M1/HP node profiles. The certified 18-L topology is "M6 Qwen3-Coder-30B
    # authority + 0 continuous workers", and the M6 local runtime serves that
    # model. The platform already ships a provider-neutral, deployment-level
    # seam for exactly this -- ``BaseProviderAdapter.register_model_alias`` --
    # which maps a canonical model id to the tag the local runtime serves.
    #
    # This binds the already-selected LOCAL model to the M6 tag. It does NOT:
    # add a provider, register a model, change the router, change topology,
    # start a worker, or reference M1/HP hardware. Both ``local-m1`` and
    # ``local-hp`` provider ids point at 127.0.0.1 (this M6); they are labels
    # for the local runtime endpoint, not remote machines.
    #
    # It is applied to the PRODUCTION system's own already-bound adapters
    # (reached through the execution engine that O-2 drives), not to a
    # separately constructed registry.
    # -----------------------------------------------------------------------
    from autoforge_ai_infrastructure.metadata import ModelQuery  # noqa: E402

    registry = system.execution_engine._ai._executor
    adapters = getattr(registry, "_executors", None) or {}
    bound_models: list[str] = []
    for _pid, _adapter in adapters.items():
        if hasattr(_adapter, "register_model_alias"):
            for _m in ("qwen2.5-coder-7b", "qwen2.5-coder-3b", "ornith-9b"):
                _adapter.register_model_alias(_m, MODEL_ID)
                bound_models.append(f"{_pid}:{_m}->{MODEL_ID}")
    out_registered_models = [
        {"model_id": m.model_id, "provider_id": m.provider_id,
         "quality_tier": m.quality_tier}
        for m in system.kernel.model_router._router.registry.query_models(ModelQuery())
    ] if hasattr(system.kernel.model_router, "_router") else []
    mark("m6_deployment_binding",
         model=MODEL_ID, aliases=bound_models,
         catalog_models=out_registered_models)

    out: dict[str, Any] = {
        "phase": "18-L-B greenfield autonomous engineering",
        "model": MODEL_ID,
        "runtime_url": RUNTIME_URL,
        "m6_aliases": bound_models,
        "catalog_models": out_registered_models,
        "workspace": str(ws),
        "request_text": REQUEST_TEXT,
        "verify_command": VERIFY_COMMAND,
        "timeline": timeline,
    }

    try:
        # =====================================================================
        # 1-4. Request accepted -> intent -> strategy -> executable workflow
        # =====================================================================
        res = await system.kernel.submit_request(
            Request(
                user_id=uuid.uuid4(),
                request_text=REQUEST_TEXT,
                configuration={"environment": "production", "execute": False},
            )
        )
        project_id = res["project_id"]
        mark("request_accepted", project_id=str(project_id), status=res.get("status"))

        state = await system.runtime_facade.get_project_state(project_id)
        out["intent"] = {
            "status": _status_value(state),
            "acceptance_criteria": state.get("acceptance_criteria"),
            "quality_gates": state.get("quality_gates"),
            "task_count": state.get("task_count"),
        }
        mark("intent_and_plan_formed", **out["intent"])

        wf_id = system.kernel.completion_module._project_workflow_id(state)
        out["workflow_id"] = str(wf_id) if wf_id else None
        mark("executable_workflow_correlated", workflow_id=out["workflow_id"])

        # =====================================================================
        # 5-8. O-2 executes the workflow; the M6 model writes real source.
        #
        # ``submit_request(configuration={"execute": True})`` already drives the
        # canonical path end to end (Kernel.execute_project -> O-2). The request
        # is submitted with ``execute: False`` and executed explicitly ONCE, so
        # the timeline records the phases individually and the project is not
        # finalized twice (the project state machine correctly refuses a second
        # execution of a terminal project).
        # =====================================================================
        exec_result = await system.kernel.execute_project(project_id)
        mark("o2_execution_returned", result_keys=sorted(exec_result.keys()))
        out["execute_project_result"] = exec_result

        # Files actually present in the workspace afterwards.
        produced = sorted(
            p.relative_to(ws).as_posix()
            for p in ws.rglob("*")
            if p.is_file() and ".autoforge" not in p.parts
        )
        out["generated_source_files"] = produced
        out["generated_file_hashes"] = {
            rel: _sha256_file(ws / rel)
            for rel in produced
            if (ws / rel).is_file()
        }
        mark("source_files_on_disk", files=produced)

        # =====================================================================
        # 9-10. Durable artifact evidence (authoritative 18-K catalog).
        # =====================================================================
        catalog = system.durable_catalog
        states = catalog.find_by_workflow(wf_id) if wf_id else []
        durable: list[dict[str, Any]] = []
        for s in states or []:
            entry = {
                "artifact_id": str(s.artifact_id),
                "artifact_name": s.artifact_name,
                "artifact_type": s.artifact_type,
                "status": str(getattr(s.status, "value", s.status)),
                "content_hash": s.content_hash,
                "size_bytes": s.size_bytes,
                "storage_path": s.storage_path,
                "physical_exists": bool(s.storage_path and Path(s.storage_path).exists()),
            }
            if s.storage_path and Path(s.storage_path).exists():
                entry["physical_sha256"] = _sha256_file(Path(s.storage_path))
            durable.append(entry)
        durable.sort(key=lambda e: e["artifact_name"])
        out["durable_artifacts"] = durable
        out["durable_artifact_counts"] = {
            "total": len(durable),
            "committed": sum(1 for e in durable if e["status"] == "committed"),
            "source_code": [e for e in durable if e["artifact_type"] == "source_code"],
        }
        mark("durable_artifacts_collected", total=len(durable))

        # =====================================================================
        # 11-12. Validation + the project's own test suite.
        # =====================================================================
        test_run = subprocess.run(
            VERIFY_COMMAND, cwd=ws, capture_output=True, text=True, timeout=600
        )
        out["project_test_run"] = {
            "command": VERIFY_COMMAND,
            "returncode": test_run.returncode,
            "stdout_tail": test_run.stdout[-3000:],
            "stderr_tail": test_run.stderr[-2000:],
        }
        mark("project_tests_run", returncode=test_run.returncode)

        # =====================================================================
        # 13-14. REAL final review over the REAL artifacts.
        # =====================================================================
        gate = await system.kernel.completion_module._run_final_review(project_id)
        out["final_review"] = {
            "approved": gate.get("approved"),
            "reason": gate.get("reason"),
            "evidence_files": gate.get("evidence_files"),
            "review_result": gate.get("review_result"),
        }
        mark("final_review_completed", **{
            k: out["final_review"][k] for k in ("approved", "evidence_files")
        })

        # =====================================================================
        # 15-17. Completion (only after approval), durability, export/recovery.
        #
        # ``Kernel.execute_project`` already runs the completion gate, so the
        # project may legitimately already be terminal here. The state machine
        # correctly REFUSES a second finalization of a terminal project; that
        # refusal is recorded as evidence of the fail-closed contract rather
        # than treated as a harness error.
        # =====================================================================
        try:
            finalize = await system.kernel.completion_module.finalize_project(
                project_id
            )
            out["finalize_project"] = finalize
            out["finalize_note"] = "explicit finalize_project call succeeded"
        except Exception as exc:
            state_now = await system.runtime_facade.get_project_state(project_id)
            already_finished = _status_value(state_now) == "finished"
            out["finalize_project"] = {
                "success": already_finished,
                "already_terminal": already_finished,
                "refusal": f"{type(exc).__name__}: {exc}",
            }
            out["finalize_note"] = (
                "execute_project already ran the completion gate; the project "
                "state machine refused a second finalization, which is the "
                "documented fail-closed behaviour for a terminal project"
            )
        mark("finalize_project", success=out["finalize_project"].get("success"))

        state_after = await system.runtime_facade.get_project_state(project_id)
        out["final_state"] = {
            "status": _status_value(state_after),
            "finished_at": state_after.get("finished_at"),
        }
        mark("final_state", **out["final_state"])

        # Durability: read the artifacts back through the authoritative catalog
        # and verify every COMMITTED source artifact's physical bytes.
        recovered: list[dict[str, Any]] = []
        for s in (catalog.find_by_workflow(wf_id) or []) if wf_id else []:
            if str(getattr(s.status, "value", s.status)) != "committed":
                continue
            p = Path(s.storage_path) if s.storage_path else None
            recovered.append({
                "artifact_name": s.artifact_name,
                "content_hash": s.content_hash,
                "recovered": bool(p and p.exists()),
                "sha256_matches": bool(p and p.exists() and _sha256_file(p) == s.content_hash),
            })
        out["recovery"] = {
            "recovered_committed": len(recovered),
            "all_recovered": all(e["recovered"] for e in recovered) if recovered else False,
            "all_hash_verified": all(e["sha256_matches"] for e in recovered) if recovered else False,
            "detail": recovered,
        }
        mark("durability_recovery_verified", **{
            k: out["recovery"][k] for k in ("recovered_committed", "all_hash_verified")
        })

        out["timeline"] = timeline
        _write("greenfield_run.json", out)
        print(json.dumps({k: v for k, v in out.items() if k != "timeline"},
                         indent=2, default=str)[:14000])
        return 0
    finally:
        await system.shutdown()


if __name__ == "__main__":
    sys.exit(asyncio.run(run()))
