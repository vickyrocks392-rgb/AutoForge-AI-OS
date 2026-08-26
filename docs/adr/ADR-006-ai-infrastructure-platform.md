# ADR-006: AI Infrastructure Platform Boundary (Capability Registry, Model Router, Execution Continuity Manager)

**Date:** 2026-08-26

**Status:** Accepted

---

## Context

`architecture/ROADMAP.md` Phase 7 requires provider abstraction through
three components: a Capability Registry, a Model Router and an Execution
Continuity Manager. At the start of this phase:

- No provider/model runtime existed (no Ollama, no cloud SDK, no
  `ModelProvider` implementation) — real provider integrations belong to
  later phases.
- The Kernel already declares frozen service ABCs —
  `autoforge_kernel.interfaces.ModelRouter` and
  `autoforge_kernel.interfaces.ExecutionContinuityManager` — which nothing
  implemented. Per Kernel v1.0 governance, the Kernel cannot know any
  concrete platform; dependencies must be injected from outside.
- ADR-002 fixed the Runtime State Manager as the sole authority for durable
  state including checkpoints; ADR-001 fixed `autoforge_events` as the one
  canonical event vocabulary; ADR-003 reserved model-context assembly for
  Context Engineering.
- The platform philosophy is local-first (LOCAL deployment preferred,
  offline-capable).

Forces: build provider abstraction now with zero vendor coupling, keep every
previously frozen foundation intact, keep routing reproducible and
unit-testable, and keep resilience behaviour separate from selection.

---

## Decision

A new package, `packages/ai_infrastructure`
(`autoforge_ai_infrastructure`), is added with three components and three
structural ports. The composition root remains the sole place where
components are constructed and injected.

1. **Capability Registry — metadata only.**
   `InMemoryCapabilityRegistry` implements the abstract
   `CapabilityRegistryPort`. It stores provider/model/capability/deployment
   metadata with strict duplicate protection, provider-level availability
   gating and deterministically ordered query results (`query_models()`
   sorted by `model_id`). It NEVER routes, executes, retries or fails over.
   Providers, models and capabilities are ordinary registered *data* —
   string-identified entities added at runtime; no vendor name appears in
   any module of the package.

2. **Model Router — selection only.**
   `ModelRouterService(registry, default_policy=None, *,
   decision_log_size, clock)` takes the registry and an optional routing
   policy; when omitted it falls back to `LocalFirstRoutingPolicy`.
   Routing is hard-filter (registry `query_models`) then rank
   (pure-function policy scoring; deterministic tie-break by cost then
   `model_id`). It returns a `RoutingDecision` carrying the selected
   candidate PLUS all ranked alternatives — this IS the failover order.
   The router never retries, fails over or executes anything. Policies form
   an open set (`BUILTIN_POLICIES` plus arbitrary custom `RoutingPolicy`
   implementations); `offline_only` is a hard constraint restricting
   selection to locally executable modes.

3. **Execution Continuity Manager — resilience only.**
   `ExecutionContinuityService(router, executors, *, retry_policy,
   classifier, checkpoints, events, sleeper)` walks the ranked candidate
   chain; per candidate it retries retryable failures up to
   `RetryPolicy.max_attempts` with deterministic exponential backoff
   clamped by `max_backoff_seconds`; when retries are exhausted it records
   retry exhaustion and FAILOVERS to the next candidate, incrementing
   failovers per provider switch. All-candidates exhaustion raises
   `FailoverExhaustedError` carrying the full attempt history — failures
   are surfaced, never swallowed. Backoff sleeps go through the injectable
   async `sleeper`, keeping tests deterministic.

4. **Structural ports for cross-package boundaries (no reverse imports).**
   - `RuntimeCheckpointPort` mirrors the Runtime State Manager's checkpoint
     API structurally; this package imports NO runtime module. ADR-002's
     ownership stands: composition adapts `RuntimeStateManager` → port via
     `autoforge_composition.RuntimeCheckpointAdapter`.
   - `CanonicalEventSink` publishes ONLY frozen `autoforge_events` types
     (no new EventTypes); continuity facts map onto `FAILURE_DETECTED`,
     `RECOVERY_STARTED`, `SERVICE_DEGRADED`, `RECOVERY_COMPLETED`,
     `RECOVERY_FAILED`, `CHECKPOINT_RESTORED` with structured detail in
     event metadata.
   - `ModelExecutor` protocol + `ExecutorRegistry` form the seam where real
     provider adapters plug in during future provider integration; Phase 7
     ships no concrete executor (deterministic test doubles satisfy the
     protocol).

5. **Kernel dependency inversion via adapters.**
   `KernelModelRouter` implements the Kernel's `ModelRouter` ABC
   (`select_model` / `get_model_capabilities` / `get_provider_health`,
   producing canonical-domain `ModelProfile`s); `KernelContinuityManager`
   implements the Kernel's `ExecutionContinuityManager` ABC (`retry` /
   `failover` / `restore_checkpoint` / `recover`) over the platform
   services. `autoforge_ai_infrastructure` depends on `autoforge-kernel`
   interfaces only, never the reverse.

6. **Composition root wiring.**
   `autoforge_composition.build_ai_infrastructure(*, runtime,
   default_policy=None, retry_policy=None, event_sink=None,
   sleeper=None)` constructs registry (+ non-normative reference catalog),
   router, executor registry, checkpoint adapter, event factory and
   continuity service, returning an `AIInfrastructureServices` handle that
   exposes both raw services and Kernel-facing adapters. Policy, retry
   policy, executor bindings and providers remain caller-owned
   configuration points: swapping local/cloud providers or routing policies
   requires no change to the composition root beyond registration and
   injection.

7. **Determinism.** Scores are pure functions of `(model, provider,
   request)`; ordering ties break deterministically; backoff is clamped;
   all sleeps route through the injectable sleeper.

---

## Consequences

Positive:

- Future provider integrations implement `ModelExecutor` (plus register
  metadata) WITHOUT architectural change to the composition root, Kernel or
  router.
- Local-first/offline behaviour and cross-provider failover are directly
  enforced and validated (hard-filtered routing plus candidate-chain
  continuity).
- Kernel v1.0 interfaces gain real implementations while the Kernel stays
  untouched and unaware of the platform.
- Single checkpoint system (Runtime) and single event vocabulary preserved
  — no duplication of either.

Costs / risks:

- No real provider adapter exists yet: end-to-end execution is exercised
  with deterministic test doubles behind the `ModelExecutor` protocol until
  provider integration lands.
- Selection is metadata-driven: live health/cost reality must be fed back
  via status updates; stale metadata degrades routing quality.
- The shipped reference catalog (`reference-local`, `reference-cloud`) is
  generic NON-NORMATIVE seed data used by tests and demo wiring; operators
  must register their own providers.
- `PreservedExecutionContext` instances are held in-process keyed by
  `execution_id`; durability comes only through the Runtime checkpoint
  port.

---

## Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Couple concrete provider SDKs directly | Violates vendor-agnostic/local-first constraint; roadmap defers connectors to later phases; SDK churn would leak into architecture |
| Let the Model Router also own retries/failover | Conflates selection with resilience; ARCHITECTURE.md assigns retry/failover/checkpoint-recovery to the Execution Continuity Manager |
| Give the package its own checkpoint store and event types | Contradicts ADR-001 (one canonical vocabulary) and ADR-002 (Runtime owns durable state); would create parallel systems |
| Assemble model-facing prompts in preserved context | Competes with Context Engineering (ADR-003); preserved context intentionally limited to resume state |