# ADR-014: Worker Model Policy & Runtime Model Allocation Integration

## Status
Proposed

## Context
Phase 13 of AutoForge AI OS established 23 specialized engineering workers (14 Greenfield, 9 Legacy Modernization) with deterministic capability matching, execution loops, and evidence preservation. 

However, forensic analysis identified that while workers declare high-level domain capabilities, their explicit model requirements (reasoning depth, coding capability, context window, structured output, local-only constraints) were not populated on worker definitions, and `AIInfrastructureAdapter` in the execution layer defaulted to a generic, hardcoded `CODE_COMPLETION` capability request for all LLM interactions.

To achieve intelligent, deterministic model allocation without violating the single-authority routing architecture:
1. Workers must declare **what kind of model they need** (Worker Model Profile).
2. Tasks must be able to **refine or strengthen** these defaults (Task Model Requirements).
3. The system must deterministically merge them into **Effective Model Requirements**.
4. The `ModelAllocator` (via `CapacityAwareRouter` and `ModelRouterService`) must remain the **single authoritative decision-maker** for selecting models across local and future inference nodes.
5. Workers must **never own a fixed model identity**.

## Decision

1. **Separation of Concerns**:
   - **Worker Capability**: Domain role definition for workforce dispatch (e.g. `backend_coding`, `code_archaeology`).
   - **Worker Model Profile / Policy**: Specification of LLM requirements and preferences (e.g. `CapabilityIds.REASONING`, `min_context_window_tokens=32768`, `local_only`).
   - **Task Model Requirements**: Task-specific refinement attached to task definitions/inputs.
   - **Effective Model Requirements**: Deterministically resolved requirements passed to execution context.
   - **Model Selection**: Concrete model identity chosen by `ModelRouterService` and `ModelCapacityManager`.

2. **Deterministic Precedence Rules**:
   - **Mandatory Constraints**: Worker mandatory requirements + task mandatory requirements form a strengthened union/intersection (e.g., higher context window, required capabilities). Task requirements can strengthen but cannot silently weaken mandatory worker constraints.
   - **Conflicting Constraints**: If task requirements contradict worker policy (e.g. attempting to relax a local-only privacy rule without authority), the router fails deterministically.
   - **Preferences**: Preferences (quality, latency, cost) feed into deterministic candidate ranking.

3. **Dynamic Runtime Propagation**:
   - `WorkforceDispatcher` resolves `EffectiveModelRequirements` from `WorkerModelProfile` and `TaskModelRequirements`.
   - `ExecutionContext` carries `EffectiveModelRequirements`.
   - `AIInfrastructureAdapter` builds a dynamic `RoutingRequest` directly from `EffectiveModelRequirements`, removing all hardcoded `CODE_COMPLETION` assumptions.
   - `ModelAllocator` filters candidates deterministically and verifies capacity before dispatching to execution.

4. **Multi-Model and Future Hardware Compatibility**:
   - Generic node abstraction supports concurrent multi-model execution across `local-m1`, `local-hp`, and simulated `local-mac-mini-m6`.
   - Adding new nodes requires only registry configuration; worker classes remain unchanged.

5. **HITL Governance**:
   - Routine model selection is deterministic and automated.
   - Consequential milestones (technology stack finalization, modernization architecture approval, migration cutover) strictly require Human-in-the-loop (HITL) approval.

## Consequences

- **Positive**: All 23 workers receive role-appropriate LLM allocations (e.g. `ResearchEngineer` gets reasoning models; `BackendEngineer` gets coding models; `LegacyCodeArchaeologist` gets large-context models).
- **Positive**: Eliminates hardcoded model assumptions and prevents duplicate routing logic.
- **Positive**: Fully compatible with Phase 7 AI Infrastructure and Phase 14 Observability platforms.
- **Negative / Constraints**: Tasks must provide valid requirements; invalid or conflicting requirement combinations are rejected deterministically.
