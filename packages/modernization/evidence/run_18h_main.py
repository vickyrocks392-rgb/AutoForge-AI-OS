"""18-H main: optimized commercial performance run (two full runs + package +
clean-env + restart consistency). Same workload, same verification standard as
the frozen 18-G Run-8 baseline. Critical-path optimizations only:
  OPT-1 build || inference overlap
  OPT-2 warm model preload (keep_alive=-1)
  OPT-3 keep-alive inference calls
  OPT-4 Maven -B -q -T 1C
  OPT-5 parallel RAG
  OPT-6 0.1s health polling
"""
import asyncio
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import run_18g_entry_a as ea
from run_18g_helpers_b import sha256_of
from run_18g_pipe_g import pipe_package
from run_18h_helpers import (
    clean_env_restart_fast,
    clean_env_workflow_fast,
    warm_preload,
)
from run_18h_opt import _run_once_18h


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _resource_sampler(stop_evt, sink, interval=2.0):
    while not stop_evt.is_set():
        try:
            out = subprocess.run(["ps", "-axo", "%cpu,rss,comm"],
                                 capture_output=True, text=True, timeout=5).stdout
            rows = []
            for line in out.splitlines()[1:]:
                parts = line.split(None, 2)
                if len(parts) == 3:
                    cpu, rss, comm = parts
                    base = comm.rsplit("/", 1)[-1]
                    if base in ("java", "ollama", "mvn", "qdrant"):
                        rows.append({"proc": base, "cpu_pct": float(cpu),
                                     "rss_mb": round(float(rss) / 1024.0, 1)})
            sink.append({"ts": _iso(), "rows": rows})
        except Exception:
            pass
        stop_evt.wait(interval)


async def amain():
    perf_root = ea.REPO_ROOT / "18H_OPTIMIZATION"
    golden = perf_root / "18H_REAL_PROJECT_DELIVERABLE"
    for d in (perf_root, golden / "evidence", golden / "package", golden / "clean_env"):
        d.mkdir(parents=True, exist_ok=True)

    mod = {
        "EVDIR": golden / "evidence",
        "PKGDIR": golden / "package",
        "CLEANDIR": golden / "clean_env",
        "java_bin": ea._java_bin,
        "http_get": ea.http_get,
    }

    llm_sink: list = []
    prov_sink: list = []
    warm_sink: list = []
    res_sink: list = []
    stop_evt = threading.Event()
    sampler = threading.Thread(target=_resource_sampler, args=(stop_evt, res_sink),
                               daemon=True)
    sampler.start()

    wall_start_iso = _iso()
    t_cert = time.perf_counter()

    # OPT-2: preload all three fleet models (~1 tiny call each, keep_alive=-1)
    t_w = time.perf_counter()
    await warm_preload([
        (ea.M1_URL, ea.CODING, "M1"),
        (ea.M1_URL, ea.REASON, "M1"),
        (ea.HP_URL, ea.HP_CODING, "HP"),
    ], warm_sink)
    warm_wall = time.perf_counter() - t_w

    r1_start_iso = _iso()
    t1 = time.perf_counter()
    r1 = await _run_once_18h("1", 8091, llm_sink, prov_sink, warm_sink)
    r1_wall = time.perf_counter() - t1
    r1_end_iso = _iso()

    pkg_start_iso = _iso()
    t2 = time.perf_counter()
    pkg = pipe_package({"PKGDIR": mod["PKGDIR"], "Path": Path, "sha": sha256_of},
                       r1["jar"], r1["bdir"])
    pkg_wall = time.perf_counter() - t2

    t3 = time.perf_counter()
    first = clean_env_workflow_fast(mod, pkg["jar"], 8092)
    rest = clean_env_restart_fast(mod, 8092, first["components"])
    first["checks"].append(rest)
    cleanenv_wall = time.perf_counter() - t3

    delivery_wall = time.perf_counter() - t_cert
    delivery_end_iso = _iso()

    r2_start_iso = _iso()
    t4 = time.perf_counter()
    r2 = await _run_once_18h("2", 8093, llm_sink, prov_sink, warm_sink)
    r2_wall = time.perf_counter() - t4
    r2_end_iso = _iso()

    assert r2["sub_files"] == r1["sub_files"]
    assert r2["sub_loc"] == r1["sub_loc"]
    assert r2["classes"] == r1["classes"]
    assert all(b["status"] == "PASSED" for b in r2["behavior"])
    assert all(b["status"] == "PASSED" for b in r1["behavior"])

    total_wall = time.perf_counter() - t_cert
    wall_stop_iso = _iso()
    stop_evt.set()
    sampler.join(timeout=3)
    return (r1, r2, pkg, first, llm_sink, prov_sink, warm_sink, res_sink,
            {"wall_start": wall_start_iso, "wall_stop": wall_stop_iso,
             "warm_preload_wall_sec": round(warm_wall, 2),
             "run1_wall_sec": round(r1_wall, 2), "run2_wall_sec": round(r2_wall, 2),
             "r1_start": r1_start_iso, "r1_end": r1_end_iso,
             "r2_start": r2_start_iso, "r2_end": r2_end_iso,
             "package_wall_sec": round(pkg_wall, 2),
             "clean_env_wall_sec": round(cleanenv_wall, 2),
             "delivery_wall_sec": round(delivery_wall, 2),
             "delivery_end": delivery_end_iso,
             "total_wall_sec": round(total_wall, 2)})


def _write_evidence(evdir, golden, r1, r2, pkg, first, llm_sink, prov_sink,
                    warm_sink, res_sink, wc):
    evdir.mkdir(parents=True, exist_ok=True)
    (evdir / "run1.json").write_text(json.dumps(r1, indent=2, default=str))
    (evdir / "run2.json").write_text(json.dumps(r2, indent=2, default=str))
    (evdir / "llm_calls.jsonl").write_text(
        "\n".join(json.dumps(c) for c in llm_sink) + "\n")
    (evdir / "warm_preload.json").write_text(json.dumps(warm_sink, indent=2))
    (evdir / "provenance_manifest.json").write_text(
        json.dumps(prov_sink, indent=2, default=str))
    (evdir / "rag_telemetry.json").write_text(
        json.dumps(r1["rag"] + r2["rag"], indent=2, default=str))
    (evdir / "repair_telemetry.json").write_text(
        json.dumps(r1["rep"] + r2["rep"], indent=2, default=str))
    (evdir / "resource_samples.json").write_text(json.dumps(res_sink, indent=2))
    (evdir / "wall_clock.json").write_text(json.dumps(wc, indent=2))
    in_tok = sum(c.get("input_tokens", 0) for c in llm_sink)
    out_tok = sum(c.get("output_tokens", 0) for c in llm_sink)
    (evdir / "evidence_summary.json").write_text(json.dumps({
        "gate": "18-H HEAVY OPTIMIZATION",
        "timestamp": wc["wall_stop"],
        "source": {"repo": "https://github.com/IBM/Bank-of-Z",
                   "commit": "e13539daca1846ccf0d363d97af1dcc6b51fae9c",
                   "total_files": r1["inv_files"], "total_loc": r1["inv_loc"]},
        "subsystem": {"name": "BANKING_CORE", "files": r1["sub_files"],
                      "loc": r1["sub_loc"], "nloc": r1["sub_nloc"]},
        "package": pkg,
        "telemetry": {
            "total_wall_sec": wc["total_wall_sec"],
            "delivery_wall_sec": wc["delivery_wall_sec"],
            "warm_preload_wall_sec": wc["warm_preload_wall_sec"],
            "llm_calls": len(llm_sink), "in_tokens": in_tok,
            "out_tokens": out_tok,
            "mean_tps": round(sum(c.get("throughput_tps", 0.0) for c in llm_sink)
                              / max(len(llm_sink), 1), 2),
            "mean_ttft_ms": round(sum(c.get("TTFT_ms", 0.0) for c in llm_sink)
                                  / max(len(llm_sink), 1), 1)},
        "nloc_per_hour": {
            "source_total_wall": round(
                r1["sub_nloc"] / max(wc["total_wall_sec"] / 3600, 1e-9), 1),
            "source_delivery_inclusive": round(
                r1["sub_nloc"] / max(wc["delivery_wall_sec"] / 3600, 1e-9), 1)},
    }, indent=2))
    (golden / "README.md").write_text(
        "# 18-H Optimized Real Project Deliverable\n\n"
        "BANKING_CORE -> Spring Boot with critical-path optimizations "
        "(build||inference overlap, warm keep-alive fleet, Maven -B -q -T 1C, "
        "parallel RAG, fast health polling). Use package/. Evidence in evidence/.\n")


def main():
    (r1, r2, pkg, first, llm_sink, prov_sink, warm_sink, res_sink, wc) = asyncio.run(amain())
    perf_root = ea.REPO_ROOT / "18H_OPTIMIZATION"
    golden = perf_root / "18H_REAL_PROJECT_DELIVERABLE"
    _write_evidence(golden / "evidence", golden, r1, r2, pkg, first,
                    llm_sink, prov_sink, warm_sink, res_sink, wc)
    print("18-H OPTIMIZED RUN COMPLETE total=%.1fs delivery=%.1fs r1=%.1fs r2=%.1fs "
          "warm=%.1fs llm=%d classes=%d jar=%d" % (
              wc["total_wall_sec"], wc["delivery_wall_sec"], wc["run1_wall_sec"],
              wc["run2_wall_sec"], wc["warm_preload_wall_sec"],
              len(llm_sink), r1["classes"], pkg["jar_bytes"]), flush=True)


if __name__ == "__main__":
    main()

