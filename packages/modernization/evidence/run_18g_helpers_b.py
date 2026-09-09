import asyncio
import hashlib
import json
import time
import urllib.request
from datetime import datetime, timezone


def sha256_of(content):
    if isinstance(content, str):
        content = content.encode("utf-8")
    return hashlib.sha256(content).hexdigest()


async def async_call_ollama(endpoint, model, role, prompt, task_type, project_id,
                            task_id, artifact_affected, machine_name, worker_id,
                            telemetry_sink, timeout=120):
    req_id = "llm-%s-%d-%d" % (machine_name.lower(), int(time.time() * 1000),
                               len(telemetry_sink) + 1)
    t_start = time.perf_counter()
    ts_iso = datetime.now(timezone.utc).isoformat()
    payload = json.dumps({"model": model, "prompt": prompt, "stream": False,
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
               "retry_count": 0, "result": "SUCCESS"}
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
               "retry_count": 1, "result": "FAILED: %s" % e}
        telemetry_sink.append(tel)
        return {"response": "", "telemetry": tel}
