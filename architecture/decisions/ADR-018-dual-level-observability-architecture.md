# ADR-018: Dual-Level Observability Architecture (Phase 17-A Extension)

**Status:** Accepted  
**Date:** 2026-08-29  
**Context:** Phase 17-A — Dual-Level Observability Extension (Parent: Phase 17 — AI Runtime & Real Model Integration)  
**Deciders:** Core Architecture Team  

---

## 1. Context & Problem Statement

Phase 17 established real inference execution across multi-node hardware (`local-m1` Apple Silicon controller and `local-hp` LAN cluster workstation). 

However, inspecting multi-node systems requires answering two fundamentally distinct operational questions simultaneously:
1. **Node-Local Observability:** *"What is happening on THIS AutoForge node?"* (host identity, local memory/accelerator utilization, local inference latency & throughput, locally installed models, local worker tasks, local capacity saturation).
2. **Fleet / Control-Plane Observability:** *"What is happening across ALL AutoForge nodes?"* (aggregate fleet health, multi-node inventory, model-to-node distribution matrix, end-to-end routing decision trails `task → requirements → candidate scoring → selected node/model → outcome`, fleet-wide capacity saturation, and failover/retry metrics).

Without a structured architectural distinction, observability systems often either conflate local and global telemetry into a confusing mixture or maintain bifurcated, redundant pipelines that drift apart.

---

## 2. Decision & Architecture

### 2.1 Two Views of One Canonical Event Pipeline

AutoForge establishes **Dual-Level Observability** where Node-Local and Fleet Observability are two projections derived deterministically from the **same canonical event platform**:

```
                                  CANONICAL EVENTS
                  (Execution, Model Invocations, Routing Decisions, Health)
                                          │
                                          ▼
                            EventTelemetryCollector
                                          │
                                          ▼
                                  DashboardManager
                                   (Thread-Safe)
                                   /           \
                                  /             \
                                 ▼               ▼
                      NodeObservabilityReadModel  FleetObservabilityReadModel
                           (Per Node Scoped)       (Aggregated Fleet Scope)
                                 │                       │
                                 ▼                       ▼
                     GET /api/observability/node  GET /api/observability/fleet
                                 │                       │
                                 ▼                       ▼
                       AUTOFORGE NODE VIEW     AUTOFORGE FLEET VIEW
```

### 2.2 Canonical Stable Node Identity vs. Volatile IP Addresses

Every AutoForge node has a stable domain identity:
- `node_id`: Canonical identifier (`local-m1`, `local-hp`, `local-mac-mini-m6`).
- `display_name`: Human-readable label.
- `hostname`: Machine network hostname.
- `platform`: OS platform (`darwin`, `linux`, `windows`).
- `architecture`: CPU architecture (`arm64`, `x86_64`).
- `autoforge_version` & `runtime_version`: Platform release and Python runtime version.
- `health`: Explicit state enum (`HEALTHY`, `DEGRADED`, `OFFLINE`, `UNAVAILABLE`, `UNKNOWN`).
- `capacity_slots` & `active_slots`: Concurrency management.
- `resource_metadata`: Memory, accelerator/GPU, disk metrics.

**Invariant:** IP addresses (`192.168.1.105:11434`) are network metadata, NEVER node identities.

### 2.3 Hardware Honesty Invariant

Uninstrumented or unavailable metrics are NEVER fabricated:
- If GPU or memory telemetry is unavailable, it is explicitly reported as `"Unavailable"` or `null`.
- Future/planned hardware specifications (`local-mac-mini-m6`) are explicitly registered as `NodeStatusEnum.UNAVAILABLE` and `is_live_hardware = False`.

### 2.4 End-to-End Routing Decision Observability

Every routing and allocation event records a structured `RoutingDecisionRecord`:
$$\text{Task Requirements} \xrightarrow{\text{Filter}} \text{Candidate Scoring} \xrightarrow{\text{Capacity Check}} \text{Selected Node + Model} \xrightarrow{\text{Continuity Execution}} \text{Outcome}$$

This trail is captured in `FleetObservabilityReadModel.routing_decisions` and exposed in both REST APIs and UI inspection tables.

---

## 3. Security & Governance Invariants

1. **Zero Secret Leakage:** Observability projections NEVER contain API keys, authorization tokens, raw credentials, private prompts, or chain-of-thought secrets. All API responses run through `redact_secrets()`.
2. **Read-Only Non-Authority:** Observability endpoints are strictly read-only and cannot mutate runtime, governance, or execution states.
3. **Local Boundary:** Node-local endpoints are bound locally by default and cannot be exposed to the public Internet without explicit security gateway configuration.

---

## 4. Resilience Guarantees

1. **Node Disconnection:** When a node goes offline, its health state transitions to `OFFLINE` or `DEGRADED`. Missing telemetry is NEVER assumed to be healthy.
2. **Fleet Isolation:** A failure or partition on a single node does not crash or invalidate the fleet dashboard.
3. **Non-Blocking Inference:** Telemetry collection and read model projection updates are asynchronous and never block critical inference execution paths.

---

## 5. Physical Multi-Node Verification

Dual-Level Observability was verified on physical hardware:
- **`local-m1`:** Apple Silicon Host (`qwen2.5-coder:7b-instruct-q3_K_M` & `ornith-9b-iq3m-4k:latest`)
- **`local-hp`:** HP Workstation on LAN (`192.168.1.105:11434`, `qwen2.5-coder:3b`)

Both nodes successfully recorded unmocked inference execution in their respective node-local dashboards and aggregated into the fleet control plane.
