"""18-G Run 7 entry D: wire + main (two runs, package, clean-env)."""
import asyncio
import json
import time
from datetime import datetime, timezone
from pathlib import Path

from run_18g_entry_a import REPO_ROOT, http_get, _java_bin
from run_18g_entry_c2 import _run_once
from run_18g_helpers_b import sha256_of
from run_18g_pipe_g import pipe_package
from run_18g_pipe_h1 import clean_env_workflow
from run_18g_pipe_h2 import clean_env_restart


def _strip(run):
    return {k: v for k, v in run.items() if k in (
        "pid", "run_label", "http_port", "wall", "stages", "routing", "rag", "rep",
        "inv_files", "inv_loc", "sub_files", "sub_loc", "sub_nloc", "sel_paths",
        "modules", "procs", "entities", "planned", "n_arts", "classes",
        "jar_bytes", "bdir", "behavior", "runtime", "purged", "prov_links")}


def _wire():
    async def run_once(label, port, llm_sink, prov_sink):
        return await _run_once(label, port, llm_sink, prov_sink)

    def do_package(jar, bdir):
        return pipe_package({"PKGDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "package",
                             "Path": Path, "sha": sha256_of}, jar, bdir)

    return {
        "OUTDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE",
        "EVDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "evidence",
        "PKGDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "package",
        "CLEANDIR": REPO_ROOT / "18G_REAL_PROJECT_DELIVERABLE" / "clean_env",
        "COMMIT": "e13539daca1846ccf0d363d97af1dcc6b51fae9c",
        "run_once": run_once, "do_package": do_package,
        "clean_env": clean_env_workflow, "strip": _strip,
        "http_get": http_get, "java_bin": _java_bin,
    }


async def amain():
    mod = _wire()
    for d in (mod["OUTDIR"], mod["EVDIR"], mod["PKGDIR"], mod["CLEANDIR"]):
        d.mkdir(parents=True, exist_ok=True)
    llm_sink: list = []
    prov_sink: list = []
    t_cert = time.perf_counter()
    r1 = await mod["run_once"]("1", 8091, llm_sink, prov_sink)
    pkg = mod["do_package"](r1["jar"], r1["bdir"])
    first = mod["clean_env"](mod, pkg["jar"], 8092)
    rest = clean_env_restart(mod, 8092, first["components"])
    first["checks"].append(rest)
    r2 = await mod["run_once"]("2", 8093, llm_sink, prov_sink)
    assert r2["sub_files"] == r1["sub_files"]
    assert r2["sub_loc"] == r1["sub_loc"]
    assert r2["classes"] == r1["classes"]
    assert all(b["status"] == "PASSED" for b in r2["behavior"])
    total_wall = time.perf_counter() - t_cert
    in_tok = sum(c.get("input_tokens", 0) for c in llm_sink)
    out_tok = sum(c.get("output_tokens", 0) for c in llm_sink)

    def mean(xs):
        return round(sum(xs) / len(xs), 2) if xs else 0.0

    summary = {
        "gate": "18-G REAL PROJECT AUTONOMY",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "source": {"repo": "https://github.com/IBM/Bank-of-Z",
                   "commit": mod["COMMIT"],
                   "total_files": r1["inv_files"], "total_loc": r1["inv_loc"]},
        "subsystem": {"name": "BANKING_CORE", "files": r1["sub_files"],
                      "loc": r1["sub_loc"], "nloc": r1["sub_nloc"],
                      "closure": "COMPLETE", "paths": r1["sel_paths"]},
        "package": pkg, "clean_env": first,
        "telemetry": {"wall_sec": round(total_wall, 2),
                      "llm_calls": len(llm_sink),
                      "m1": sum(1 for c in llm_sink if c["machine"] == "M1"),
                      "hp": sum(1 for c in llm_sink if c["machine"] == "HP"),
                      "in_tokens": in_tok, "out_tokens": out_tok,
                      "mean_tps": mean([c.get("throughput_tps", 0.0) for c in llm_sink])},
        "nloc_per_hour": {"source": round(r1["sub_nloc"] / max(total_wall / 3600, 1e-9), 1)},
    }
    (mod["EVDIR"] / "run1.json").write_text(json.dumps(mod["strip"](r1), indent=2))
    (mod["EVDIR"] / "run2.json").write_text(json.dumps(mod["strip"](r2), indent=2))
    (mod["EVDIR"] / "llm_calls.jsonl").write_text(
        "\n".join(json.dumps(c) for c in llm_sink) + "\n")
    (mod["EVDIR"] / "evidence_summary.json").write_text(json.dumps(summary, indent=2))
    (mod["OUTDIR"] / "README.md").write_text(
        "# 18-G Real Project Deliverable\n\nBANKING_CORE -> Spring Boot. "
        "Use package/. Evidence in evidence/.\n")
    print("18-G RUN COMPLETE wall=%.1fs llm=%d classes=%d jar=%d" % (
        total_wall, len(llm_sink), r1["classes"], pkg["jar_bytes"]), flush=True)


if __name__ == "__main__":
    asyncio.run(amain())
