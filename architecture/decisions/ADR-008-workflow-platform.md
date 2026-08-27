# ADR-008: Phase 9 — Workflow Platform Architecture

**Status:** Accepted  
**Phase:** 9 — Workflow Platform  
**Date:** 2026-08-27  
**Authors:** AutoForge AI Platform Team  

---

## Context

Phase 8 delivered the Connector Platform — a uniform boundary over external
systems (filesystem, git, GitHub).  Phase 7 delivered the AI Infrastructure
Platform (model routing, inference, memory).  The runtime (Phase 5) provides
authoritative state management.

The next architectural need is a **Workflow Orchestration Substrate** that can
coordinate multi-step engineering processes across connectors and agents
deterministically.  Without this substrate, autonomous engineering (Phase 10)
cannot be made reliable or recoverable.

Key requirements identified in `ARCHITECTURE.md` and `ROADMAP.md`:

* Directed Acyclic Graph (DAG) execution with dependency resolution.
* Deterministic scheduling: priority-aware, concurrency-bounded.
* Retry policies with configurable backoff — no randomness, no model judgment.
* HITL (Human-in-the-Loop) approval gates for consequential actions.
* Recovery via checkpoint snapshot/restore.
* No distributed message broker (in-process, single-node for Phase 9).
* Workflow Engine must NOT create a competing state store — Runtime remains
  the authoritative state platform.

---

## Decision

### 1. Package: `autoforge-workflows`

A standalone `autoforge-workflows` package is introduced alongside the
existing Phase 7/8 packages.  It depends on:

* `autoforge-models` — shared enums and value types.
* `autoforge-events` — canonical event vocabulary for publishing lifecycle events.
* `autoforge-runtime` — state transition validation (used read-only as a
  reference; the engine's own `WorkflowTaskStatus` state machine is defined
  in `state.py`).

**Dependency direction (one-way, no cycles):**

```
autoforge-composition
  └── autoforge-workflows
        ├── autoforge-events
        ├── autoforge-models
        └── autoforge-runtime
```

### 2. Module Decomposition

Each concern is isolated in its own module with a single responsibility:

| Module | Responsibility |
|--------|----------------|
| `models.py` | Immutable definition-time value objects (WorkflowDefinition, TaskDefinition, RetryPolicy, ExecutionPolicy, ApprovalGatePolicy) |
| `state.py` | Deterministic WorkflowTaskStatus state machine + transition table |
| `dag.py` | DAG construction, cycle detection (Kahn's algorithm), dependency readiness queries |
| `queue.py` | Priority-aware, readiness-gated, FIFO-within-priority task queue |
| `scheduler.py` | Eligibility evaluation, concurrency-bounded dispatch, failure policy |
| `retry.py` | Deterministic retry eligibility and backoff computation |
| `approval.py` | HITL approval gate with multi-approver support and timeout detection |
| `recovery.py` | Snapshot/restore for recovery from interruption |
| `engine.py` | Central orchestrator composing all subsystems; event sink integration |
| `errors.py` | Exception hierarchy rooted at WorkflowError |

### 3. WorkflowTaskStatus State Machine

A separate `WorkflowTaskStatus` enum is introduced for the Workflow Platform
rather than re-using the Runtime's `TaskStatus`.  This allows the Workflow
Engine to own its own state machine cleanly.

```
PENDING → READY | BLOCKED | CANCELLED
READY → RUNNING | BLOCKED | CANCELLED
RUNNING → SUCCEEDED | FAILED | WAITING_APPROVAL | CANCELLED
BLOCKED → READY | CANCELLED
WAITING_APPROVAL → RUNNING | CANCELLED
RETRYING → RUNNING | FAILED
FAILED → RETRYING | CANCELLED
SUCCEEDED  (terminal)
CANCELLED  (terminal)
```

All transitions are enforced by a static lookup table in `state.py`.
**No AI model inference is used for state transition decisions.**

### 4. DAG Engine

The DAG is built from `WorkflowDefinition.dependencies` using Kahn's BFS-based
topological sort.  Cycle detection is O(V+E) and produces deterministic error
reports.  When multiple tasks are equally eligible (same in-degree), they are
sorted lexicographically by `task_id` for reproducible ordering.

The DAG answers these queries deterministically:
* `is_dependency_satisfied(task_id, statuses)` — should a task become READY?
* `is_blocked_by_failure(task_id, statuses)` — should a task become BLOCKED?
* `get_ready_tasks(statuses)` — batch eligibility check for scheduling tick.

### 5. Task Queue

`TaskQueue` is an in-process, priority-sorted, FIFO-within-priority queue.
Priority bands: `critical=0 > high=1 > medium=2 > low=3`.

Tasks are only dequeued when their recorded status is `READY` — this provides
the readiness gate that prevents dispatching tasks before their dependencies
are satisfied.

**There is no distributed queue.** This is explicitly scoped to in-process
orchestration as mandated by the Phase 9 requirements.

### 6. Scheduler

`WorkflowScheduler.tick()` is a pure function: given the DAG, task states,
queue, and execution policy, it returns a `SchedulingDecision` describing:
* tasks that became READY this tick
* tasks that became BLOCKED this tick
* tasks to dispatch (up to `max_concurrent_tasks`)
* whether the workflow is complete or failed
* tasks to cancel due to failure policy

**The scheduler never executes tasks** — it only decides eligibility.
Phase 10 engineering workers are the execution layer.

### 7. Retry Policies

Retry decisions are computed by `should_retry(context, policy)` — a pure
deterministic function.  The retry policy supports:

* `max_attempts` — total execution attempts.
* `BackoffStrategy` — FIXED, LINEAR, EXPONENTIAL (capped at `max_delay_seconds`).
* `non_retryable_error_codes` — explicit blocklist.
* `retryable_error_codes` — optional allowlist.

**No AI model is consulted to decide whether to retry.**

### 8. HITL Approval Gates

Tasks with an `ApprovalGatePolicy` pause the workflow at execution completion.
The `ApprovalGate` tracks `ApprovalDecision` records with `decided_by` identity
and `ApprovalOutcome` (APPROVED/REJECTED).  Multi-approver support requires N
approvals before the gate is opened.

The gate is in-process; network delivery of approval requests is Phase 15
(Security/API).

### 9. Recovery

`WorkflowRecovery.create_snapshot()` captures task states, the queue, and
approval gate states into a plain `WorkflowSnapshot` dictionary.
`WorkflowRecovery.recover()` reconstructs the workflow with deterministic rules:

* SUCCEEDED/CANCELLED tasks are preserved unchanged.
* RUNNING/WAITING_APPROVAL tasks at interrupt time are reset to READY.
* FAILED tasks with retries remaining are reset to RETRYING.
* PENDING/BLOCKED/RETRYING tasks are kept as-is.

Snapshots can be stored in the Runtime's `CheckpointManager` or any
`dict`-based store.

### 10. Event Integration

The `WorkflowEngine` accepts an optional `event_sink` conforming to
`EventSinkProtocol`.  On task and workflow lifecycle events, it publishes
canonical events using the existing `autoforge_events` vocabulary.

**The engine NEVER defines new event types.**  All emitted events use the
existing frozen event vocabulary.  Event sink failures are silently swallowed
so they cannot break the workflow engine.

### 11. Runtime Integration

The `WorkflowEngine` accepts an optional `runtime_facade` conforming to
`RuntimeFacadeProtocol`.  Without a facade the engine is self-contained.
The facade records workflow and task state into the Runtime's authoritative
store so that Runtime remains the single source of truth for platform state.

---

## Consequences

### Positive

* Clean single-responsibility module decomposition — each module has one job.
* Zero distributed infrastructure required — no Redis, Kafka, Celery, Temporal.
* Deterministic-first: all scheduling, retry, and dependency decisions are pure
  functions that are easily unit-tested and reasoned about.
* HITL capability built-in from day one, enabling governance gates for
  consequential autonomous actions.
* Recovery is built-in — workflow interruptions can be resumed from checkpoint.
* Phase 7 and Phase 8 are completely preserved; no regressions introduced.
* 194 new Phase 9 tests; 36 Phase 7 baseline tests continue to pass.

### Negative / Trade-offs

* The Workflow Engine is not distributed — horizontal scaling requires Phase 12+
  (Distributed Execution) to introduce a coordinator layer over this engine.
* Phase 10 workers are not yet implemented — `report_task_success()` is called
  by the test harness/caller rather than by autonomous workers.

### Neutral

* `WorkflowTaskStatus` and Runtime's `TaskStatus` are deliberately separate.
  The engine projects its state into Runtime via the facade boundary; this
  avoids coupling the workflow engine to Runtime's internal representation.

---

## Compliance

* ✅ No new distributed infrastructure introduced.
* ✅ Deterministic-first logic for all scheduling decisions.
* ✅ Workflow Engine does NOT create a competing state store.
* ✅ HITL supported via ApprovalGate pause/resume.
* ✅ Phase 7 and Phase 8 preserved and not modified.
* ✅ ADR follows the established numbering convention (ADR-008).
