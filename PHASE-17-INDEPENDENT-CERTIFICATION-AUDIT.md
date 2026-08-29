# PHASE 17 — INDEPENDENT FORENSIC AUDIT REPORT
**AI RUNTIME & REAL MODEL INTEGRATION**

**Date of Audit:** 2026-08-29  
**Repository:** AutoForge AI Monorepo  
**Phase Under Audit:** Phase 17 — AI Runtime & Real Model Integration  
**Prior Frozen Baseline:** Phase 16 Commit `abed333ae53ba8df305cc7c469ccb96ea8e2c056`  
**Audit Stance:** Independent, Adversarial, Non-Modifying, Source-Verified  

---

## 1. Executive Verdict

### **VERDICT: CERTIFIED**

Phase 17 successfully establishes real inference execution across the authoritative AutoForge runtime path. The transition from abstract routing and simulated execution to verified physical local inference is complete, robust, security-governed, and fully observable.

```mermaid
flowchart LR
    W[Worker] -->|Agnostic Requirements| WR[Worker Profile]
    WR --> TR[Task Requirements]
    TR --> ER[Effective Requirements]
    ER --> MA[Model Allocator]
    MA --> MR[Model Router]
    MR --> ECS[Execution Continuity]
    ECS --> PA[Ollama Provider Adapter]
    PA --> NODE[local-m1 Node]
    NODE --> REAL[Physical Model]
    REAL --> TELEM[Observability Telemetry]
```

### Key Audit Highlights
1. **Model-Agnostic Workforce**: All 23 workers define only capabilities, permissions, context bounds, and quality constraints. Zero concrete model IDs exist in worker definitions.
2. **Authoritative Routing & Allocation**: `CapacityAwareRouter` and `ModelRouterService` enforce capability matching, context windows, quality tiers, local-first privacy, concurrency limits, and health constraints without bypass.
3. **Verified Live Local Inference**: Real, un-mocked inference execution was independently verified on host hardware (`local-m1`, Apple Silicon M1) for both canonical models:
   - **`qwen2.5-coder-7b`** (`qwen2.5-coder:7b-instruct-q3_K_M`): Code generation & implementation planning (1,047 tokens, 8.86 tok/s).
   - **`ornith-9b`** (`ornith-9b-iq3m-4k:latest`): Deep architectural reasoning & strategy formulation (521 tokens, 6.24 tok/s).
4. **Hardware Honesty**: Future hardware (`local-mac-mini-m6`) is explicitly registered as `ProviderStatus.UNAVAILABLE` and marked offline by default in `ModelCapacityManager`. Zero false availability reporting exists.
5. **Observability & Security Governance**: Real token metrics (`prompt_eval_count`, `eval_count`, latency, tok/s) flow into canonical events (`CONNECTOR_EXECUTED`) and `DashboardManager` read models. Cloud adapters query credentials via Phase 15 `SecretsManager` with zero hardcoded keys or leaked secrets.
6. **Regression Integrity**: Monorepo test suite stands at **1,151 passed tests, 0 failures, 0 skips, 0 xfails, 0 errors** across all 15 packages and API application.

---

## 2. Scope of Audit

The audit examined all Phase 17 deliverables, contracts, source code, tests, and runtime artifacts:
- Provider Adapter subsystem in `packages/ai_infrastructure/src/autoforge_ai_infrastructure/adapters/`
- AI adapter in `packages/execution/src/autoforge_execution/ai_adapter.py`
- Model allocator & capacity routing in `packages/workforce/src/autoforge_workforce/model_allocator.py`
- Workforce dispatching in `packages/workforce/src/autoforge_workforce/dispatch.py`
- Observability collector in `packages/observability/src/autoforge_observability/collector.py`
- Platform composition wiring in `packages/composition/src/autoforge_composition/ai_infrastructure_wiring.py`
- Live inference verification scripts `scripts/verify_real_inference.py` and `scripts/verify_ornith_inference.py`
- All unit and integration test suites across monorepo packages

---

## 3. Evidence Reviewed

| Artifact / Source | Inspection Method | Verified State |
| :--- | :--- | :--- |
| `packages/ai_infrastructure/src/autoforge_ai_infrastructure/adapters/` | AST & Static Code Inspection | Implements `BaseProviderAdapter`, `OllamaProviderAdapter`, `OpenAICompatibleProviderAdapter`, `AnthropicProviderAdapter`, `GeminiProviderAdapter` |
| `packages/execution/src/autoforge_execution/ai_adapter.py` | AST & Dynamic Inspection | Bridges `ExecutionContext` to `ModelRouter` and `ExecutionContinuityService` with structured prompts and telemetry recording |
| `packages/workforce/src/autoforge_workforce/workers.py` | Regex & Full File Audit | All 23 workers declare `WorkerModelProfile` with zero hardcoded model IDs |
| `packages/workforce/src/autoforge_workforce/model_allocator.py` | AST & Behavioral Tests | Future M6 node registered as `ProviderStatus.UNAVAILABLE`; concurrency tracking and failover verified |
| `packages/observability/src/autoforge_observability/collector.py` | AST & Event Ingestion Tests | Ingests integer and dictionary token structures safely into read models |
| `scripts/verify_real_inference.py` | Live Process Execution | Real live execution of `qwen2.5-coder:7b-instruct-q3_K_M` on `local-m1` |
| `scripts/verify_ornith_inference.py` | Live Process Execution | Real live execution of `ornith-9b-iq3m-4k:latest` on `local-m1` |
| `15 Monorepo Packages + apps/api` | Automated Pytest Regression | 1,151 tests passed, 0 failed, 0 skipped |

---

## 4. Architecture Compliance

The implementation strictly honors the foundational AutoForge architecture:
- **No Orchestration Framework Leaks**: Zero usage of LangChain, LangGraph, CrewAI, AutoGen, or external agent frameworks.
- **Platform Authority**: All routing decisions are made by `ModelRouterService` and `CapacityAwareRouter`; all resilience is owned by `ExecutionContinuityService`.
- **Single Source of Truth**: The capability registry is `InMemoryCapabilityRegistry`; execution state stays owned by `PreservedExecutionContext` / `RuntimeStateManager`.
- **Model Agnosticism**: Workers declare only requirements; tasks refine requirements; runtime resolves effective requirements.

---

## 5. Model-Agnostic Workforce Audit

A full scan was conducted across `packages/workforce/src/autoforge_workforce/`:
- **Worker Profile Audit**: All 23 workers (14 greenfield + 9 legacy) define explicit, non-empty `WorkerModelProfile` instances attached to `ExpertiseModel`.
- **Zero Concrete Model IDs in Workers**: Automated regex search for model identifiers (`qwen`, `ornith`, `claude`, `gpt`, `gemini`, `llama`) returned **zero** occurrences in worker class definitions.
- **Requirement Resolution Precedence**:
  - Worker profile defines baseline role requirements (e.g. `BackendEngineer` requires `CODE_GENERATION` and `min_context_window_tokens=32768`).
  - Task requirements strengthen worker defaults (e.g. adding `REASONING` or requesting larger context).
  - Mandatory worker constraints (e.g. `privacy_policy="local_only"`) cannot be weakened by task parameters.
- **Runtime Propagation**: `WorkforceDispatcher.dispatch_task` resolves `effective_reqs = resolve_effective_requirements(worker.model_profile, task_model_reqs)` and injects `effective_model_requirements` directly into `ExecutionContext`.

---

## 6. Model Allocation & Routing Call Graph Audit

The complete call graph was traced and verified:

1. **Task Dispatch**: `TaskDefinition` dispatched via `WorkforceDispatcher.dispatch_task`
2. **Context Creation**: `ExecutionContext` constructed with `effective_model_requirements`
3. **Allocation / Routing Request**: `AIInfrastructureAdapter._build_routing_request` extracts required capabilities, context bounds, and privacy constraints into a `RoutingRequest`
4. **Capacity Routing**: `CapacityAwareRouter.route_task` queries `ModelCapacityManager` for active node availability and concurrency slots
5. **Deterministic Ranking**: `ModelRouterService.route` evaluates candidate models against hard constraints (capabilities, context window, provider availability, allowed deployment modes) and ranks by scoring function
6. **Execution Continuity**: `ExecutionContinuityService.execute` runs the candidate chain with retry policies and candidate failover
7. **Provider Execution**: `OllamaProviderAdapter.execute` receives normalized `ExecutionRequest` and `ExecutionTarget`, maps the canonical model ID to physical tag, and executes HTTP request
8. **Result Capture**: Response is parsed into `ExecutionResult`, recording tokens, latency, throughput, and error status

**Verdict:** Authoritative routing path is strictly maintained with zero side-channels or bypasses.

---

## 7. Canonical Model Inventory & Hardware Mapping

| Canonical Model ID | Physical Provider / Tag | Capabilities | Quality Tier | Native Context | Provider / Node | Status |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| `qwen2.5-coder-7b` | `qwen2.5-coder:7b-instruct-q3_K_M` | `text_generation`, `code_generation`, `structured_output`, `tool_use` | 3 | 32,768 tokens | `local-m1` (Apple Silicon M1) | **ACTIVE** |
| `ornith-9b` | `ornith-9b-iq3m-4k:latest` | `text_generation`, `reasoning`, `structured_output` | 3 | 262,144 (4k configured) | `local-m1` (Apple Silicon M1) | **ACTIVE** |
| `qwen2.5-coder-3b` | `qwen2.5-coder:3b` | `text_generation`, `code_generation` | 2 | 32,768 tokens | `local-hp` (HP local node) | **ACTIVE** |
| `mac-mini-m6-node` | Future Apple M6 node | `text_generation`, `code_generation`, `reasoning`, `structured_output` | 4 | 65,536 tokens | `local-mac-mini-m6` | **UNAVAILABLE (SIMULATED)** |

**Hardware Honesty Check:**
- `local-mac-mini-m6` is registered with `status=ProviderStatus.UNAVAILABLE` and defaults to `offline_nodes={"local-mac-mini-m6"}` in `ModelCapacityManager`.
- Live routing tests confirm `local-mac-mini-m6` is never selected over active `local-m1` hardware during normal execution.

---

## 8. Real Live Inference Forensic Verification

Both canonical local models were executed live on the host system against the local Ollama daemon:

### A. Ornith-9B Real Inference Audit
- **Worker Used**: `planning_engineer` (model-agnostic)
- **Task Description**: Distributed in-memory cache invalidation architecture & strategy
- **Allocated Model ID**: `ornith-9b`
- **Physical Tag Invoked**: `ornith-9b-iq3m-4k:latest`
- **Node**: `local-m1` (Apple Silicon M1)
- **Input Tokens**: `171` (verified from Ollama `prompt_eval_count`)
- **Output Tokens**: `350` (verified from Ollama `eval_count`)
- **Total Tokens**: `521`
- **Throughput**: `6.24 tokens/second`
- **Inference Latency**: `62,143.68 ms`
- **Generated Response**: Comprehensive, technically coherent 5-section distributed cache invalidation plan with ASCII architectural diagrams, cache-aside/write-through hybrid protocols, and Redis pub/sub invalidation bus.
- **Classification**: **AUTHENTIC REAL INFERENCE** (verified via `llama-server` process CPU telemetry and token timing).

### B. Qwen 2.5 Coder 7B Real Inference Audit
- **Worker Used**: `backend_engineer` (model-agnostic)
- **Task Description**: FastAPI CRUD REST API with SQLAlchemy and validation
- **Allocated Model ID**: `qwen2.5-coder-7b`
- **Physical Tag Invoked**: `qwen2.5-coder:7b-instruct-q3_K_M`
- **Node**: `local-m1` (Apple Silicon M1)
- **Input Tokens**: `122` (verified from Ollama `prompt_eval_count`)
- **Output Tokens**: `925` (verified from Ollama `eval_count`)
- **Total Tokens**: `1,047`
- **Throughput**: `8.86 tokens/second`
- **Inference Latency**: `105,077.07 ms`
- **Generated Response**: Complete 8-step implementation plan including SQLAlchemy models, Pydantic schemas, CRUD routes, validation constraints, Pytest test suite, and Swagger docs.
- **Classification**: **AUTHENTIC REAL INFERENCE** (verified via live token metrics and process instrumentation).

---

## 9. Provider Adapter Subsystem Audit

| Adapter | Classification | Features Verified |
| :--- | :--- | :--- |
| `OllamaProviderAdapter` | **IMPLEMENTED & WIRED** | Native `/api/chat` & `/api/tags`, JSON mode, exact token accounting (`prompt_eval_count`, `eval_count`), throughput calculation, streaming generator, health checks, memory-safe `num_ctx` management. |
| `OpenAICompatibleProviderAdapter` | **IMPLEMENTED & WIRED** | Standard `/chat/completions`, JSON object response format, usage token parsing (`prompt_tokens`, `completion_tokens`), Phase 15 `SecretsManager` service credentials. |
| `AnthropicProviderAdapter` | **IMPLEMENTED** | Native Messages API (`/v1/messages`), system instruction separation, temperature scaling, usage token parsing, `SecretsManager` integration. |
| `GeminiProviderAdapter` | **IMPLEMENTED** | Google Gemini REST API (`generateContent`), role normalization (`user`/`model`), `usageMetadata` token extraction, `SecretsManager` integration. |

---

## 10. Node & Capacity Management Audit

- **Concurrency Limits**: `ModelCapacityManager` enforces per-model and per-node concurrency limits via `asyncio.Lock` and queue events.
- **Slot Reservation & Release**: `acquire_slot()` and `release_slot()` maintain accurate `active_runs` counters.
- **Capacity Failover**: When all slots on `local-m1` are saturated, `CapacityAwareRouter` routes subsequent tasks to available alternatives (e.g. `local-hp`).
- **Health Management**: `set_node_health(provider_id, online=False)` dynamically removes offline nodes from candidate selection.

---

## 11. Observability Audit

- **Telemetry Ingestion**: `EventTelemetryCollector.process_event` ingests `CONNECTOR_EXECUTED` events with `action="llm_inference"`.
- **Safe Parsing**: Ingests integer, dictionary (`{"total_tokens": N}`), or `"UNAVAILABLE"` string metrics without throwing type errors.
- **Read Model Updates**: `DashboardManager` and `ModelDashboardReadModel` aggregate:
  - `total_model_calls`
  - `successful_model_calls`
  - `token_usage` by model ID and aggregate total
  - `average_model_latency_ms`
- **Trace Continuity**: Correlation IDs and execution IDs are preserved across event payloads.

---

## 12. Security & Governance Audit

- **Zero Hardcoded Secrets**: Rigorous search across the monorepo confirmed zero hardcoded API keys or credentials.
- **Phase 15 SecretsManager Integration**: Provider adapters request credentials via `SecretsManager.get_secret(subject, key_name)` using `SubjectType.SERVICE` (e.g. `service:ai_infrastructure:openai_api_key`).
- **Safe Failure Mode**: Missing credentials throw `ProviderUnavailableError` without exposing tokens or execution traces in logs.
- **Execution Governance**: Execution sandboxes and workspace path traversal protections remain intact.

---

## 13. Failure & Recovery Audit

| Failure Scenario | Tested Behavior | Result |
| :--- | :--- | :--- |
| **Ollama Daemon Unreachable** | Throws `ProviderUnavailableError`, continuity attempts retry budget, fails over or halts safely | **PASS** |
| **Model Not Installed (HTTP 404)** | Throws `ModelUnavailableError`, continuity fails over to next candidate model | **PASS** |
| **Unbound Provider Executor** | Throws `ExecutorNotBoundError`, continuity fails over to bound alternative | **PASS** |
| **Simulated Future Hardware** | Node registered as `UNAVAILABLE` and marked offline; excluded from active routing | **PASS** |
| **Execution Timeout** | Clamped by `timeout_seconds`, throws `ExecutionTimeoutError`, preserving execution context | **PASS** |

---

## 14. Test Suite Forensic Accounting

```
================================================================================
MONOREPO TEST SUITE REGRESSION METRICS
================================================================================
Package                      Passed    Failed    Skipped    XFailed    Errors    Total
--------------------------------------------------------------------------------
packages/ai_infrastructure       97         0          0          0         0       97
packages/workforce               23         0          0          0         0       23
packages/execution               37         0          0          0         0       37
packages/composition             24         0          0          0         0       24
packages/observability           12         0          0          0         0       12
packages/security                37         0          0          0         0       37
packages/runtime                 36         0          0          0         0       36
packages/kernel                 100         0          0          0         0      100
packages/event_platform          56         0          0          0         0       56
packages/events                 228         0          0          0         0      228
packages/workflows              194         0          0          0         0      194
packages/artifacts               13         0          0          0         0       13
packages/connectors              93         0          0          0         0       93
packages/persistence             70         0          0          0         0       70
packages/review                 114         0          0          0         0      114
apps/api                         17         0          0          0         0       17
--------------------------------------------------------------------------------
TOTAL                          1151         0          0          0         0     1151
================================================================================
```

- **Total Tests**: 1,151
- **Passed**: 1,151 (100.0%)
- **Failed**: 0
- **Skipped**: 0
- **XFailed**: 0
- **Errors**: 0
- **Skip / XFail Bypasses Found**: None.

---

## 15. Git Forensics

### A. Modified Tracked Files (6 files)
1. `packages/ai_infrastructure/src/autoforge_ai_infrastructure/__init__.py`: Export provider adapter classes at package root.
2. `packages/composition/src/autoforge_composition/ai_infrastructure_wiring.py`: Helper functions for binding default provider adapters and workforce models.
3. `packages/execution/src/autoforge_execution/ai_adapter.py`: Enhanced `AIInfrastructureAdapter` with rich prompt construction, execution history tracking, and flexible executor binding.
4. `packages/observability/src/autoforge_observability/collector.py`: Safe parsing of token payloads from LLM inference events into read models.
5. `packages/workforce/src/autoforge_workforce/model_allocator.py`: Default offline setting for future M6 node; guard duplicate capability registrations.
6. `packages/workforce/tests/test_model_allocation.py`: Updated test helper to bring online M6 node during simulated failover test.

### B. Untracked Phase 17 Files (5 items)
1. `packages/ai_infrastructure/src/autoforge_ai_infrastructure/adapters/`: Full provider adapter subsystem (`base.py`, `ollama.py`, `openai_compatible.py`, `anthropic.py`, `gemini.py`, `__init__.py`).
2. `packages/ai_infrastructure/tests/test_provider_adapters.py`: Unit test suite for provider adapters (14 tests).
3. `packages/workforce/tests/test_real_runtime_integration.py`: End-to-end integration test for workforce policy -> allocator -> router -> adapter -> telemetry.
4. `scripts/verify_real_inference.py`: Controlled live verification script for `qwen2.5-coder-7b`.
5. `scripts/verify_ornith_inference.py`: Controlled live verification script for `ornith-9b`.

---

## 16. Classified Findings

### Finding 1: Memory-Safe Context Window for Large Native Context Local Models
- **Severity**: **OBSERVATION**
- **Description**: Models like `ornith-9b` have native context lengths of 256k tokens. On resource-constrained local nodes (e.g. 8GB M1 Mac), allocating a 256k KV cache can induce memory pressure.
- **Resolution in Phase 17**: `OllamaProviderAdapter` defaults `num_ctx=4096` when unspecified in request parameters, and maps `ornith-9b` to `ornith-9b-iq3m-4k:latest`, achieving fast, memory-safe local inference (6.24 tok/s).

### Finding 2: Capability Duplication Guard in Model Registration
- **Severity**: **LOW** (Mitigated)
- **Description**: When calling both reference catalog installation and workforce model registration on the same registry, capability metadata was re-registered.
- **Resolution in Phase 17**: `register_workforce_models` checks `if registry.get_capability(cap_id) is None` before registration, ensuring idempotent composition.

---

## 17. Final Certification Conclusion

All requirements for **Phase 17 — AI Runtime & Real Model Integration** have been implemented, tested, verified on live hardware, and audited. The implementation upholds AutoForge's core architecture, maintains worker model-agnosticism, enforces security governance, produces honest observability metrics, and achieves 100% test pass rate across the monorepo.

**Final Certification Verdict: CERTIFIED**
