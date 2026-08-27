# ADR-009: Phase 10 — Execution Platform Architecture

**Status:** Accepted  
**Phase:** 10 — Execution Platform  
**Date:** 2026-08-27  
**Authors:** AutoForge AI Platform Team  

---

## Context

Phase 9 delivered the Workflow Platform — providing DAG execution, deterministic scheduling, task queueing, retry policies, recovery, and HITL approval gates.

Phase 10 provides the **autonomous engineering execution substrate** that executes actual engineering tasks dispatched by the Workflow Platform. It transforms planned tasks into concrete project modifications through autonomous engineering loops (Understand → Plan → Implement → Execute/Test → Evaluate → Diagnose → Repair → Retest).

Key requirements:
* Execution Engine coordinating workers, loops, environments, and artifacts.
* Worker lifecycle (`CREATED → READY → RUNNING → COMPLETED / FAILED / CANCELLED / WAITING_APPROVAL`).
* Worker Dispatcher enforcing concurrency bounds and propagating cancellations.
* Controlled execution environment with workspace confinement, explicit argv (no shell execution), timeout enforcement, and process group isolation.
* Deterministic-first evaluation combining command exit codes, test runner parsing, and static checks, where model confidence cannot override deterministic failures.
* AI-driven failure diagnosis and repair planning informed by prior attempt failure evidence.
* Artifact pipeline capturing logs, diffs, test summaries, and evaluation reports with rich provenance.
* HITL governance before consequential final actions (e.g. tech-stack finalization, git push, deployment).
* Integration with RuntimeStateManager (authoritative state) and CanonicalEventBus (canonical events).
* Real end-to-end engineering loop acceptance test executing in a controlled workspace.

---

## Decision

### 1. Package: `autoforge-execution`

A standalone `autoforge-execution` package is introduced. It depends on:
* `autoforge-models`
* `autoforge-events`
* `autoforge-runtime`
* `autoforge-ai-infrastructure`
* `autoforge-connectors`
* `autoforge-workflows`

**Dependency direction:**
```
autoforge-composition
  └── autoforge-execution
        ├── autoforge-workflows
        ├── autoforge-connectors
        ├── autoforge-ai-infrastructure
        ├── autoforge-runtime
        ├── autoforge-events
        └── autoforge-models
```

### 2. Module Decomposition

| Module | Responsibility |
|--------|----------------|
| `models.py` | Immutable & mutable domain models (WorkerStatus, CommandSpec, CommandResult, EvaluationResult, DiagnosisReport, ArtifactRecord, LoopConfig, WorkerState) |
| `environment.py` | WorkspaceEnvironment: path confinement, safe subprocess execution, timeout with process-tree cleanup, integration with WorkspaceFilesystem & GitConnector |
| `context.py` | ExecutionContext: task context assembly, file states, and prior attempt histories without duplicating knowledge/memory |
| `ai_adapter.py` | AIEngineeringProvider & AIInfrastructureAdapter: routes reasoning requests via ModelRouter / ExecutionContinuityService |
| `evaluation.py` | EvaluationEngine: deterministic verification of command exits, test runner parsing (pytest/unittest), and check rules |
| `diagnosis.py` | FailureDiagnoser: failure evidence assembly and AI diagnosis report generation |
| `loop.py` | EngineeringLoop: bounded autonomous execution loop with understand-plan-implement-test-evaluate-diagnose-repair cycles |
| `artifacts.py` | ArtifactPipeline: captures artifacts, diffs, execution logs, and provenance metadata |
| `governance.py` | ExecutionGovernance: evaluates consequential actions against policy and raises/manages ApprovalGates |
| `worker.py` | EngineeringWorker: worker lifecycle management and loop execution |
| `dispatcher.py` | WorkerDispatcher: concurrency-bounded worker creation and task dispatch |
| `events.py` | ExecutionEvents: canonical event publishing for execution sessions and loop phases |
| `recovery.py` | ExecutionRecovery: state snapshot and restoration for checkpoints |
| `engine.py` | ExecutionEngine: central facade orchestrating workers, dispatcher, workflows, runtime, and events |
| `errors.py` | Exception taxonomy rooted at ExecutionError |

### 3. Worker Lifecycle & State Machine

Workers follow an explicit, deterministic state machine:
```
CREATED → READY → RUNNING → COMPLETED | FAILED | CANCELLED | WAITING_APPROVAL
```
Runtime remains the single authoritative store for platform state; worker state captures execution-specific details (iteration history, active commands, artifacts).

### 4. Deterministic-First Engineering Loop

The autonomous loop is strictly bounded:
* `max_iterations`: Limits repair attempts (default: 3).
* `timeout_seconds`: Hard wall-clock budget for the entire loop.
* `max_consecutive_failures`: Prevents endless repetition of identical failures.
* Exit code != 0 or failed tests unconditionally cause `EvaluationStatus.FAILED`.
* AI reasoning is used where appropriate: generating initial implementation, diagnosing test output/stderr, and creating informed repair strategies.

### 5. HITL Governance at Consequential Boundaries

Routine engineering loop steps (editing working files, running local unit tests) run autonomously.
Consequential actions (technology stack finalization, architecture finalization, git push, deployment) pause the execution and require human approval via `ApprovalGate` before proceeding.

---

## Consequences

### Positive
* Working autonomous engineering execution platform capable of solving real engineering tasks.
* Real repair loop: failing tests trigger diagnosis that informs the next attempt rather than repeating blindly.
* Security guarantees preserved: confined workspace root, explicit argv lists, subprocess timeout and SIGTERM/SIGKILL process-group cleanup.
* Full integration with existing platforms: AI Infrastructure for model routing, Connector Platform for workspace filesystem/git, Workflow Platform for orchestration, Runtime State Manager for persistence, and Canonical Event Bus for events.
* Full artifact provenance preserved for future Review and Artifact Platforms.

### Compliance
* ✅ Phase 7, 8, and 9 platform architectures preserved and unmodified.
* ✅ No new distributed infrastructure (in-process, local-first execution).
* ✅ Deterministic-first safety guarantees.
* ✅ HITL governance for consequential actions.
* ✅ ADR follows the established numbering convention (ADR-009).
