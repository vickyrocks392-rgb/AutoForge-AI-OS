# ADR-001: Canonical Event Vocabulary and Event Platform Boundary

**Date:** 2026-08-26

**Status:** Accepted

---

#### Context

The repository contained THREE parallel event vocabularies (verified by the
Architecture Alignment Validation and `docs/AUTONOMOUS_WORKER_ARCHITECTURE_RECONCILIATION.md`
§10):

1. `autoforge_events` — frozen immutable `BaseEvent` + ~90 dot-notation
   `EventType` values; consumed by the Kernel.
2. `autoforge_event_platform.models.event` — a second `Event` model with its
   own 155-value `EventType`; used exclusively inside the Event Platform,
   which had zero external importers ("island").
3. `autoforge_models.Event` + `enums.EventType` — a third, weaker vocabulary.

Building any further subsystem on this substrate would hard-wire duplication
forever. The Phase 0 mission requires ONE canonical contract with the Event
Platform functioning strictly as transport/routing/delivery infrastructure.

---

#### Decision

1. **`autoforge_events` is THE canonical event vocabulary** of AutoForge
   (decision D3(a) of the reconciliation audit). All subsystems publish and
   consume canonical `BaseEvent` instances carrying `EventType`,
   `EventCategory`, correlation/causation IDs, aggregate identity, schema
   version, timestamp and metadata.

2. **A single sanctioned adapter** —
   `autoforge_event_platform.adapter.canonical_adapter` — translates between
   the canonical contract and the transport model:
   - `to_transport_event()` / `from_transport_event()` guarantee round-trip
     fidelity via an opaque canonical envelope carried in the transport
     payload.
   - Type resolution maps canonical dotted types onto the transport enum;
     legacy flat verbs resolve as `<category>.<verb>`; untranslatable types
     raise `CanonicalTransportError` instead of being silently re-typed.
   - Wire-level type/category coherence is taken from the transport's own
     `SchemaRegistry`, which remains the authority for transport schemas.
   - `CanonicalEventBus` exposes publish/subscribe speaking ONLY canonical
     events; subscribers never see transport internals.

3. **The Event Platform keeps transport ownership only**: delivery, routing,
   ordering, priority, retries, DLQ, replay, schemas. It MUST NOT define or
   reinterpret domain meaning, and MUST NOT become a second domain-event
   authority.

4. **`autoforge_models.Event` / `enums.EventType` are DEPRECATED** (docstring
   notices added). They remain functional for existing domain-model tests but
   must not be used by new code.

5. **Additive canonical extension**: `EventCategory.CHECKPOINT`,
   `EventType.CHECKPOINT_CREATED` and `EventType.CHECKPOINT_DELETED` were
   added to `autoforge_events` (backwards compatible; no renames) so runtime
   checkpoint operations can be expressed canonically.
   `CHECKPOINT_RESTORED` already existed.

---

#### Consequences

Positive:

- One event language across Kernel, Runtime, and all future subsystems.
- The previously isolated Event Platform becomes usable without importing
  its models anywhere else in the platform.
- Round-trip fidelity is test-enforced; semantic loss fails loudly.

Negative / limitations:

- The adapter adds one translation step on the publish/delivery path.
- Canonical categories without a transport equivalent map to documented
  transport-level categories for ROUTING ONLY; the original category is
  preserved in the envelope.

---

#### Alternatives Considered

| Alternative | Reason for Rejection |
|---|---|
| Migrate everything onto the Event Platform's `Event` model | Would dethrone the frozen canonical vocabulary and force mass renames; rejected by audit D3 |
| Keep three vocabularies and translate ad hoc at each call site | Multiplies duplication; no single source of truth |
| Delete the Event Platform | Discards the only mature pub/sub infrastructure (routing/DLQ/replay); wasteful |