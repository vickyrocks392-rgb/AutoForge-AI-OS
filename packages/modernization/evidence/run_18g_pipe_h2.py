"""18-G pipe H2: restart-consistency + main entrypoint."""
import asyncio
import json
import subprocess
import time
from datetime import datetime, timezone


def clean_env_restart(mod, port, before):
    java_bin = mod["java_bin"]()
    clean_jar = mod["CLEANDIR"] / "app.jar"
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           "JAVA_HOME": "/opt/homebrew/Cellar/openjdk/26.0.2.1/libexec/openjdk.jdk/Contents/Home"}
    with open(mod["CLEANDIR"] / "clean_restart.log", "w") as logf:
        proc2 = subprocess.Popen(
            [java_bin, "-Dserver.port=%d" % port, "-Dspring.main.banner-mode=off",
             "-jar", str(clean_jar)],
            stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    deadline = time.time() + 45
    up2 = False
    while time.time() < deadline:
        time.sleep(1.0)
        if proc2.poll() is not None:
            break
        try:
            st, body = mod["http_get"](port, "/api/health", timeout=2.0)
            if st == 200 and body.get("status") == "UP":
                up2 = True
                break
        except Exception:
            continue
    assert up2, "clean-env restart failed"
    after = mod["http_get"](port, "/api/subsystem/components")[1]["totalComponents"]
    proc2.terminate()
    try:
        proc2.wait(timeout=8)
    except Exception:
        proc2.kill()
    assert before == after
    return {"step": "restart-consistency", "status": "PASSED",
            "before": before, "after": after}


async def amain(wire):
    mod = wire()
    for d in (mod["OUTDIR"], mod["EVDIR"], mod["PKGDIR"], mod["CLEANDIR"]):
        d.mkdir(parents=True, exist_ok=True)
    llm_sink = []
    prov_sink = []
    t_cert = time.perf_counter()
    r1 = await mod["run_once"]("1", 8091, llm_sink, prov_sink)
    pkg = mod["do_package"](r1["jar"], r1["bdir"])
    first = mod["clean_env"](mod, pkg["jar"], 8092)
    second = clean_env_restart(mod, 8092, first["components"])
    first["checks"].append(second)
    clean = first
    r2 = await mod["run_once"]("2", 8093, llm_sink, prov_sink)
    assert r2["sub_files"] == r1["sub_files"]
    assert r2["sub_loc"] == r1["sub_loc"]
    assert r2["classes"] == r1["classes"]
    assert all(b["status"] == "PASSED" for b in r2["behavior"])
    total_wall = time.perf_counter() - t_cert
    in_tok = sum(c.get("input_tokens", 0) for c in llm_sink)
    out_tok = sum(c.get("output_tokens", 0) for c in llm_sink)
    m1 = [c for c in llm_sink if c["machine"] == "M1"]
    hp = [c for c in llm_sink if c["machine"] == "HP"]

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
        "package": pkg, "clean_env": clean,
        "telemetry": {"wall_sec": round(total_wall, 2), "llm_calls": len(llm_sink),
                      "m1": len(m1), "hp": len(hp),
                      "in_tokens": in_tok, "out_tokens": out_tok,
                      "mean_tps": mean([c.get("throughput_tps", 0.0) for c in llm_sink])},
        "nloc_per_hour": {
            "source": round(r1["sub_nloc"] / max(total_wall / 3600, 1e-9), 1)},
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


def run_main(wire):
    asyncio.run(amain(wire))
