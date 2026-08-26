# AUTOFORGE AI — CURRENT-STATE RECONCILIATION & AUTONOMOUS WORKER ARCHITECTURE AUDIT

**Audit date:** 2026-08-24
**Audited commit:** `22b42d0` (`main`, HEAD)
**Scope:** Full-repository reconciliation against the *Local-First Autonomous Technical Worker* direction.
**Method:** Direct source inspection, live test execution, dependency/import analysis. Every claim below is tagged:

| Tag | Meaning |
|---|---|
| **VERIFIED** | Confirmed by reading source or executing code/tests |
| **INFERRED** | Strongly indicated by code/docs but not executed |
| **MISSING** | Required capability absent from repository |
| **UNKNOWN** | Could not be determined within this audit |

> **This document is an audit. No implementation accompanied it.** All recommendations are proposals pending the decisions listed in §28.

---

# 1. Executive Summary

AutoForge AI today is **not** an autonomous engineering platform yet. It is a **well-architected foundation of six implemented Python packages** (Kernel, Runtime State Manager, Events, Event Platform, Models, Knowledge Platform) plus one partially installable package (Persistence), surrounded by **documentation-only scaffolding** from an earlier TypeScript-era plan that no longer matches reality.

**What genuinely exists and is worth keeping (VERIFIED):**

- A **Kernel** (`packages/kernel`, 13 modules, ~5,000 LOC) implementing request intake → intent analysis → planning coordination → orchestration → approval → completion → recovery → lifecycle, with clean ABC-based boundaries and DI. Its own certification audit (`packages/kernel/CERTIFICATION_AUDIT_REPORT.md`) found it **NOT CERTIFIED**; several findings have since been fixed (version bump, review-engine stub), but most remain.
- A **Runtime State Manager** (`packages/runtime`, 17 modules) with state machines, transition validation, concurrency control, checkpoints, query engine, and an in-memory persistence layer. Its test suite currently **cannot even be collected** due to a missing `RuntimeSnapshot` export.
- **Domain events** (`packages/events`) — frozen Pydantic `BaseEvent` with `event_id/correlation_id/causation_id/aggregate_id/version/metadata`, ~90 typed dot-notation event types, 228 passing tests.
- An **Event Platform** (`packages/event_platform`, ~30 modules) — full bus with routing, filtering, priority queues, DLQ, schema registry, replay/correlation engines, 56 passing tests — **but nothing in the repo integrates with it** (zero external importers).
- **Canonical domain models** (`packages/models`, 14 models / 12 enums, 80 passing tests via root `tests/models`).
- A large **Knowledge Platform** (`packages/knowledge_platform`, 74 modules across retrieval/fusion/trust/citation/research/context/connectors) — including a knowledge-scoped `ContextAssembler`, weighted relevance ranking, deduplication, provenance tracking — **with zero tests and no composition root** (it is never instantiated anywhere).

**What does NOT exist (VERIFIED MISSING):** any model provider/runtime (no Ollama, no `ModelProvider` implementation), any tool runtime (`packages/tools` is a README), any memory implementation (`packages/memory` is a README despite a frozen 4,432-line Memory Platform Specification v1.0), any repository intelligence/indexing, any general-purpose context engine, any worker abstraction, any verification/evidence subsystem, and any durable storage (Runtime "PersistentStore" is plain dicts).

**The three structural problems that must be resolved before new subsystems are built:**

1. **Three parallel event vocabularies** (§10): `autoforge_events.EventType` (dot-notation, canonical, used by Kernel), `autoforge_event_platform.models.event.EventType` (its own enum + Event model, used by nothing outside itself), and `autoforge_models.Event` + `enums.EventType` (a third, weaker vocabulary). Building the Autonomous Worker on top of this without unification would hard-wire the duplication forever.
2. **Two parallel state vocabularies**: domain models (`Project`, `Task`…) vs runtime state models (`ProjectState`, `TaskState`…). `runtime/snapshots.py` snapshots the *domain* models while `state_manager.py` manages *runtime state* models — and `snapshots.py` is imported by **nothing except its own test**, which currently fails to import.
3. **No wiring layer exists.** The Kernel's factory accepts injected services, but there is no composition root that constructs RuntimeStateManager + an EventBus + engines together. Every integration test passes only via mocks. The platform has never been run end-to-end.

**Reconciliation verdict:** the KEEP→EXTEND strategy holds. Roughly 80% of existing code survives: events/models/runtime/knowledge/event-platform are KEEP or EXTEND; the Kernel needs REFACTOR (logging, exception handling, timeouts, contract fixes); `models/event.py` and the TypeScript-era root scaffolding are DEPRECATE candidates. The Context Engineering Engine should be a **new small subsystem** that *consumes* the Knowledge Platform's assembler rather than duplicating it (§14). The first 10 tasks (§24) are all stabilization/unification work inside Phase 0 — none of them start the Worker.

---

# 2. Current Architecture

```
                        ┌─────────────────────────────────────────────┐
                        │                  KERNEL                     │
                        │  (autoforge_kernel — coordinator only)      │
                        │                                             │
                        │  request_intake → intent_analysis (rules)   │
                        │  planning_coordination → orchestration      │
                        │  approval / completion / recovery           │
                        │  lifecycle / infrastructure                 │
                        └──────┬──────────────────────┬───────────────┘
              depends on ABCs  │                      │  publishes via helper
            (interfaces.py)    ▼                      ▼
   ┌─────────────────────────────────┐   ┌──────────────────────┐
   │  RUNTIME STATE MANAGER          │   │  EVENTS (canonical)  │
   │  autoforge_runtime              │   │  BaseEvent + enums   │
   │  state/transitions/validation   │   └──────────┬───────────┘
   │  checkpoints/query/concurrency  │              │ carried by EventBus ABC
   │  in-memory persistence          │              │ (NO concrete impl exists)
   └────────────┬────────────────────┘              ▼
                │                        ┌──────────────────────┐
                ▼                        │  EVENT PLATFORM      │
   ┌─────────────────────────────────┐   │  (ISLAND — zero      │
   │  MODELS (domain)                │◄──┼─ importers outside   │
   │  Project/Task/Artifact/...      │   │  itself)             │
   └─────────────────────────────────┘   └──────────────────────┘

   ┌─────────────────────────────────┐   ┌──────────────────────┐
   │  PERSISTENCE (repos/UoW protos) │   │  KNOWLEDGE PLATFORM  │
   │  not installed in env; unused   │   │  74 modules, no      │
   └─────────────────────────────────┘   │  tests, no wiring    │
                                         └──────────────────────┘
```

## 2.1 Architectural style (VERIFIED)

- **Hexagonal/ports-and-adapters inside each package**: ABCs in `interfaces.py`, implementations beside them, DI via constructors.
- **Event-driven aspiration, mock-driven reality**: Kernel publishes through `publish_event()` helper onto its own `EventBus` ABC; no concrete bus satisfies that ABC anywhere in the repo.
- **Synchronous in-memory state** everywhere. Nothing persists to disk. Nothing crosses a process boundary.
- Python ≥3.11/3.12 targets, Pydantic v2 throughout. Tests: pytest + pytest-asyncio (auto mode).

---

# 3. Current Package Inventory

| Path | Package | State | Evidence |
|---|---|---|---|
| `packages/kernel` | `autoforge_kernel` (13 modules) | Implemented; NOT certified by own audit; 99/100 tests pass, 1 fail | **VERIFIED** |
| `packages/runtime` | `autoforge_runtime` (17 modules) | Implemented; test suite fails at collection (`RuntimeSnapshot` ImportError); pyproject version 0.1.0 | **VERIFIED** |
| `packages/events` | `autoforge_events` (8 modules) | Implemented, 228 tests green; canonical domain events | **VERIFIED** |
| `packages/event_platform` | `autoforge_event_platform` (~30 modules) | Implemented, 56 tests green; **isolated island** — no external importers | **VERIFIED** |
| `packages/models` | `autoforge_models` (14 modules) | Implemented; tests live at root `tests/models` (80 green), no local tests dir | **VERIFIED** |
| `packages/persistence` | `autoforge_persistence` (9 modules) | Source complete (repositories, UoW, protocols); **not installed** → own tests fail with `ModuleNotFoundError`; no importer anywhere | **VERIFIED** |
| `packages/knowledge_platform` | `autoforge_knowledge_platform` (74 modules) | Large component library (retrieval, fusion, trust, citation, research, context, connectors, cache, validation); **zero tests**; never instantiated; standalone deps (pydantic+aiofiles only) | **VERIFIED** |
| `packages/tools` | — | README only | **VERIFIED** |
| `packages/memory` | — | README only (spec frozen v1.0 exists) | **VERIFIED** |
| `packages/workflows`, `prompts`, `execution`, `shared` | — | README only | **VERIFIED** |
| `services/*` (11 dirs) | — | README-only placeholders for an SDLC agent-service architecture | **VERIFIED** |
| `apps/web`, `apps/api` | — | README only | **VERIFIED** |
| Root TS scaffolding | `package.json`, `tsconfig.base.json`, `.nvmrc`, `docker-compose.yml` | Leftovers of planned Node stack; contradict Python reality | **VERIFIED** |

Installed in current env (homebrew Python 3.14.6, `pip3 list`): editable installs of kernel(0.1.0 — stale vs pyproject 1.0.0), runtime, events, models, event-platform. **persistence and knowledge_platform are NOT installed** (**VERIFIED** — cause of persistence test failure).

---

# 4. Existing Capabilities

## 4.1 Kernel (`autoforge_kernel`) — VERIFIED

| Capability | Status | Notes |
|---|---|---|
| Request intake/validation/normalization | Working | `Request` Pydantic model, max 10k chars |
| Intent analysis | Working but heuristic | Keyword/classifier rules in `intent_analysis.py`; no model involvement; `knowledge_engine` accepted but unused |
| Planning coordination | Interface-complete | Delegates to `StrategicEngine`/`WorkflowEngine` ABCs — **no real implementations exist anywhere** |
| Orchestration | Partially working | Coordinates loop dispatch through `ExecutionEngine` ABC (mock-only in practice) |
| Worker dispatch coordination | Present | `DefaultWorkerDispatchCoordinator` validates assignments; behind ABCs |
| Approval flow | Present | `ApprovalCoordinatorModule`, `approval.required/.decided` events, decision processing incl. modified/rejected paths |
| Completion | Mostly working | Validation → transitions to Completing/Finished; review-engine call now real (old stub fixed); still swallows review exceptions |
| Recovery | Present w/ issues | `RecoveryModuleWrapper`, failure detection, checkpoint restore path; broad `except Exception` sites |
| Lifecycle | Present | Kernel status machine (CREATED→READY→…→STOPPED), project lifecycle manager |
| Infrastructure coordination | Weak | ~19 swallowed exceptions in `infrastructure.py` health/connect operations |
| Event subscription | Partial | `_subscribe_to_events()` handles loop/task/approval/review/recovery/service events; `unsubscribe_from_events()` contains note "Event bus interface would need to support unsubscribe" — incomplete |
| `verify_connection` on startup | **BROKEN** | `kernel.py:639` awaits `runtime_state_manager.verify_connection()` — exists on **neither** the Kernel ABC nor the real runtime nor test mocks → live test failure |

## 4.2 Runtime State Manager (`autoforge_runtime`) — VERIFIED

- Entity state machines: Project/Workflow/Loop/Task/Worker/Checkpoint/Recovery with explicit transition tables and validation functions.
- `ConcurrencyController`, `CheckpointManager` (Creator/Restorer/Cleaner roles), `QueryEngine` (parse/filter/aggregate), `RecoveryManager`.
- Event publishing via injectable callback (decoupled from any bus — good).
- `PersistenceLayer`: cache + "PersistentStore" — **in-memory dicts only** despite docstrings saying "durable storage".
- `snapshots.py`: immutable `RuntimeSnapshot` over **domain models** (Project/Task/ExecutionSession/Artifact/MemoryEntry) + create/restore helpers. **Not exported in `__init__.py`; used by nothing except its own failing test** → orphaned module blocking suite collection.

## 4.3 Events (`autoforge_events`) — VERIFIED

Frozen immutable `BaseEvent` (event_id, event_type/category, occurred_at UTC-enforced, correlation_id, causation_id, aggregate_id/type, schema version, metadata) + per-domain event classes + `EventType` enum with ~90 dot-notation values covering project/task/execution/artifact/memory/loop/approval/failure/review/service/kernel lifecycles. Structurally satisfies brief §20 preservation requirements.

**Missing vs §20 list (VERIFIED grep counts = 0):** `request.received`, `context.retrieved`, `iteration.started`, `tool.started/completed/failed`, `verification.started/completed`, `diagnosis.created`, `repair.started/completed`, `checkpoint.created`, `worker.completed/failed`. Semantic mismatch: spec language says `approval.requested`, code defines `approval.required`.

## 4.4 Event Platform (`autoforge_event_platform`) — VERIFIED (island)

Complete infrastructure-grade bus: EventBus (publish/subscribe/unsubscribe/health), router, filter engine, ordering manager, priority queue, dispatcher, subscription manager, DLQ, archiver/history store, schema registry/validator/transformer, replay/correlation engines. Own rich `Event` model (source, sequence_number, priority, delivery_mode…). **Critical finding:** zero external importers; shares neither model types nor vocabulary with `autoforge_events`.

## 4.5 Models (`autoforge_models`) — VERIFIED

14 domain models on shared base classes; 12 enums. Known debt TECH-001/002: deprecated `json_encoders` config → 93–107 deprecation warnings per run (**VERIFIED**).

## 4.6 Persistence (`autoforge_persistence`) — VERIFIED source, UNVERIFIED behavior

Protocols + repositories for project/task/execution/artifact/memory + unit-of-work. Depends only on models. Not importable in current env (not installed); zero importers elsewhere.

## 4.7 Knowledge Platform (`autoforge_knowledge_platform`) — VERIFIED structure, UNVERIFIED behavior

- `retrieval/`: RankEngine (weighted scoring: relevance 50% / trust 30% / freshness 10% / access 5% / cross-ref 5% — real arithmetic read), DeduplicationEngine, FilterEngine, RetrievalPipeline, strategies.
- `fusion/`: merge/conflict resolution/consensus/contradiction detection. `trust/`: source trust evaluator, recency weighting, historical accuracy, expert endorsement.
- `citation/`: CitationManager, ProvenanceTracker, formatter/validator/indexer/generator.
- `context/ContextAssembler`: rank → trust-threshold filter → dedupe → citations → `context_window_manager.fit(...)` — knowledge-domain assembly only.
- **Zero tests. No factory/wiring. The assembler's required `context_window_manager` dependency has NO implementation anywhere in the repo.**

## 4.8 Documentation corpus — VERIFIED present

Frozen specs: Kernel Spec v1.0 (4,296 lines), Runtime SMS v1.0, Event Platform Spec v1.0, Knowledge Platform Spec v1.0, Memory Platform Spec v1.0 (4,432 lines — **spec only, no implementation**). `architecture/ARCHITECTURE.md` (1,276 lines) describes a much larger system than what exists. `docs/TECH_DEBT.md` tracks TECH-001..010. `docs/PROJECT_DASHBOARD.md` is stale (claims next commit is Persistence Layer; claims 3/21 phases done).

---

# 5. Existing Specifications

| Spec | Status | Relationship to code | Reconciliation note |
|---|---|---|---|
| Kernel Spec v1.0 | Frozen (tag) | Implementation diverges (certification report lists 15 mandatory gaps) | Keep spec; fix code or amend spec via ADR |
| Runtime SMS v1.0 | Frozen (tag) | Largely implemented in-memory; snapshot API mismatch | Keep; decide snapshots in/out |
| Event Platform Spec v1.0 | Frozen (tag) | Implemented but unintegrated | Keep; integrate via adapter (§23) |
| Knowledge Platform Spec v1.0 | Frozen (tag) | Implemented breadth-first, untested | Keep; add tests before extending |
| Memory Platform Spec v1.0 | Frozen (tag) | **No implementation at all** | Keep spec; implement later phase; do not let Context Engine absorb it |
| ARCHITECTURE.md v1.0 | Frozen | Describes engines that don't exist | Treat as north star; do NOT treat as current state |
| MODEL_ROUTER.md | Doc | Cost/cloud-provider-centric; contradicts local-first M1/8GB direction | Needs revision (§26) |

---

# 6. Existing Tests

Executed 2026-08-24, Python 3.14.6, pytest 9.1.1:

| Suite | Result | Detail |
|---|---|---|
| `packages/kernel/tests` | **1 failed / 99 passed**, 93 warnings | Fail: `test_integration.py::TestLifecycleCoordination::test_runtime_lifecycle` → `AttributeError: Mock object has no attribute 'verify_connection'` |
| `packages/runtime/tests` | **Collection ERROR** | `ImportError: cannot import name 'RuntimeSnapshot' from 'autoforge_runtime'` — suite never runs |
| `packages/events/tests` | 228 passed | Clean |
| `packages/event_platform/tests` | 56 passed | Clean |
| `packages/persistence/tests` | **Collection ERROR** | `ModuleNotFoundError: No module named 'autoforge_persistence'` (not installed) |
| `tests/models` (root) | 80 passed, 107 warnings | Warnings = Pydantic `json_encoders` deprecation |
| `packages/knowledge_platform` | **No tests exist** | 74 untested modules |

**Test-quality observations (VERIFIED):**
- Kernel tests are mock-heavy; two `RuntimeWarning: coroutine ... was never awaited` warnings prove misused AsyncMocks.
- No repository-wide test runner: Makefile `make test` prints "not yet implemented"; no root pytest config.
- No coverage measurement configured anywhere.
- Test layout inconsistency: models' tests live at root `tests/models` while every other package keeps local `tests/`.

---

# 7. Current Failures and Warnings

## 7.1 Hard failures (VERIFIED by execution)

1. Kernel: `verify_connection` AttributeError (contract break between Kernel and Runtime — see §9-C1).
2. Runtime: whole-suite collection failure via missing `RuntimeSnapshot` export (see §9-C2).
3. Persistence: uncollectable due to packaging/environment (see §9-C3).

## 7.2 Warnings (VERIFIED)

- ~93–107 × `PydanticDeprecatedSince20: json_encoders` per run (TECH-001/002 open) — removal scheduled for Pydantic v3; will break builds eventually.
- 2 × `RuntimeWarning: coroutine 'AsyncMockMixin._execute_mock_call' was never awaited` in kernel orchestration tests.

## 7.3 Verification of the 19 known issues from the direction brief

| # | Claimed issue | Verdict | Evidence |
|---|---|---|---|
| 1 | Kernel test failure re `verify_connection` | **CONFIRMED, still present** | Live test run; `kernel.py:639`; symbol absent from runtime src and Kernel ABC |
| 2 | Async coroutine warnings | **CONFIRMED, still present** | pytest warnings summary |
| 3 | `RuntimeSnapshot` import/export issue | **CONFIRMED, still present** | Live collection error; defined in `snapshots.py`, omitted from `__init__.py`; module otherwise unreferenced |
| 4 | Incomplete repository-wide test invocation | **CONFIRMED** | No root config; Makefile placeholder; 3 suites broken/skipped-by-default |
| 5 | Silent exception swallowing | **CONFIRMED** | 19 `except…pass` sites in kernel src (grep -A2), concentrated in `infrastructure.py` (~15), plus completion/recovery/orchestration |
| 6 | Incomplete infrastructure lifecycle | **CONFIRMED (code) / INFERRED (behavior)** | Swallowed-error health checks; certification audit says coordinator never invoked in pipeline |
| 7 | Event semantic inconsistencies | **CONFIRMED** | 3 vocabularies (§10); `approval.required` vs documented `approval.requested`; audit noted `worker.dispatched` type misuse |
| 8 | Incomplete event unsubscription | **CONFIRMED** | `kernel.py:583–585` comment admits interface gap; no cleanup on shutdown |
| 9 | Recovery exception swallowing | **CONFIRMED** | `recovery.py:214,334` broad catches |
| 10 | Incomplete checkpoint restoration | **INFERRED** | Restore paths exist in kernel recovery + runtime CheckpointManager; no cross-package round-trip test; audit flagged partial restoration |
| 11 | Hardcoded versions | **PARTIALLY FIXED, inconsistent** | Kernel pyproject now 1.0.0 ✓ but pip shows stale 0.1.0 install; `kernel_factory.py` defaults `version="0.1.0"`; runtime pyproject 0.1.0; knowledge `__version__="1.0.0"` |
| 12 | Incomplete structured logging | **CONFIRMED** | Zero `import logging`/`getLogger` in kernel+runtime src |
| 13 | Incomplete timeout handling | **CONFIRMED** | No timeout wrapping on any awaited external call in kernel (28 grep hits are docstrings/comments) |
| 14 | Incomplete retry handling | **CONFIRMED** | No retry/backoff code in kernel/runtime |
| 15 | Resource cleanup | **CONFIRMED missing** | `active_projects` entries added (`kernel.py:259`) with no removal path; subscriptions not cleaned on stop |
| 16 | Runtime health checks | **PARTIAL** | event_platform has `get_health`; Kernel exposes status string only |
| 17 | Concurrency safety | **CONFIRMED concern** | Kernel mutates `active_projects`/approvals without locks (runtime has ConcurrencyController; kernel doesn't use it) |
| 18 | Unbounded active project state | **CONFIRMED** | `kernel.py:202` dict grows unbounded |
| 19 | Behavioral integration test gaps | **CONFIRMED** | Mock-only cross-package tests; zero tests for persistence/knowledge; nothing exercises two real packages together |

---

# 8. Existing Stubs/TODOs

| Location | Kind | Detail |
|---|---|---|
| `packages/tools`, `memory`, `workflows`, `prompts`, `execution`, `shared` | Whole-package stubs | README-only |
| `services/*` (11), `apps/web`, `apps/api` | Stubs | README-only placeholders |
| `Makefile` | Stub targets | install/build/test/lint/format/clean all print "not yet implemented" |
| `kernel_factory.py` default version | Stale constant | `"0.1.0"` vs pyproject `1.0.0` |
| `completion.py` review block | Semi-stub | Real call made, but `except Exception: pass` hides outcome |
| `intent_analysis.py` | Heuristic stub-for-model | Rule-based classification; `knowledge_engine` param ignored |
| `runtime/persistence.py` | Misleading naming | Classes named PersistentStore/"durable" but dict-backed |
| Knowledge Platform ContextAssembler dep | Unimplemented dependency | `context_window_manager.fit()` required; no implementation exists |
| TECH register | Open items | TECH-001/002 (json_encoders), TECH-009 (packaging convention), TECH-010 (reserved-name audit) |

Explicit `# TODO` comments are rare; the repo's "stubs" are mostly structural (README packages) rather than marked code. (**VERIFIED** via search.)

---

# 9. Architecture Contradictions

**C1 — Kernel↔Runtime contract break (VERIFIED).** `Kernel.initialize()` awaits `runtime_state_manager.verify_connection()`. Neither the Kernel's own `RuntimeStateManager` ABC nor `autoforge_runtime.RuntimeStateManager` defines that method. Today it only explodes in tests because mocks are strict; in production it would crash every startup against the real runtime. *What exists:* a health-connection ritual invented in one package, absent in the other. *Should happen:* either add `verify_connection()` to both ABC and implementation (and test with the real runtime), or drop the call in favor of a generic `health_check()` on the ABC. *Why:* autonomous workers cannot boot on a Kernel whose startup contract doesn't match its dependency.

**C2 — Snapshot module vs state-manager reality (VERIFIED).** `snapshots.py` captures domain models; `RuntimeStateManager` owns runtime-state models (`ProjectState` etc.) stored in its own PersistenceLayer. They model the same world twice. Nothing composes them. Meanwhile the test suite imports `RuntimeSnapshot` from the package root and fails. *Should happen:* pick ONE snapshot mechanism — recommended: extend the existing `CheckpointManager` (state-model-based) and either port `snapshots.py` onto state models or delete it (decision D1, §28). *Why:* two snapshot vocabularies would multiply under the Worker's checkpoint/rollback needs.

**C3 — Three event systems (VERIFIED; detailed in §10).**

**C4 — "Execution Engine" exists as docs+ABCs only (VERIFIED).** ARCHITECTURE.md's central engine has no implementation; Kernel orchestration therefore cannot actually execute anything. The Autonomous Worker effort will either implement something in that role or make the Worker runtime the executor. Decision required (§28-D2) so we don't build two executors.

**C5 — README/roadmap vs reality (VERIFIED).** README declares Node.js/TypeScript stack with RabbitMQ/Kubernetes ambitions; root tsconfig/package.json remain; ROADMAP.md declares "✓ Kernel v1.0 Frozen" while the Kernel's own audit forbade freezing; PROJECT_DASHBOARD is 5+ commits stale. *Should happen:* docs truth-pass (§26). *Why:* the brief explicitly forbids blindly following old docs; future contributors/agents will read these first.

**C6 — Local-first contradiction in MODEL_ROUTER.md (VERIFIED).** Spec text optimizes cloud cost/pricing; direction requires M1/HP-local Ollama-first routing with observability of inference location. Doc must be revised before Phase 2 (Model Runtime).

**C7 — Persistence naming collision (VERIFIED).** `autoforge_runtime.persistence.PersistenceLayer` (in-memory internals) vs `autoforge_persistence` package (repository layer, unused). Same concept name, different layers, neither integrated. *Should happen:* rename runtime's to an explicit in-memory name; adopt `autoforge_persistence` as the durability adapter behind Runtime later (Phase 8).

---

# 10. Duplicate Responsibilities

| Domain | Duplicates found (all VERIFIED) | Recommendation |
|---|---|---|
| Event model | `autoforge_events.BaseEvent` • `autoforge_event_platform.models.event.Event` • `autoforge_models.Event` | Canonicalize `autoforge_events`; DEPRECATE `models.Event`; adapt platform via translator (§23) |
| EventType enum | `events/event_types.py` (~90 values, dotted) • `event_platform/models/event.py` (own enum, 200+ literal strings) • `models/enums.py EventType` (flat verbs like `gate_passed`) | One enum; others map/deprecate |
| EventBus | `kernel/interfaces.EventBus` (ABC, consumed) • `event_platform.core.EventBus` (impl, unused) • `event_platform.interfaces.IEventBus` (ABC) | Write one adapter: Kernel ABC satisfied by event_platform impl after model translation |
| State representation | Domain models vs runtime StateModels | Keep both but define mapping once (Runtime owns transitions; domain models own identity/content); forbid a third vocabulary |
| Snapshot/checkpoint | `runtime/snapshots.py` vs `runtime/checkpoint_manager.py` (+ kernel recovery restore path) | Consolidate into CheckpointManager (C2) |
| Persistence | runtime internal PersistenceLayer vs packages/persistence | Rename internal (C7); integrate package as durable adapter in Phase 8 |
| Context-ish assembly | Knowledge `ContextAssembler` (executable, knowledge-scoped) vs MEMORY spec `load_context` (paper) vs EXECUTION_ENGINE.md "Execution Context Manager" (paper) | Future Context Engine consumes these; none becomes the general engine (§13/§14) |
| Intent analysis | Kernel rules-based analyzer vs ARCHITECTURE.md Strategic Engine (unbuilt) | Rules version is fine for now; mark as replaceable strategy behind `IntentAnalyzer` ABC |

---

# 11. KEEP / EXTEND / REFACTOR / DEPRECATE / REPLACE Matrix

| Component | Decision | Why (evidence-based) |
|---|---|---|
| `packages/events` | **KEEP** (extend later) | Cleanest package in repo: frozen immutable base, correlation/causation IDs, 228 green tests, already canonical for Kernel. Extends with worker/tool/verification event types in Phase 1. |
| `packages/models` | **KEEP** + small EXTEND | Solid Pydantic v2 domain core, 80 green tests. Add ModelCapabilities/worker fields later; remove duplicate `Event` model. |
| `packages/runtime` core (state, transitions, validation, checkpoints, query, concurrency, recovery) | **KEEP + EXTEND** | Real state-machine engine matching a frozen spec; strongest basis for worker task state, bounded iterations, pause/resume. Extend: durable store adapter, snapshot decision (C2), export fixes. |
| `packages/kernel` | **KEEP architecture / REFACTOR implementation** | Responsibility boundaries praised even by its hostile audit ("architecture sound"); but 19 swallowed exceptions, zero logging, no timeouts/retries/cleanup, broken `verify_connection`, unbounded state. Refactor in place; do not rebuild. |
| `packages/event_platform` | **KEEP** (integrate via adapter) | Fully built infra-grade bus; discarding it would waste the only mature pub/sub code. Must be bridged to canonical events or it stays an island. |
| `packages/knowledge_platform` | **KEEP** (test, then extend) | Unique assets: trust scoring, fusion/contradiction detection, citation/provenance, weighted ranking — exactly the raw material the Context Engine's Authority/Freshness/Conflict stages need. But 0 tests ⇒ freeze feature growth until tests exist. |
| `packages/persistence` | **KEEP** (install now, wire later) | Right-shaped repository/UoW protocols; harmless until adopted as Runtime durability adapter (Phase 8). Immediate action is packaging hygiene only. |
| `kernel/interfaces.py` service ABCs (MemoryEngine, ModelRouter, ConnectorLayer, ObservabilityService, SecurityService…) | **EXTEND** gradually | Correct seams for future subsystems; empty today by design. New subsystems should implement these ABCs rather than invent parallel ones. |
| `runtime/snapshots.py` | **REFACTOR or DELETE** (decision D1 §28) | Orphaned, dual-vocabulary, breaks suite. If kept: port onto StateModels + export + tests. |
| `autoforge_models/event.py` + `enums.EventType` | **DEPRECATE** | Third event vocabulary; superseded by `autoforge_events`; only self-imported. |
| `runtime.persistence` internal naming | **REFACTOR** (rename) | Collision with packages/persistence confuses ownership (C7). |
| Root TS scaffolding (`package.json`, `tsconfig.base.json`, `.nvmrc`) + README stack section | **DEPRECATE → remove after doc pass** | Contradict actual Python implementation; mislead every newcomer/agent (C5). |
| `services/*` README placeholders | **DEPRECATE (park)** | Belong to SDLC-agent-services architecture superseded by single-worker-engine direction. |
| `apps/web`, `apps/api` | **PARK** | No UI work per brief §0. |
| `docs/subsystems/MODEL_ROUTER.md` cost model | **REFACTOR** (rewrite) | Cloud-cost framing contradicts local-first mandate (C6). |
| `docs/PROJECT_DASHBOARD.md` | **REFACTOR** (refresh) | Factually stale (§4.8). |
| `architecture/ROADMAP.md` phases | **EXTEND** | Append reconciliation-corrected status + new phases via ADR; don't rewrite history. |
| Anything else | **REPLACE: nothing wholesale** | No subsystem is so misconceived that replacement beats repair — consistent with the KEEP→EXTEND mandate. |

---

# 12. Autonomous Worker Gap Analysis

Target loop (brief §2) mapped against today's code:

| Loop stage | Exists? | Where / Gap |
|---|---|---|
| UNDERSTAND | Partial | Kernel `RequestIntake` + heuristic `IntentAnalyzer`; no repository understanding at all |
| PLAN | Interface-only | `PlanningCoordinator` delegates to unbuilt Strategic/Workflow engines; no planner implementation |
| GATHER CONTEXT | Knowledge-only | Knowledge Platform retrieves *external* knowledge; nothing gathers repo/test/error/terminal context |
| SELECT TOOLS | **MISSING** | No tools exist (`packages/tools` empty) |
| ACT | **MISSING** | No file edit/terminal/git capability anywhere |
| OBSERVE | **MISSING** | No observation normalization (stdout/stderr/exit/diff) |
| VERIFY | **MISSING** | No test/build/lint runner, no evidence model. Closest: runtime `QualityGate` domain model (unused) |
| SUCCESS? / DIAGNOSE | **MISSING** | No failure classification (runtime has `FailureRecord/FailureSeverity/FailureSource/FailureRecoverability` models — reusable seeds, unused) |
| REPAIR / RETEST | **MISSING** | No iteration controller; Kernel loop concepts (LOOP_* states/events) exist but drive nothing |
| COMPLETE | Partial | Kernel `CompletionModule` finalizes *projects*, assumes engines produced artifacts |
| Bounded iterations/timeouts/retries | **MISSING in practice** | Spec'd in docs; unimplemented in code |
| Pause/resume/cancel | Partial | Kernel + Runtime lifecycle APIs exist (mock-level tested) |
| Checkpoints/rollback | Partial | Runtime CheckpointManager solid for *state*; no Git/filesystem rollback (needs Tool Runtime) |
| Failure classification | Seeds only | Runtime `FailureRecord` enums exist; no classifier |
| Human escalation/approval gates | Partial | Kernel ApprovalCoordinator works (mock-tested); policy model thin (`approval_policy: dict`) |
| Persistent task state | **MISSING (durable)** | Everything in-memory |
| Event emission | Strong | Canonical events + platform; missing worker-stage types (§4.3) |
| Memory | **MISSING impl** | Spec frozen; `MemoryEntry` model + memory_events + persistence repo exist; zero engine |
| Verification evidence | **MISSING** | No evidence record type anywhere |

**AutonomousWorker abstraction:** nothing named or shaped like it exists. Nearest seams worth reusing: Kernel's `WorkerDispatchCoordinator`, the `Employee` domain model (an AI-employee with role/model config), and runtime `WorkerState`. **Recommendation:** evolve these — `AutonomousWorker` becomes the concrete protocol that `WorkerDispatchCoordinator` dispatches and `WorkerState` tracks — rather than introducing a competing hierarchy. Composition over inheritance per brief §3 and repo PRINCIPLES.

---

# 13. Context Engineering Gap Analysis (audit per brief §30)

Searches performed: `context`, `token budget`, `prompt`, `provenance`, `relevance`, `context window`, `summariz`, `compress`, `rank`, `RAG`, `embedding`, `conversation`, plus package listings.

### 13.1 What already exists

| Asset | Location | Scope | Reusable for Context Engine? |
|---|---|---|---|
| `ContextAssembler` (rank→trust-filter→dedupe→citations→window-fit) | `knowledge_platform/context/` | Knowledge items only | **Yes — as delegated source-assembler**; implements pipeline stages 2–7 of brief §8 for the Knowledge source |
| Weighted relevance scoring (50/30/10/5/5) | `retrieval/rank_engine.py` | Knowledge items | Yes — seed for RelevanceScorer |
| Deduplication by ID | `retrieval/deduplication_engine.py` | Knowledge items | Yes (extensible to content-hash) |
| Trust/source evaluation, recency weighting | `trust/*` | Knowledge sources | Yes — Authority/Freshness evaluator material |
| Provenance tracking (source, retrieved-at, chain) | `citation/provenance_tracker.py` | Knowledge citations | Pattern + code to generalize |
| Conflict/contradiction detection | `fusion/contradiction_detector.py`, `validation/consistency_checker.py` | Knowledge claims | Seed for ConflictResolver |
| `IContextAssembler` interface | `interfaces/knowledge_interfaces.py` | Knowledge | Reference shape |
| `Request.context` passthrough dict | `kernel/interfaces.py` | Raw | Input source only |
| Memory-spec `load_context(project_id)` flow | docs only | Paper | Contract to honor later |
| EXECUTION_ENGINE.md "Execution Context Manager", token budgets | docs only | Paper | Requirements source |

### 13.2 Answers to the mandated questions

1. **What context functionality exists?** Knowledge-domain assembly + ranking + dedupe + trust + provenance. Nothing else executable.
2. **Who owns it today?** Knowledge Platform (correctly, for knowledge). Kernel carries opaque `Request.context` dicts. Memory spec *describes* context loading it doesn't implement.
3. **Duplication?** No executable duplication — but three *paper* owners (Knowledge assembler / Memory load_context / Execution Context Manager) which WILL collide if built independently.
4. **Embedded where?** Executable logic inside Knowledge (acceptable). Kernel embedding limited to passthrough fields.
5. **Reusable?** Yes — see table.
6. **Must be extracted?** Nothing needs extraction; the general engine should be NEW but SMALL, consuming knowledge components via their interfaces.
7. **Should remain where it is?** Knowledge ranking/trust/fusion/provenance stay in Knowledge Platform. Memory stays in Memory Platform. Runtime state stays in Runtime.
8. **Interfaces existing?** `IContextAssembler` (knowledge); Kernel `MemoryEngine`/`KnowledgeEngine` ABCs define consumption seams.
9. **Token budgeting today?** None executable. `context_window` is an int passed to a nonexistent `fit()`. **MISSING entirely** (no tokenizer, counting, or truncation strategy).
10. **Telemetry?** `context_utilization` ratio from assembler; `memory.retrieved` event exists. No record of *what was included/excluded and why*. **MISSING.**
11. **Missing overall:** model-capability awareness; token counting/budget enforcement; non-knowledge sources (repo files, task state, errors, terminal output, git, prior attempts); compression/summarization; inclusion/exclusion rationale records; deterministic assembly controls; per-decision usage records; quality metrics.

**Verdict:** a dedicated Context Engineering subsystem IS justified — but as a thin orchestrator over existing parts, NOT the 13-component maximal decomposition of brief §31. Recommended merged shape in §14.

---

# 14. Proposed Context Engineering Architecture

New package: `packages/context_engine` (`autoforge_context_engine`). Deliberately minimal — five units, not thirteen:

```
ContextEngine                  (facade; owns assembly orchestration)
├── ContextSourceRegistry      (pluggable providers: TaskStateProvider,
│                              RepositoryFileProvider, ErrorProvider,
│                              TerminalOutputProvider, PlanProvider,
│                              PriorAttemptsProvider, MemoryProvider→MemoryPlatform,
│                              KnowledgeProvider→delegates to KnowledgePlatform
│                                ContextAssembler/RankEngine/TrustScorer)
├── CandidateCollector         (gathers typed candidates w/ provisional metadata)
├── SelectionPipeline          (ordered, optional stages:
│                              score → authorize(trust/authority) → freshen
│                              → dedupe → resolve conflicts → compress
│                              → fit budget)
├── BudgetManager              (tokenizer-adapter; per-source reserves;
│                              hard cap; overflow eviction by score)
└── UsageRecorder              (immutable ContextUsageRecord per assembly)
```

Key contracts (sketch):

```python
class ContextCandidate(BaseModel):
    source_type: ContextSourceType   # RepositoryFile, TaskState, TestOutput, ...
    content: str
    provenance: Provenance           # origin, observed_at, authoritative flag
    scores: Scores                   # relevance, authority, freshness
    est_tokens: int

class ContextRequest(BaseModel):
    task_id: uuid.UUID
    goal: str
    model_capabilities: ModelCapabilities   # consumed, never imported from a provider
    stage: WorkerStage
    constraints: ContextConstraints  # max_tokens, required kinds, determinism seed

class ContextUsageRecord(BaseModel):
    request: ContextRequest
    included: list[IncludedItem]
    excluded: list[ExcludedItem]     # with reasons
    budget: BudgetLedger
    latency_ms: float
    assembler_version: str
```

Design rules enforced by this shape:

- **Model-aware, model-neutral (brief §9):** consumes a `ModelCapabilities` value object supplied by Model Runtime; contains zero provider imports.
- **Ownership respected (§11/§12 of brief):** engine *requests* from Memory/Knowledge/Runtime via interfaces; never stores their data.
- **Small-model bias:** BudgetManager default profile tuned for ≤8k-token local models (aggressive dedupe/compress, narrow retrieval, exact-errors priority); profiles selected per capabilities.
- **Determinism where practical (§7.17):** stable sort keys + optional seed recorded in the usage record.
- **Independently testable:** pure-Python pipeline with fake sources; golden fixtures in `tests/fixtures/sample_project/`.

Explicitly NOT in scope for this package: embeddings/vector store (later, likely inside Knowledge Platform), prompt *template* management (`packages/prompts` concept), conversation-history storage (Memory).

---

# 15. Proposed Autonomous Worker Architecture

Evolution of existing seams — no second orchestration system:

```
KERNEL (unchanged role: intake, governance, project lifecycle)
   │ submit_request → intent → plan-coordination
   ▼
WORKER DISPATCH (existing Kernel module gains a registry)
   │ resolves domain id → WorkerFactory
   ▼
AutonomousWorker (protocol, packages/worker_runtime)
   ├── Perception      ← Repository Intelligence (new pkg) + request
   ├── Context         ← ContextEngine.assemble(stage=…)
   ├── Planning        ← Planner strategy (LLM-backed; falls back to Kernel's rule analyzer)
   ├── Execution       ← ToolRuntime.invoke(tool_call)        (new pkg)
   ├── Observation     ← normalized ToolResult (typed outputs/errors)
   ├── Verification    ← Verifier (runs checks → EvidenceRecord; claim ≠ success)
   ├── Repair          ← RepairController (classify → strategy → bounded retry;
   │                      feeds PriorAttempts back into ContextEngine)
   ├── Memory          ← MemoryPlatform.write(reflection, qualified)
   ├── Governance      ← Kernel ApprovalCoordinator (policy hooks on risky tools)
   └── Communication   ← typed events (extended EventType set) + final WorkerReport
```

Loop control owned by `WorkerRunController` inside `worker_runtime`: iteration caps, wall-clock budget, per-call timeouts, cancellation tokens, checkpoint-before-risky-action (Runtime CheckpointManager + Git checkpoint tool), pause/resume via runtime `WorkerState` transitions.

Domain specialization = configuration + strategy plug-ins (perception profiles, verifier sets, tool whitelists) — **not** subclasses of a god-class. `SoftwareEngineerWorker` is the first configuration of this engine.

Relationship to ARCHITECTURE.md's unbuilt engines: worker_runtime *is* the concrete thing that plays the Execution Engine role for worker-style work; WorkflowEngine remains available later for long DAG projects (decision D2).

---

# 16. Ownership Boundaries

| Subsystem | Owns | Must NOT own |
|---|---|---|
| Kernel | lifecycle, request intake, governance, approvals, project/task lifecycle, module wiring | engineering work, context selection, model calls, tool execution |
| Runtime | authoritative state, transitions, checkpoints (state), history, queries | business meaning of state, file/git effects |
| Events | event vocabulary + payloads | transport, delivery guarantees |
| Event Platform | delivery, routing, ordering, DLQ, replay, schemas | event *meaning* |
| Models pkg | domain schemas | behavior/services |
| Persistence | durable aggregates + UoW | in-memory runtime speed path |
| Knowledge Platform | acquisition, trust, fusion, citation, research, knowledge-context slice | general model-context assembly, memory |
| Memory Platform (future impl) | retention policy, qualification, recall | context assembly decisions |
| Context Engine | selection/budget/packaging/usage telemetry | owning sources' data, inference, tools |
| Model Runtime | provider adapters, capabilities, health, routing | prompt content, task logic |
| Tool Runtime | tool contracts, execution, safety gates, audit events | planning, verification semantics |
| Repository Intelligence | index, symbols, search, diffs, test discovery | writing files (tools do that) |
| Worker Runtime | loop control, attempts, reports | governance policy (asks Kernel), state authority (uses Runtime) |

---

# 17. Dependency Graph

Current (**VERIFIED** from imports/pyprojects):

```
models ◄── events        [events has NO autoforge deps — standalone]
models ◄── runtime ──► events
models ◄── kernel  ──► runtime, events
models ◄── persistence   [unused by anyone]
(none) ◄── event_platform         [ISLAND]
(none) ◄── knowledge_platform     [pydantic+aiofiles only]
```

Target additions (each new package may depend leftward only):

```
context_engine ► models, events, (interfaces of) runtime/memory/knowledge
model_runtime  ► models, events
tool_runtime   ► models, events
repo_intel     ► models
worker_runtime ► context_engine, model_runtime, tool_runtime, repo_intel,
                 runtime, events, kernel(interfaces only)
composition    (new top-level wiring / future apps/cli)
               ► worker_runtime + kernel + event_platform(adapter)
```

Rules: Kernel depends on interfaces only; no cycles; the event_platform adapter isolates its model dialect; knowledge_platform stays dependency-free (good isolation today — preserve it).

---

# 18. Control Flow

Today (**VERIFIED path**): `submit_request()` → validate → normalize → init project (Runtime) → emit `project.created` → intent analysis (rules) → planning delegation (ABC; mock in tests) → orchestrate workflow (ABC; mock) → event fan-in via `_handle_*_event` handlers → completion (validation→transitions) or failure→recovery→approval escalation.

Target worker flow: request → understand (repo-intel + context) → plan → bounded [act⇄observe⇢verify] loop → repair branch (≤N attempts, each context-informed) → checkpoint → report; every stage emits canonical events; approvals interrupt flow through Kernel.

Gap: the middle of today's flow terminates in unimplemented ABCs; the worker runtime fills exactly that hole without disturbing the Kernel's edges.

---

# 19. Data Flow

- **State data:** domain entities (models) ⇄ runtime StateModels via registration/transitions; history appended per transition; checkpoints serialize state slices. All in-memory (**VERIFIED**).
- **Event data:** `BaseEvent` instances → (target) translated → platform Event → router/dispatcher → subscribers; persisted by platform stores (currently an unused path).
- **Knowledge data:** connectors → ingest → validate/trust-score → index → retrieve/rank/fuse → cite/provenance. No persistence wired (cache module exists).
- **Context data (proposed):** providers snapshot *copies* + provenance into candidates → selection pipeline → packaged ModelContext + ContextUsageRecord → emitted as events for observability; originals untouched (ownership rule).

---

# 20. Failure/Recovery Flow

Existing pieces (**VERIFIED**): runtime FailureRecord taxonomy (severity/source/recoverability); RecoveryManager (runtime); Kernel RecoveryModule (detect→strategy→checkpoint-restore→escalate-to-approval on failed recovery); approval.decided handlers resume/remediate; LOOP_REMEDIATING state exists.

Broken/missing (**VERIFIED**): swallowed exceptions hide root causes (infrastructure/recovery); no cross-package round-trip test (create checkpoint in Runtime → crash → restore via Kernel → resume); Git/filesystem rollback absent (needs tools); no failure-classification→repair-strategy mapping.

Target: same skeleton, plus: classify(FailureCategory) → choose RepairStrategy → new attempt with PriorAttempts context → escalate on budget exhaustion; every step evidenced and evented; "I implemented the change but verification failed" is a first-class report outcome (brief §21).

---

# 21. Testing Strategy

Current: 463 green tests across 4 healthy suites; 2 suites broken at collection; knowledge untested; mock-dominant; no CI wiring (Makefile stubs); homebrew Python 3.14 env with editable installs and version drift.

Target ladder (per brief §27):

1. **Unit tests** — exist; keep.
2. **Contract tests** — persistence protocols vs fake stores; Kernel ABCs vs real Runtime / EventPlatform adapter (**NEW**; directly prevents C1-class breaks).
3. **Integration tests** — real-object Kernel+Runtime+Events triangle (**NEW**).
4. **Real tool tests** — tmp-dir filesystem ops, git in temp repo, subprocess echo (with Phase 3).
5. **Local model smoke tests** — optional-marked Ollama ping/generate (Phase 2).
6. **E2E autonomous worker tests** — fixture-repo task → verified diff (Phase 6+).
7. **Context engine tests** — golden-context fixtures, determinism, budget eviction (Phase 5).

Infrastructure actions (inside Task 3): root pytest workspace config running all suites; real `make test`; coverage gate; pinned dev requirements; deterministic fixture repository `tests/fixtures/sample_project/` (multiple source files, tests, dependencies, configuration, one intentional bug) introduced early so later phases consume it.

---

# 22. Migration Strategy

Ordered per the brief's default ladder, applied per component (details in §11 matrix):

- **KEEP:** events, models (minus Event), runtime core, event_platform, knowledge components, persistence sources, all five frozen specs.
- **EXTEND:** events (+worker-stage types), runtime (+durability adapter, snapshot decision), kernel (+logging/timeouts/retry/cleanup/registry), models (+capabilities), knowledge (+tests first).
- **REFACTOR:** kernel internals in place (behavior-preserving), runtime persistence naming, snapshots consolidation, MODEL_ROUTER.md, dashboard, intent-analyzer seam.
- **DEPRECATE:** `models/event.py` (+enum), root TS scaffolding, services/* placeholders (park), stale dashboard claims.
- **REPLACE:** nothing wholesale. Even the three-event-system tangle resolves via adapter+deprecation, not rewrite.

Sequence logic: stabilize what exists (Phase 0) → unify vocabulary so new subsystems speak one language → add leaf runtimes (model/tools) that nothing depends on yet → repo-intel + context engine (consume stabilized parts) → worker (compose) → memory/recovery depth → benchmark → scale-out → voice → second worker.

---

# 23. Exact Implementation Order

| Phase | Content | Reconciliation adjustments vs brief §34 |
|---|---|---|
| **0 — Reconcile & Stabilize** (now) | Fix 3 broken suites; kill silent exceptions; logging spine; timeout/retry utils; resource cleanup; event-vocabulary unification ADR + adapter; snapshot decision; packaging/root-test hygiene; json_encoders migration; docs truth-pass | **Expanded from brief** — audit proved stabilization must precede contracts; includes vocabulary unification originally implicit |
| **1 — Worker Contracts** | `AutonomousWorker` protocol, `WorkerStage`, `WorkerReport`, `EvidenceRecord`; extend EventType set; wire `WorkerDispatchCoordinator` registry | Uses existing Kernel seams (§12) |
| **2 — Model Runtime** | `ModelProvider/Request/Response/Capabilities/Health` ABCs + `LocalOllamaProvider` + router skeleton + smoke tests | Confirmed; revise MODEL_ROUTER.md first |
| **3 — Tool Runtime** | fs/terminal/git/dev tools; typed IO; timeouts; permission-policy hooks → Kernel approvals; audit events | Confirmed |
| **4 — Repository Intelligence** | tree/lang-detect/index/symbols/search/diffs/test-discovery on fixture repo | Confirmed |
| **5 — Context Engine** | §14 five-unit engine; knowledge delegation first, repo/error sources next; UsageRecords | **Leaner than brief §31 candidate**; earlier start possible since Knowledge pieces already exist |
| **6 — SE Worker** | Compose; run against fixture repo; real E2E | Confirmed |
| **7 — Self-Repair + Verification** | Classifier, strategies, bounded retries; verifier evidence | Confirmed |
| **8 — Memory + Recovery Integration** | Implement Memory Platform core (spec exists); durable runtime store via packages/persistence; full checkpoint/rollback incl. git | Durability deliberately deferred to here |
| **9 — Autonomy Benchmark** | Scored tasks on fixture repos; Task-Success-per-Context-Token metric from UsageRecords | Metric lands naturally thanks to Phase 5 telemetry |
| **10 — Multi-Machine Routing** | Router policies M1/HP; availability/load; single-machine always works | Confirmed |
| **11 — Voice**, **12 — Second Domain Worker** | Unchanged | — |

---

# 24. First 10 Engineering Tasks (Phase 0 + entry to Phase 1)

| # | Task | Packages touched |
|---|---|---|
| 1 | Resolve `verify_connection` contract break: add `verify_connection()` (or `health_check()`) to Kernel's `RuntimeStateManager` ABC **and** implement in runtime; test with the real runtime instance, not a mock | kernel, runtime |
| 2 | Resolve snapshot contradiction (decision D1; default: delete orphaned `snapshots.py`+test, rely on CheckpointManager — or port to StateModels and export) | runtime |
| 3 | Packaging & test-runner hygiene: editable-install persistence+knowledge (refresh stale kernel install); root pytest workspace config + real `make test`; move root `tests/models` into `packages/models/tests`; pin dev requirements | root, persistence, knowledge, models |
| 4 | Eliminate all 19 silent `except…pass` sites: log-and-wrap or re-raise per severity; regression tests for infrastructure health paths | kernel |
| 5 | Structured logging spine: `get_logger(name)` helper + JSON formatter (stdlib logging only), instrument kernel+runtime modules | kernel, runtime |
| 6 | Timeout & retry primitives (`asyncio.wait_for` wrapper + small backoff util); apply to every cross-package awaited call in Kernel | kernel (+ shared util per D4) |
| 7 | Resource governance: bound/clean `active_projects`; track & unsubscribe event subscriptions on shutdown; implement `restart()` per Kernel Spec §6.3 | kernel |
| 8 | Event vocabulary unification (ADR D3): declare `autoforge_events` canonical; write event_platform adapter translating BaseEvent↔platform Event satisfying Kernel's EventBus ABC; deprecate `models/event.py`; fix `approval.requested` naming; add missing worker-stage event types (request.received, context.retrieved, iteration.*, tool.*, verification.*, diagnosis.created, repair.*, checkpoint.created, worker.completed/failed) | events, event_platform, kernel |
| 9 | Migrate `json_encoders` → `@field_serializer` (TECH-001/002) — eliminates ~100 warnings/run before Pydantic v3 removal | models |
| 10 | Docs truth-pass + ADRs: README (actual Python stack), PROJECT_DASHBOARD refresh, ROADMAP annotation via ADR, park/remove TS scaffolding (D5), write ADR-0001..0006 (§28) | docs, root |

Each task is one shippable commit with tests. None starts Model/Tool/Context/Worker implementation.

---

# 25. Acceptance Criteria

| # | Acceptance |
|---|---|
| 1 | Kernel + runtime suites fully green; startup test constructs a **real** `RuntimeStateManager` and asserts healthy connection check; no mock-only coverage of that path |
| 2 | Runtime suite collects and passes; `python -c "from autoforge_runtime import ..."` reflects the recorded snapshot decision; no orphaned dual-vocabulary module remains |
| 3 | Single command `make test` runs ALL suites from clean checkout; exit code aggregates results; persistence+knowledge importable in fresh venv via documented bootstrap; CI config file exists (runners may be off) |
| 4 | `grep -rn -A2 "except" packages/kernel/src \| grep -c "pass$"` returns **0**; each former site logs or re-raises with a test |
| 5 | Every kernel/runtime module has a module logger; scripted request lifecycle emits structured log lines validated by unit test |
| 6 | Timeout util raises `TimeoutError` and cancels inner task (no leaked-coroutine warning); retry respects max_attempts/backoff; ≥10 previously-unprotected Kernel awaits wrapped |
| 7 | Script registering N projects then shutting down leaves zero residual references (weakref check); unsubscribe path covered; `restart()` reaches READY with test |
| 8 | Adapter test: BaseEvent published through adapter arrives on platform bus with preserved correlation/causation/aggregate IDs; one Kernel integration test uses the real bus end-to-end; `models/event.py` emits DeprecationWarning; new worker-stage event types have enum+payload tests |
| 9 | Model test suite emits **0** Pydantic deprecation warnings; serialized UUID/datetime JSON matches pre-migration golden output |
| 10 | README/Dashboard claims each verifiable against repo (checklist committed); ADR-0001..0006 merged with statuses; TS files removed or parked with tracked issue |

Global gate after Task 10: `make test` green across all suites; no unresolved row left in the §7.3 verification table.

---

# 26. Documentation Changes Required

| Document | Required change | Trigger |
|---|---|---|
| `README.md` | Replace Node/TS stack section with actual Python architecture; fix roadmap checkboxes; link this reconciliation | C5 |
| `docs/PROJECT_DASHBOARD.md` | Regenerate metrics/status from current tree | Staleness |
| `architecture/ROADMAP.md` | Annotate completed-vs-actual; append Phases 0–12 via ADR | C5 |
| `docs/subsystems/MODEL_ROUTER.md` | Rewrite around local-first routing/capabilities; move cost-optimization to cloud appendix | C6 |
| `docs/subsystems/MEMORY_ENGINE.md` + Memory Platform Spec | Mark "spec frozen, implementation pending"; forbid context-engine absorption | §11 boundary |
| Event docs (EVENT_BUS.md, EVENT_PLATFORM_SPECIFICATION) | Document canonical-events ↔ platform translation + adapter | Task 8 |
| `packages/kernel/PHASE_2.2_COMPLETE.md`, `PHASE_2.3_VALIDATION_REPORT.md` | Mark SUPERSEDED by certification audit + this document | Audit trail |
| `docs/adr/ADR.md` | Append ADR-0001..0006 (§28 decisions) | Governance |
| New: `docs/PYTHON_PACKAGING.md` | Resolves TECH-009 packaging convention | Task 3 |
| `architecture/GLOSSARY.md` | Add AutonomousWorker, ContextEngine, EvidenceRecord, WorkerStage; disambiguate event systems during migration | Task 8 |

---

# 27. Risks

| Risk | Likelihood | Impact | Mitigation |
|---|---|---|---|
| Vocabulary unification (Task 8) touches many files → regressions | Medium | High | Adapter-first (zero breaking change), deprecation cycle, full-suite gate |
| Kernel refactor scope creep into re-architecture | Medium | High | Task-sized PRs; behavior-preserving rule; certification-report checklist as boundary |
| Frozen specs contradict needed changes (e.g., approval naming) | High | Medium | ADR process explicitly allowed by ROADMAP header; amend specs alongside code, never silently |
| Python 3.14/homebrew env drift breaks reproducibility | Medium | Medium | Pinned dev-requirements + documented bootstrap; consider 3.12 venv convention (TECH-009) |
| Knowledge Platform stays untested → silent rot before Phase 5 needs it | High | Medium | Smoke+contract tests pulled into Phase 0/2 window |
| 8GB M1 constraint underestimated by eager context designs | Medium | High | Conservative BudgetManager defaults; benchmark metric guards |
| Event Platform integration stalls → island gets forked ideas instead | Medium | Medium | Task 8 makes the adapter the ONLY sanctioned bridge |
| Report shelved; old docs keep misleading contributors/agents | Medium | High | Task 10 mandatory — README is every session's entry point |

---

# 28. Decisions Required

| ID | Decision | Options | Auditor recommendation |
|---|---|---|---|
| D1 | Fate of `runtime/snapshots.py` | (a) port to StateModels + export; (b) delete, rely on CheckpointManager | (b) delete — CheckpointManager already covers the need; less surface (revisit if cross-process snapshots demanded) |
| D2 | Executor of record for worker loop | (a) worker_runtime fills Execution Engine role; (b) build WorkflowEngine first | (a) worker_runtime executes; WorkflowEngine deferred until multi-phase DAG projects return |
| D3 | Canonical event system | (a) `autoforge_events` canonical + platform as transport; (b) migrate everything onto platform models | (a) smaller blast radius; preserves frozen events API; platform gains its rightful transport job |
| D4 | Home for shared utilities (logging/timeout/retry) | (a) create minimal `packages/shared` now; (b) defer, colocate per-package | (a) three small helpers now — prevents duplication across five imminent packages |
| D5 | TypeScript-era root artifacts | (a) delete now; (b) park under `docs/legacy/`; (c) leave | (b) park + README note — history visible, confusion removed; delete at Phase 1 exit |
| D6 | Worker package naming | `worker_runtime` vs `workers` vs `autonomous_worker` | `worker_runtime` (mirrors model_runtime/tool_runtime symmetry) |

---

# 29. Final Recommendation

**Proceed with Phase 0 exactly as scoped in §24 — and nothing else — before any Autonomous Worker code is written.**

Justification: the audit shows the platform's problem today is not missing ambition but **broken integration fabric**: two suites cannot run, one startup contract is structurally broken, nineteen error paths are silenced, three event languages coexist, and no two packages have ever been composed in a live process. Building Model Runtime, Tools, Context Engine, or the Worker on this substrate would inherit every one of those faults and multiply them.

Conversely, nothing needs replacing. The KEEP→EXTEND thesis survives contact with the code: events/models/runtime/knowledge/event-platform/kernel together provide most of the Worker's *nervous system* (state, events, governance, lifecycle, knowledge intelligence). The missing organs — model access, tools, repository perception, context assembly, verification, repair — are all *additive* packages with clean seams already waiting in `kernel/interfaces.py`.

Execute Tasks 1–10, hold the acceptance gates, record ADRs D1–D6, then enter Phase 1 with a substrate that is green, observable, unified — and honest.

---

*End of reconciliation report. Prepared as an audit-only deliverable; no production code was modified.*

