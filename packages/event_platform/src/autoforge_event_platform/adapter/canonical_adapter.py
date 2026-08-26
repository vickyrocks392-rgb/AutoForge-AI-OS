"""Translator between canonical domain events and platform transport events.

Canonical contract: :mod:`autoforge_events` (frozen ``BaseEvent`` +
``EventType``/``EventCategory`` enums).

Transport contract: :mod:`autoforge_event_platform.models.event` (``Event``).

The adapter guarantees:

- Round-trip fidelity — a canonical event translated to transport and back
  yields an equivalent canonical event (identity, type, category, timestamps,
  correlation/causation, aggregate, schema version and metadata).
- No silent semantic loss — a canonical event type with no transport
  representation raises :class:`CanonicalTransportError` instead of being
  silently remapped.
- The transport never becomes a second domain-event authority — all domain
  semantics stay in the canonical payload/envelope.
"""

from __future__ import annotations

import uuid
from typing import Any, Callable, Iterable

from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory as CanonicalCategory
from autoforge_events.event_types import EventType as CanonicalEventType

from autoforge_event_platform.core.event_bus import EventBus
from autoforge_event_platform.models.event import (
    Event as TransportEvent,
)
from autoforge_event_platform.models.event import (
    EventCategory as TransportCategory,
)
from autoforge_event_platform.models.event import (
    EventType as TransportEventType,
)
from autoforge_event_platform.models.event import (
    PublicationResult,
    SubscriptionRequest,
)
from autoforge_event_platform.persistence.schema_registry import SchemaRegistry

__all__ = [
    "CANONICAL_CATEGORY_TO_TRANSPORT",
    "CanonicalTransportError",
    "to_transport_event",
    "from_transport_event",
    "canonical_category_to_transport",
    "resolve_transport_event_type",
    "CanonicalEventBus",
]

# Reserved payload key preserving the exact canonical envelope across the
# transport. The transport treats it as opaque data.
_CANONICAL_ENVELOPE_KEY = "_canonical"

#: Explicit, documented mapping from canonical categories to transport
#: categories. Identity entries are omitted. Where the transport vocabulary
#: has no equivalent, the closest *transport-level* category is used for
#: routing only; the original category is preserved in the envelope.
CANONICAL_CATEGORY_TO_TRANSPORT: dict[CanonicalCategory, TransportCategory] = {
    CanonicalCategory.SYSTEM_EVENT: TransportCategory.INFRASTRUCTURE,
    CanonicalCategory.SERVICE: TransportCategory.INFRASTRUCTURE,
    CanonicalCategory.FAILURE: TransportCategory.RECOVERY,
    CanonicalCategory.LOOP: TransportCategory.WORKFLOW,
}

_IDENTITY_CATEGORIES = {
    CanonicalCategory.PROJECT: TransportCategory.PROJECT,
    CanonicalCategory.TASK: TransportCategory.TASK,
    CanonicalCategory.EXECUTION: TransportCategory.EXECUTION,
    CanonicalCategory.ARTIFACT: TransportCategory.ARTIFACT,
    CanonicalCategory.MEMORY: TransportCategory.MEMORY,
    CanonicalCategory.APPROVAL: TransportCategory.APPROVAL,
    CanonicalCategory.REVIEW: TransportCategory.REVIEW,
    CanonicalCategory.CHECKPOINT: TransportCategory.CHECKPOINT,
}


class CanonicalTransportError(Exception):
    """A canonical event cannot be represented on the transport."""


def transport_category_for_type(
    transport_type: TransportEventType,
    schema_registry: SchemaRegistry | None = None,
) -> TransportCategory:
    """
    Determine the transport category the platform expects for a type.

    The transport's own schema registry is the single authority for
    type/category coherence on the wire; the static fallback below is used
    only for types without a registered schema.
    """
    if schema_registry is not None:
        schema = schema_registry.get_schema(transport_type)
        if schema is not None:
            return schema.category

    prefix = transport_type.value.split(".", 1)[0]
    try:
        return TransportCategory(prefix)
    except ValueError:
        return TransportCategory.INFRASTRUCTURE


def canonical_category_to_transport(
    category: CanonicalCategory,
) -> TransportCategory:
    """Map a canonical event category onto the transport vocabulary."""
    mapped = _IDENTITY_CATEGORIES.get(category) or CANONICAL_CATEGORY_TO_TRANSPORT.get(
        category
    )
    if mapped is None:
        raise CanonicalTransportError(
            f"Canonical event category {category!r} has no transport mapping"
        )
    return mapped


def resolve_transport_event_type(
    event_type: CanonicalEventType,
    category: CanonicalCategory,
) -> TransportEventType:
    """
    Resolve the transport event type for a canonical event type.

    Resolution order:

    1. Exact dotted-value match (e.g. ``"project.created"``).
    2. Legacy flat verb prefixed with its canonical category
       (e.g. ``("created", PROJECT) → "project.created"``).
    3. Failure — raise :class:`CanonicalTransportError`.
    """
    value = event_type.value
    try:
        return TransportEventType(value)
    except ValueError:
        pass

    prefixed = f"{category.value}.{value}"
    try:
        return TransportEventType(prefixed)
    except ValueError:
        raise CanonicalTransportError(
            f"Canonical event type {value!r} (category {category.value!r}) "
            f"cannot be represented in the transport vocabulary"
        ) from None

def to_transport_event(
    event: BaseEvent,
    *,
    source: str = "autoforge",
    schema_registry: SchemaRegistry | None = None,
) -> TransportEvent:
    """
    Translate a canonical domain event into a platform transport event.

    Args:
        event: The canonical domain event.
        source: Identifier of the emitting component.
        schema_registry: Optional transport schema registry consulted for the
            expected wire category (keeps type/category coherence).

    Returns:
        An immutable transport Event carrying an opaque canonical envelope.
    """
    transport_type = resolve_transport_event_type(event.event_type, event.event_category)
    schema_category = transport_category_for_type(transport_type, schema_registry)
    if schema_category is not None:
        transport_category: TransportCategory = schema_category
    else:
        transport_category = canonical_category_to_transport(event.event_category)

    envelope: dict[str, Any] = {
        "event_type": event.event_type.value,
        "category": event.event_category.value,
        "version": event.version,
    }

    return TransportEvent(
        event_id=event.event_id,
        event_type=transport_type,
        event_category=transport_category,
        source=source,
        timestamp=event.occurred_at,
        version=f"{event.version}.0.0",
        correlation_id=event.correlation_id or uuid.uuid4(),
        causation_id=event.causation_id,
        aggregate_id=event.aggregate_id,
        aggregate_type=event.aggregate_type,
        payload={
            _CANONICAL_ENVELOPE_KEY: envelope,
            "metadata": dict(event.metadata),
        },
    )


def from_transport_event(transport: TransportEvent) -> BaseEvent:
    """
    Rebuild a canonical domain event from a platform transport event.

    Uses the reserved canonical envelope when present; otherwise falls back
    to best-effort reconstruction from transport fields.
    """
    envelope = transport.payload.get(_CANONICAL_ENVELOPE_KEY)
    metadata = dict(transport.payload.get("metadata", {}))

    if isinstance(envelope, dict):
        type_value = str(envelope.get("event_type", transport.event_type.value))
        category_value = str(envelope.get("category", ""))
        version = int(envelope.get("version", 1))
    else:
        type_value = transport.event_type.value
        category_value = ""
        version = int(str(transport.version).split(".")[0] or 1)

    try:
        canonical_type = CanonicalEventType(type_value)
    except ValueError:
        raise CanonicalTransportError(
            f"Transport event type {type_value!r} has no canonical counterpart"
        ) from None

    if category_value:
        try:
            canonical_category = CanonicalCategory(category_value)
        except ValueError:
            raise CanonicalTransportError(
                f"Transport category {category_value!r} has no canonical counterpart"
            ) from None
    else:
        # Best-effort inverse using the canonical type's own dotted prefix.
        prefix = type_value.split(".", 1)[0]
        try:
            canonical_category = CanonicalCategory(prefix)
        except ValueError:
            canonical_category = CanonicalCategory.SYSTEM_EVENT

    return BaseEvent(
        event_id=transport.event_id,
        event_type=canonical_type,
        event_category=canonical_category,
        occurred_at=transport.timestamp,
        correlation_id=transport.correlation_id,
        causation_id=transport.causation_id,
        aggregate_id=transport.aggregate_id,
        aggregate_type=transport.aggregate_type,
        version=max(1, version),
        metadata=metadata,
    )


class CanonicalEventBus:
    """
    Publish/subscribe facade over the platform bus speaking ONLY canonical
    domain events.

    Subscribers receive reconstructed canonical :class:`BaseEvent` instances;
    they never see transport internals. This class contains no business
    logic — it is pure boundary plumbing.
    """

    def __init__(
        self,
        bus: EventBus,
        *,
        default_source: str = "autoforge",
        schema_registry: SchemaRegistry | None = None,
    ) -> None:
        """Wrap an existing platform event bus."""
        self._bus = bus
        self._default_source = default_source
        self._schema_registry = schema_registry

    @property
    def bus(self) -> EventBus:
        """The underlying transport bus (for platform-level operations)."""
        return self._bus

    def publish(self, event: BaseEvent) -> PublicationResult:
        """Publish a canonical event through the transport."""
        return self._bus.publish(
            to_transport_event(
                event,
                source=self._default_source,
                schema_registry=self._schema_registry,
            )
        )

    def subscribe(
        self,
        handler: Callable[[BaseEvent], None],
        *,
        event_types: Iterable[CanonicalEventType] | None = None,
        categories: Iterable[CanonicalCategory] | None = None,
    ) -> str:
        """
        Subscribe to canonical events.

        Args:
            handler: Called with the canonical event on delivery.
            event_types: Restrict delivery to these canonical types.
            categories: Restrict delivery to these canonical categories.

        Returns:
            The transport subscription identifier.
        """
        transport_types: list[TransportEventType] | None = None
        if event_types is not None:
            transport_types = [
                resolve_transport_event_type(t, _category_for_type(t))
                for t in event_types
            ]

        transport_categories: list[TransportCategory] | None = None
        if categories is not None:
            transport_categories = [
                canonical_category_to_transport(c) for c in categories
            ]

        request = SubscriptionRequest(
            event_types=transport_types,
            event_categories=transport_categories,
            callback=lambda transport_event: handler(
                from_transport_event(transport_event)
            ),
        )
        subscription_id, _status = self._bus.subscribe(request)
        return subscription_id

    def unsubscribe(self, subscription_id: str) -> bool:
        """Remove a subscription."""
        return self._bus.unsubscribe(subscription_id)


def _category_for_type(event_type: CanonicalEventType) -> CanonicalCategory:
    """Infer a canonical category from a canonical event type's prefix."""
    if "." not in event_type.value:
        # Legacy flat verbs carry no prefix; treat them as system events for
        # transport-resolution purposes only.
        return CanonicalCategory.SYSTEM_EVENT
    prefix = event_type.value.split(".", 1)[0]
    try:
        return CanonicalCategory(prefix)
    except ValueError:
        return CanonicalCategory.SYSTEM_EVENT
