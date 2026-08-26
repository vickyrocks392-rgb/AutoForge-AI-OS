# State Manager

> **⚠️ LEGACY / SUPERSEDED (2026-08-26):** This short-form document is superseded by the frozen **Runtime State Manager Specification v1.0** (`docs/subsystems/RUNTIME_STATE_MANAGER_SPECIFICATION.md`), implemented by `packages/runtime` (`autoforge_runtime`). Composition with the Kernel is defined in **`docs/adr/ADR-002`**. Retained for history only.

## Purpose

This document defines the state manager — the component responsible for maintaining the authoritative, consistent state of all execution entities within the AutoForge AI platform. The state manager ensures that every component has access to the current state of tasks, projects, workflows, and agents, and that state transitions are atomic, consistent, and auditable.

## Scope

This document covers the state model, state storage architecture, consistency guarantees, and query patterns. It does not cover checkpointing (persistence for recovery) or event management — those concerns are addressed in their respective documents.

---

## Overview

The state manager is the single source of truth for the current state of the execution system. Every component — the scheduler, the execution engine, the checkpoint manager, the event bus — reads from and writes to the state manager. It provides a consistent view of the system at any point in time.

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│  Scheduler   │    │  Execution   │    │  Checkpoint  │
│              │    │  Engine      │    │  Manager     │
└──────┬───────┘    └──────┬───────┘    └──────┬───────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼───────┐
                    │    State     │
                    │   Manager    │
                    │              │
                    │  ┌────────┐  │
                    │  │ Cache  │  │
                    │  └───┬────┘  │
                    │      │       │
                    │  ┌───▼────┐  │
                    │  │  DB    │  │
                    │  └────────┘  │
                    └──────────────┘
```

## State Entities

The state manager maintains state for the following entities:

### Project State
| Field | Description |
|---|---|
| `projectId` | Unique identifier |
| `status` | Current project status (created, running, paused, finished, failed, cancelled) |
| `taskGraphId` | Reference to the current task graph version |
| `taskCount` | Total number of tasks in the project |
| `completedCount` | Number of completed tasks |
| `failedCount` | Number of failed tasks |
| `runningCount` | Number of currently running tasks |
| `progress` | Overall progress percentage |
| `currentCheckpointId` | Most recent checkpoint |
| `startedAt` | When execution started |
| `estimatedDuration` | Estimated total duration |
| `actualDuration` | Actual elapsed duration |

### Task State
The task state mirrors the Task Model (see TASK_MODEL.md) with the addition of runtime fields:

| Field | Description |
|---|---|
| `status` | Current task status |
| `assignedWorker` | Which worker slot is executing this task |
| `assignedModel` | Which LLM model is being used |
| `currentRetryCount` | Current retry attempt |
| `lastHeartbeat` | Timestamp of last progress signal from the agent |
| `stateHash` | Hash of the task's current state for change detection |

### Worker State
| Field | Description |
|---|---|
| `workerId` | Unique identifier |
| `status` | idle, busy, draining, offline |
| `currentTaskId` | Task currently being executed (if busy) |
| `assignedModel` | Model assigned to this worker |
| `startedAt` | When the worker became active |
| `taskCount` | Number of tasks completed by this worker |
| `totalCost` | Total token cost incurred by this worker |

### Queue State
| Field | Description |
|---|---|
| `queueType` | ready, priority, retry, blocked, approval |
| `depth` | Number of tasks in the queue |
| `oldestTaskAge` | How long the oldest task has been waiting |
| `tasks` | Ordered list of task IDs in the queue |

## Consistency Model

### Read-Your-Writes
After a component writes a state update, it is guaranteed to read that update on subsequent reads. This ensures that components can safely read their own writes without race conditions.

### Atomic State Transitions
All state transitions are atomic. A task cannot be in both `running` and `completed` states simultaneously. State transitions use optimistic concurrency control with version numbers.

### Eventual Consistency Across Components
While the state manager provides strong consistency for individual entities, different components may see slightly different views of the overall system state at any instant. The event bus provides the ordering mechanism to reconcile these views.

## Storage Architecture

### Cache Layer
An in-memory cache (Redis) provides low-latency access to frequently accessed state:

- Current task statuses
- Queue states
- Worker states
- Project progress

### Persistent Layer
A relational database (PostgreSQL) provides durable storage:

- Complete task records with audit trails
- Project records
- Historical state snapshots
- Worker history

### Read Path
1. Component requests state
2. State manager checks cache
3. If cache miss, reads from database
4. Returns state to component
5. Optionally updates cache

### Write Path
1. Component submits state transition
2. State manager validates transition rules
3. Writes to database (durable)
4. Updates cache (fast)
5. Publishes state change event to event bus
6. Returns confirmation to component

## Query Patterns

The state manager supports the following query patterns:

- **Get by ID** — Retrieve a single entity by its identifier
- **Get by status** — Retrieve all entities with a given status (e.g., all running tasks)
- **Get by project** — Retrieve all tasks for a given project
- **Get by owner** — Retrieve all tasks assigned to a given agent service
- **Get by dependency** — Retrieve all tasks that depend on a given task
- **Aggregation** — Count tasks by status, calculate project progress, compute average task duration

## Future Implementation Notes

- The state manager should support subscription-based queries where components are notified of state changes without polling
- State schemas should be versioned to support migration
- The state manager should expose health check endpoints for monitoring
- Read replicas should be supported for scaling read-heavy workloads

## Open Questions

- Should the state manager support multi-tenant isolation at the storage level?
- How should the state manager handle conflicts when two components attempt to update the same entity simultaneously?
- Should the state manager support time-travel queries (what was the state at time T)?
- What is the acceptable latency for state reads and writes?
- Should the state manager support soft deletes or hard deletes for completed projects?