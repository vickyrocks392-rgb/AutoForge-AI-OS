# ADR-013: Phase 13 — AI Workforce and Model Allocation Architecture

**Status:** Proposed  
**Phase:** 13 — AI Workforce  
**Date:** 2026-08-28  
**Authors:** AutoForge AI Platform Team  

---

## Context

Phase 13 introduces the specialized workforce capability for greenfield engineering and legacy systems modernization. This adds:
1. **23 specialized worker roles**:
   - 14 Greenfield workers (Research Engineer, Architecture Engineer, Planning Engineer, UI Designer, Backend Engineer, Frontend Engineer, Database Engineer, ML Engineer, Infrastructure Engineer, DevOps Engineer, QA Engineer, Security Engineer, Performance Engineer, Documentation Engineer).
   - 9 Legacy workers (Legacy Systems Research Engineer, Legacy Code Archaeologist, Legacy Architecture Analyst, Legacy Data Engineer, Legacy Integration Engineer, Business Rules Analyst, Dependency & Impact Analyst, Modernization Architect, Migration Engineer).
2. **Deterministic capability matching** based on worker expertise.
3. **Local topology model routing** and resource allocation.
4. **Model/Provider/Deployment/Node distinction** (supporting local M1, HP nodes, and simulated Mac mini nodes).
5. **Legacy evidence tracking** categorized as `FACT`, `INFERENCE`, `HYPOTHESIS`, or `UNKNOWN`.

---

## Decision

To support these additions in a structured, observable manner:
- The worker registrations, capability matching, and loop execution are isolated within the `autoforge-workforce` package.
- The model allocation logic is managed via a thread-safe `ModelCapacityManager` and `CapacityAwareRouter` inside the workforce package, avoiding duplication of state authority.
- The 23-worker taxonomy is defined as explicit classes extending `WorkforceWorker` (which inherits from `EngineeringWorker`).
- Legacy evidence analyzer models represent findings with dynamic confidence attributes and traceability references.
- All actions (dispatch, model allocation, loop iterations, legacy discovery) publish canonical events to the event platform.

---

## Consequences

### Positive
- Fully structured, modular workforce taxonomy with strict separation of tasks.
- Non-overlapping worker responsibility.
- Local-first capacity routing preventing node contention.
- Fully traceable legacy modernization journey from intake to migration plan.

### Compliance
- ✅ Retains frozen execution substrate.
- ✅ Interoperable with the Event Platform and Runtime State Manager.
- ✅ Reconciled architecture accurately reflects the 23-worker taxonomy.
