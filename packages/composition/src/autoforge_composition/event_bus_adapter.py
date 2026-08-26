"""Kernel-facing event bus adapter.

Implements the Kernel's ``EventBus`` ABC on top of the canonical event
transport (:class:`autoforge_event_platform.adapter.CanonicalEventBus`).

This is the ONLY place where the Kernel's synchronous-callback delivery is
bridged onto the transport; the Kernel itself never imports the Event
Platform.
"""

from __future__ import annotations

import asyncio
import inspect
import uuid
from collections.abc import Coroutine
from typing import Any, Callable

from autoforge_events.base import BaseEvent as DomainBaseEvent
from autoforge_events.event_types import EventType

from autoforge_event_platform.adapter import CanonicalEventBus

from autoforge_kernel.interfaces import EventBus


class CanonicalKernelEventBus(EventBus):
    """Adapts canonical transport deliveries to the Kernel's bus contract."""

    def __init__(self, canonical_bus: CanonicalEventBus) -> None:
        """Wrap the canonical event transport."""
        self._canonical_bus = canonical_bus
        self._subscription_ids: dict[str, uuid.UUID] = {}
        self._reverse_ids: dict[uuid.UUID, str] = {}

    async def publish(self, event: DomainBaseEvent) -> None:
        """Publish a canonical event; reject if the transport refuses it."""
        result = self._canonical_bus.publish(event)
        if result.status.value != "accepted":
            raise RuntimeError(
                f"Event {event.event_type} was not accepted by the event "
                f"transport (status={result.status.value}, "
                f"errors={getattr(result, 'errors', None)})"
            )

    async def subscribe(
        self,
        event_types: list[EventType],
        handler: Callable[[DomainBaseEvent], Coroutine[Any, Any, None]],
    ) -> uuid.UUID:
        """Subscribe with a coroutine handler; returns a Kernel-visible ID."""

        def _on_delivery(delivered: DomainBaseEvent) -> None:
            outcome = handler(delivered)
            if inspect.iscoroutine(outcome):
                # Delivery happens inside the publisher's running loop.
                asyncio.get_running_loop().create_task(outcome)

        transport_id = self._canonical_bus.subscribe(_on_delivery, event_types=event_types)
        try:
            kernel_id = uuid.UUID(str(transport_id))
        except ValueError:
            kernel_id = uuid.uuid4()
        self._subscription_ids[transport_id] = kernel_id
        self._reverse_ids[kernel_id] = transport_id
        return kernel_id

    async def unsubscribe(self, subscription_id: uuid.UUID) -> None:
        """Remove a previously created subscription."""
        transport_id = self._reverse_ids.pop(subscription_id, None)
        if transport_id is not None:
            self._subscription_ids.pop(transport_id, None)
            self._canonical_bus.unsubscribe(transport_id)