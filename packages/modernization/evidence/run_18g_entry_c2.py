"""18-G Run 7 entry C2: run_once orchestrating production pipes."""
import os as _os
import time
import uuid
from pathlib import Path

from run_18g_entry_a import REPO_ROOT, _java_bin, _rag, async_call_ollama, http_get, sha256_of
from run_18g_entry_b import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
    GenericTransformationPlanner,
    AutonomousTargetRepairCycle,
    ModernizationProvenanceChain,
    ProjectLifecycleManager,
    ProjectPersistencePolicy,
    ProjectState,
    ProjectTechnologyDiscoveryEngine,
    SpringBootApplicationRunner,
    TargetSpecification,
    TargetToolchainVerifier,
    TransformationWorkloadSelector,
    pipe_build,
    pipe_closure,
    pipe_discover,
    pipe_generate,
    pipe_inference,
    pipe_plan,
)
from run_18g_entry_c1 import _ai_tasks
from run_18g_pipe_e import pipe_runtime
from run_18g_pipe_f import pipe_repair
from run_18g_pipe_g import pipe_provenance, pipe_purge
from run_18g_pipe_d2 import pipe_semantics


async def _run_once(label, port, llm_sink, prov_sink):
    from autoforge_kernel.project_lifecycle import ProjectPurgeVerifier, ProjectResourceRegistry
    from autoforge_modernization.provenance import ProvenanceLink, ProvenanceStage

    lifecycle = ProjectLifecycleManager()
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
        "Runner": SpringBootApplicationRunner,
        "ProvChain": ModernizationProvenanceChain,
        "ProvLink": ProvenanceLink,
        "Stage": ProvenanceStage,
        "PurgeVerifier": ProjectPurgeVerifier,
        "Registry": ProjectResourceRegistry,
        "COMPLETED_STATE": ProjectState.COMPLETED,
        "BANKZ": Path("/tmp/Bank-of-Z"),
        "Path": Path, "COMMIT": "e13539daca1846ccf0d363d97af1dcc6b51fae9c",
        "QDRANT": _os.environ.get("AUTOFORGE_QDRANT_URL", "http://192.168.1.102:6333"),
        "OUTDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE",
        "EVDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "evidence",
        "PKGDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "package",
        "CLEANDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "clean_env",
        "call_llm": async_call_ollama, "sha": sha256_of, "http_get": http_get,
        "rag_fn": _rag, "ai_tasks": _ai_tasks, "java_bin": _java_bin,
    }
    t_run = time.perf_counter()
    pid = "bankzcore_%s" % uuid.uuid4().hex[:8]
    print("18-G RUN %s: BANKING_CORE (port %d)" % (label, port), flush=True)
    stages: list = []
    rag_tel: list = []
    rep_tel: list = []
    routing: list = []
    ctx = lifecycle.create_project(project_id=pid,
                                   persistence_policy=ProjectPersistencePolicy.EPHEMERAL)
    lifecycle.initialize_project(pid)
    inv = pipe_discover(mod, pid, stages)
    sel, workload, proof = pipe_closure(mod, pid, stages)
    sm = pipe_semantics(sel, mod, pid, stages, workload)
    t0 = time.perf_counter()
    _rag(pid, "Bank-of-Z account balance debit credit rules", rag_tel)
    _rag(pid, "Bank-of-Z funds transfer double-entry invariants", rag_tel)
    _rag(pid, "Bank-of-Z customer onboarding constraints", rag_tel)
    stages.append({"stage": "rag_retrieval",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "queries": len(rag_tel)})
    plan = pipe_plan(mod, pid, stages, sm)
    arts, spec = pipe_generate(mod, sm, plan)
    await pipe_inference(mod, pid, stages, routing, llm_sink, prov_sink, arts, sha256_of)
    verifier, mvn = pipe_build(mod, pid, stages, arts, spec)
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
