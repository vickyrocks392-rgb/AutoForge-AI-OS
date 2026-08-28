# ADR-012: Phase 14 — Observability Platform Architecture

**Status:** Proposed  
**Phase:** 14 — Observability Platform  
**Date:** 2026-08-28  
**Authors:** AutoForge AI Platform Team  

---

## Context

AutoForge AI OS needs deep visibility across workflows, tasks, worker dispatches, model allocations, execution steps, reviews, and artifact generation. Rather than just collecting isolated logs, AutoForge requires a correlated observability model that links actions across the whole lifecycle:
`Project → Workflow → Task → Worker → Loop → Model → Provider → Node → Execution → Artifact → Review → Approval`

At the same time, we must maintain strict architectural separation of concerns:
- Observability is a **shared platform service**.
- Observability is **observational only**: it MUST NOT influence system runtime execution, control workflow transitions, or store authoritative state.
- Telemetry must be aggregated **deterministically** where possible (durations, counts, statuses) rather than using AI predictions or judgments.
- Telemetry must respect **security boundaries** and never store credentials, secret tokens, or API keys.

---

## Decision

### 1. Subsystem: `packages/observability`

We introduce a standalone, local-first package `autoforge-observability` under `packages/observability`. It will depend on:
- `autoforge-models`
- `autoforge-events`
- `autoforge-event-platform`

**Dependency Direction:**
```
autoforge-composition
  └── autoforge-observability
        ├── autoforge-event-platform
        ├── autoforge-events
        └── autoforge-models
```

This ensures that the dependency direction is strictly:
`Authoritative Subsystem → Event / Observation → Observability`
No authoritative system will depend on `autoforge-observability`, avoiding circular dependencies.

### 2. Module Decomposition

| Module | Responsibility |
|--------|----------------|
| `models.py` | Telemetry data structures (MetricObservation, StructuredLogEntry, TraceSpan, DashboardState) |
| `metrics.py` | Deterministic metrics aggregation (uptime, throughput, durations, latencies, success rates, token counts) |
| `logging.py` | Structured JSON log generation, supporting levels, components, correlation IDs, and secret redaction |
| `tracing.py` | Span creation and context propagation across the request lifecycle |
| `read_models.py` | Programmatic dashboard read-models for the 13 required dashboards (System, Workflow, Execution, Workforce, AI Infrastructure, Capability, Provider, Model, Inference Node, Artifact, Review, Legacy Modernization, HITL / Governance) |
| `collector.py` | Subscribes to the canonical `EventPlatform` and routes received events to update metrics, traces, structured logs, and dashboard read models |
| `errors.py` | Normalizes and maps error observations without replacing or overriding domain exception classes |

### 3. Correlation Engine

Every trace span, structured log entry, and metric observation will propagate correlation context using:
- `correlation_id` (the root transaction ID)
- Subsystem identifiers: `project_id`, `workflow_id`, `task_id`, `execution_id`, `attempt_id`, `worker_id`, `loop_id`, `artifact_id`, `review_id`, `approval_id`, `model_id`, `provider_id`, `deployment_id`, `node_id`.

This correlation context allows tracing the derivation and provenance of any execution step.

### 4. Non-Authoritative Subscription Boundary

- The Observability platform will initialize by registering a subscription with the central `EventPlatform` facade.
- It will process incoming `TransportEvent` messages, translate them to appropriate read models, and aggregate telemetry.
- It does not mutate or update workflow engines, execution engines, or database records.

---

## Consequences

### Positive
* Complete visibility across greenfield execution, legacy modernization, workforce tasks, and model allocations.
* Zero coupling between authoritative engines and observability logic.
* Non-blocking, local-first in-memory aggregation with zero external database dependencies.
* Completely deterministic metrics calculation, including cost estimation and latency calculation.
* Optional adapters for external platforms (e.g. Langfuse) can wrap the observability facade without becoming dependencies of AutoForge.

### Compliance
* ✅ Complies with ADR-001, ADR-002, ADR-009, ADR-011.
* ✅ No prohibited frameworks (LangChain, CrewAI, etc.).
* ✅ Deterministic-first.
* ✅ HITL governance for final choices.
