# ADR-010 (Proposed Draft): Durable Workflow Orchestration — OrchestrationAdapter + Optional External Backend

**Status:** Proposed (draft — NOT accepted; no canonical change)
**Phase target:** Phase 9 boundary / Phase 12+/21
**Date:** 2026-08-27
**Author:** AutoForge AI OS — Architecture Reconciliation mission

> This is a **proposed draft ADR**. Per the repository ADR governance, a canonical ADR
> that changes architecture is written as **Accepted** only after formal approval. This
> document is placed in the drafting area (`docs/adr/`) and must not be treated as
> approved architecture. It documents the decision recommended by the architecture
> reconciliation and must be ratified through the project's ADR review process before any
> implementation.

---

## Context

The canonical architecture requires long-running, recoverable, checkpointable
executions (VISION §3), while AutoForge remains *local-first*, *vendor-neutral*, and
*deterministic-first* (MANIFEST, PRINCIPLES).

Phase 9 (`autoforge-workflows`) implements an in-process, deterministic orchestrator:
DAG, state machine, queue, scheduler, deterministic retry semantics, HITL approval gates,
and snapshot-based recovery. Phase 10 (`autoforge-execution`) implements the autonomous
engineering execution substrate. Both are certified and frozen.

Constraints observed:
- **Local-first** — ordinary development must not require cloud or distributed infra.
- **Vendor-neutral / model-agnostic** — no required backend product.
- **Deterministic-first** — the LLM must never be a policy engine; orchestration decisions
  remain deterministic.
- **Runtime is the single authority** for durable platform state and checkpoints (ADR-002).
- **Single canonical event vocabulary** (ADR-001).
- Current Phase 9/10 are frozen and must not be replaced or redesigned.

---

## Decision (Reconciliation Result)

1. The current **`WorkflowEngine` becomes the stable AutoForge domain abstraction** for
   orchestration — it remains authoritative on workflow semantics, dependency policy,
   HITL/approval policy, task meaning, governance, and engineering lifecycle.
2. Introduce a **Workflow Orchestration Adapter** — the single, replaceable boundary that
   maps AutoForge domain intent to an execution backend. It has two implementations:
   - **InProcessExecution** — deterministic, offline, local-first backend (the current
     engine). **Default** and required.
   - **Temporal execution** — optional **production** backend for durable, distributed
     long-running workflows (timers, durable waits/signals, crash recovery, distributed
     worker scheduling).
3. **Temporal, if adopted, is a component behind the adapter.** It never replaces the
   domain engine and never appears in AutoForge domain code. Adoption is deferred and
   orthogonal to Phase 11 (Review).
4. All other candidate frameworks evaluated by this mission are **not adopted**:
   **LangGraph** and **LangChain** and **CrewAI** = DO NOT USE (reasoning and multi-agent
   orchestration are already served by the Engineering Loop, Model Router, Worker
   Dispatcher, and Workflow Engine). **Langfuse** = OPTIONAL LLM-telemetry adapter at
   Phase 14, never the runtime system of record.
5. **Deterministic-first is preserved**: policy, dependencies, retry, timeout, security,
   and approval requirements remain AutoForge-owned and deterministic; AI contributes only
   planning/analysis/tradeoff/reasoning and can never override a deterministic gate.

---

## Consequences

Positive:
- Preserves the certified Phase 9/10 implementation and local-first dev (in-process default).
- Gains an optional, replaceable durable-execution path for production long-running
  sessions without coupling to a specific product.
- Keeps Runtime as the authority and canonical events intact.
- Formalizes the Auto-driven adapter-for-framework principle.

Negative / trade-offs:
- Requires a clear adapter today for the durable path to be honest later.
- Temporal (if adopted) introduces external infrastructure and operational cost.
- An additional abstraction layer must be kept thin to avoid over-engineering.

Neutral:
- InProcess default means no behavior change for current tests (431 passing baseline preserved).

---

## Alternatives Considered

| Alternative | Reason for not accepted |
|---|---|
| Replace WorkflowEngine with raw Temporal APIs | Destroys deterministic domain semantics, HITL, canonical events, and Runtime authority; forbidden |
| Use LangGraph / LangChain / CrewAI now in execution | Already-served by Engineering Loop / Model Router / Dispatcher; causes overlapping ownership and coupling |
| Declare Temporal mandatory | Violates local-first and vendor-neutrality; in-process remains a valid production path |