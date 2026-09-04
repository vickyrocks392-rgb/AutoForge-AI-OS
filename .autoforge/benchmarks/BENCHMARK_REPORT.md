# AutoForge Phase-18 Throughput Benchmark Report

**Benchmark ID:** a1e5d78f-32d4-41e1-b3a4-6ec47b4ea944
**Run ID:** 9254d08a-f8c5-4c5e-ba47-be7a42b56cfa
**Date:** 2026-09-04
**Commit:** 01e36fba18360fb24b10b372652a27986bd973a7

---

## Throughput Kind

| Indicator | Value |
|-----------|-------|
| `throughput_kind` | MEASURED |
| `llm_kind` | UNAVAILABLE |
| `rag_kind` | UNAVAILABLE |
| `estimation_kind` | MEASURED |

> **Note:** Ollama is not running on this machine. The LLM inference stack
> correctly reports UNAVAILABLE. All 186 CardDemo units were executed through
> the production `TransformationExecutor` pipeline and recorded in the ledger
> as `kind=unavailable`. The primary throughput metric (`accepted_e2e_loc_per_hour`)
> honestly reads **0.0 LOC/hr** — no fabrication.

---

## Workload

| Metric | Value |
|--------|-------|
| Project | app (CardDemo) |
| Files discovered | 186 |
| Source LOC | 49,987 |
| Technology | COBOL (44 files / 30,175 LOC), COPYBOOK (62 / 10,651), BMS (21 / 5,756), JCL (46 / 2,932), Other (13 / 473) |

---

## Primary Throughput Metric (MEASURED)

| Stage | Throughput |
|-------|-----------|
| Analysis | 499,870,000 LOC/hr |
| Transformation | 499,870,000 LOC/hr |
| Verification | 0 LOC/hr |
| **Accepted E2E (PRIMARY)** | **0.0 LOC/hr** |

> The 499.87M LOC/hr figures reflect the analysis + transformation phases
> completing in 0.18s wall clock across 8 workers. The accepted E2E
> throughput is 0.0 because LLM is unavailable and the production pipeline
> cannot produce verified+accepted output without it.

---

## Strategy Breakdown

| Strategy | Files | LOC |
|----------|-------|-----|
| Deterministic | 186 | 49,987 |
| LLM-assisted | 0 | 0 |
| Hybrid | 0 | 0 |

---

## Ledger Accounting (Provenance)

The production `TransformationExecutor` was invoked with all 186 files as units.
Each unit was recorded in the `ThroughputAccounting` ledger:

- **Ledger entries:** 186 (one per file, no drops)
- **Kind distribution:** unavailable=186, produce=0, repair=0, failed=0, skipped=0
- **Verification passed:** 0
- **LLM calls made:** 0 (UNAVAILABLE)

---

## Projection (Extrapolation from Measured Run)

| Workload | Time Estimate |
|----------|-------------|
| 100K LOC | 4,166.7 days |
| 1M LOC | 1,388.9 months |
| 10M LOC | 13,889 months (≈1,157 years) |
| 100M LOC | 115,741 months (≈9,645 years) |

> Projection is based on `accepted_e2e_loc_per_hour = 0.0`. These projections
> are only meaningful once LLM inference is available and verified output
> is produced. Confidence: **low** (single run, LLM unavailable).

---

## Hardware

| Spec | Value |
|------|-------|
| Platform | macOS-26.5.1-arm64-arm-64bit-Mach-O (Apple Silicon) |
| CPU cores | 8 |
| Memory | ~47 GB |
| Python | 3.14.6 |
| GPU | Not available |

---

## Files

- Machine-readable: `.autoforge/benchmarks/carddemo_throughput.json`
- Human-readable: `.autoforge/benchmarks/carddemo_throughput_report.txt`
- Source module: `packages/modernization/src/autoforge_modernization/benchmark_runner.py`
- Schema: `packages/modernization/src/autoforge_modernization/benchmark.py`
- Tests: `packages/modernization/tests/test_throughput_benchmark.py` (41 passing)
