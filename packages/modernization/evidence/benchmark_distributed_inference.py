import asyncio
import httpx
import json
import time

m1_url = "http://127.0.0.1:11434/api/generate"
hp_url = "http://192.168.1.104:11434/api/generate"

prompt = "Translate this COBOL record definition to a modern Java domain model with getters and setters:\n01 TRANSACTION-RECORD.\n   05 TRANS-ID PIC X(16).\n   05 TRANS-AMOUNT PIC 9(9)V99.\n   05 TRANS-DATE PIC X(10).\n   05 TRANS-STATUS PIC XX.\nBe concise."

async def query(client, url, model):
    req_data = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "options": {"temperature": 0.1, "num_predict": 128}
    }
    t0 = time.perf_counter()
    r = await client.post(url, json=req_data, timeout=120)
    data = r.json()
    dur = time.perf_counter() - t0
    out_tok = data.get("eval_count", 0)
    return {"url": url, "model": model, "duration": dur, "tokens": out_tok}

async def main():
    async with httpx.AsyncClient() as client:
        # Serial execution (M1 then HP)
        t0_serial = time.perf_counter()
        res_m1 = await query(client, m1_url, "qwen2.5-coder:7b")
        res_hp = await query(client, hp_url, "qwen2.5-coder:3b")
        t_serial = time.perf_counter() - t0_serial
        total_tokens_serial = res_m1["tokens"] + res_hp["tokens"]

        m1_dur = res_m1["duration"]
        hp_dur = res_hp["duration"]
        print(f"SERIAL EXECUTION: M1={m1_dur:.2f}s, HP={hp_dur:.2f}s, Total Wall={t_serial:.2f}s, Tokens={total_tokens_serial}, EffTPS={total_tokens_serial/t_serial:.2f}")

        # Concurrent execution (M1 and HP simultaneously)
        t0_parallel = time.perf_counter()
        p_res_m1, p_res_hp = await asyncio.gather(
            query(client, m1_url, "qwen2.5-coder:7b"),
            query(client, hp_url, "qwen2.5-coder:3b"),
        )
        t_parallel = time.perf_counter() - t0_parallel
        total_tokens_parallel = p_res_m1["tokens"] + p_res_hp["tokens"]

        p_m1_dur = p_res_m1["duration"]
        p_hp_dur = p_res_hp["duration"]
        speedup = t_serial / t_parallel if t_parallel > 0 else 1.0
        efficiency = (speedup / 2.0) * 100.0
        print(f"PARALLEL EXECUTION: M1={p_m1_dur:.2f}s, HP={p_hp_dur:.2f}s, Total Wall={t_parallel:.2f}s, Tokens={total_tokens_parallel}, EffTPS={total_tokens_parallel/t_parallel:.2f}")
        print(f"SPEEDUP: {speedup:.2f}x (Scaling efficiency: {efficiency:.1f}%)")

if __name__ == "__main__":
    asyncio.run(main())
