"""
Event model — a domain event emitted during execution.

Events are the primary mechanism for communication between subsystems.
They represent something that happened in the domain and can be
consumed by event handlers, observers, and the event bus.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from pydantic import Field

from autoforge_models.base import AutoForgeBaseModel
from autoforge_models.enums import EventType


class Event(AutoForgeBaseModel):
    """
    A domain event emitted during execution.

    .. deprecated::
        This model is a legacy, weaker event vocabulary retained only for
        backwards compatibility with early domain-model consumers. The
        CANONICAL event contract for AutoForge is ``autoforge_events``
        (``BaseEvent`` + ``EventType``/``EventCategory``). New code MUST
        publish and consume canonical events; the Event Platform transports
        them via its adapter boundary (see ADR-001).

    Events capture something that happened in the platform. They are
    immutable records that can be published to an event bus, stored
    in an event log, or used to trigger side effects.
    """

    event_type: EventType = Field(
        ...,
        description="The type/category of the event.",
    )
    source: str = Field(
        ...,
        min_length=1,
        max_length=256,
        description="Identifier of the subsystem or component that emitted the event.",
    )
    subject_id: uuid.UUID | None = Field(
        default=None,
        description="UUID of the domain object this event is about.",
    )
    subject_type: str | None = Field(
        default=None,
        max_length=64,
        description="Type name of the domain object (e.g. 'Task', 'Artifact').",
    )
    project_id: uuid.UUID | None = Field(
        default=None,
        description="UUID of the related Project, if applicable.",
    )
    data: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific payload data.",
    )
    timestamp: datetime = Field(
        default_factory=datetime.now,
        description="When the event occurred.",
    )
    correlation_id: uuid.UUID | None = Field(
        default=None,
        description="UUID for correlating related events across subsystems.",
    )
    causation_id: uuid.UUID | None = Field(
        default=None,
        description="UUID of the event that caused this event (causation chain).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata key-value store.",
    )