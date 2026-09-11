"""18-H optimized run_once: same production pipes, same workload, same verification
standard as golden 18-G. Only critical-path optimizations applied:
  OPT-1  Maven build runs CONCURRENTLY with distributed inference (independent DAG nodes)
  OPT-3  keep_alive on all inference calls (no model reload, warm TTFT)
  OPT-4  Maven -B -q -T 1C flags (mvn_extra_flags param; golden default unchanged)
  OPT-5  parallel RAG queries (Qdrant stays HP-only)
  OPT-6  0.1s health polling for runtime start (configurable param; golden default unchanged)
All golden asserts preserved; per-stage telemetry recorded for critical-path analysis.
"""
import asyncio
import time
import uuid
from pathlib import Path

from run_18g_entry_a import (
    CODING, HP_CODING, HP_URL, M1_URL, QD_URL, REASON,
    REPO_ROOT, _java_bin, _rag, http_get, sha256_of,
)
from run_18g_entry_c1 import _ai_tasks
from run_18g_helpers_c import execute_qdrant_rag as _raw_rag, get_nomic_embedding
from run_18g_pipe_d1 import pipe_discover, pipe_closure
from run_18g_pipe_d2 import pipe_generate, pipe_plan, pipe_semantics
from run_18g_pipe_e import pipe_runtime
from run_18g_pipe_f import pipe_repair
from run_18g_pipe_g import pipe_provenance, pipe_purge
from run_18h_helpers import (
    async_call_ollama_warm as call_llm,
    run_rag_parallel,
    warm_preload,
)

from autoforge_kernel.project_lifecycle import (
    ProjectLifecycleManager,
    ProjectPersistencePolicy,
    ProjectPurgeVerifier,
    ProjectResourceRegistry,
    ProjectState,
)
from autoforge_modernization.composition.app_runner import SpringBootApplicationRunner
from autoforge_modernization.composition.verifier import TargetToolchainVerifier
from autoforge_modernization.discovery.engine import ProjectTechnologyDiscoveryEngine
from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import GenericTransformationPlanner
from autoforge_modernization.composition.repair import AutonomousTargetRepairCycle
from autoforge_modernization.composition.workload_selector import (
    TransformationWorkloadSelector,
)
from autoforge_modernization.target.specification import TargetSpecification
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)


class _FastPollRunner(SpringBootApplicationRunner):
    """Same production runner with 0.1s health polling (OPT-6)."""

    def __init__(self, **kw):
        kw.setdefault("health_poll_interval_s", 0.1)
        super().__init__(**kw)


# OPT-4: Maven build pipe with -B -q -T 1C (identical verification semantics)
async def pipe_build_fast(mod, pid, stages, arts, spec):
    loop = asyncio.get_event_loop()

    def _sync_build():
        from tempfile import mkdtemp
        t0 = time.perf_counter()
        verifier = mod["Verifier"]()
        bdir = Path(mkdtemp(prefix="autoforge_18h_build_"))
        mvn = verifier.verify_maven(arts, spec, build_directory=bdir,
                                    mvn_extra_flags=["-B", "-q", "-T", "1C"])
        stages.append({"stage": "maven_build_package",
                       "duration_sec": round(time.perf_counter() - t0, 4),
                       "status": "COMPLETED" if mvn.passed else "FAILED",
                       "toolchain": mvn.toolchain_used, "command": mvn.command_executed,
                       "fat_jar": mvn.fat_jar_path,
                       "fat_jar_bytes": mvn.fat_jar_size_bytes,
                       "classes": mvn.class_count, "build_directory": mvn.build_directory,
                       "optimized": "B_q_T1C_flags"})
        assert mvn.passed, "Maven build failed: " + (mvn.output_snippet or "")[-3000:]
        assert mvn.fat_jar_size_bytes > 10 * 1024 * 1024
        return verifier, mvn

    return await loop.run_in_executor(None, _sync_build)


async def pipe_inference_18h(mod, pid, stages, routing, llm_sink, prov_sink, arts, sha_fn):
    """Golden pipe_inference body but routed through keep-alive warm calls."""
    t0 = time.perf_counter()
    tasks = mod["ai_tasks"]()

    async def one(spec_t, attempt=0):
        comp, role, prompt, machine, endpoint, tag, worker = spec_t
        if attempt == 0:
            routing.append({"component": comp, "role": role, "machine": machine,
                            "endpoint": endpoint, "model": tag, "worker": worker})
        res = await call_llm(endpoint, tag, role, prompt, "code_generation",
                             pid, "task-ai-" + comp.lower(),
                             "design-note/" + comp + ".md",
                             machine, worker, llm_sink)
        if res["telemetry"]["result"] != "SUCCESS" and attempt < 2:
            return await one(spec_t, attempt=attempt + 1)
        return res

    ai_res = await asyncio.gather(*[one(t) for t in tasks])
    failed = [r["telemetry"] for r in ai_res if r["telemetry"]["result"] != "SUCCESS"]
    assert not failed, "fleet inference failures: %s" % failed[:3]
    stages.append({"stage": "concurrent_distributed_inference",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "llm_calls": len(ai_res),
                   "ai_note_lines": sum(len(r["response"].splitlines()) for r in ai_res),
                   "ai_note_chars": sum(len(r["response"].encode("utf-8")) for r in ai_res),
                   "optimized": "keep_alive_warm_calls"})
    for a in arts:
        prov_sink.append({"artifact_id": a.artifact_id, "project_id": pid,
                          "component_name": a.component_name,
                          "relative_path": a.relative_path,
                          "target_language": a.target_language,
                          "classification": "DETERMINISTIC_COMPILER_SYNTHESIS",
                          "is_ai_generated": False, "is_deterministic": True,
                          "originating_stage": "GenericTargetArtifactGenerator",
                          "sha256": sha_fn(a.code)})
    for spec_t, res in zip(tasks, ai_res):
        prov_sink.append({"artifact_id": "art-ai-" + spec_t[0].lower() + "-" + pid[:6],
                          "project_id": pid, "component_name": spec_t[0],
                          "relative_path": "design-notes/" + spec_t[0] + ".md",
                          "target_language": "MARKDOWN", "classification": "AI_DESIGN_NOTE",
                          "is_ai_generated": True, "is_deterministic": False,
                          "originating_stage": spec_t[4] + ":" + spec_t[5],
                          "originating_model": spec_t[5], "worker": spec_t[6],
                          "sha256": sha_fn(res["response"])})
    return ai_res




async def _run_once_18h(label, port, llm_sink, prov_sink, warm_sink=None):
    t_run = time.perf_counter()
    pid = "bankzcore18h_%s" % uuid.uuid4().hex[:8]
    print("18-H OPT RUN %s: BANKING_CORE (port %d)" % (label, port), flush=True)
    stages: list = []
    rag_tel: list = []
    rep_tel: list = []
    routing: list = []

    lifecycle = ProjectLifecycleManager()
    ctx = lifecycle.create_project(project_id=pid,
                                   persistence_policy=ProjectPersistencePolicy.EPHEMERAL)
    lifecycle.initialize_project(pid)

    # OPT-2: warm preload overlaps with discovery (fire and forget)
    warm_task = None
    if warm_sink is not None:
        warm_task = asyncio.get_event_loop().create_task(
            warm_preload([(M1_URL, CODING, "M1"), (M1_URL, REASON, "M1"),
                          (HP_URL, HP_CODING, "HP")], warm_sink))

    mod = {
        "lifecycle": lifecycle, "EPHEMERAL": ProjectPersistencePolicy.EPHEMERAL,
        "Discovery": ProjectTechnologyDiscoveryEngine,
        "Selector": TransformationWorkloadSelector,
        "Planner": GenericTransformationPlanner,
        "Generator": GenericTargetArtifactGenerator,
        "Verifier": TargetToolchainVerifier,
        "RepairCycle": AutonomousTargetRepairCycle,
        "Artifact": GeneratedArtifact,
        "TargetSpec": TargetSpecification,
        "Runner": _FastPollRunner,
        "ProvChain": ModernizationProvenanceChain,
        "ProvLink": ProvenanceLink,
        "Stage": ProvenanceStage,
        "PurgeVerifier": ProjectPurgeVerifier,
        "Registry": ProjectResourceRegistry,
        "COMPLETED_STATE": ProjectState.COMPLETED,
        "BANKZ": Path("/tmp/Bank-of-Z"),
        "Path": Path, "COMMIT": "e13539daca1846ccf0d363d97af1dcc6b51fae9c",
        "QDRANT": QD_URL,
        "OUTDIR": REPO_ROOT / "18H_OPTIMIZATION",
        "EVDIR": REPO_ROOT / "18H_OPTIMIZATION",
        "PKGDIR": REPO_ROOT / "18H_OPTIMIZATION" / "package",
        "CLEANDIR": REPO_ROOT / "18H_OPTIMIZATION" / "clean_env",
        "call_llm": call_llm, "sha": sha256_of, "http_get": http_get,
        "rag_fn": _rag, "ai_tasks": _ai_tasks, "java_bin": _java_bin,
    }

    inv = pipe_discover(mod, pid, stages)
    sel, workload, proof = pipe_closure(mod, pid, stages)
    sm = pipe_semantics(sel, mod, pid, stages, workload)


    # OPT-5: parallel RAG queries (independent, HP-only Qdrant)
    t0 = time.perf_counter()
    run_rag_parallel(_raw_rag,
                     lambda q: get_nomic_embedding(M1_URL, "nomic-embed-text:latest", q),
                     QD_URL, pid,
                     ["Bank-of-Z account balance debit credit rules",
                      "Bank-of-Z funds transfer double-entry invariants",
                      "Bank-of-Z customer onboarding constraints"], rag_tel)
    stages.append({"stage": "rag_retrieval",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "queries": len(rag_tel),
                   "optimized": "parallel_queries"})

    plan = pipe_plan(mod, pid, stages, sm)
    arts, spec = pipe_generate(mod, sm, plan)

    if warm_task is not None:
        await warm_task  # models resident before the critical-path overlap window

    # OPT-1: Maven build CONCURRENT with distributed inference (independent nodes)
    loop = asyncio.get_event_loop()
    build_task = loop.create_task(pipe_build_fast(mod, pid, stages, arts, spec))
    t_inf = time.perf_counter()
    ai_res = await pipe_inference_18h(mod, pid, stages, routing, llm_sink,
                                      prov_sink, arts, sha256_of)
    inf_wall = time.perf_counter() - t_inf
    verifier, mvn = await build_task
    build_wall = stages[-2]["duration_sec"]
    stages.append({"stage": "build_inference_overlap",
                   "duration_sec": round(max(inf_wall, build_wall), 4),
                   "status": "COMPLETED",
                   "serialized_sum": round(inf_wall + build_wall, 4),
                   "wall_saved_sec": round(inf_wall + build_wall
                                           - max(inf_wall, build_wall), 4),
                   "optimized": "OPT1_build_parallel_inference"})

    # Behavioral verification: production pipe (same tests as golden), fast runner
    behavior, runtime = pipe_runtime(mod, pid, stages, port, plan, mvn)

    pipe_repair(mod, pid, stages, rag_tel, rep_tel, verifier, arts, spec)
    prov = pipe_provenance(mod, pid, inv, proof, plan, arts, 6, mvn)
    purged = pipe_purge(mod, pid, ctx)
    return {"pid": pid, "run_label": label, "http_port": port,
            "wall": round(time.perf_counter() - t_run, 2), "stages": stages,
            "routing": routing, "rag": rag_tel, "rep": rep_tel,
            "inv_files": inv.total_files_scanned, "inv_loc": inv.total_physical_loc,
            "sub_files": proof.total_files, "sub_loc": proof.physical_loc,
            "sub_nloc": proof.non_comment_loc, "sel_paths": proof.selected_relative_paths,
            "modules": sm.total_modules, "procs": sm.total_procedures,
            "entities": len(sm.entities), "planned": len(plan.target_components),
            "n_arts": len(arts), "classes": mvn.class_count, "jar": mvn.fat_jar_path,
            "jar_bytes": mvn.fat_jar_size_bytes, "bdir": mvn.build_directory,
            "behavior": behavior, "runtime": runtime,
            "purged": purged.get("is_clean", True), "prov_links": len(prov.links)}


if __name__ == "__main__":
    import json as _json

    async def _two_runs():
        r1 = await _run_once_18h("1", 8091, [], [])
        r2 = await _run_once_18h("2", 8093, [], [])
        return r1, r2

    a, b = asyncio.run(_two_runs())
    assert b["sub_files"] == a["sub_files"] and b["sub_loc"] == a["sub_loc"]
    assert b["classes"] == a["classes"]
    assert all(x["status"] == "PASSED" for x in a["behavior"] + b["behavior"])
    print(_json.dumps({"run1_wall_sec": a["wall"], "run2_wall_sec": b["wall"],
                       "classes": a["classes"], "sub_nloc": a["sub_nloc"],
                       "jar_bytes": a["jar_bytes"]}, indent=2))


