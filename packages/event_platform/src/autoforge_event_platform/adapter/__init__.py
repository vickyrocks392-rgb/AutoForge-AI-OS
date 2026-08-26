"""Canonical-event adapter for the AutoForge Event Platform.

This package is the SINGLE sanctioned bridge between the canonical domain
event vocabulary (:mod:`autoforge_events`) and the Event Platform's
transport infrastructure.

Ownership rules (see ADR-001):

- ``autoforge_events`` owns the event vocabulary and payloads (domain
  semantics).
- ``autoforge_event_platform`` owns delivery, routing, ordering, retries,
  DLQ, replay and schemas (transport semantics).
- This adapter translates between the two and deliberately does NOT let the
  platform define or reinterpret domain meaning.
"""

from autoforge_event_platform.adapter.canonical_adapter import (
    CANONICAL_CATEGORY_TO_TRANSPORT,
    CanonicalEventBus,
    CanonicalTransportError,
    from_transport_event,
    to_transport_event,
)

__all__ = [
    "CANONICAL_CATEGORY_TO_TRANSPORT",
    "CanonicalEventBus",
    "CanonicalTransportError",
    "from_transport_event",
    "to_transport_event",
]