# 18-H3 MULTI-NODE INFERENCE FABRIC EXPERIMENT PLAN
**M1 + HP + Mac Mini Distributed Multi-Agent Inference Topology**
**Artifact:** `18H3_MULTI_NODE_INFERENCE_EXPERIMENT_PLAN.md`
**Status:** FROZEN & PREPARED (Awaiting Physical Mac Mini Arrival)
**Author:** Antigravity Autonomous Engineering Agent
**Date:** September 19, 2026

---

## 1. Executive Summary & Objective

The objective of Phase 18-H3 is to evaluate and certify the performance, throughput, and wall-clock delivery acceleration of AutoForge's newly model-backed 23-worker multi-agent workforce across a heterogeneous, local multi-node inference fabric:
1. **Node 1 (Local Primary):** Apple Silicon M1 Max (32GB Unified Memory)
2. **Node 2 (Secondary Worker):** HP Workstation (x86_64, LAN Node)
3. **Node 3 (Additive High-Throughput Node):** Apple Silicon Mac Mini M4/M4 Pro

### Core Architectural Principle
**The primary metric is real AutoForge engineering-job completion time, not synthetic tokens per second.**
Micro-benchmarking single-token decode speeds provides zero assurance of end-to-end engineering velocity if queue contention, network serialization, context reloading, or routing mismatches dominate real agent workflows.

---

## 2. Experimental Configurations

The experiment tests three incremental hardware topologies and two provider runtime stacks:

### Hardware Topologies

| Configuration | Active Nodes | Description | LAN Endpoints |
|---------------|--------------|-------------|---------------|
| **Config A** | M1 Only | Single-node baseline. All 21 AI workers compete for local M1 resources. | `AUTOFORGE_M1_OLLAMA_URL=http://127.0.0.1:11434` |
| **Config B** | M1 + HP | Two-node distributed topology (18-H baseline). Offloads secondary coding and review tasks. | Config A + `AUTOFORGE_HP_OLLAMA_URL=http://192.168.1.102:11434` |
| **Config C** | M1 + HP + Mac Mini | Full three-node fabric. High-concurrency agent dispatch across all 21 AI workers. | Config B + `AUTOFORGE_MACMINI_OLLAMA_URL=http://192.168.1.110:11434` |

### Provider Runtime Comparisons

Within **Configuration C**, two provider configurations will be benchmarked:
1. **Ollama Unified Configuration:**
   - All three nodes run Ollama daemons serving standard quantized GGUF weights.
   - Preserves 100% software parity and uniform API contracts across nodes.
2. **Apple Silicon Optimized Configuration (oMLX/MLX):**
   - Apple Silicon nodes (M1 and Mac Mini) run optimized MLX inference engines (via `OMLXProviderAdapter`), exploiting Unified Memory architecture and native Metal kernels.
   - HP node runs its optimized backend (Ollama/vLLM).
   - Verifies whether specialized local backends yield higher real-world engineering velocity than uniform Ollama instances without altering any worker code.

---

## 3. Workload Specification

The experiment will execute authoritative, non-synthetic AutoForge engineering workflows:

### Workload 1: Greenfield Distributed Cache & Storage Service
- **Sequence:** Intake → Research (`ResearchEngineer`) → Architecture (`ArchitectureEngineer`) → Wave Planning (`PlanningEngineer`) → Schema Design (`DatabaseEngineer`) → Backend Implementation (`BackendEngineer`) → Frontend Monitoring (`FrontendEngineer`) → Test Strategy & Implementation (`QAEngineer`) → Security Threat Modeling (`SecurityEngineer`) → CI/CD Deployment Automation (`DevOpsEngineer`) → Technical Documentation (`DocumentationEngineer`).
- **Concurrency:** Multi-agent parallel waves (Waves 1..4).
- **Target Deliverable:** Working Python/FastAPI distributed cache with full test suite, schema, Dockerfile, and OpenAPI documentation.

### Workload 2: Legacy Mainframe Core Banking Modernization
- **Sequence:** Ingestion → AST Lexical Discovery (`LegacySystemsResearchEngineer`, deterministic) → Code Archaeology (`LegacyCodeArchaeologist`) → Business Rule Extraction (`BusinessRulesAnalyst`, deterministic) → Data Modeling (`LegacyDataAnalyst`) → Integration Interface Analysis (`LegacyIntegrationAnalyst`) → Target Architecture Translation (`ModernizationArchitect`) → Wave Migration Planning (`MigrationPlanner`) → Deterministic Code Synthesis & CICS Semantics.
- **Source Input:** Enterprise COBOL/CICS banking module (batch interest calculation and account balance ledger).
- **Target Deliverable:** Verified Python/FastAPI microservice matching legacy precision semantics with automated test assertions.

---

## 4. Measurement & Metric Framework

Every run will capture metrics across the entire stack via `EventTelemetryCollector`, `AIInfrastructureAdapter`, and OS-level telemetry:

### 1. Primary Velocity Metrics
- **Total Wall-Clock Delivery Time ($T_{\text{total}}$):** Elapsed time from workflow submission to final artifact verification.
- **Engineering Job Completion Time:** Total time per worker wave and per specialized task.
- **NLOC / Hour:** Net lines of generated, syntax-valid code delivered per hour.
- **Verified NLOC / Hour:** Net lines of verified code passing automated test suites and deterministic regression checks.
- **Deterministic Synthesis Time:** Fraction of modernization time spent in the deterministic engine vs. AI reasoning.

### 2. Inference & Model Telemetry
- **Time to First Token (TTFT):** Latency from request dispatch to receipt of initial stream/token chunk.
- **Decode Tokens per Second ($\text{TPS}_{\text{decode}}$):** Aggregate and per-node token generation throughput.
- **Prompt Evaluation Duration:** Nanosecond-precision prefill timing across prompt lengths (1k..16k tokens).
- **Queue Wait Time:** Time tasks spend waiting for concurrency slots on `ModelCapacityManager`.
- **Capacity Utilization:** Active concurrency slots vs. maximum capacity per node.
- **Routing Decisions:** Distribution of dispatches across `node_local_m1`, `node_secondary_hp`, and `node_mac_mini`.
- **Retries & Failovers:** Count of retry events or candidate model failovers triggered by `ExecutionContinuityService`.

### 3. Hardware & Systems Health
- **Memory Consumption:** Resident set size (RSS), Unified Memory pressure, and KV cache allocation per node.
- **CPU & GPU Utilization:** Core utilization profiles during prefill and decode phases.
- **Thermal Throttling Events:** Thermal state changes and clock-rate step-downs on M1 and Mac Mini.
- **Network Overhead:** Serialization latency and bytes transferred over local LAN.

---

## 5. Execution Protocol & Safety Gates

1. **Pre-Flight Network Check:** Verify ping and HTTP health probe responses for all configured node endpoints.
2. **Clean Baseline State:** Cold-start daemons and record baseline memory footprints prior to benchmark execution.
3. **No Dynamic Model Swapping Mid-Job:** Models are pre-warmed on nodes to prevent cold-start IO skewing task measurements.
4. **Fail-Visible Verification:** Ensure zero silent fallbacks occur; any inference outage must visibly abort or reroute per policy.
5. **Three-Run Averaging:** Each configuration will be executed three times (Run 1, Run 2, Run 3) to compute mean, median, and variance.

---

## 6. Target Hypothesis

1. **Scalability:** Transitioning from **Config A (M1)** to **Config C (M1 + HP + Mac Mini)** will reduce total wall-clock engineering delivery time by $\ge 45\%$ for concurrent multi-agent waves.
2. **Queue Relief:** Mac Mini will absorb heavy planning and code generation loads (`qwen2.5-coder:32b`), dropping queue wait time in `ModelCapacityManager` to near zero.
3. **Architecture Decoupling:** 100% of runs will execute without requiring a single code edit in any of the 23 worker classes or their specialized loops.
