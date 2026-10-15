# Phase 20-C Gate 1: Custom AI Agent Inference Provider Alignment Report

**Status:** PASS  
**Date:** 2026-10-16  
**Capability:** Custom AI Agent Power Engine (`autoforge_power_engines.agent`)  
**Target Inference Endpoint:** `http://127.0.0.1:19801/v1`  
**Approved Model:** `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`  
**Inference Provider:** `GenericHTTPModelProvider` (OpenAI-compatible HTTP provider)  

---

## 1. Baseline Git State

- **Branch:** `main`
- **Initial HEAD:** `6735418a7e27c6564aefe51a234978d697e4ab2e`
- **Working Tree Cleanliness:** Verified. All pre-existing tracked files were completely clean and synchronized with `origin/main`. Untracked files and certification artifacts from prior phases were untouched and preserved.

---

## 2. Verified Root Cause

Prior to Phase 20-C Gate 1, inspection of the Custom AI Agent codebase revealed:

1. **Implicit Ollama Defaults:**
   - `AgentModelConfig` in `agent/spec.py` declared default `provider = "ollama"`, `base_url = "http://127.0.0.1:11434"`, and `model_name = "qwen2.5-coder:7b-instruct-q3_K_M"`.
   - `StandaloneCustomerAgentGenerator` in `agent/generator.py` defaulted generated configurations, troubleshooting instructions, and documentation to `OllamaModelProvider` and `OLLAMA_BASE_URL`.
   - Generated client runtime template hardcoded `_call_model` to `f"{self.settings['ollama_base_url']}/api/chat"`.

2. **Provider Contract Incompatibility with Port 19801:**
   - `GenericHTTPModelProvider.generate_turn` constructed endpoints via `f"{self.base_url}/v1/chat/completions"`. When passed the canonical `http://127.0.0.1:19801/v1`, this resulted in `http://127.0.0.1:19801/v1/v1/chat/completions` (HTTP 404).
   - In multi-turn tool loops, assistant messages and tool observations did not preserve OpenAI-compatible `tool_calls` payloads and `tool_call_id` attributes, causing multi-turn reasoning degradation on strict OpenAI-compatible engines.

---

## 3. Files Changed and Rationale

| File | Change Summary & Rationale |
|---|---|
| `packages/power_engines/src/autoforge_power_engines/agent/spec.py` | Updated `AgentModelConfig` defaults: `provider="generic_http"`, `base_url="http://127.0.0.1:19801/v1"`, `model_name="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"`. Updated deployment profile environment generation to emit `LLM_BASE_URL` with docker gateway translation while retaining alias compatibility. |
| `packages/power_engines/src/autoforge_power_engines/agent/runtime.py` | Updated `GenericHTTPModelProvider` default parameters to MLX authority. Normalized endpoint resolution to correctly handle base URLs with or without `/v1` or `/chat/completions`. Enhanced `StandaloneAgentRuntime.run` to record OpenAI-compliant `tool_calls` in assistant messages and attach `tool_call_id` in tool observation turns. |
| `packages/power_engines/src/autoforge_power_engines/agent/generator.py` | Aligned deliverable generation in `StandaloneCustomerAgentGenerator`: updated README config table, `settings.json`, generated `src/config.py` defaults to `generic_http` / `LLM_BASE_URL`, and updated generated customer `_call_model` to dynamically support OpenAI `/chat/completions` alongside legacy Ollama. |
| `packages/power_engines/tests/test_agent_power_engine.py` | Aligned live inference tests 29 and 30 with the authorized local MLX server (`http://127.0.0.1:19801/v1`), removing Ollama dependencies. |
| `packages/power_engines/tests/test_agent_inference_alignment.py` | Added comprehensive regression test suite covering all 7 Phase 20-C Gate 1 requirements plus live MLX smoke validation. |

---

## 4. Provider Compatibility Evidence

Direct curl and programmatic invocations confirmed compatibility with the running MLX server:

1. **Model Acceptance:**
   - Endpoint: `http://127.0.0.1:19801/v1/models`
   - Confirmed model presence: `mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2`.
2. **Chat Completions:**
   - Single-turn prompt returned valid JSON choice with `role: "assistant"`.
3. **Native Tool Calling:**
   - When tools schema was provided, MLX generated standard `finish_reason: "tool_calls"` with structured function name and argument JSON string.
4. **Tool Observation Continuation:**
   - Providing assistant `tool_calls` and corresponding `role: "tool"` with matching `tool_call_id` enabled MLX to ingest tool output and deliver final arithmetic computation in a single turn.
5. **Bounded Failure Isolation:**
   - Probing an invalid port (`19899` / `19998`) raised `requests.exceptions.ConnectionError`, which transitioned the agent state machine to `AgentExecutionState.FAILED` and recorded error telemetry without hanging and without implicit fallback.

---

## 5. Test Results

### A. Mocked Unit & Regression Tests (`test_agent_inference_alignment.py`)

Executed via `.venv/bin/pytest packages/power_engines/tests/test_agent_inference_alignment.py -v`:

| Test Case | Description | Result |
|---|---|---|
| `test_01_default_configuration_resolves_to_authorized_mlx` | Verifies `AgentModelConfig` and runtime resolve to `http://127.0.0.1:19801/v1` and approved 30B model | **PASS** |
| `test_02_explicit_configuration_overrides` | Verifies explicit custom URLs and explicit Ollama opt-in still work | **PASS** |
| `test_03_no_implicit_ollama_fallback_on_failure` | Proves failures do not silently invoke Ollama | **PASS** |
| `test_04_unreachable_endpoint_produces_bounded_failure` | Proves unreachable endpoints fail fast and bounded | **PASS** |
| `test_05_malformed_responses_handled_safely` | Proves malformed/empty JSON responses are safely handled | **PASS** |
| `test_06_tool_call_parsing_and_execution_intact` | Verifies OpenAI tool calling and local sandboxing loop | **PASS** |
| `test_07_no_live_ollama_required` | Verifies unit test suite executes with zero Ollama requirement | **PASS** |
| `test_08_live_mlx_smoke_test` | Live arithmetic execution against authorized running MLX server | **PASS** |

**Summary:** 8 passed in 4.51s (Exit code 0).

### B. Full Custom AI Agent Power Engine Test Suite (`test_agent_power_engine.py`)

Executed via `.venv/bin/pytest packages/power_engines/tests/test_agent_power_engine.py`:

- **Total Tests:** 30
- **Passed:** 30
- **Skipped:** 0
- **Failed:** 0
- **Duration:** 10.99s (Exit code 0)
- **Includes Live Tests:**
  - `test_29_real_mlx_model_execution_with_tools`: PASSED (live MLX calculation `1234 * 5678 = 7,006,652`).
  - `test_30_commercial_demonstration_operations_research_agent`: PASSED (live document lookup + calculation `2400 * 1.25 = 3000`).

### C. Capability Routing & Platform Invariants (`packages/composition/tests/test_capability_routing.py`)

- **Total Tests:** 26
- **Passed:** 26
- **Failed:** 0
- **Duration:** 5.32s (Exit code 0)

---

## 6. Architectural Invariants Maintained

- `autoforge_kernel.orchestration.DefaultOrchestrationEngine` remains the sole canonical orchestrator.
- Canonical pipeline preserved: Kernel → `DefaultOrchestrationEngine` → `CommercialCapabilityRouter` → `CustomAIAgentPowerEngine` → `ExecutionOutcome`.
- Local-first inference topology preserved: zero external cloud calls; no Ollama dependencies on production path; MLX authority on port 19801 is the default.
- No second inference server launched; no modification to frozen model topology.

---

## 7. Remaining Limitations

- MLX LM server must remain running on port 19801 for live customer agent workloads. If the MLX daemon is stopped, agent executions fail boundedly with `requests.exceptions.ConnectionError` and do not fall back.

---

## 8. Final Disposition

**PASS** — Phase 20-C Gate 1 is certified and verified. Ready for Gate 2.
