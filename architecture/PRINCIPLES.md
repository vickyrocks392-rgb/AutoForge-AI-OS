# Principles

## Purpose

This document defines the core engineering and design principles that guide every decision made in the AutoForge AI platform. These principles are the immutable foundation upon which the system is built.

## Scope

These principles apply to all architectural decisions, code contributions, documentation, and operational practices within the project.

---

## Engineering Principles

### 1. Separation of Concerns
Every component owns one domain and one responsibility. Services do not overlap. Packages do not duplicate. Boundaries are explicit and enforced.

### 2. Contract-First Design
All inter-component communication is governed by versioned, validated contracts. Contracts are defined before implementation and treated as living documentation.

### 3. Determinism Where Possible
Given identical inputs and context, the system should produce identical outputs. Non-determinism is isolated, documented, and controlled.

### 4. Fail Gracefully
Every component handles errors explicitly. Failures are logged with full context. The system degrades safely rather than crashing or producing silent corruption.

### 5. Humans in the Loop
AI drives execution. Humans review, approve, and steer. The platform is designed to augment human engineers, not replace them without oversight.

### 6. Transparency by Default
Every decision, artifact, and action is logged, versioned, and inspectable. There are no black boxes. The system explains its reasoning.

### 7. Incremental Value
Each iteration produces a working, verifiable artifact. The system is always in a deployable state. Progress is measured by shipped value, not lines of code.

## Design Principles

### 8. Composition Over Inheritance
Capabilities are composed from small, focused units. Services are assembled from packages. Workflows are composed from steps.

### 9. Convention Over Configuration
Sensible defaults exist for everything. Configuration is explicit only when deviation from convention is required.

### 10. Observable by Design
Observability is not an afterthought. Every component emits structured logs, metrics, and traces as a first-class concern.

## Architectural & Governance Principles

### 11. AutoForge as the Primary Architecture
AutoForge remains the authoritative operating platform. External frameworks do not become architectural authorities. Domain models, state lifecycles, and orchestration contracts are owned solely by AutoForge.

### 12. External Framework Containment
- **Temporal**: Remains an OPTIONAL durable orchestration adapter behind the `OrchestrationAdapter` interface. `WorkflowEngine` remains the AutoForge domain abstraction and policy owner.
- **LangGraph, LangChain, CrewAI**: Remain excluded from the live execution path. They must not silently enter the platform.
- **Langfuse**: May serve as an optional observability adapter for telemetry export, but never becomes the system of record. AutoForge Observability is canonical.

### 13. AI Non-Authority Invariant
AI models do not own governance, policy, state authority, HITL approval gates, determinism, or engineering meaning. AI provides probabilistic generation; the platform provides deterministic control.

### 14. UI Non-Authority Invariant
The user interface is strictly a presentation, monitoring, and control layer. Authoritative state resides exclusively in the Runtime State Manager, Kernel, and platform services.

### 15. Worker Model Agnosticism & Centralized Allocation
Workers declare domain capabilities and model requirements (via `WorkerModelProfile`); workers NEVER hardcode concrete model IDs. Model selection and capacity management remain strictly centralized in `ModelAllocator` and `ModelRouterService`.

### 16. First-Class Legacy Modernization & Specialized Workforce
Legacy modernization is a co-equal, first-class capability supported by 9 specialized workers. The 23-worker workforce (14 Greenfield + 9 Legacy) is preserved and never reduced to generic agents.

### 17. Strict Epistemic Separation
Unfamiliar codebases and systems are analyzed using deterministic evidence collection with strict separation of `FACT`, `INFERENCE`, `HYPOTHESIS`, and `UNKNOWN`. Analysis gaps are explicitly represented; the system never hallucinates missing information.

### 18. Context Engineering as a First-Class Capability (ADR-003)
Context Engineering composes Knowledge and Memory capabilities without duplicating them, delivering rich, provenance-aware context to execution units.

### 19. Memory ≠ Learning Boundary (ADR-005)
Memory preserves state, artifacts, and historical context; Learning synthesizes generalized adaptations and platform optimizations.

### 20. Strictly Gated Self-Improvement Pipeline
All candidate optimizations (routing, prompt, workflow, or heuristics) must pass through the mandatory safety pipeline:
`Candidate → Evaluation → Benchmark → Regression → Accept/Reject → Version → Rollback Capability → Activate`.
Silent self-modification is strictly forbidden.