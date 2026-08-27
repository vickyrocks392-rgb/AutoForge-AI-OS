# ADR-011: Artifact Platform — Phase 12

## Status

**Accepted** — Phase 12

## Date

2026-08-28

## Context

Phases 10 (Execution) and 11 (Review) produce engineering artifacts — code, diffs, test reports, review findings, repair plans. Phase 10's `ArtifactPipeline` captures execution-side artifacts in memory with basic provenance; Phase 11 consumes but does not store artifacts independently.

Neither phase provides canonical lifecycle management: versioning, lineage, publishing, rollback, or cross-phase traceability. Engineering output lacks formal version history, integrity verification, and governed publication.

The Artifact Platform (Phase 12) formalizes these capabilities as a single canonical platform, consistent with PRINCIPLES.md:
- **Separation of Concerns** — Artifact Platform owns the artifact lifecycle domain.
- **Transparency by Default** — every artifact version, lineage edge, and publication is logged.
- **Humans in the Loop** — consequential actions (publish, rollback) are HITL-gated.

## Decision

### 1. Module Decomposition

The Artifact Platform is a single package (`autoforge-artifacts`) with focused modules:

| Module | Responsibility |
|--------|---------------|
| `models.py` | Domain models: Artifact, ArtifactVersion, CanonicalProvenance, lineage/publication/rollback records |
| `errors.py` | Error taxonomy (8 distinct error types) |
| `store.py` | Storage protocol + LocalArtifactStore (in-memory) |
| `versioning.py` | Immutable version creation, parent chain, history |
| `lineage.py` | Parent→child derivation graph (BFS traversal) |
| `provenance.py` | Provenance assembly + Phase 10 adapter |
| `publishing.py` | Controlled publication with HITL policy |
| `rollback.py` | History-preserving rollback |
| `events.py` | Canonical event emission (frozen vocabulary) |
| `policies.py` | Deterministic governance policies |
| `engine.py` | ArtifactManager facade + platform construction |

### 2. Versioning Model

- **Immutable versions**: content changes produce new versions; existing versions are never mutated.
- **Content identity**: SHA-256 content hashing; identical content produces identical hashes.
- **Monotonic numbering**: version numbers increment (1, 2, 3, …) per artifact.
- **Parent chain**: explicit `parent_version_id` linking versions for traversal.

### 3. Lineage Representation

- In-memory adjacency list (not a graph database).
- BFS traversal for transitive ancestors/descendants.
- Each `ArtifactLineageEntry` captures parent artifact, child artifact, transformation type, actor, and execution/correlation context.

### 4. Storage Abstraction

- `ArtifactStoreProtocol` — minimal protocol for storage backends.
- `LocalArtifactStore` — thread-safe in-memory implementation.
- Content integrity verification by SHA-256 recomputation.
- No cloud dependencies.

### 5. HITL Governance

- Publication and rollback are policy-gated.
- `PublicationPolicy` and `RollbackPolicy` define which operations require HITL.
- Default: DEPLOYMENT artifacts and production/release destinations require HITL.
- Compatible with Phase 9 `ApprovalGate` pattern.

### 6. Rollback Model

- History-preserving: rollback creates a new version with the target's content.
- The version chain is never broken: v1 → v2 → v3 → rollback-to-v2 (v4).
- Rollback validates target existence, ownership, and integrity before proceeding.

### 7. Event Integration

- Uses frozen `autoforge_events` vocabulary ONLY: `ARTIFACT_CREATED`, `ARTIFACT_UPDATED`.
- No new event types are introduced.
- Event emission failures never break artifact operations (safe publish).

### 8. Relationship to Phase 10/11

- Phase 10's `ArtifactRecord` is the execution-time producer; the canonical Artifact Platform is the consumer/store.
- `from_execution_provenance()` adapter converts Phase 10 `ArtifactProvenance` to `CanonicalProvenance`.
- Phase 10/11 code is NOT modified; adapters live at the composition boundary.

## Consequences

- All engineering artifacts have a single canonical store with formal lifecycle management.
- Version history enables rollback without history loss.
- Lineage enables traceability from research to deployment.
- Publication requires explicit action; consequential actions require HITL.
- The platform works locally with zero external infrastructure.

## Alternatives Considered

1. **Extend Phase 10's ArtifactPipeline directly** — Rejected: ArtifactPipeline is execution-scoped and lives inside the execution package. Extending it would violate Separation of Concerns and create a bidirectional dependency.

2. **Use a database backend** — Rejected: violates the "local-first, no external infrastructure" constraint. The in-memory LocalArtifactStore is sufficient for Phase 12; database backends can be added later as alternative `ArtifactStoreProtocol` implementations.

3. **Automatic publication** — Rejected: violates HITL governance principle. Publication is always explicit.
