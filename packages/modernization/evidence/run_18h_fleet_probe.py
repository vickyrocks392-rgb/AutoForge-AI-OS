"""18-H fleet probe: real measured routing/concurrency/batching/TTFT/RAG data.

Uses ONLY the canonical four-model fleet. Real Ollama calls to M1 + HP.
Results are written to 18H_OPTIMIZATION/*.json. No model is installed or changed.
"""
import asyncio
import json
import statistics
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from run_18g_entry_a import (
    CODING, HP_CODING, HP_URL, M1_URL, QD_URL, REASON, REPO_ROOT,
)
from run_18g_helpers_c import execute_qdrant_rag as _raw_rag, get_nomic_embedding

OUT = REPO_ROOT / "18H_OPTIMIZATION"
PROMPTS = {
    CODING: "Design balance-inquiry validation rules for a Spring banking service.",
    REASON: "Reason about customer onboarding validation and cross-module consistency.",
    HP_CODING: "Design inter-account transfer invariants: debit source and credit "
               "destination by the same amount; reject non-positive amounts.",
}
FLEET = [("M1", M1_URL, CODING), ("M1", M1_URL, REASON), ("HP", HP_URL, HP_CODING)]


def _call(endpoint, model, prompt, num_predict=96, timeout=180, keep_alive=-1):
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False,
                          "keep_alive": keep_alive,
                          "options": {"temperature": 0.1, "num_predict": num_predict}}).encode()
    req = urllib.request.Request(endpoint + "/api/generate", data=payload,
                                 headers={"Content-Type": "application/json"})
    t0 = time.perf_counter()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    total_ms = (time.perf_counter() - t0) * 1000.0
    ec = data.get("eval_count", 0)
    ens = data.get("eval_duration", total_ms * 1000000)
    gen_ms = ens / 1000000.0 if ens else total_ms * 0.85
    ttft = max(total_ms - gen_ms, 1.0)
    tps = (ec / (gen_ms / 1000.0)) if gen_ms > 0 and ec else 0.0
    return {"model": model, "total_ms": round(total_ms, 1), "ttft_ms": round(ttft, 1),
            "gen_ms": round(gen_ms, 1), "output_tokens": int(ec),
            "tps": round(tps, 2), "input_tokens": data.get("prompt_eval_count", 0)}


def solo_benchmark(reps=2):
    rows = []
    for machine, ep, model in FLEET:
        for i in range(reps):
            r = _call(ep, model, PROMPTS[model])
            r.update({"machine": machine, "rep": i + 1})
            rows.append(r)
    return rows


async def _aconcurrent(level, tasks_spec, num_predict=96):
    loop = asyncio.get_event_loop()

    async def one(machine, ep, model):
        return await loop.run_in_executor(
            None, lambda: _call(ep, model, PROMPTS[model], num_predict=num_predict))

    t0 = time.perf_counter()
    res = await asyncio.gather(*[one(*t) for t in tasks_spec])
    wall = time.perf_counter() - t0
    return {"level": level, "wall_sec": round(wall, 2),
            "calls": len(tasks_spec), "results": res,
            "aggregate_tps": round(sum(r["output_tokens"] for r in res) / wall, 2)}


async def concurrency_scaling():
    out = {}
    # fleet of 6 jobs (3 on M1 models, 3 on HP) exactly like 18-G inference stage
    base = [("M1", M1_URL, CODING), ("HP", HP_URL, HP_CODING),
            ("M1", M1_URL, REASON), ("HP", HP_URL, HP_CODING),
            ("M1", M1_URL, REASON), ("M1", M1_URL, CODING)]
    for level in (1, 2, 4, 6):
        spec = [base[i % len(base)] for i in range(level)]
        out[str(level)] = await _aconcurrent(level, spec)
    return out


async def batching_experiment():
    base = [("M1", M1_URL, CODING), ("HP", HP_URL, HP_CODING),
            ("M1", M1_URL, REASON), ("HP", HP_URL, HP_CODING),
            ("M1", M1_URL, REASON), ("M1", M1_URL, CODING)]
    loop = asyncio.get_event_loop()
    t0 = time.perf_counter()
    for m, ep, model in base:
        _call(ep, model, PROMPTS[model], num_predict=96)
    seq_wall = time.perf_counter() - t0
    batch = await _aconcurrent(6, base)
    return {"sequential_wall_sec": round(seq_wall, 2),
            "concurrent_wall_sec": batch["wall_sec"],
            "speedup": round(seq_wall / max(batch["wall_sec"], 0.01), 2),
            "note": "same 6 independent requests; no dependency ordering violated"}


def rag_latency():
    rows = []
    pid = "18hprobe"
    for q in ["Bank-of-Z account balance debit credit rules",
              "Bank-of-Z funds transfer double-entry invariants",
              "Bank-of-Z customer onboarding constraints"]:
        rec = _raw_rag(QD_URL, lambda t: get_nomic_embedding(M1_URL, "nomic-embed-text:latest", t),
                       pid, q, rows)
    # purge probe collection (project isolation)
    try:
        req = urllib.request.Request(QD_URL + "/collections/project_18hprobe_knowledge",
                                     method="DELETE")
        urllib.request.urlopen(req, timeout=5)
    except Exception:
        pass
    return rows


def embedding_latency(n=8):
    ts = []
    t0 = time.perf_counter()
    for i in range(n):
        t1 = time.perf_counter()
        get_nomic_embedding(M1_URL, "nomic-embed-text:latest", "query %d" % i)
        ts.append(round((time.perf_counter() - t1) * 1000.0, 1))
    wall = time.perf_counter() - t0
    return {"sequential_ms_each": ts, "sequential_wall_sec": round(wall, 2),
            "mean_ms": round(statistics.mean(ts), 1)}


async def amain():
    OUT.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).isoformat()

    print("[probe] solo model benchmark...", flush=True)
    solo = solo_benchmark()
    (OUT / "ttft_benchmark.json").write_text(json.dumps({
        "timestamp": stamp, "method": "real Ollama calls, num_predict=96, keep_alive=-1",
        "solo_results": solo,
        "per_model": {m: {"mean_ttft_ms": round(statistics.mean(
            r["ttft_ms"] for r in solo if r["model"] == m), 1),
            "mean_tps": round(statistics.mean(
                r["tps"] for r in solo if r["model"] == m), 2)}
            for m in {r["model"] for r in solo}}}, indent=2))
    print("[probe] concurrency scaling 1/2/4/6...", flush=True)
    conc = await concurrency_scaling()
    (OUT / "concurrency_benchmark.json").write_text(json.dumps({
        "timestamp": stamp, "fleet": "M1(qwen2.5-coder:7b-q3_K_M, ornith-9b-iq3m-4k) + HP(qwen2.5-coder:3b)",
        "levels": conc}, indent=2))
    print("[probe] batching experiment...", flush=True)
    batch = await batching_experiment()
    (OUT / "batching_benchmark.json").write_text(json.dumps({
        "timestamp": stamp, **batch}, indent=2))
    print("[probe] RAG + embedding latency...", flush=True)
    rag = rag_latency()
    emb = embedding_latency()
    (OUT / "rag_latency_benchmark.json").write_text(json.dumps({
        "timestamp": stamp, "qdrant": "HP-only (unchanged)", "rag_queries": rag,
        "embedding": emb}, indent=2))
    print("[probe] done", flush=True)


if __name__ == "__main__":
    asyncio.run(amain())

