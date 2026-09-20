# AutoForge Runtime State & Durability Platform

## Purpose

The AutoForge Runtime provides the authoritative durable persistence, lifecycle state machine, execution identity, and recovery subsystem for AutoForge AI.

As certified in Phase 18-J and production-hardened in Phase 18-K, the Runtime is backed by a transactional SQLite WAL architecture via `PersistenceLayer`. It establishes the single source of truth across process crashes, restarts, and retries.

## Architectural Components

### 1. Persistence Layer (`PersistenceLayer`, `SQLiteStorage`)
- Backed by SQLite WAL mode (`PRAGMA journal_mode=WAL`, `PRAGMA synchronous=NORMAL`, `busy_timeout=30000ms`).
- Immediate transactions (`BEGIN IMMEDIATE`) preventing deadlocks under cross-thread and cross-process concurrency.
- Monotonic `state_version` for Optimistic Concurrency Control (OCC).
- Indexed expression queries (`query_entities`) across entity JSON payloads.
- Append-only audit history (`runtime_history`).

### 2. Durable Execution Store (`DurableExecutionStore`)
- Phase 18-J.2 canonical execution identity derived deterministically via UUID5 from `(workflow_id, task_id)`.
- Monotonic attempt tracking (`1..N`) for workflow task retries.
- Checkpoint boundaries committed prior to external worker dispatch.

### 3. Durable Workflow Store & Reconstruction (`DurableWorkflowStore`, `WorkflowReconstructor`)
- Phase 18-J.3 deterministic state reconstruction and resume after OS crash or process death.
- Reconstructs DAG execution status, ready tasks, and in-flight queue entries from durable SQLite records.

### 4. Durable Idempotency & Side-Effect Safety (`DurableIdempotencyStore`, `SideEffectExecutor`)
- Phase 18-J.4 idempotent operation claims (`ACQUIRED -> RUNNING -> COMPLETED / FAILED / ABORTED`).
- Request fingerprinting and duplicate side-effect suppression.

### 5. Durable Human-in-the-Loop (HITL) Approvals (`DurableApprovalStore`)
- Phase 18-J.5 durable approval requests (`REQUESTED -> PENDING -> APPROVED / REJECTED / CANCELLED / EXPIRED`).
- Crash-safe timeout detection and deterministic resume upon human decision.

### 6. Durable Artifact Catalog & Physical Store (`DurableArtifactCatalog`, `PhysicalArtifactStore`)
- Phase 18-K production durability authority for all system artifacts.
- Two-phase staging and atomic publish protocol (`CREATED -> STAGING -> COMMITTED -> RETIRED`).
- Physical filesystem boundary enforcement with path traversal protection, atomic rename, and directory fsync.
- Strict SHA-256 and size verification: `COMMITTED` state is never permitted without valid physical existence and matching cryptographic fingerprint.
- Conservative recovery policy: Startup reconciliation validates process liveness before acting on abandoned records.

## Usage

```python
from pathlib import Path
from autoforge_runtime import (
    PersistenceLayer,
    DurableArtifactCatalog,
    PhysicalArtifactStore,
    derive_artifact_key,
)

# 1. Initialize durable storage
persistence = PersistenceLayer(db_path="/path/to/project/.autoforge/state.db")
physical_store = PhysicalArtifactStore(artifact_root=Path("/path/to/artifacts"))
catalog = DurableArtifactCatalog(persistence=persistence, physical_store=physical_store)

# 2. Register artifact (CREATED state)
key = derive_artifact_key(artifact_name="output.json", task_id="build_step")
artifact = catalog.register_artifact(artifact_key=key, artifact_name="output.json")

# 3. Stage and write physical content
staging_path = physical_store.create_staging_file(key)
catalog.begin_staging(artifact.artifact_id, staging_path=str(staging_path))
content_hash, size_bytes = physical_store.write_staging_text(staging_path, '{"success": true}')

# 4. Atomically publish and commit to durable catalog
published_path = physical_store.atomic_publish(staging_path, "output.json")
committed = catalog.commit_artifact(
    artifact.artifact_id,
    storage_path=str(published_path),
    content_hash=content_hash,
    size_bytes=size_bytes,
)
```