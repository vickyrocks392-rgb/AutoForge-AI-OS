# ADR-017: AutoForge Product Experience Architecture & UI Non-Authority Invariant

**Status:** Accepted  
**Date:** 2026-08-28  
**Context:** Phase 16 — AutoForge Product Experience  
**Deciders:** Core Architecture Team  

---

## 1. Context & Problem Statement

AutoForge AI OS is an autonomous software engineering operating system. To enable human operators to inspect, steer, govern, and interact with the platform, a top-level Product Experience is required.

Crucially, the platform operates under strict architectural invariants:
1. **The UI is NEVER an authority.** Canonical state, workflow state, execution state, artifact state, security policy, governance gates, worker authority, memory authority, learning authority, and model selection authority must NEVER reside in or be governed by the UI.
2. **First-Class Legacy Modernization:** AutoForge serves as an internal platform delivering *Legacy Modernization as a Service*. The UI must provide a dedicated Legacy Modernization Workspace with explicit visibility into epistemic uncertainty (`FACT`, `INFERENCE`, `HYPOTHESIS`, `UNKNOWN`).
3. **Desktop-First & Local-First:** The UI is designed to run locally and will form the basis of the official AutoForge Desktop Application in Phase 21.

---

## 2. Decision & Architecture

### 2.1 Architectural Hierarchy

The Product Experience sits at the complete top of the architecture:

```
┌─────────────────────────────────────────────────────────────┐
│                       AUTOFORGE UI                          │
│               Product / Control Experience                  │
└──────────────────────────────┬──────────────────────────────┘
                               │
               Engineering Experience / Read Models (ADR-004)
                               │
                               ▼
                Application / API Service Boundary
                               │
                               ▼
               Authoritative Platform Services
             (Kernel, Runtime, Security, Engines)
                               │
         ┌─────────────────────┼─────────────────────┐
         ▼                     ▼                     ▼
     Workflows             Execution             Workforce (23 Workers)
                                                     │
                                                     ▼
                                                AI Runtime
                                                     │
                                               ModelAllocator
                                                     │
                                                ModelRouter
                                                     │
                                          Providers / Deployments
                                                     │
                                            M1 / HP / Future M6
```

### 2.2 UI Non-Authority Rules

1. **No Direct Mutation:** The UI cannot directly mutate runtime states, workflow tasks, or artifact databases. All operations are submitted as requests to authoritative services (`Kernel`, `WorkflowEngine`, `ExecutionEngine`, `ArtifactPlatformServices`, `SecurityPlatform`).
2. **Strict Governance & Anti-Bypass:** Consequential operations (stack finalization, architecture finalization, migration execution, migration cutover, deployment, destructive cleanup, credential access, security configuration, artifact publication) must flow through `SecurityPlatform.governance` and require explicit human-in-the-loop (HITL) approval. No AI worker or model may self-approve.
3. **Secrets Redaction:** Raw secrets and sensitive tokens are strictly redacted in all API responses before reaching the UI.
4. **Hardware Honesty:** The future M6 hardware configuration is explicitly reported as a compatibility specification / planned node and never falsely claimed as active physical hardware.
5. **No Autonomous Self-Modification in UI:** The Self-Improvement Center is exposed as an informational, reviewable, and gated interface in compliance with ADR-005 and Phase 19 boundaries.

### 2.3 Epistemic Uncertainty in Legacy Modernization

The Legacy Modernization Workspace categorizes all archaeological findings, business rules, and reconstructed architectural components into four explicit epistemic states:
- **`FACT`**: Directly observed in source code, configuration files, or database schemas with 100% provenance.
- **`INFERENCE`**: Derived deterministically or strongly correlated from observed code patterns and call graphs (confidence ≥ 0.85).
- **`HYPOTHESIS`**: Plausible interpretation or candidate rule requiring verification (confidence < 0.85).
- **`UNKNOWN`**: Unresolved dependency, unparsed dialect, missing source, or gap in archaeological coverage.

---

## 3. Consequences

### Positive
- Strict separation between presentation and platform authority ensures system resilience, auditability, and safety.
- Local-first API architecture cleanly isolates the frontend and prepares for seamless packaging in Phase 21.
- Complete visibility into all 23 specialized workers (14 Greenfield + 9 Legacy) and 13 observability read models.
- Epistemic uncertainty prevents hallucinated assumptions during legacy modernization.

### Negative / Trade-offs
- The UI cannot perform optimistic client-side state mutation; all actions require server-side round trips and authoritative validation.
