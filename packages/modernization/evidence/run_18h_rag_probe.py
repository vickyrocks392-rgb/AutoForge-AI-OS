"""Regenerate RAG latency benchmark (parallel queries, HP-only Qdrant)."""
import json
import time
import urllib.request

from run_18g_entry_a import M1_URL, QD_URL
from run_18g_helpers_c import execute_qdrant_rag as _raw_rag, get_nomic_embedding
from run_18h_helpers import run_rag_parallel

rows = []
t0 = time.perf_counter()
run_rag_parallel(_raw_rag,
                 lambda q: get_nomic_embedding(M1_URL, "nomic-embed-text:latest", q),
                 QD_URL, "18hprobe",
                 ["Bank-of-Z account balance debit credit rules",
                  "Bank-of-Z funds transfer double-entry invariants",
                  "Bank-of-Z customer onboarding constraints"], rows)
wall = time.perf_counter() - t0
try:
    urllib.request.urlopen(urllib.request.Request(
        QD_URL + "/collections/project_18hprobe_knowledge", method="DELETE"), timeout=5)
except Exception:
    pass
json.dump({"timestamp": "18H probe", "mode": "parallel_queries",
           "parallel_wall_sec": round(wall, 3),
           "per_query_latency_ms": [r["latency_ms"] for r in rows],
           "queries": rows},
          open("/Users/kalachanddash/Documents/18H_OPTIMIZATION/rag_latency_benchmark.json", "w"),
          indent=2)
print("RAG parallel wall %.3fs" % wall)
