# AutoForge Composition Root

The foundational composition root for the AutoForge AI platform.

It constructs and injects:

- the **Kernel** (`autoforge_kernel`) — orchestrator,
- the **Runtime State Manager** (`autoforge_runtime`) — authoritative state,
- canonical **domain events** (`autoforge_events`),
- the **Event Platform** (`autoforge_event_platform`) — transport.

This package owns wiring only. It contains no business logic and grants no
subsystem new responsibilities. See `docs/adr/ADR-001` and `ADR-002`.
