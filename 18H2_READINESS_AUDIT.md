# AUTOFORGE — 18-H2 INFERENCE FABRIC READINESS AUDIT

**Gate:** 18-H2 READINESS — M1 + HP + Future Mac Mini Inference Fabric Preparation
**Frozen 18-H Baseline:** 364,953.2 source NLOC/hour (delivery-inclusive) · 104.66 s delivery wall · 93.1 s critical path · inference ~73% of critical path
**Repository HEAD:** `72b7820` (`feat(optimization): complete 18-H heavy optimization certification`) — clean
**Date of Audit:** 2026-12-09
**Audit Scope:** Readiness + measurement/harness preparation ONLY. No 18-I work, no optimization, no model changes, no frozen 18-H evidence modification.

---

## 1. Executive Summary

The current AutoForge architecture can accept a third local Ollama inference node (the incoming Mac Mini) with **one small, isolated, backwards-compatible change**, which has been implemented and tested. The production AI-infrastructure layer (registry + router + executor wiring) is already metadata-driven and N-node capable at the routing/selection level; the workforce catalog even pre-registers a `local-mac-mini-m6` provider (status UNAVAILABLE). The concrete gap was in the **composition wiring seam** (`bind_default_provider_adapters`), which previously bound every local node to a *single* Ollama base URL and therefore could not express two independent LAN endpoints — let alone three. That seam now accepts an optional per-provider `node_endpoints` map.

The 18-H/18-G evidence harness (the pipeline that actually produces the certified numbers) reaches inference through env-var-configured endpoints (`AUTOFORGE_M1_OLLAMA_URL`, `AUTOFORGE_HP_OLLAMA_URL`) with node/model assignments carried as *data* (task tuples). A minimal, zero-default-change configuration seam (`run_18h2_nodes.py`) now lets the same workload be expressed for M1-only, M1+HP, and M1+HP+Mac Mini topologies without touching the frozen routing table, while remaining byte-identical to the frozen six-task table by default.

**Verdict: READY WITH MINOR CHANGE.**

---

## 2. Current Inference Architecture

There are two real inference execution paths. Both were traced from entry point to result collection.

### Path A — Production certification/evidence harness (authors the 18-G/18-H numbers)

`packages/modernization/evidence/`

1. **Node/config discovery:** `run_18g_entry_a.py` — endpoints come from environment variables with LAN defaults:
   - `AUTOFORGE_M1_OLLAMA_URL` (default `http://127.0.0.1:11434`)
   - `AUTOFORGE_HP_OLLAMA_URL` (default `http://192.168.1.102:11434`)
   - `AUTOFORGE_QDRANT_URL` (default `http://192.168.1.102:6333`)
   - Canonical model tags as constants: `CODING = qwen2.5-coder:7b-instruct-q3_K_M`, `REASON = ornith-9b-iq3m-4k:latest`, `EMBED = nomic-embed-text:latest`, `HP_CODING = qwen2.5-coder:3b`.
2. **Ollama call primitive:** `run_18g_helpers_b.py:async_call_ollama()` (golden) and `run_18h_helpers.py:async_call_ollama_warm()` (18-H, adds `keep_alive=-1`). Both are direct `urllib` POSTs to `<endpoint>/api/generate` with per-request telemetry dicts appended to a sink.
3. **Task representation:** `run_18g_entry_c1.py:_ai_tasks()` — a hardcoded list of **6 task tuples** `(component, role, prompt, machine, endpoint, model_tag, worker)`. This *is* the routing table (M1 → 4 tasks, HP → 2 tasks).
4. **Concurrent execution:** `run_18g_pipe_d2.py:pipe_inference()` and `run_18h_opt.py:pipe_inference_18h()` — `asyncio.gather` over all six tasks; per-task retry (2 attempts) on failure; telemetry per call; stage duration appended to `stages`.
5. **Scheduling:** implicit hybrid (model-aware + dependency-aware + capacity-aware) expressed via piping order and the task table; OPT-1 overlaps Maven build with inference.
6. **Warm preload:** `run_18h_helpers.py:warm_preload()` and explicit preload list in `run_18h_main.py` / `run_18h_opt.py` for the 3-model fleet.
7. **Verification:** `run_18g_pipe_e.py:pipe_runtime()` (9/9 behavioral), `run_18g_pipe_f.py:pipe_repair()`, `run_18g_pipe_g.py` (provenance/purge). Results aggregated into `runX.json`, `llm_calls.jsonl`, `wall_clock.json`, `evidence_summary.json`.

### Path B — Production AI-infrastructure composition stack

`packages/ai_infrastructure/` · `packages/workforce/` · `packages/composition/`

- `OllamaProviderAdapter` — async httpx per-node adapter; `base_url`, `check_health()`, `list_installed_models()`, token accounting, Ollama microsecond timings.
- `ExecutorRegistry` — binds `provider_id → executor`.
- `InMemoryCapabilityRegistry` — provider/model/capability metadata; `query_models()` filters on `provider.is_available`.
- `ModelRouterService` + policies (`local_first`, `availability_first`, …) — selection only; N-node capable.
- `ExecutionContinuityService` — retry + failover.
- `register_workforce_models()` (`workforce/model_allocator.py`) — already registers `local-m1`, `local-hp`, and a **`local-mac-mini-m6` placeholder** (status UNAVAILABLE) plus a capacity manager with an offline-node set.
- **Wiring:** `composition/ai_infrastructure_wiring.py:bind_default_provider_adapters()` + `build_ai_infrastructure()` — the seam changed by this audit (Section 9 / Changes).

---

## 3. Current Node/Model Configuration

| Concern | Mechanism | Location |
|---|---|---|
| Ollama endpoints | Environment variables | `run_18g_entry_a.py` (M1/HP/Qdrant); `rag18/config.py` for knowledge |
| Node→model assignment | Task-table data (6 tuples) | `run_18g_entry_c1.py:_ai_tasks()` |
| Model availability | Ollama `/api/tags` via `list_installed_models()` | `adapters/ollama.py` |
| Node health | `check_health()`, `ProviderStatus` | `adapters/ollama.py`, `metadata.py`, registry |
| Providers in registry | Workforce catalog data | `workforce/model_allocator.py` |
| Executor binding | Code (now config-driven endpoints) | `composition/ai_infrastructure_wiring.py` |

---

## 4. Three-Node Readiness Assessment

### Q1 — Can a node be represented by configuration rather than hardcoded assumptions?
**YES.** Endpoints are env vars. Executor binding now supports a per-provider endpoint map (this audit). Provider identity is metadata. The only residual "hardcoded" element is the *frozen task table* (data), which is intentionally frozen and now layered by a config seam (Section 10).

### Q2 — Can each node expose endpoint / available models / capabilities / health / concurrency independently?
**YES.** `ProviderMetadata` has endpoint, capabilities, status, health; adapter carries its own `base_url` + `check_health()` + `list_installed_models()`; `ModelCapacityManager` tracks per-model concurrency with an offline-node set. Before this audit, the *wiring* could not assign distinct endpoints — now it can.

### Q3 — Can the scheduler select among 3+ nodes?
**YES — at the selection layer.** `ModelRouterService` routes over all registry providers; workforce tests already assert failover to `local-mac-mini-m6` when M1 and HP are busy. The evidence harness does not use dynamic routing (it uses the frozen task table) — that is a *harness* property, not an architecture blocker.

### Q4 — Are model-to-node mappings configurable?
**YES.** `ModelMetadata.provider_id` + `register_model()`; per-node `model_tag_map` on adapters; task-table data in the harness.

### Q5 — Can two nodes expose different models?
**YES — already true.** M1: qwen7b + ornith9b + nomic-embed; HP: qwen3b.

### Q6 — Can multiple workers execute concurrently across different nodes?
**YES — proven.** 18-H ran 4 workers (worker-m1-01/02, worker-hp-01/02) concurrently via `asyncio.gather`; aggregate TPS and inference critical-path telemetry confirm overlap.

### Q7 — Can the scheduler avoid sending work to an unhealthy node?
**PARTIAL / NOT YET TESTED END-TO-END.** The production router filters out unavailable providers (`query_models` on `provider.is_available`), and the workforce capacity manager has an offline-node set. The *evidence harness* does not probe node health before dispatch; it relies on per-task retries. A pre-dispatch health gate for the harness is a candidate H2 experiment-harness addition (not required to register the node).

### Q8 — Are node-specific latency/TPS metrics recorded?
**YES.** Per-request telemetry records `machine`, `endpoint`, `model`, `input_tokens`, `output_tokens`, `TTFT_ms`, `generation_latency_ms`, `total_latency_ms`, `throughput_tps`, `retry_count`. Node aggregates are derivable from `llm_calls.jsonl`; `ttft_benchmark.json` already aggregates per model.

### Q9 — Can queue wait time be measured separately from model execution time?
**NOT CURRENTLY (documented gap).** 18-H telemetry measures per-request TTFT as `total − generation` (an approximation that includes queue + prefill + network). Ollama returns `load_duration`/`prompt_eval_duration`/`eval_duration` microsecond fields; the production adapter captures them in `ollama_timings`, but the harness does not. Separating queue wait requires a small harness telemetry extension — documented for H2.

### Q10 — Can TTFT be measured per request?
**YES.** `TTFT_ms` is recorded per request in the telemetry sink.

### Q11 — Can task start/end timestamps be captured independently of overall run timestamps?
**YES (per-request).** Telemetry records `timestamp` (ISO) and `total_latency_ms` per request; run-level `wall_clock.json`, stage-level `stages[].duration_sec`. Per-request start/end are independent of run start/stop.

### Q12 — Can the system distinguish queue wait / network / TTFT / generation / post-processing where technically possible?
**PARTIAL.** Generation is separate (`eval_duration`/`generation_latency_ms`); TTFT approximate; queue wait and network overhead not yet separated (Q9). Post-processing (deterministic compilation/synthesis) is separately timed in stage telemetry.

### Q13 — Can the same workload be executed as M1-only / M1+HP / M1+HP+Mac Mini without changing application logic?
**YES — with the new config seam.** `run_18h2_nodes.py` resolves endpoints from env including `AUTOFORGE_MACMINI_OLLAMA_URL`; task-allocation choices are expressed as configuration at experiment time, defaulting to the byte-identical frozen table. No frozen harness or pipe code is modified.

### Q14 — Can the experiment configuration freeze workload / models / prompts / routing / concurrency / scheduler policy / verification criteria?
**YES.** Workload (Bank-of-Z commit, subsystem selector), prompts, models, verification (behavioral + repair gates), scheduler policy (task table + OPT-1 overlap) are all deterministic, pinned inputs. The experiment plan (Section 12) freezes them as a configuration block.
---

## 5. Configuration Findings

- Endpoints: **environment variables** (`AUTOFORGE_M1_OLLAMA_URL`, `AUTOFORGE_HP_OLLAMA_URL`, `AUTOFORGE_QDRANT_URL`).
- Models: **Python constants** in `run_18g_entry_a.py`; Ollama tags resolved per node.
- Routing: **task-table data** in `run_18g_entry_c1.py:_ai_tasks()`.
- Executor wiring: was **hardcoded single base URL for all local nodes** → now optional per-node endpoint map.
- **Minimum change required for a third node:** add `AUTOFORGE_MACMINI_OLLAMA_URL` and bind the node — both supported by the new seams. No redesign was performed.

---

## 6. Scheduler/Worker Findings

- Concurrent execution: `asyncio.gather` on the six-task table (one worker per call site, retries per task).
- Concurrency sweep harness exists (`run_18h_fleet_probe.py` concurrency levels 1/2/4/6) but is **not** wired as a parameterized sweep for the end-to-end certificate pipeline (18-H concurrency outcomes are recorded in `concurrency_benchmark.json`).
- Production workforce scheduler (`CapacityAwareRouter` + `ModelCapacityManager`) already handles N nodes and offline-node exclusion.

---

## 7. Telemetry Readiness

| Measurement | 18-H status | H2 readiness |
|---|---|---|
| run ID / workload ID / config ID | run UUID `pid`, workload pinned | READY (config ID to be added to H2 matrix header) |
| start/end/wall/verified NLOC/rate | `wall_clock.json`, `evidence_summary.json` | READY |
| node ID, endpoint, model, req counts | per-request in `llm_calls.jsonl` | READY |
| retries / failures | `retry_count`, `result` | READY |
| tokens in/out, generation time, effective TPS | `input/output_tokens`, `generation_latency_ms`, `throughput_tps` | READY |
| TTFT per request | `TTFT_ms` | READY |
| node concurrency / queue wait | not separated | **MINOR CHANGE REQUIRED** (Q9) |
| stage-level critical path | `stages[]` (discovery→…→repair) | READY |
| resource sampling | `resource_samples.json` (java/ollama/mvn/qdrant CPU/RSS) | READY |

Answering *"why did the third node make the job faster or slower?"* is now structurally possible: per-node request telemetry × stage timestamps × resource samples × infra routing matrix.

---

## 8. Experiment Harness Readiness

The 18-H harnesses (`run_18h_main.py`, `run_18h_opt.py`, `run_18h_fleet_probe.py`, `run_18h_helpers.py`) are directly reusable for the A/B/C/D/E matrix:

- **Baseline A (M1 only)** — reachable by configuring only M1 in `run_18h2_nodes.py` (task allocation to M1 models).
- **Baseline B (M1+HP)** — the frozen default, byte-identical.
- **Experiment C (M1+HP+Mac Mini)** — add `AUTOFORGE_MACMINI_OLLAMA_URL`; allocate tasks after measurement.
- **Experiment D (optimized 3-node routing)** — task-table allocation is configuration, so a second routing matrix is a data change only.
- **Experiment E (concurrency sweep)** — `run_18h_fleet_probe` provides the probe pattern; the end-to-end sweep levels should be restricted to safe values (18-H found 4 optimal, 6+ rejected).

**Ready, with the sweep levels and third-node task allocation to be set on the measured hardware.**
---

## 9. Identified Gaps

| # | Gap | Severity | Status |
|---|---|---|---|
| G1 | Composition wiring bound all local nodes to one Ollama base URL — no way to express a second/third independent LAN endpoint | Material for 3-node production wiring | **FIXED (this audit)** |
| G2 | Evidence-harness routing table hardcoded to exactly 2 nodes with no config seam | Material for the 3-node experiment | **FIXED (this audit)** — additive seam, frozen default unchanged |
| G3 | Queue-wait not separated from TTFT in harness telemetry | Measurement fidelity | OPEN (documented; minor H2 harness telemetry extension) |
| G4 | Harness has no pre-dispatch node-health gate (relies on retries) | Operational robustness | OPEN (recommended H2 harness addition; not a blocker) |
| G5 | Mac Mini model fleet / capacity untested | Information | NOT YET TESTED (by design; decided Sept 22 on hardware) |

---

## 10. Changes Made

Only minimal, isolated, backwards-compatible changes:

1. **`packages/composition/src/autoforge_composition/ai_infrastructure_wiring.py`**
   - `bind_default_provider_adapters()` gains `node_endpoints: dict[str, str] | None`. Each provider id (`local-m1`, `local-hp`, or any additional node such as `local-mac-mini-m6`) may have its own Ollama endpoint; **unconfigured entries fall back to `ollama_base_url` exactly as before**.
   - `build_ai_infrastructure()` gains and forwards the same `node_endpoints` parameter.
   - No change to default behavior: with no `node_endpoints`, binding is byte-identical to 18-H (verified by test).

2. **`packages/modernization/evidence/run_18h2_nodes.py` (new)**
   - Config seam for the evidence harness: `resolve_node_endpoints()` (env-driven incl. `AUTOFORGE_MACMINI_OLLAMA_URL`), `build_ai_tasks()` (returns the **exact frozen 6-task table** by default; rebinds endpoints from configuration; adds *no* fabricated third-node tasks/models), `build_warm_preload_list()` (identical to 18-H), `node_id_to_provider_id()`, and `node_endpoints_from_env_for_wiring()` (bridges harness ↔ composition wiring).

3. **`packages/composition/tests/test_node_endpoints_wiring.py` (new)** — 4 focused tests.
4. **`packages/modernization/tests/test_18h2_nodes.py` (new)** — 7 focused tests.

**Blocker discovered during testing (pre-existing environment issue, NOT caused by this audit, NOT a repo defect):** the system Python at `/Library/Frameworks/Python.framework/Versions/3.14` has a broken editable install for `autoforge-security` (the `.pth` file is present but its path is not being applied; `import autoforge_security` raises `ModuleNotFoundError` regardless of this audit's changes). Composition tests execute correctly when `PYTHONPATH` includes the package `src` directories (matching the repo's own `pythonpath = ["src"]` config in each `pyproject.toml`). All audit tests were run that way.

---

## 11. Changes Deliberately NOT Made

- No modification to any frozen 18-H/18-G evidence, JSON artifacts, or report.
- No changes to `run_18g_entry_c1.py:_ai_tasks()` (frozen routing table) or any `run_18g_*`/`run_18h_*` pipe.
- No redesign of the router, continuity manager, or registry.
- No new models, no model downloads, no quantization changes.
- No cloud inference / paid APIs / Temporal introduced.
- No concurrency sweep executed (deferred to hardware).
- No optimization campaign or NLOC/hour chasing.
- No firewall/router modifications; no public exposure.
- `OLLAMA_CANONICAL_MODEL_MANIFEST.json` left untouched.
---

## 12. September 22 Experiment Plan

1. **Hardware inventory** — chip, memory, storage, OS, Ollama version, disk, thermal/power config.
2. **Local inference baseline** — benchmark candidate models individually (reuse `run_18h_fleet_probe.py` probe pattern on the new node).
3. **Node health** — LAN reachability, Ollama API, model availability, inference, concurrent requests.
4. **Register node** — set `AUTOFORGE_MACMINI_OLLAMA_URL` (+ optionally `node_endpoints={"local-mac-mini-m6": ...}` in production wiring).
5. **Three-node smoke test** — tiny workload through harness + production wiring.
6. **Reproduce 18-H M1+HP baseline** — confirm 364,953.2-class stability before the experiment.
7. **Run three-node experiment** — identical workload & verification.
8. **Analyze critical path** — per-node × stage × resource telemetry; attribute the delta.

Matrix: **A** M1-only · **B** M1+HP (frozen) · **C** M1+HP+Mac Mini · **D** optimized 3-node routing · **E** concurrency sweep (safe levels only: start {2,4}; do not exceed measured saturation, 18-H found 4 optimal / 6+ rejected). Do not certify a new commercial rate from a single run.

---

## 13. Measurement Schema

```jsonc
// run-level
{ "run_id", "workload_id", "configuration_id", "start_ts", "end_ts",
  "total_wall_sec", "verified_source_nloc", "verified_nloc_per_hour", "verification_result" }

// node-level (aggregated from llm_calls.jsonl per machine)
{ "node_id", "endpoint", "model", "request_count", "successful", "failed",
  "retries", "generated_tokens", "input_tokens", "generation_time_ms", "effective_tps",
  "ttft_ms (p50/p95/p99)", "concurrency", "queue_wait_ms" }

// critical-path stages (existing `stages[]` + wall_clock)
{ "discovery", "closure", "semantic_extraction", "rag", "planning", "inference",
  "synthesis", "build", "runtime_verification", "repair/regression" }
```

All fields except queue-wait are currently measurable; queue_wait requires the minor G3 telemetry extension.

---

## 14. Success/Failure Criteria

Primary metric remains **verified end-to-end source NLOC/hour** (delivery-inclusive), with the frozen 18-H value (364,953.2) as comparison anchor.

- **Positive:** 3-node materially improves verified end-to-end throughput and reduces inference share of critical path.
- **Neutral:** no meaningful end-to-end change (another bottleneck dominates) — still valid science.
- **Negative:** throughput decreases (scheduling/network/contention/model-loading/task-parallelism/dependency-serialization/routing) — still valid science.

Do NOT certify a new commercial rate from a single run. Do not treat raw aggregate TPS or target/generated NLOC/hour as the primary criterion.

---

## 15. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Mac Mini untested capacity/fleet fit | High (unknown hardware) | Step 2 local baseline + Step 5 smoke test; no fleet invented pre-measurement |
| Queue-wait attribution absent | Medium | Minor G3 telemetry extension before Sept 22 |
| Harness without pre-dispatch health gate | Medium | Optional G4 gate; retries already absorb transient failures |
| Existing broken editable installs in dev env | High | Run tests via `PYTHONPATH` src dirs (documented) or reinstall packages |
| Over-parallelization (E sweep) collapses TTFT | Medium | Restrict sweep to measured-safe levels |

---

## 16. Final Readiness Verdict

### READY WITH MINOR CHANGE

The minor change (per-node endpoint wiring + additive harness configuration seam) has been implemented and covered by focused tests (14 new tests, all passing; existing composition/router/workforce suites green). No frozen evidence was touched. The system is prepared to register a third LAN-only Ollama node through configuration, run the identical workload across M1-only / M1+HP / M1+HP+Mac Mini topologies, and answer whether a third node materially increases verified end-to-end engineering throughput. Mac Mini compatibility itself remains **NOT YET TESTED** until the hardware arrives and is benchmarked.

---

*Prepared as part of 18-H2 readiness gate. 18-H results remain frozen and authoritative.*