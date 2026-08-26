# PHASE 0 — FOUNDATION STABILIZATION & INTEGRATION REPORT

**Date:** 2026-08-26
**Scope:** One phase, executed in full per the Phase 0 mission brief.
**Status:** COMPLETE — all acceptance gates pass.
**Commit state:** Working tree only. **Nothing committed or pushed**, pending the independent certification pass.

---

## 1. Objective

Stabilize the existing AutoForge foundation and prove that the frozen
subsystems (Kernel v1.0, Runtime State Manager v1.0, canonical Events,
Event Platform v1.0) can be composed and exercised together in a real
process — moving from "packages that theoretically fit together" to
"packages that actually run together" — without redesigning any subsystem
and without implementing Worker/Learning/Self-Improvement/Memory/Context
Engine.

---

## 2. Changes Made

| Area | Change |
|---|---|
| Runtime | Ported `RuntimeSnapshot` onto runtime STATE models (one snapshot vocabulary); exported from package root; added `RuntimeStateManager.create_snapshot()`, `.restore_snapshot()`, `.health_check()`; added `PersistentStore/PersistenceLayer.snapshot_store()`; snapshots deeply isolated and collection-immutable (`MappingProxyType`) with a JSON-safe serializer; fixed `EventRouter` (prefix-pattern subscription + real unsubscribe); rewrote orphaned test suite against the authoritative frozen-spec API |
| Kernel | Added `health_check()` to the `RuntimeStateManager` service ABC; replaced broken `verify_connection()` call in `initialize()` |
| Canonical events | Additive extension only: `EventCategory.CHECKPOINT`, `EventType.CHECKPOINT_CREATED`, `CHECKPOINT_DELETED` (`CHECKPOINT_RESTORED` already existed). No renames/removals |
| Event Platform | New `autoforge_event_platform.adapter`: `CanonicalEventBus`, `to/from_transport_event`, `CanonicalTransportError`; round-trip envelope; wire type/category coherence from the transport's own `SchemaRegistry` |
| Models | Deprecation notices on `autoforge_models.Event` / `enums.EventType` (third vocabulary) pointing to `autoforge_events` |
| Composition | New `packages/composition` (`autoforge_composition`): `KernelRuntimeFacade`, `CanonicalKernelEventBus`, `build_autoforge_system()` composition root |
| Tests | Integration suite: smoke lifecycle, checkpoint round-trip w/ restart simulation, Kernel↔Runtime boundary incl. import-direction checks |
| Docs/ADR | ADR-001…ADR-005 + index; ROADMAP dated addendum (no restructuring); PROJECT_DASHBOARD and legacy short-form docs marked superseded/historical |

---

## 3. Event Architecture Decision

**Canonical vocabulary = `autoforge_events`. Event Platform = transport.**
Full rationale: **ADR-001**
(`docs/adr/ADR-001-canonical-event-vocabulary-and-event-platform-boundary.md`).

- `EventType` / `EventCategory` / payload contract / correlation ID /
  causation ID / event version / source / timestamp / aggregate info:
  owned by canonical frozen `BaseEvent`.
- Publication, subscription, routing, delivery, DLQ, replay: owned by
  `autoforge_event_platform`, reachable ONLY through the adapter when
  speaking canonical events.
- The platform's own `Event` model is untouched and internal; no second
  canonical model was created; `autoforge_models.Event` deprecated, not
  deleted.


## 4. Composition Root

`packages/composition/src/autoforge_composition/composition_root.py`
(`build_autoforge_system()`), documented in **ADR-002**:

- EventPlatform (transport) → CanonicalEventBus (adapter, ADR-001)
- RuntimeStateManager (authoritative state); its callbacks are lifted into
  canonical events
- KernelRuntimeFacade (Kernel's service ABC over the runtime)
- CanonicalKernelEventBus (Kernel's bus ABC over the transport)
- Kernel (orchestrator, default intake modules injected)

Real dependency injection at every seam; no hardcoded business logic; no
circular imports; subsystem responsibilities unchanged. Platform engines
(Strategic/Workflow/Execution) are deliberately NOT stubbed — they are
later-roadmap subsystems and plug into the same injection point.

## 5. Kernel ↔ Runtime Boundary

Verified through interfaces, imports and behaviour
(`packages/composition/tests/test_kernel_runtime_boundary.py`):

- Kernel depends only on its ABC; a subprocess import-check proves the
  Kernel pulls in neither `autoforge_runtime` nor `autoforge_event_platform`.
- The facade forwards requests; the RUNTIME validates/executes transitions
  (invalid requests raise from the runtime; state untouched).
- Identity preservation: Kernel-generated IDs are runtime entity IDs.
- `health_check()` fixed both sides of the former C1 contract break.
- Dependency direction: Runtime independent of Kernel/Events/Transport;
  Events standalone; adapter is the only events←platform edge.

## 6. Event Platform Boundary

Enforced chain: Domain subsystem → canonical contract (`autoforge_events`)
→ canonical adapter (single sanctioned bridge) → Event Platform transport
(routing/delivery/DLQ/replay). Subscribers receive reconstructed CANONICAL
events only; unmappable types fail loudly (`CanonicalTransportError`);
round-trip fidelity verified by tests.

## 7. Checkpoint Round-Trip

`packages/composition/tests/test_checkpoint_round_trip.py`, real runtime
components via the composition root: create state (Kernel request) →
transitions (planning→running with runtime preconditions) → checkpoint →
post-checkpoint mutation → full runtime serialization out-of-process
("failure") → fresh `RuntimeStateManager` revives from snapshot →
`restore_checkpoint()` → integrity assertions:

- persistence + revival of project/task/checkpoint entities,
- exact state-version restoration, identity preservation,
- transition history recorded (`created→planning→running`),
- `checkpoint.created` / `checkpoint.restored` observed as canonical
  events on the transport,
- idempotency: double restore rejected (`InvalidStateError`), state
  provably unchanged after rejection.

## 8. Context Engineering Contract

**ADR-003** — contract only, zero implementation. The future Context Engine
gathers candidates, scores/selects relevance, removes redundancy, respects
token budgets, preserves critical errors, tracks provenance, is model-aware,
and produces structured model context. It CONSUMES Knowledge/Memory/
Repository-Intelligence/tool observations/runtime state/git/test-output
capabilities and MUST NOT own retrieval infrastructure, trust scoring,
memory storage/retention, repository state, runtime state or models.

## 9. Engineering Experience Contract

**ADR-004** — read-oriented, provenance-aware, correlation-aware,
export-friendly composition of an engineering trajectory (Task → … →
Metrics) built from canonical events, runtime history, checkpoints,
artifacts/execution records, test results, failure records, metrics.
Runtime does NOT own it; no trajectory database created; no training
pipeline exists.

## 10. Memory vs Learning Boundary

**ADR-005** — amendment without rewriting frozen specs:

| Concept | Definition |
|---|---|
| Memory | preserves and recalls experience/context |
| Learning | extracts patterns and changes future behaviour |
| Model Training | changes model parameters |
| Self-Improvement | adopts measurable improvements via the gated pipeline |

Memory Platform stays responsible for memory only; the future Learning

## 11. Tests Executed

| Suite | Result |
|---|---|
| `packages/kernel/tests` | **100 passed**, 93 warnings, 0 failed/skipped/errors |
| `packages/runtime/tests` | **36 passed**, 88 warnings (was: collection ERROR) |
| `packages/events/tests` | **228 passed** (no regression after additive extension) |
| `packages/event_platform/tests` | **56 passed** (no regression) |
| root `tests/models` | **80 passed**, 107 warnings |
| `packages/composition/tests` | **11 passed** (new integration suite) |
| `autoforge_knowledge_platform` | import gate OK (no test suite exists — pre-existing gap) |

Totals: **511 passed / 0 failed / 0 skipped / 0 errors** across all runnable
suites. Warnings are pre-existing Pydantic v2 `json_encoders` deprecations.

## 12. Integration Results

- Composition-root smoke test PASS: user request → Kernel → runtime state
  (planning, version ≥2) → canonical `project.created` observed through the
  transport by a subscriber → clean shutdown (`kernel.stopped`).
- Checkpoint round-trip incl. restart simulation: PASS (§7).
- Kernel↔Runtime boundary tests: PASS (4/4).
- Canonical↔transport integration: PASS (delivery, fidelity, loud failure on
  unmappable types, checkpoint event flow).
- Import validation: `autoforge_kernel`, `autoforge_runtime`,
  `autoforge_events`, `autoforge_event_platform`, `autoforge_models`,
  `autoforge_knowledge_platform`, `autoforge_composition` — ALL OK.

## 13. Architecture Verification

- No circular dependencies introduced (subprocess import-direction checks:
  kernel-clean PASS, runtime-independent PASS, events-standalone PASS).
- No duplicate canonical event model introduced (platform model untouched;
  adapter is translation-only).
- Kernel remains orchestrator; Runtime remains state authority; Event
  Platform remains transport.
- No Memory ownership leakage; no Learning implementation; no Worker
  implementation; no Context Platform duplication.

## 14. Files Changed

Modified:

```
architecture/ROADMAP.md                      docs/PROJECT_DASHBOARD.md
docs/adr/ADR.md                              docs/subsystems/EVENT_BUS.md
docs/subsystems/MEMORY_ENGINE.md             docs/subsystems/STATE_MANAGER.md
packages/events/src/autoforge_events/event_types.py
packages/kernel/src/autoforge_kernel/interfaces.py
packages/kernel/src/autoforge_kernel/kernel.py
packages/models/src/autoforge_models/event.py
packages/runtime/src/autoforge_runtime/__init__.py
packages/runtime/src/autoforge_runtime/event_publisher.py
packages/runtime/src/autoforge_runtime/persistence.py

## 15. Known Remaining Gaps

1. Pydantic v2 `json_encoders` deprecation warnings (~90/run) — pre-existing
   TECH-001/002; removal belongs to the Pydantic v3 migration.
2. Durable persistence: the runtime store remains in-memory by design;
   durable adapters belong to later roadmap phases (the Persistence package
   exists but is intentionally not wired here).
3. Domain `Checkpoint.execution_session_id` temporarily carries the project
   ID at the facade seam (documented in ADR-002) until an ExecutionSession
   aggregate exists on the runtime side.
4. Knowledge Platform still has no test suite of its own (pre-existing);
   Phase 0 verified importability only, per "must not regress".
5. Internal runtime diagnostics (`snapshot.*`) are observable on the
   runtime's own publisher rather than being force-fitted into the canonical
   vocabulary.
6. Environment note: editable installs live in Homebrew Python 3.14
   site-packages (`python3 -m pip install -e <pkg> --break-system-packages`);
   the bare `pip` points at a different framework interpreter.

## 16. Scope-Discipline Confirmation

Explicitly confirmed — **NO implementation work was performed** on:

- [x] Autonomous Worker
- [x] Learning Engine
- [x] Self-Improvement Engine
- [x] Context Engine implementation (contract ADR only)
- [x] Memory Platform implementation (boundary ADR only)
- [x] Benchmark Platform / Model Training / LoRA / trajectory pipeline
- [x] Production distributed infrastructure / cloud / security /
      observability platforms

Roadmap structure untouched (dated addendum only). Frozen subsystem specs
untouched (Memory boundary recorded as ADR-005 interpretation amendment).
Nothing committed or pushed — awaiting independent certification.

---

*End of Phase 0 implementation report.*

packages/runtime/src/autoforge_runtime/snapshots.py
packages/runtime/src/autoforge_runtime/state_manager.py
packages/runtime/tests/test_state_manager.py
```

New:

```
docs/PHASE_0_FOUNDATION_STABILIZATION_REPORT.md  (this file)
docs/adr/ADR-001…ADR-005 (five ADR files)
packages/composition/  (pyproject, README, src/, tests/)
packages/event_platform/src/autoforge_event_platform/adapter/
```

Git diff reviewed file-by-file: no accidental changes, no unrelated
refactors, no generated junk, no secrets, no speculative infrastructure.

Engine owns learning; the Kernel coordinates but never learns.
