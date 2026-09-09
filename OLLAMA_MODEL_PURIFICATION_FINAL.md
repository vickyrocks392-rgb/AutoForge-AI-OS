# AUTOFORGE AI — FINAL OLLAMA MODEL PURIFICATION REPORT

## 1. Executive Summary

We have permanently purified both local Ollama inference nodes and locked the **authoritative Four-Model Production Fleet** across AutoForge AI's distributed infrastructure. All non-canonical models, speculative/benchmark models, and unquantized/inferior duplicate variants have been cleanly removed using the official Ollama deletion API.

---

## 2. Storage & Model Count Summary

### Apple Silicon M1 Node (`http://127.0.0.1:11434`)
* **Before Purification**: 10 models (33.98 GB)
* **After Purification**: **3 models (7.91 GB)**
* **Reclaimed Space**: **26.07 GB**

### HP Windows Host (`http://192.168.1.102:11434`)
* **Before Purification**: 12 models (38.73 GB)
* **After Purification**: **1 model (1.80 GB)**
* **Reclaimed Space**: **36.93 GB**

### Total Fleet
* **Fleet Total Before**: 22 models (72.72 GB)
* **Fleet Total After**: **4 models (9.71 GB)**
* **Total Storage Reclaimed**: **63.01 GB**

---

## 3. Canonical Production Fleet Topology

| Host | Canonical Role | Model ID | Physical Ollama Tag | Quantization | Size | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **M1** | Primary Coding & Modernization | `qwen2.5-coder-7b` | `qwen2.5-coder:7b-instruct-q3_K_M` | Q3_K_M | 3.55 GB | **ACTIVE** |
| **M1** | Architectural Reasoning & Planning | `ornith-9b` | `ornith-9b-iq3m-4k:latest` | IQ3_M | 4.11 GB | **ACTIVE** |
| **M1** | Vector Embeddings for Qdrant RAG | `nomic-embed-text` | `nomic-embed-text:latest` | F16 | 0.25 GB | **ACTIVE** |
| **HP** | Secondary Distributed Coding Worker | `qwen2.5-coder-3b` | `qwen2.5-coder:3b` | Q4_K_M | 1.80 GB | **ACTIVE** |

---

## 4. Retained Non-Canonical Models

`NONE` (Zero non-canonical, speculative, or duplicate models remain installed on either host).

---

## 5. Deleted Models & Rationale

### M1 Node (7 models purged):
1. `deepseek-coder:6.7b-instruct` (3.56 GB) — Speculative alternative model not in production fleet.
2. `llama3.2:3b` (1.88 GB) — Speculative helper model not in production fleet.
3. `maxwell1500/ornith-9b:IQ3_M` (4.11 GB) — Redundant tag alias of `ornith-9b-iq3m-4k:latest`.
4. `qwen2.5-coder:7b` (4.70 GB) — Unquantized duplicate of `qwen2.5-coder:7b-instruct-q3_K_M`.
5. `ornith:9b` (5.20 GB) — Unquantized duplicate of `ornith-9b-iq3m-4k:latest`.
6. `qwen3:4b` (2.50 GB) — Zero references in AutoForge codebase.
7. `llama3.1:8b` (4.12 GB) — Unneeded heavy model.

### HP Windows Host (11 models purged):
1. `deepseek-coder:6.7b-instruct-q3_K_M` (3.07 GB) — Speculative alternative model not in production fleet.
2. `qwen2.5-coder:7b-instruct-q3_K_M` (3.55 GB) — Speculative symmetric model (HP role is 3b).
3. `ornith-9b-iq3m-4k:latest` (4.11 GB) — Speculative reasoning model (M1 holds reasoning role).
4. `llama3.2:3b` (1.88 GB) — Speculative helper model not in production fleet.
5. `deepseek-coder:6.7b-instruct-q2_K` (2.60 GB) — Inferior q2_K quantization.
6. `deepseek-coder:6.7b-instruct` (3.56 GB) — Unquantized duplicate.
7. `qwen2.5-coder:7b-instruct-q2_K` (2.90 GB) — Inferior q2_K quantization.
8. `qwen2.5-coder:7b` (4.70 GB) — Unquantized duplicate.
9. `starcoder2:7b` (4.10 GB) — Zero references in AutoForge codebase.
10. `yi-6b-4k:latest` (3.60 GB) — Zero references in AutoForge codebase.
11. `hf.co/SamPurkis/Yi-6B-GGUF:Q4_K_M` (3.60 GB) — Redundant tag alias.
12. `maxwell1500/ornith-9b:IQ3_M` (4.11 GB) — Redundant tag alias.

---

## 6. Live Verifications

* **M1 Primary Qwen (`qwen2.5-coder:7b-instruct-q3_K_M`)**: 2.94s (8.50 tok/s) — **PASS**
* **M1 Architectural Reasoning (`ornith-9b-iq3m-4k:latest`)**: 11.74s (4.26 tok/s) — **PASS**
* **M1 Vector Embedding (`nomic-embed-text:latest`)**: 1.167s (Dense dimension: 768) — **PASS**
* **HP Secondary Qwen (`qwen2.5-coder:3b`)**: 6.36s (7.86 tok/s) — **PASS**
* **HP Qdrant Database (`http://192.168.1.102:6333`)**: Reachable (10 collections) — **PASS**

---

## 7. Concurrent Distributed Smoke Test (4 Parallel Workers)

* **Wall-Clock Duration**: **14.04s**
* **Total Tokens Generated**: **200 tokens**
* **Aggregate Effective Throughput**: **14.25 tokens/second**
* **Worker Breakdown**:
  - `m1-worker-1` (`http://127.0.0.1:11434`): 9.13s | 50 tokens | 5.48 tok/s | Success: True
  - `m1-worker-2` (`http://127.0.0.1:11434`): 13.92s | 50 tokens | 3.59 tok/s | Success: True
  - `hp-worker-1` (`http://192.168.1.102:11434`): 6.16s | 50 tokens | 8.12 tok/s | Success: True
  - `hp-worker-2` (`http://192.168.1.102:11434`): 11.02s | 50 tokens | 4.54 tok/s | Success: True

---

## 8. Routing Integrity & Test Suite Verification

* **Dangling Model References**: **0**
* **Workforce Model Allocation & Router Tests**: **11 passed out of 11 (100%)**
  - `packages/workforce/tests/test_model_allocation.py` (10/10 passed)
  - `packages/workforce/tests/test_real_runtime_integration.py` (1/1 passed)
