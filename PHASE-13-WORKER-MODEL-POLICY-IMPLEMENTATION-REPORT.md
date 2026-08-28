# PHASE-13 WORKER MODEL POLICY & RUNTIME MODEL ALLOCATION IMPLEMENTATION REPORT

**Author**: AutoForge AI OS Autonomous Agent  
**Date**: 2026-08-28  
**Status**: COMPLETE (Stopped for Human Review, No Git Push/Commit, No Premature Certification)  
**Governing ADR**: [`architecture/decisions/ADR-014-worker-model-policy-allocation.md`](file:///Users/kalachanddash/Documents/AutoForge%20AI/architecture/decisions/ADR-014-worker-model-policy-allocation.md)

---

## 1. Executive Summary

This report documents the architectural design, implementation, and multi-package integration of the **Worker Model Policy and Runtime Model Allocation Layer** in AutoForge AI OS. Following an independent forensic audit that identified a missing abstraction between worker capabilities and model execution, we have implemented role-specific model profiles for all 23 workers (14 Greenfield, 9 Legacy Modernization), established deterministic precedence rules for merging task requirements with worker defaults, and eliminated hardcoded capability assumptions in `AIInfrastructureAdapter`. All 1082 automated tests across all 14 packages pass with 0 failures and 0 errors.

---

## 2. Forensic Findings Summary

The initial audit revealed the following architectural gaps:
1. **Unpopulated Worker Profiles**: Workers exposed domain expertise strings but lacked structured LLM requirements (reasoning requirements, context windows, privacy tiers).
2. **Hardcoded Adapter Assumptions**: `AIInfrastructureAdapter` hardcoded `CapabilityIds.CODE_COMPLETION` for all model requests (planning, code generation, failure diagnosis, and repair).
3. **Missing Precedence Resolver**: Task-level model refinements could not be combined with worker defaults.

---

## 3. Architecture Decision Summary (ADR-014)

[`ADR-014-worker-model-policy-allocation.md`](file:///Users/kalachanddash/Documents/AutoForge%20AI/architecture/decisions/ADR-014-worker-model-policy-allocation.md) formalizes:
- **Separation of Concerns**: Workers define *what they need*; `ModelAllocator` (via `ModelRouterService`) decides *what runs*.
- **Precedence Hierarchy**: Task requirements refine and strengthen worker defaults; tasks cannot weaken mandatory worker policies.
- **Single Authority**: `ModelAllocator` remains the sole authority for candidate selection and capacity management.
- **Local-First & Hardware Portability**: Support for `local-m1`, `local-hp`, and simulated `local-mac-mini-m6` without modifying worker code.

---

## 4. Separation of Concerns

```text
┌──────────────────────────────────────────────────────────┐
│                   WORKER CAPABILITY                      │
│ Domain role definition for workforce dispatch (e.g. backend, archaeology)│
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│               WORKER MODEL POLICY / PROFILE              │
│ Declarative LLM needs (reasoning, context window, privacy, structured output)│
└────────────────────────────┬─────────────────────────────┘
                             │  + Task Requirements
┌────────────────────────────▼─────────────────────────────┐
│              EFFECTIVE MODEL REQUIREMENTS                │
│ Deterministic merge via resolve_effective_requirements() │
└────────────────────────────┬─────────────────────────────┘
                             │
┌────────────────────────────▼─────────────────────────────┐
│                     MODEL SELECTION                      │
│ ModelAllocator / ModelRouterService -> Node & Model ID   │
└──────────────────────────────────────────────────────────┘
```

---

## 5. Complete 23-Worker Model Profile Matrix

| # | Worker Class | Worker Type | Required Capabilities | Min Context | Reasoning | Coding | Structured Output | Tool Use | Quality Tier | Privacy |
|---|--------------|-------------|-----------------------|-------------|-----------|--------|-------------------|----------|--------------|---------|
| 1 | `ResearchEngineer` | `research_engineer` | `text_generation`, `reasoning` | 16,384 | Yes | No | No | No | 3 | `local_only` |
| 2 | `ArchitectureEngineer` | `architecture_engineer` | `text_generation`, `reasoning`, `structured_output` | 16,384 | Yes | No | Yes | No | 4 | `local_only` |
| 3 | `PlanningEngineer` | `planning_engineer` | `text_generation`, `reasoning`, `structured_output` | 16,384 | Yes | No | Yes | No | 3 | `local_only` |
| 4 | `UIDesigner` | `ui_designer` | `text_generation`, `structured_output` | 8,192 | No | No | Yes | No | 2 | `local_only` |
| 5 | `BackendEngineer` | `backend_engineer` | `code_generation`, `structured_output` | 32,768 | No | Yes | Yes | No | 3 | `local_only` |
| 6 | `FrontendEngineer` | `frontend_engineer` | `code_generation`, `structured_output` | 16,384 | No | Yes | Yes | No | 3 | `local_only` |
| 7 | `DatabaseEngineer` | `database_engineer` | `code_generation`, `structured_output` | 16,384 | No | Yes | Yes | No | 3 | `local_only` |
| 8 | `MLEngineer` | `ml_engineer` | `code_generation`, `tool_use`, `reasoning` | 16,384 | Yes | Yes | No | Yes | 3 | `local_only` |
| 9 | `InfrastructureEngineer` | `infrastructure_engineer` | `code_generation`, `structured_output` | 16,384 | No | Yes | Yes | No | 3 | `local_only` |
| 10 | `DevOpsEngineer` | `devops_engineer` | `code_generation`, `structured_output` | 16,384 | No | Yes | Yes | No | 3 | `local_only` |
| 11 | `QAEngineer` | `qa_engineer` | `code_generation`, `tool_use` | 16,384 | No | Yes | No | Yes | 3 | `local_only` |
| 12 | `SecurityEngineer` | `security_engineer` | `code_generation`, `reasoning`, `tool_use` | 32,768 | Yes | Yes | No | Yes | 4 | `local_only` |
| 13 | `PerformanceEngineer` | `performance_engineer` | `reasoning`, `tool_use` | 16,384 | Yes | No | No | Yes | 3 | `local_only` |
| 14 | `DocumentationEngineer` | `documentation_engineer` | `text_generation` | 16,384 | No | No | No | No | 2 | `local_only` |
| 15 | `LegacySystemsResearchEngineer` | `legacy_systems_research_engineer` | `text_generation`, `reasoning` | 16,384 | Yes | No | No | No | 3 | `local_only` |
| 16 | `LegacyCodeArchaeologist` | `legacy_code_archaeologist` | `code_generation`, `text_generation` | 32,768 | No | Yes | No | No | 4 | `local_only` |
| 17 | `LegacyArchitectureAnalyst` | `legacy_architecture_analyst` | `text_generation`, `reasoning`, `structured_output` | 16,384 | Yes | No | Yes | No | 4 | `local_only` |
| 18 | `LegacyDataEngineer` | `legacy_data_engineer` | `code_generation`, `structured_output` | 16,384 | No | Yes | Yes | No | 3 | `local_only` |
| 19 | `LegacyIntegrationEngineer` | `legacy_integration_engineer` | `code_generation`, `structured_output` | 16,384 | No | Yes | Yes | No | 3 | `local_only` |
| 20 | `BusinessRulesAnalyst` | `business_rules_analyst` | `text_generation`, `reasoning`, `structured_output` | 16,384 | Yes | No | Yes | No | 4 | `local_only` |
| 21 | `DependencyImpactAnalyst` | `dependency_impact_analyst` | `reasoning`, `structured_output`, `tool_use` | 16,384 | Yes | No | Yes | Yes | 4 | `local_only` |
| 22 | `ModernizationArchitect` | `modernization_architect` | `text_generation`, `reasoning`, `structured_output` | 16,384 | Yes | No | Yes | No | 5 | `local_only` |
| 23 | `MigrationEngineer` | `migration_engineer` | `code_generation`, `tool_use`, `structured_output` | 32,768 | No | Yes | Yes | Yes | 4 | `local_only` |

---

## 6. Greenfield Worker Profiles (14)

All 14 greenfield workers have distinct profiles matching their engineering responsibilities:
- **Strategic Roles** (`ResearchEngineer`, `ArchitectureEngineer`, `PlanningEngineer`): Demand reasoning and structured output models.
- **Coding Roles** (`BackendEngineer`, `FrontendEngineer`, `DatabaseEngineer`, `InfrastructureEngineer`, `DevOpsEngineer`): Demand code generation and structured output with 16k–32k context windows.
- **Verification Roles** (`QAEngineer`, `SecurityEngineer`, `PerformanceEngineer`): Demand tool use and code reasoning.
- **UI & Documentation Roles** (`UIDesigner`, `DocumentationEngineer`): Lightweight text generation and structured specs with fast turnaround.

---

## 7. Legacy Modernization Worker Profiles (9)

All 9 legacy workers feature specialized profiles tailored for legacy codebase modernization:
- **`LegacyCodeArchaeologist`**: Requires 32k context window and code generation to ingest legacy source files (COBOL, Java, SQL).
- **`BusinessRulesAnalyst`**: Requires structured reasoning to identify and isolate embedded business rules and conflicts.
- **`ModernizationArchitect`**: Configured with top quality tier (5) to perform high-stakes trade-off analyses.
- **`MigrationEngineer`**: Requires high reliability (0.98), code generation, and tool use for automated migration scripting.

---

## 8. Task-Level Model Requirements Abstraction

Tasks can define optional refinements in `TaskDefinition.input_data["model_requirements"]` or `TaskDefinition.metadata["model_requirements"]`:
```python
task_def = TaskDefinition(
    task_id="task-arch-01",
    name="AST Parsing",
    task_type="legacy_code_archaeologist",
    input_data={
        "model_requirements": {
            "min_context_window_tokens": 65536,
            "tool_use_required": True
        }
    }
)
```

---

## 9. Effective Model Requirements Resolution Algorithm

The `resolve_effective_requirements(worker_profile, task_requirements)` function:
1. Normalizes `task_requirements` (handling dicts or `TaskModelRequirements` objects).
2. Computes the union of worker and task required capabilities.
3. Automatically adds capability IDs implied by boolean requirement flags (`reasoning` -> `REASONING`, `coding` -> `CODE_GENERATION`, `structured_output` -> `STRUCTURED_OUTPUT`, `tool_use` -> `TOOL_USE`).
4. Computes effective minimum context: `max(worker.min_context, task.min_context)`.
5. Enforces privacy invariants: worker's `local_only` constraint cannot be relaxed by a task.
6. Computes effective quality tier: `max(worker.quality_priority, task.quality_priority)`.

---

## 10. Precedence & Constraint Intersection Rules

- **Strengthening Allowed**: Tasks can demand larger context windows, higher quality tiers, or additional capabilities.
- **Weakening Forbidden**: Tasks cannot lower context windows below the worker's minimum or route sensitive work to cloud providers if the worker requires `local_only`.
- **Deterministic Resolution**: If conflicting constraints occur, the system resolves to the most restrictive valid policy or fails deterministically.

---

## 11. Removal of Hardcoded Assumptions in Execution Layer

In `packages/execution/src/autoforge_execution/ai_adapter.py`:
- `_build_routing_request(context)` extracts effective model requirements directly from `context.effective_model_requirements`.
- Eliminated all hardcoded `frozenset({CapabilityIds.CODE_COMPLETION})` references.
- Dynamic capabilities are passed into `RoutingRequest(required_capabilities=..., min_context_window_tokens=..., allowed_deployment_modes=...)`.

---

## 12. Propagation Path Architecture & Tracing

```text
1. TaskDefinition (with input_data.model_requirements)
   ↓
2. WorkforceDispatcher.dispatch_task()
   ↓ [WorkerModelProfile + TaskModelRequirements -> EffectiveModelRequirements]
3. ExecutionContext(effective_model_requirements=...)
   ↓
4. WorkforceWorker.execute_task() -> EngineeringLoop.run()
   ↓
5. AIInfrastructureAdapter.generate_plan() / generate_implementation()
   ↓ [builds RoutingRequest from effective_model_requirements]
6. ModelRouterService.route(RoutingRequest) + ModelCapacityManager
   ↓
7. RoutedModelExecutor -> Concrete Inference Node & Model
```

---

## 13. Model Allocator Integration & Precedence

The `CapacityAwareRouter` and `ModelCapacityManager` under `packages/workforce/src/autoforge_workforce/model_allocator.py` maintain full backward and forward compatibility with the Phase-7 `ModelRouterService`:
- Query hard constraints against `CapabilityRegistryPort`.
- Filter out unhealthy/offline nodes.
- Rank candidates by score (quality, latency, cost).
- Check concurrency capacity; queue/defer if capacity is exhausted.

---

## 14. Concurrency, Capacity, and Failover Architecture

- **Concurrency Locks**: `ModelCapacityManager` enforces slot acquisition with async locks.
- **Queue/Defer**: Waiters are queued on an `asyncio.Event` and notified upon `release_slot()`.
- **Node Failover**: If the primary candidate node is busy or offline, the router automatically fails over to the next eligible candidate (e.g., `qwen2.5-coder-7b` on `local-m1` -> `qwen2.5-coder-3b` on `local-hp`).

---

## 15. Multi-Node and Simulated M6 Hardware Support

- **Reference Nodes**:
  - `local-m1`: Hosts `qwen2.5-coder-7b` (Code/Structured Output) and `ornith-9b` (Reasoning/Text).
  - `local-hp`: Hosts `qwen2.5-coder-3b` (Code/Text).
  - `local-mac-mini-m6`: Hosts simulated `mac-mini-m6-node` (65k context, all capabilities, unmeasured throughput).
- **Extensibility**: Additional nodes can be registered in the capability registry without altering any worker definitions.

---

## 16. HITL Governance & Decision Gating

- Routine model selection is automated and deterministic.
- Consequential actions (technology stack selections, modernization proposals, migration execution) require human-in-the-loop approval before cutover.

---

## 17. Independent Test Suite Architecture & Results

Test suite in `packages/workforce/tests/test_model_allocation.py`:
- `test_all_23_workers_have_explicit_model_profiles`: Verifies profile completeness on all 23 workers.
- `test_materially_appropriate_role_profiles`: Verifies role-specific requirement assignments.
- `test_task_refinement_strengthens_worker_defaults`: Verifies task-level requirement strengthening.
- `test_mandatory_constraints_cannot_be_weakened_by_tasks`: Verifies privacy and context constraints cannot be downgraded.
- `test_runtime_propagation_via_context_and_adapter`: Verifies dynamic `RoutingRequest` construction.
- `test_different_tasks_within_one_worker_receive_different_models`: Verifies tasks within one worker route to different models.
- `test_deterministic_candidate_filtering_and_ranking`: Verifies capability and context candidate filtering.
- `test_capacity_constraints_and_failover`: Verifies capacity exhaustion and failover to secondary nodes.
- `test_legacy_end_to_end_multi_model_routing_pipeline`: Verifies multi-model flow for legacy modernization.
- `test_workforce_dispatcher_end_to_end_dispatch`: Verifies end-to-end task dispatch with effective model requirements.

---

## 18. Legacy End-to-End Multi-Model Routing Verification

The legacy pipeline verification proved:
1. `LegacyCodeArchaeologist` (Code Gen + 32k context) -> routes to `qwen2.5-coder-7b` on `local-m1`.
2. `BusinessRulesAnalyst` (Reasoning + Structured Output) -> routes to `ornith-9b` on `local-m1`.
3. `ModernizationArchitect` (Quality 5 Reasoning) -> routes to `ornith-9b` on `local-m1`.
4. `MigrationEngineer` (Code Gen + Tool Use + 32k context) -> routes to `qwen2.5-coder-7b` on `local-m1`.

---

## 19. Full Workspace Regression Test Results

Executed aggregated test runner across all 14 packages:

```text
============================================================
 ALL TESTS AGGREGATED REPORT
============================================================
Package                   | Passed | Failed | Skipped | Errors | Exit Code
--------------------------------------------------------------------
ai_infrastructure         | 83     | 0      | 0       | 0      | 0        
artifacts                 | 13     | 0      | 0       | 0      | 0        
composition               | 24     | 0      | 0       | 0      | 0        
connectors                | 93     | 0      | 0       | 0      | 0        
event_platform            | 56     | 0      | 0       | 0      | 0        
events                    | 228    | 0      | 0       | 0      | 0        
execution                 | 37     | 0      | 0       | 0      | 0        
kernel                    | 100    | 0      | 0       | 0      | 0        
observability             | 12     | 0      | 0       | 0      | 0        
persistence               | 70     | 0      | 0       | 0      | 0        
review                    | 114    | 0      | 0       | 0      | 0        
runtime                   | 36     | 0      | 0       | 0      | 0        
workflows                 | 194    | 0      | 0       | 0      | 0        
workforce                 | 22     | 0      | 0       | 0      | 0        
--------------------------------------------------------------------
TOTAL                     | 1082   | 0      | 0       | 0      |
====================================================================
```

---

## 20. Invariant & Quality Assurance Matrix

| Criterion | Requirement | Verification Result |
|---|---|---|
| 1 | 23 Workers with Model Profiles | PASS |
| 2 | Role-Appropriate Profiles | PASS |
| 3 | No Hardcoded Model IDs on Workers | PASS |
| 4 | Worker Capability vs Model Separation | PASS |
| 5 | Task Requirements Refinement | PASS |
| 6 | Mandatory Policy Preservation | PASS |
| 7 | Deterministic Precedence Resolution | PASS |
| 8 | Dynamic Adapter Routing | PASS |
| 9 | Single Authority Model Allocator | PASS |
| 10 | Local-First & Privacy Constraints | PASS |
| 11 | Capacity & Failover Management | PASS |
| 12 | Simulated M6 Hardware Node Support | PASS |
| 13 | Legacy Multi-Model Pipeline | PASS |
| 14 | HITL Consequential Action Gating | PASS |
| 15 | 100% Green Workspace Test Suite | PASS (1082/1082) |

---

## 21. Remaining Limitations & Environmental Context

- **Local Inference Server**: Tests use deterministic registry test doubles and simulated node topologies as real local llama.cpp / Ollama instances are not spawned in the automated test runner.
- **M6 Node Profile**: `local-mac-mini-m6` remains explicitly registered as a simulated node with unmeasured throughput to avoid synthetic benchmarking artifacts.

---

## 22. Certification Status & Stopping Invariant

In accordance with strict operating rules:
- **Implementation Status**: Fully Implemented and Verified.
- **Git Commit / Push**: NOT performed (awaiting explicit human instruction).
- **Certification Declaration**: NOT declared certified (awaiting independent human sign-off).
