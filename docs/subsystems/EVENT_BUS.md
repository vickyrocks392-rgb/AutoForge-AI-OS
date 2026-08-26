# Event Bus

> **⚠️ LEGACY / SUPERSEDED-IN-PART (2026-08-26):** This short-form document predates the frozen subsystem specifications and is retained for history. For the authoritative event architecture see **`docs/subsystems/EVENT_PLATFORM_SPECIFICATION.md`** (Event Platform v1.0 — transport) and **`packages/events`** (`autoforge_events` — canonical vocabulary), unified per **`docs/adr/ADR-001`**. Where this document disagrees with those, they win.

> **Note:** This document is consistent with Architecture v1.0 (`architecture/ARCHITECTURE.md`). The Event Bus is a Shared Platform Service that provides the publish-subscribe infrastructure routing events from producers to consumers. It decouples subsystems by enabling asynchronous communication without direct references. The Canonical Event Model defines the schema-enforced, versioned structure that every event must conform to.

## Purpose

This document defines the event bus — the Shared Platform Service that serves as the communication backbone of the AutoForge AI execution architecture. The event bus enables decoupled, asynchronous communication between all components of the execution system, providing a single source of truth for what happened, when, and why.

## Scope

This document covers the event model, event types, publishing and subscription patterns, and delivery guarantees. It does not cover specific event bus implementations (in-memory, NATS, RabbitMQ, Kafka) — those are deployment decisions. The canonical specification for the Event Bus and Canonical Event Model is in `architecture/ARCHITECTURE.md` Section 20.

---

## Overview

The event bus is the nervous system of the execution architecture. Every significant occurrence in the system — a task starting, a checkpoint being saved, a failure being detected — is published as an event. Components subscribe to the events they care about and react accordingly.

```
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│  Scheduler  │     │State Manager│     │  Checkpoint │
│             │     │             │     │   Manager   │
└──────┬──────┘     └──────┬──────┘     └──────┬──────┘
       │                   │                   │
       └───────────────────┼───────────────────┘
                           │
                    ┌──────▼──────┐
                    │  Event Bus  │
                    └──────┬──────┘
                           │
       ┌───────────────────┼───────────────────┐
       │                   │                   │
┌──────▼──────┐     ┌──────▼──────┐     ┌──────▼──────┐
│    Model    │     │   Failure   │     │    Audit    │
│   Router    │     │  Recovery   │     │    Log      │
└─────────────┘     └─────────────┘     └─────────────┘
```

## Event Model

Every event in the system has the following structure:

| Field | Type | Description |
|---|---|---|
| `eventId` | UUID | Globally unique identifier for the event |
| `eventType` | String | The type of event (see event catalog below) |
| `source` | String | The component that produced the event |
| `timestamp` | Timestamp | When the event occurred (UTC, nanosecond precision) |
| `version` | Integer | Event schema version for backward compatibility |
| `correlationId` | UUID | Identifier for correlating related events across the system |
| `causationId` | UUID | Identifier of the event that caused this event |
| `projectId` | UUID | The project this event relates to |
| `workflowId` | UUID | The workflow execution this event relates to |
| `taskId` | UUID | The task this event relates to (if applicable) |
| `payload` | JSON | Event-specific data |
| `metadata` | JSON | Additional metadata (environment, version, etc.) |

## Event Catalog

### Project Lifecycle Events

| Event | Trigger | Payload |
|---|---|---|
| `project.created` | New project created | projectId, title, config |
| `project.started` | Execution begins | projectId, taskGraphId |
| `project.paused` | Execution paused by user or system | projectId, reason |
| `project.resumed` | Execution resumes from pause | projectId, checkpointId |
| `project.finished` | All tasks completed successfully | projectId, summary, duration |
| `project.failed` | Project terminated due to unrecoverable error | projectId, error, failedTasks |
| `project.cancelled` | Project cancelled by user | projectId, reason |

### Task Lifecycle Events

| Event | Trigger | Payload |
|---|---|---|
| `task.created` | Task added to task graph | taskId, title, owner, priority |
| `task.queued` | Task ready for scheduling | taskId, dependencies |
| `task.assigned` | Task assigned to agent service | taskId, agent, model |
| `task.started` | Agent begins execution | taskId, input, estimatedCost |
| `task.completed` | Agent returns successful result | taskId, output, actualCost, duration |
| `task.failed` | Agent returns error | taskId, errorCode, errorMessage, recoverable |
| `task.retrying` | System retrying failed task | taskId, retryCount, maxRetries, backoff |
| `task.cancelled` | Task cancelled before completion | taskId, reason |
| `task.blocked` | Task blocked by dependency failure | taskId, blockedBy |
| `task.waiting` | Task waiting for external input | taskId, waitType (approval, api, user) |
| `task.review` | Task awaiting human review | taskId, output, confidence |

### Checkpoint Events

| Event | Trigger | Payload |
|---|---|---|
| `checkpoint.saved` | Checkpoint persisted successfully | checkpointId, taskId, stateHash |
| `checkpoint.restored` | System restored from checkpoint | checkpointId, taskId, restoredState |
| `checkpoint.failed` | Checkpoint save failed | checkpointId, taskId, error |

### Execution Events

| Event | Trigger | Payload |
|---|---|---|
| `execution.paused` | Execution paused | reason, pausedTasks |
| `execution.resumed` | Execution resumed | checkpointId, resumedTasks |
| `execution.interrupted` | Unexpected shutdown detected | lastCheckpointId, runningTasks |
| `execution.recovered` | System recovered after interruption | checkpointId, recoveredTasks |

### Deployment Events

| Event | Trigger | Payload |
|---|---|---|
| `deployment.started` | Deployment begins | projectId, target, config |
| `deployment.finished` | Deployment completed | projectId, url, status |
| `deployment.failed` | Deployment failed | projectId, error |

### Documentation Events

| Event | Trigger | Payload |
|---|---|---|
| `documentation.generated` | Documentation produced | projectId, docTypes, artifactRefs |

## Delivery Guarantees

### At-Least-Once Delivery
Every event is delivered at least once to all subscribers. Duplicate events are possible and must be handled idempotently by subscribers.

### Ordered Delivery per Task
Events for a given task are delivered in the order they were produced. Events for different tasks have no ordering guarantees.

### Persistent Storage
All events are persisted to durable storage. The event log is append-only and immutable. Events are retained according to configurable retention policies.

## Subscription Model

Components subscribe to events using a topic-based subscription model:

- **Exact match** — Subscribe to a specific event type (e.g., `task.completed`)
- **Wildcard** — Subscribe to a category of events (e.g., `task.*` for all task events)
- **Multi-topic** — Subscribe to multiple specific event types

## Event Sourcing

The event log serves as the source of truth for the system's state. The current state of any entity (task, project, workflow) can be reconstructed by replaying its events from the beginning of the log. This enables:

- **Audit** — Complete history of every change
- **Debugging** — Replay execution to reproduce issues
- **Recovery** — Rebuild state after data loss
- **Analysis** — Query historical event patterns

## Future Implementation Notes

- The event bus should support backpressure to prevent fast producers from overwhelming slow consumers
- Event schemas should be versioned and validated at publish time
- Dead-letter queues should capture events that cannot be delivered or processed
- The event log should support time-based and size-based retention policies
- Event bus implementations should be swappable via a common interface

## Open Questions

- Should the event bus support event transformation (enrichment, filtering) between producer and consumer?
- How should the system handle events that are published but never consumed (orphan events)?
- Should there be a separate high-priority event channel for critical events (failures, checkpoints)?
- What is the acceptable latency between event publication and consumption?
- Should the event bus support event replay from a specific point in time?