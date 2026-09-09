# AUTOFORGE AI — OLLAMA MODEL PURIFICATION REPORT

## Executive Summary

We performed a comprehensive forensic audit, classification, and purification of the local Ollama model registries on both the **Apple Silicon M1 Mac** (primary orchestration node) and the **HP Windows Host** (secondary distributed inference node over private LAN `192.168.1.102`).

Across both machines, **12 unused/duplicate models** were cleanly removed, reclaiming **44.95 GB of disk space** while preserving all canonical production models and optimization candidates for the upcoming heavy performance-optimization phase.

---

## 1. Disk Space & Model Count Summary

| Node / Metric | Models Before | Models After | Storage Before | Storage After | Space Reclaimed |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **M1 Mac (127.0.0.1)** | 10 | **5** | 33.98 GB | **13.36 GB** | **20.62 GB** |
| **HP Host (192.168.1.102)** | 12 | **5** | 38.73 GB | **14.41 GB** | **24.32 GB** |
| **TOTAL FLEET** | 22 | **10** | 72.72 GB | **27.77 GB** | **44.95 GB** |

---

## 2. Canonical Production Model Set

| Node | Canonical Model ID | Physical Tag | Purpose | Status |
| :--- | :--- | :--- | :--- | :--- |
| **M1** | `qwen2.5-coder-7b` | `qwen2.5-coder:7b-instruct-q3_K_M` | Primary code generation / transformation | **ACTIVE_PRODUCTION** |
| **M1** | `ornith-9b` | `ornith-9b-iq3m-4k:latest` | Architectural reasoning / planning | **ACTIVE_PRODUCTION** |
| **M1** | `nomic-embed-text` | `nomic-embed-text:latest` | 768-dim embedding for Qdrant RAG | **ACTIVE_PRODUCTION** |
| **HP** | `qwen2.5-coder-3b` | `qwen2.5-coder:3b` | Secondary/fast distributed code generation | **ACTIVE_PRODUCTION** |

---

## 3. Retained Planned Optimization Models

These models are preserved specifically for the upcoming heavy performance-optimization phase (benchmarking quantization, multi-model specialization, and symmetric 7B vs 3B distributed routing):
* **M1**: `llama3.2:3b` (1.88 GB) — Fast classification & testing
* **M1**: `deepseek-coder:6.7b-instruct` (3.56 GB) — Alternative coding architecture
* **HP**: `qwen2.5-coder:7b-instruct-q3_K_M` (3.55 GB) — Dual-7B symmetric distributed coding
* **HP**: `deepseek-coder:6.7b-instruct-q3_K_M` (3.07 GB) — Alternative quantized coder on HP
* **HP**: `ornith-9b-iq3m-4k:latest` (4.11 GB) — Distributed reasoning on HP
* **HP**: `llama3.2:3b` (1.88 GB) — Fast routing & auxiliary classification

---

## 4. Models Removed (UNUSED)

### M1 Mac (5 removed, 20.62 GB):
- `maxwell1500/ornith-9b:IQ3_M` (Duplicate alias of ornith-9b-iq3m-4k:latest (redundant tag))
- `qwen2.5-coder:7b` (Unquantized duplicate of qwen2.5-coder:7b-instruct-q3_K_M)
- `ornith:9b` (Unquantized duplicate of ornith-9b-iq3m-4k:latest)
- `qwen3:4b` (Zero references in AutoForge codebase)
- `llama3.1:8b` (Unneeded heavy model (llama3.2:3b and qwen2.5-coder serve all requirements))

### HP Windows Host (7 removed, 24.32 GB):
- `deepseek-coder:6.7b-instruct-q2_K` (Lower quality duplicate quant (q3_K_M retained))
- `deepseek-coder:6.7b-instruct` (Unquantized duplicate of deepseek-coder (q3_K_M retained))
- `qwen2.5-coder:7b-instruct-q2_K` (Lower quality duplicate quant (q3_K_M retained))
- `qwen2.5-coder:7b` (Unquantized duplicate of qwen2.5-coder:7b-instruct-q3_K_M)
- `yi-6b-4k:latest` (Zero references in AutoForge codebase)
- `hf.co/SamPurkis/Yi-6B-GGUF:Q4_K_M` (Zero references in AutoForge codebase (alias of yi-6b))
- `maxwell1500/ornith-9b:IQ3_M` (Duplicate alias of ornith-9b-iq3m-4k:latest)

---

## 5. Live Verification & Distributed Smoke Test

### Single-Model Generation Verification:
* **M1 Primary (`qwen2.5-coder:7b-instruct-q3_K_M`)**: 6.76s (3.11 tok/s) — **PASS**
* **M1 Reasoning (`ornith-9b-iq3m-4k:latest`)**: 13.05s (4.6 tok/s) — **PASS**
* **HP Secondary (`qwen2.5-coder:3b`)**: 8.74s (4.69 tok/s) — **PASS**

### Concurrent Distributed Smoke Test (4 Parallel Workers: 2 M1 + 2 HP):
* **Wall-Clock Duration**: **15.15s**
* **Total Tokens Generated**: **240 tokens**
* **Effective Aggregate Throughput**: **15.84 tok/s**
* **Worker Breakdown**:
  - `m1-worker-1` (http://127.0.0.1:11434) | 9.37s | 60 tokens | 6.4 tok/s
  - `m1-worker-2` (http://127.0.0.1:11434) | 15.13s | 60 tokens | 3.96 tok/s
  - `hp-worker-1` (http://192.168.1.102:11434) | 12.13s | 60 tokens | 4.95 tok/s
  - `hp-worker-2` (http://192.168.1.102:11434) | 6.14s | 60 tokens | 9.77 tok/s

---

## 6. Routing & Reference Integrity

* **Dangling Model References**: **0**
* **ModelRouterService & CapacityAwareRouter**: Fully verified.
* **Qdrant Embedding & Ingestion**: Unaffected (`nomic-embed-text` fully operational).
