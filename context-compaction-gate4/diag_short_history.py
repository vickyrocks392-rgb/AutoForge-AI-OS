"""Diagnose the short-history required_facts=0 result in Arm B."""

"""Establish the M6 30B runtime's servable-context ceiling on this host.

Limitation probe (not an experiment). After the observed GPU OOM it is essential
to distinguish two candidate causes:
  (a) a genuine context-length ceiling, versus
  (b) permanent server poisoning after a single OOM.

Each probe runs against a freshly restarted server, so the two are separable.
"""

import json
import sys
import urllib.request
from pathlib import Path

from corpus import M6_MODEL_PATH

HERE = Path(__file__).parent


def ask(prompt: str, max_tokens: int = 24, timeout: int = 150):
    body = json.dumps({
        "model": M6_MODEL_PATH,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens, "temperature": 0.0,
    }).encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8080/v1/chat/completions", data=body,
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, json.loads(r.read())["choices"][0]["message"]["content"][:50]
    except Exception as exc:  # noqa: BLE001
        return False, f"{type(exc).__name__}: {str(exc)[:100]}"


def restart_server() -> None:
    import subprocess
    import time

    subprocess.run(["pkill", "-9", "-f", "mlx_lm.server"], check=False)
    time.sleep(8)
    subprocess.Popen(
        [sys.executable, "-u", "-m", "mlx_lm.server", "--model", M6_MODEL_PATH,
         "--host", "127.0.0.1", "--port", "8080"],
        stdout=open("/tmp/m6_probe.log", "w"), stderr=subprocess.STDOUT,
        stdin=subprocess.DEVNULL, start_new_session=True,
    )
    for _ in range(40):
        time.sleep(3)
        try:
            with urllib.request.urlopen("http://127.0.0.1:8080/v1/models", timeout=5):
                return
        except Exception:  # noqa: BLE001
            continue
    raise RuntimeError("M6 did not come up")


def main() -> int:
    # ~4 chars per token is the conservative ratio for this estimator.
    sizes = [600, 1200, 1800, 2400, 3400]
    rows = []
    for approx_tokens in sizes:
        restart_server()
        padding = "engineering iteration history line. " * int(approx_tokens / 3)
        prompt = f"CONTEXT:\n{padding}\n\nQ: Reply with the single word OK."
        ok, detail = ask(prompt)
        rows.append({"approx_tokens": approx_tokens, "served": ok, "detail": detail})
        print(f"approx_tokens={approx_tokens:5d} served={ok} {detail[:60]}")

    served = [r["approx_tokens"] for r in rows if r["served"]]
    print()
    print("MAX APPROX CONTEXT SERVED:", max(served) if served else "none")
    (HERE / "m6_context_limit.json").write_text(
        json.dumps({"probe": rows,
                    "max_approx_tokens_served": max(served) if served else None},
                   indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


