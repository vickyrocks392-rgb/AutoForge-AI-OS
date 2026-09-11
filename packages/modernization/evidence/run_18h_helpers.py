"""18-H optimization helpers: warm fleet, keep-alive LLM calls, semantic cache,
parallel RAG, fast clean-env variants. Golden 18-G files are NOT modified."""
import asyncio
import hashlib
import json
import shutil
import subprocess
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path


def _iso():
    return datetime.now(timezone.utc).isoformat()


# ---------------------------------------------------------------- warm LLM call


async def async_call_ollama_warm(endpoint, model, role, prompt, task_type, project_id,
                                 task_id, artifact_affected, machine_name, worker_id,
                                 telemetry_sink, timeout=120):
    """Identical contract to run_18g_helpers_b.async_call_ollama, plus:
      * keep_alive=-1 so the model stays resident (TTFT optimization)
      * optional cache lookup via sink attribute `_18h_cache` (dict or None)
    Telemetry schema is unchanged; cache hits add cache_hit: true."""
    cache = getattr(telemetry_sink, "_18h_cache", None)
    ckey = None
    if cache is not None:
        ckey = "%s|%s|%s" % (model, machine_name,
                             hashlib.sha256(prompt.encode("utf-8")).hexdigest())
        cached = cache.get(ckey)
        if cached is not None:
            tel = {"request_id": "llm-cache-%s-%d" % (machine_name.lower(),
                                                      len(telemetry_sink) + 1),
                   "timestamp": _iso(), "project_id": project_id,
                   "task_id": task_id, "machine": machine_name, "endpoint": endpoint,
                   "model": model, "role": role, "worker": worker_id,
                   "task": task_type, "artifact_affected": artifact_affected,
                   "input_tokens": 0, "output_tokens": 0, "TTFT_ms": 0.0,
                   "generation_latency_ms": 0.0, "total_latency_ms": 0.0,
                   "throughput_tps": 0.0, "tokens_per_second": 0.0,
                   "retry_count": 0, "result": "SUCCESS", "cache_hit": True}
            telemetry_sink.append(tel)
            return {"response": cached, "telemetry": tel}

    req_id = "llm-%s-%d-%d" % (machine_name.lower(), int(time.time() * 1000),
                               len(telemetry_sink) + 1)
    t_start = time.perf_counter()
    ts_iso = _iso()
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False,
                          "keep_alive": -1,
                          "options": {"temperature": 0.1, "num_predict": 160}}).encode()
    req = urllib.request.Request(endpoint + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    loop = asyncio.get_event_loop()
    try:
        raw = await loop.run_in_executor(
            None, lambda: urllib.request.urlopen(req, timeout=timeout).read())
        data = json.loads(raw.decode("utf-8"))
        total_ms = (time.perf_counter() - t_start) * 1000.0
        pe = data.get("prompt_eval_count", int(len(prompt.split()) * 1.3))
        ec = data.get("eval_count", 0)
        ens = data.get("eval_duration", total_ms * 1000000)
        gen_ms = ens / 1000000.0 if ens else total_ms * 0.85
        ttft = max(total_ms - gen_ms, 1.0)
        tps = (ec / (gen_ms / 1000.0)) if gen_ms > 0 and ec else 0.0
        tel = {"request_id": req_id, "timestamp": ts_iso, "project_id": project_id,
               "task_id": task_id, "machine": machine_name, "endpoint": endpoint,
               "model": model, "role": role, "worker": worker_id, "task": task_type,
               "artifact_affected": artifact_affected, "input_tokens": int(pe),
               "output_tokens": int(ec), "TTFT_ms": round(ttft, 2),
               "generation_latency_ms": round(gen_ms, 2),
               "total_latency_ms": round(total_ms, 2),
               "throughput_tps": round(tps, 2), "tokens_per_second": round(tps, 2),
               "retry_count": 0, "result": "SUCCESS", "cache_hit": False}
        if cache is not None and ckey is not None:
            cache[ckey] = data.get("response", "")
        telemetry_sink.append(tel)
        return {"response": data.get("response", ""), "telemetry": tel}
    except Exception as e:
        total_ms = (time.perf_counter() - t_start) * 1000.0
        tel = {"request_id": req_id, "timestamp": ts_iso, "project_id": project_id,
               "task_id": task_id, "machine": machine_name, "endpoint": endpoint,
               "model": model, "role": role, "worker": worker_id, "task": task_type,
               "artifact_affected": artifact_affected,
               "input_tokens": len(prompt.split()), "output_tokens": 0,
               "TTFT_ms": 0.0, "generation_latency_ms": 0.0,
               "total_latency_ms": round(total_ms, 2),
               "throughput_tps": 0.0, "tokens_per_second": 0.0,
               "retry_count": 1, "result": "FAILED: %s" % e, "cache_hit": False}
        telemetry_sink.append(tel)
        return {"response": "", "telemetry": tel}


def persist_cache(store, cache_path):
    try:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(json.dumps(store, indent=2), "utf-8")
    except Exception:
        pass


# ---------------------------------------------------------------- warm preload


async def warm_preload(preloads, sink=None):
    """Preload models on each endpoint so they stay resident (keep_alive=-1).
    preloads: list of (endpoint, model_tag, machine_name)."""
    async def one(ep, tag, machine):
        payload = json.dumps({"model": tag, "prompt": "warm", "stream": False,
                              "keep_alive": -1,
                              "options": {"num_predict": 1, "temperature": 0.0}}).encode()
        req = urllib.request.Request(ep + "/api/generate", data=payload,
                                     headers={"Content-Type": "application/json"})
        t0 = time.perf_counter()
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                json.loads(resp.read().decode("utf-8"))
            wall = round((time.perf_counter() - t0) * 1000.0, 1)
            if sink is not None:
                sink.append({"endpoint": ep, "model": tag, "machine": machine,
                             "warm_load_ms": wall, "result": "SUCCESS"})
            return wall
        except Exception as e:
            if sink is not None:
                sink.append({"endpoint": ep, "model": tag, "machine": machine,
                             "warm_load_ms": round((time.perf_counter() - t0) * 1000.0, 1),
                             "error": str(e)})
            return None
    await asyncio.gather(*[one(*p) for p in preloads])


# ---------------------------------------------------------------- parallel RAG


def run_rag_parallel(raw_rag, embed_fn, qdrant_url, pid, queries, rag_tel):
    """Run independent RAG queries concurrently (Qdrant stays HP-only)."""
    import concurrent.futures as cf
    sinks = [[] for _ in queries]
    with cf.ThreadPoolExecutor(max_workers=len(queries)) as ex:
        futs = [ex.submit(raw_rag, qdrant_url, embed_fn, pid, q, sinks[i])
                for i, q in enumerate(queries)]
        for f in futs:
            f.result()
    for s in sinks:
        rag_tel.extend(s)


# ---------------------------------------------------------- fast clean-env ops


def _start_app(java_bin, jar, port, log_path, env):
    logf = open(log_path, "w")
    proc = subprocess.Popen(
        [java_bin, "-Dserver.port=%d" % port, "-Dspring.main.banner-mode=off",
         "-jar", str(jar)],
        stdout=logf, stderr=subprocess.STDOUT, env=env, start_new_session=True)
    return logf, proc


def _wait_up(proc, port, http_get, timeout=45, poll=0.1):
    deadline = time.time() + timeout
    while time.time() < deadline:
        time.sleep(poll)
        if proc.poll() is not None:
            return False
        try:
            st, body = http_get(port, "/api/health", timeout=2.0)
            if st == 200 and body.get("status") == "UP":
                return True
        except Exception:
            continue
    return False


def clean_env_workflow_fast(mod, jar_path, port):
    """Same checks as run_18g_pipe_h1.clean_env_workflow, 0.1s health polling."""
    mod["CLEANDIR"].mkdir(parents=True, exist_ok=True)
    clean_jar = mod["CLEANDIR"] / "app.jar"
    shutil.copyfile(jar_path, clean_jar)
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           "JAVA_HOME": "/opt/homebrew/Cellar/openjdk/26.0.2.1/libexec/openjdk.jdk/Contents/Home"}
    java_bin = mod["java_bin"]()
    log_path = mod["CLEANDIR"] / "clean_run.log"
    logf, proc = _start_app(java_bin, clean_jar, port, log_path, env)
    up = _wait_up(proc, port, mod["http_get"])
    assert up, "clean-env app failed to start; see %s" % log_path
    checks = [{"step": "install+start", "status": "PASSED"}]
    for name, path in [("health", "/api/health"),
                       ("actuator", "/actuator/health"),
                       ("components", "/api/subsystem/components")]:
        st, body = mod["http_get"](port, path)
        ok = st == 200 and (body.get("status") in ("UP", "SUCCESS")
                            or "totalComponents" in body or "returnCode" in body)
        checks.append({"step": name, "status": "PASSED" if ok else "FAILED", "http": st})
        assert ok, "clean-env step failed: %s -> %s" % (name, st)
    for name, path in [("date-op", "/api/subsystem/evaluate-date?date=2026-09-06"),
                       ("batch-op", "/api/subsystem/execute/Bnkstmt"),
                       ("transfer-op", "/api/execute/Bnk1tfn/execute")]:
        st, body = mod["http_get"](port, path)
        ok = st == 200 and ("returnCode" in body or "status" in body)
        checks.append({"step": name, "status": "PASSED" if ok else "FAILED", "http": st})
        assert ok, "clean-env step failed: %s -> %s" % (name, st)
    before = mod["http_get"](port, "/api/subsystem/components")[1]["totalComponents"]
    proc.terminate()
    try:
        proc.wait(timeout=8)
    except Exception:
        proc.kill()
    logf.close()
    return {"checks": checks, "log": str(log_path), "components": before,
            "proc_done": True}


def clean_env_restart_fast(mod, port, before):
    java_bin = mod["java_bin"]()
    clean_jar = mod["CLEANDIR"] / "app.jar"
    env = {"PATH": "/usr/bin:/bin:/opt/homebrew/bin",
           "JAVA_HOME": "/opt/homebrew/Cellar/openjdk/26.0.2.1/libexec/openjdk.jdk/Contents/Home"}
    logf, proc2 = _start_app(java_bin, clean_jar, port,
                             mod["CLEANDIR"] / "clean_restart.log", env)
    up2 = _wait_up(proc2, port, mod["http_get"])
    assert up2, "clean-env restart failed"
    after = mod["http_get"](port, "/api/subsystem/components")[1]["totalComponents"]
    proc2.terminate()
    try:
        proc2.wait(timeout=8)
    except Exception:
        proc2.kill()
    logf.close()
    assert before == after
    return {"step": "restart-consistency", "status": "PASSED",
            "before": before, "after": after}


