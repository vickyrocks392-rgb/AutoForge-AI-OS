# ADR-002: Composition Root and Kernel-Runtime Boundary

**Date:** 2026-08-26

**Status:** Accepted

---

#### Context

Every AutoForge package existed independently: the Kernel's factory accepted
injected services, but no composition root ever constructed RuntimeStateManager,
an event bus, and the Kernel together in one real process. All cross-package
behaviour had only ever been exercised through mocks.

Additionally, two boundary defects were verified:

- `Kernel.initialize()` called `runtime_state_manager.verify_connection()` —
  a method defined on neither the Kernel's ABC nor the real Runtime (the
  "C1" contract break; it failed the Kernel lifecycle test).
- `runtime/snapshots.py` defined `RuntimeSnapshot` over DOMAIN models while
  `RuntimeStateManager` owns runtime STATE models — two vocabularies for one
  world ("C2"), with the snapshot module exported to nothing and blocking
  test collection.

---

#### Decision

1. **Composition root** — new package `packages/composition`
   (`autoforge_composition`) is the single place where the platform is
   instantiated and wired with real dependency injection:

   ```
   EventPlatform (transport)
     -> CanonicalEventBus        (ADR-001 adapter)
     -> RuntimeStateManager      (authoritative runtime state)
     -> KernelRuntimeFacade      (Kernel's service ABC over the runtime)
     -> CanonicalKernelEventBus  (Kernel's bus ABC over the transport)
     -> Kernel                   (orchestrator)
   ```

   It contains no business logic, creates no new ownership, and never lets a
   subsystem construct another.

2. **Runtime facade** (`KernelRuntimeFacade`) implements the Kernel's
   `RuntimeStateManager` ABC by delegating to the real runtime:
   - Identity-preserving: Kernel-generated Project/Task IDs become runtime
     state entity IDs.
   - Transition requests are validated and executed BY the runtime's
     transition engine; the facade adds nothing.
   - Domain↔state translation is mechanical only. Documented compromise:
     domain `Checkpoint.execution_session_id` temporarily carries the
     project ID (mirrored in metadata) until an ExecutionSession aggregate
     exists on the runtime side.
   - `health_check()` delegates to the runtime's own report.

3. **Kernel-Runtime contract fix (C1)**: `health_check()` was ADDED to both
   the Kernel's `RuntimeStateManager` ABC and
   `autoforge_runtime.RuntimeStateManager`; `initialize()` now calls
   `health_check()`. The previously failing lifecycle test passes unchanged
   against the corrected contract.

4. **Snapshot unification (C2)**: `RuntimeSnapshot` was PORTED onto state
   models (one vocabulary) and is now exported from `autoforge_runtime`.
   `RuntimeStateManager` gained `create_snapshot()` / `restore_snapshot()`;
   snapshots are deeply isolated and collection-immutable
   (`MappingProxyType`). The orphaned domain-model test file was rewritten to
   validate the authoritative frozen-spec API (36 tests).

5. **Platform engines are NOT stubbed.** Strategic/Workflow/Execution engines
   are later-roadmap subsystems. The composition wires the Kernel with its
   own default intake modules so request intake → state creation → lifecycle
   coordination runs for real today; engines plug into the same injection
   point when implemented.

---

#### Consequences

Positive:

- The platform composes and RUNS: proven by integration tests including the
  authoritative smoke test and the cross-restart checkpoint round-trip.
- Dependency direction is enforced and test-verified: Kernel imports neither
  the runtime implementation nor the transport; Runtime imports neither
  Kernel nor events nor transport.

Negative / limitations:

- The facade is intentionally thin; Kernel capabilities that need missing
  engines remain unavailable until those subsystems are built (by design).
- Snapshot durability across processes relies on serialization of the
  in-memory persistence layer; durable stores remain future work.

---

#### Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Let the Kernel import `autoforge_runtime` directly | Inverts dependency direction; couples orchestrator to implementation |
| Port the async/domain-model test API into the runtime instead | Would create a second state vocabulary inside the manager; contradicts frozen spec |
| Stub Strategic/Workflow/Execution engines in the composition root | Fabricates fake capability; violates no-scope-creep and honest-substrate principles |
| Delete snapshots.py entirely (audit D1-b) | Phase 0 required restoring the snapshot contract without weakening tests; porting (D1-a) preserves more value |
