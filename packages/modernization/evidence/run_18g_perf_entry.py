"""18-G commercial performance: instrumented real-workload rerun (Run 8).

Same production pipes, same workload, same config as 18-G Run 7.
No workload change. Only instrumentation added:
  - ISO wall-clock timestamps (run start/stop, per-run, delivery, total)
  - target source LOC/NLOC (captured in pipe_build before lifecycle purge)
  - AI design-note output metrics (pipe_inference)
  - resource sampler (cpu/rss for ollama/java/mvn via ps, no new deps)
Outputs to 18G_COMMERCIAL_PERFORMANCE/run8 — golden 18G baseline untouched.
"""
import asyncio
import json
import subprocess
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

from run_18g_entry_d import _wire, _strip
from run_18g_entry_c2 import _run_once
import run_18g_entry_c2 as c2
from run_18g_pipe_g import pipe_package
from run_18g_pipe_h2 import clean_env_restart
from run_18g_entry_a import REPO_ROOT
from run_18g_helpers_b import sha256_of


def _iso():
    return datetime.now(timezone.utc).isoformat()


def _resource_sampler(stop_evt, sink, interval=2.0):
    while not stop_evt.is_set():
        try:
            out = subprocess.run(
                ["ps", "-axo", "%cpu,rss,comm"],
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
    perf_root = REPO_ROOT / "18G_COMMERCIAL_PERFORMANCE" / "run8"
    golden = perf_root / "18G_REAL_PROJECT_DELIVERABLE"
    for d in (perf_root, golden / "evidence", golden / "package", golden / "clean_env"):
        d.mkdir(parents=True, exist_ok=True)
    # redirect all in-pipeline writes under the perf tree (instrumentation only)
    c2.REPO_ROOT = perf_root

    mod = _wire()
    mod["OUTDIR"] = golden
    mod["EVDIR"] = golden / "evidence"
    mod["PKGDIR"] = golden / "package"
    mod["CLEANDIR"] = golden / "clean_env"
    golden_pkg = mod["PKGDIR"]

    def do_package(jar, bdir):
        return pipe_package({"PKGDIR": golden_pkg, "Path": Path,
                             "sha": sha256_of}, jar, bdir)

    mod["do_package"] = do_package

    llm_sink: list = []
    prov_sink: list = []
    res_sink: list = []
    stop_evt = threading.Event()
    sampler = threading.Thread(target=_resource_sampler,
                               args=(stop_evt, res_sink), daemon=True)
    sampler.start()

    wall_start_iso = _iso()
    t_cert = time.perf_counter()

    r1_start_iso = _iso()
    t1 = time.perf_counter()
    r1 = await mod["run_once"]("1", 8091, llm_sink, prov_sink)
    r1_wall = time.perf_counter() - t1
    r1_end_iso = _iso()

    pkg_start_iso = _iso()
    t2 = time.perf_counter()
    pkg = mod["do_package"](r1["jar"], r1["bdir"])
    pkg_wall = time.perf_counter() - t2

    t3 = time.perf_counter()
    first = mod["clean_env"](mod, pkg["jar"], 8092)
    rest = clean_env_restart(mod, 8092, first["components"])
    first["checks"].append(rest)
    cleanenv_wall = time.perf_counter() - t3

    # OFFICIAL single-delivery end-to-end: workload -> packaged -> clean-output
    # launch -> independent behavioral verification -> restart consistency.
    delivery_wall = time.perf_counter() - t_cert
    delivery_end_iso = _iso()

    r2_start_iso = _iso()
    t4 = time.perf_counter()
    r2 = await mod["run_once"]("2", 8093, llm_sink, prov_sink)
    r2_wall = time.perf_counter() - t4
    r2_end_iso = _iso()
    assert r2["sub_files"] == r1["sub_files"]
    assert r2["sub_loc"] == r1["sub_loc"]
    assert r2["classes"] == r1["classes"]
    assert all(b["status"] == "PASSED" for b in r2["behavior"])
    assert all(b["status"] == "PASSED" for b in r1["behavior"])

    total_wall = time.perf_counter() - t_cert  # includes repeatability run 2
    wall_stop_iso = _iso()
    stop_evt.set()
    sampler.join(timeout=3)

    evdir = mod["EVDIR"]
    (evdir / "run1.json").write_text(json.dumps(_strip(r1), indent=2))
    (evdir / "run2.json").write_text(json.dumps(_strip(r2), indent=2))
    (evdir / "llm_calls.jsonl").write_text(
        "\n".join(json.dumps(c) for c in llm_sink) + "\n")
    (evdir / "provenance_manifest.json").write_text(
        json.dumps(prov_sink, indent=2))
    (evdir / "rag_telemetry.json").write_text(
        json.dumps(r1["rag"] + r2["rag"], indent=2))
    (evdir / "repair_telemetry.json").write_text(
        json.dumps(r1["rep"] + r2["rep"], indent=2))
    (evdir / "resource_samples.json").write_text(
        json.dumps(res_sink, indent=2))
    (evdir / "wall_clock.json").write_text(json.dumps({
        "wall_start": wall_start_iso, "wall_stop": wall_stop_iso,
        "run1": {"start": r1_start_iso, "end": r1_end_iso,
                 "wall_sec": round(r1_wall, 2)},
        "run2": {"start": r2_start_iso, "end": r2_end_iso,
                 "wall_sec": round(r2_wall, 2)},
        "package_wall_sec": round(pkg_wall, 2),
        "clean_env_wall_sec": round(cleanenv_wall, 2),
        "delivery_wall_sec": round(delivery_wall, 2),
        "delivery_end": delivery_end_iso,
        "total_wall_sec": round(total_wall, 2),
    }, indent=2))
    (golden / "README.md").write_text(
        "# 18-G Run 8 (instrumented commercial performance rerun)\n\n"
        "Same workload/config as Run 7. Telemetry only. Use package/.\n")
    print("18-G RUN 8 COMPLETE total=%.1fs delivery=%.1fs r1=%.1fs r2=%.1fs "
          "llm=%d classes=%d jar=%d" % (
              total_wall, delivery_wall, r1_wall, r2_wall,
              len(llm_sink), r1["classes"], pkg["jar_bytes"]), flush=True)


if __name__ == "__main__":
    asyncio.run(amain())
