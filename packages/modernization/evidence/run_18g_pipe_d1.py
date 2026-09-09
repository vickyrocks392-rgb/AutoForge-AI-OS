"""18-G pipe D1: discovery+closure+semantics."""
import tempfile
import time
import uuid


def pipe_discover(mod, pid, stages):
    t0 = time.perf_counter()
    inv = mod["Discovery"]().discover(mod["BANKZ"])
    stages.append({"stage": "autonomous_discovery",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "files_scanned": inv.total_files_scanned,
                   "physical_loc": inv.total_physical_loc,
                   "technologies": inv.detected_technology_names()})
    return inv


def pipe_closure(mod, pid, stages):
    t0 = time.perf_counter()
    sel = mod["Selector"]()
    workload, proof = sel.select_coherent_subsystem_closure(
        mod["BANKZ"] / "src" / "base", subsystem_name="BANKING_CORE")
    assert proof.is_complete and proof.internal_dependency_closure == "COMPLETE"
    stages.append({"stage": "workload_closure_selection",
                   "duration_sec": round(time.perf_counter() - t0, 4),
                   "status": "COMPLETED", "subsystem": proof.subsystem_name,
                   "closure_proof": proof.internal_dependency_closure,
                   "files_selected": proof.total_files, "physical_loc": proof.physical_loc,
                   "nloc": proof.non_comment_loc,
                   "internal_dependencies": proof.internal_dependencies_count,
                   "external_boundaries": proof.external_boundaries_count})
    return sel, workload, proof
