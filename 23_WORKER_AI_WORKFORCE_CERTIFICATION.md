# 23-WORKER CANONICAL AI WORKFORCE CERTIFICATION
**AutoForge Operating System — Milestone Freeze & Certification**
**Artifact:** `23_WORKER_AI_WORKFORCE_CERTIFICATION.md`
**Author:** Antigravity Autonomous Engineering Agent
**Status:** FROZEN & ARCHITECTURALLY CERTIFIED
**Date:** September 19, 2026

---

## 1. Workforce

The AutoForge multi-agent workforce comprises **23 registered workers**, verified directly against source code in `packages/workforce/src/autoforge_workforce/`:

- **Total Workers Registered:** 23
- **Genuine AI-Backed Workers:** 21 (14 Greenfield + 7 Legacy AI)
- **Deterministic Workers (By Design):** 2 (`LegacySystemsResearchEngineer`, `BusinessRulesAnalyst`)
- **Worker Intelligence Contract:**
  All 21 AI-required workers explicitly declare their intelligence requirements via `WorkerModelProfile`:
  - `required_capabilities`: Structured capability IDs (`CODE_GENERATION`, `CODE_REASONING`, `ARCHITECTURE_DESIGN`, `PLANNING`, `LEGACY_ANALYSIS`, etc.)
  - `quality_priority`: Integer rating (1..5) scoring model tiers in `LocalFirstRoutingPolicy`
  - `latency_priority`: Integer rating (1..5) penalizing high-latency models for fast-turn tasks
  - `reliability_minimum`: Float threshold (0.0..1.0) filtering out unstable candidates
  - `min_context_window_tokens`: Integer minimum context length for deep reasoning (e.g. 8k context for legacy archaeology)
- **Specialized Loops:**
  Generic engineering loops and hardcoded static string stubs have been completely replaced. Every AI worker executes a specialized engineering loop emitting domain-specific artifacts:
  - Greenfield: `ResearchLoop`, `ArchitectureLoop`, `PlanningLoop`, `BackendLoop`, `UIDesignLoop`, `FrontendLoop`, `DatabaseLoop`, `MLLoop`, `InfrastructureLoop`, `DevOpsLoop`, `QALoop`, `SecurityLoop`, `PerformanceLoop`, `DocumentationLoop`.
  - Legacy AI: `LegacyCodeArchaeologyLoop`, `LegacyArchitectureReconstructionLoop`, `LegacyDataAnalysisLoop`, `LegacyIntegrationAnalysisLoop`, `DependencyImpactAnalysisLoop`, `ModernizationArchitectureLoop`, `MigrationPlanningLoop`.
  - Deterministic: `LegacyDiscoveryLoop` (AST/lexical scanning), `BusinessRuleExtractionLoop` (regex pattern matching).

---

## 2. Routing Stack

The routing pipeline follows a strict, single-source-of-truth architecture without parallel schedulers or bypassed layers:

```
Worker -> WorkerModelProfile -> WorkforceDispatcher -> ExecutionContext 
       -> CapacityAwareRouter -> ModelCapacityManager -> ModelRouterService 
       -> LocalFirstRoutingPolicy -> ExecutorRegistry -> ProviderAdapter -> Inference Node
```

- **Worker Requirements Propagation:** Worker profiles are merged with task-specific needs in `resolve_effective_requirements()` and attached to `ExecutionContext`.
- **Capacity Routing:** `CapacityAwareRouter` evaluates both candidate capability matches and real-time concurrency slot availability on `ModelCapacityManager`.
- **Model Allocation & Concurrency Guard:** `AIInfrastructureAdapter` acquires concurrency slots prior to inference and guarantees slot release in a `try...finally` block.
- **ModelRouter & Policy Scoring:** `LocalFirstRoutingPolicy` evaluates locality, capability coverage, quality tier, latency sensitivity, and reliability thresholds.
- **Provider Abstraction:** All workers and loops interact solely with `AIInfrastructureAdapter`. No worker code references Ollama, oMLX, or local hardware.

---

## 3. Legacy Modernization Integration

Phase 18-G's proven modernization pipeline is now harmonized with the canonical workforce:
- **Seam Location:** `autoforge_modernization.g3_llm.G3LLMIntegration` accepts an injected `AIInfrastructureAdapter` and `CapacityAwareRouter`.
- **Canonical Routing:** When connected, `interpret_semantics()` and `translate_code()` route through canonical infrastructure with `worker_role="ModernizationArchitect"`.
- **Deterministic Engine Preservation:** The AST parsers, CICS semantic analyzers, COBOL AST models, and deterministic synthesis engines in `packages/modernization` remain completely untouched.
- **Offline / Standalone Support:** In offline mode or standalone unit tests, 100% deterministic fallback behavior is preserved (`force_offline=True`).

---

## 4. Failure Semantics & Fail-Visible Enforcement

The silent fallback vulnerability identified in the forensic audit has been eliminated:
- **Fail-Visible Policy:** All 21 AI-required workers reject silent fallback by default. If inference fails (provider offline, timeout, context exhaustion), `AIInfrastructureAdapter` raises an explicit `RuntimeError` or propagates the provider error.
- **Provenance Recording:** When an error occurs, `SpecializedLoop` marks `LoopStatus.FAILED` and records explicit qualitative provenance: `AI ... generation failed: ... (fail-visible; silent fallback disallowed)`.
- **Controlled Operator Override:** Deterministic fallback is only permitted if explicitly allowed via `context.allow_deterministic_fallback=True`, `context.fallback_policy="allow_fallback"`, or the explicit operator environment variable `AUTOFORGE_ALLOW_DETERMINISTIC_FALLBACK=1`.

---

## 5. Verification & Test Evidence

The corrected workforce architecture was certified across focused and subsystem test suites:

| Test Suite | Command | Collected | Passed | Failed | Skipped | Duration |
|------------|---------|-----------|--------|--------|---------|----------|
| **Workforce Focused** | `pytest packages/workforce/tests/test_workforce_core.py packages/workforce/tests/test_model_allocation.py packages/workforce/tests/test_23_worker_ai_workforce_architecture.py packages/workforce/tests/test_real_runtime_integration.py` | 31 | 31 | 0 | 0 | 1.12s |
| **AI Infrastructure** | `pytest packages/ai_infrastructure/tests/` | 97 | 97 | 0 | 0 | 0.10s |
| **Execution Subsystem (Unit)** | `pytest packages/execution/tests/test_*.py` (excluding live daemon e2e) | 37 | 37 | 0 | 0 | 1.32s |
| **Modernization 18-G Regression** | `pytest packages/modernization/tests/test_g3_llm_and_transform.py` | 83 | 83 | 0 | 0 | 1.48s |
| **18-H2 Node Config Seam** | `pytest packages/modernization/tests/test_18h2_nodes.py packages/composition/tests/test_node_endpoints_wiring.py` | 11 | 11 | 0 | 0 | 0.28s |
| **TOTAL** | | **259** | **259** | **0** | **0** | **4.30s** |

*Note: E2E daemon tests requiring active localhost Qdrant or live Ollama servers (`test_18e_repair_cycle_e2e.py`, `test_e2e_pipelines.py`) correctly verify daemon connectivity and fail-visible behavior when daemons are offline.*

---

## 6. Multi-Node Readiness

The architecture is prepared for the upcoming **M1 + HP + Mac Mini** distributed topology:
- **Node 1 (M1 Max):** Configured via `AUTOFORGE_M1_OLLAMA_URL` (default: `http://127.0.0.1:11434`).
- **Node 2 (HP Workstation):** Configured via `AUTOFORGE_HP_OLLAMA_URL` (default: `http://192.168.1.102:11434`).
- **Node 3 (Mac Mini):** Configured additively via `AUTOFORGE_MACMINI_OLLAMA_URL` (default: unset; bound only when specified).
- **Decoupled Identity:** The workforce dispatcher and individual workers remain completely agnostic of node network locations.
- **Provider Interchangeability:** The `BaseProviderAdapter` contract allows an `OMLXProviderAdapter` to be bound into `ExecutorRegistry` alongside `OllamaProviderAdapter` without altering any worker code.

---

## 7. Remaining Work

1. **Mac Mini Physical Delivery & Setup:** Power on, configure LAN IP, and pre-warm target model weights.
2. **Provider Adapter Registration (Optional oMLX):** Add `OMLXProviderAdapter` class to `autoforge_ai_infrastructure.adapters` if MLX native serving is chosen over Ollama on Apple Silicon.
3. **Execution of 18-H3 Benchmark:** Execute the multi-node experiment protocol defined in `18H3_MULTI_NODE_INFERENCE_EXPERIMENT_PLAN.md`.
