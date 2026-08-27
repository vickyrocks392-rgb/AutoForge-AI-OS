"""Artifact event emission — Phase 12.

Uses the FROZEN autoforge_events vocabulary ONLY. No new event types are
introduced. Event emission failures never break artifact operations.

Design rules
------------
- Reuses ``ARTIFACT_CREATED``, ``ARTIFACT_UPDATED`` from frozen vocabulary.
- Preserves ``correlation_id``, ``artifact_id``, ``version_id``, ``project_id``.
- Safe emission: exceptions are swallowed to never break artifact operations.
- No new event types are created.
"""

from __future__ import annotations

import uuid
from typing import Any, Protocol

from autoforge_events.artifact_events import ArtifactCreated, ArtifactUpdated
from autoforge_events.base import BaseEvent


class ArtifactEventSinkProtocol(Protocol):
    """Protocol for event sinks that receive artifact events."""

    def publish(self, event: Any) -> None: ...


class ArtifactEvents:
    """Emits canonical artifact events using the frozen vocabulary."""

    def __init__(self, sink: ArtifactEventSinkProtocol | None = None) -> None:
        self._sink = sink

    def _safe_publish(self, event: BaseEvent) -> None:
        if self._sink is None:
            return
        try:
            self._sink.publish(event)
        except Exception:
            # Event emission failures must never break artifact operations.
            pass

    def emit_artifact_created(
        self,
        *,
        artifact_id: uuid.UUID,
        artifact_name: str,
        artifact_type: str,
        project_id: uuid.UUID | None = None,
        version_id: uuid.UUID | None = None,
        file_path: str | None = None,
        size_bytes: int | None = None,
        content_hash: str | None = None,
        correlation_id: uuid.UUID | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Emit an ARTIFACT_CREATED event."""
        try:
            event = ArtifactCreated(
                aggregate_id=artifact_id,
                project_id=project_id or uuid.uuid4(),
                artifact_name=artifact_name,
                artifact_type=artifact_type,
                file_path=file_path,
                size_bytes=size_bytes,
                content_hash=content_hash,
                correlation_id=correlation_id,
            )
            self._safe_publish(event)
        except Exception:
            pass

    def emit_artifact_versioned(
        self,
        *,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        version_number: int,
        project_id: uuid.UUID | None = None,
        content_hash: str | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        """Emit an ARTIFACT_UPDATED event for a new version."""
        try:
            event = ArtifactUpdated(
                aggregate_id=artifact_id,
                project_id=project_id or uuid.uuid4(),
                updated_fields=["version"],
                new_values={
                    "version_id": str(version_id),
                    "version_number": version_number,
                },
                new_content_hash=content_hash,
                correlation_id=correlation_id,
            )
            self._safe_publish(event)
        except Exception:
            pass

    def emit_artifact_published(
        self,
        *,
        artifact_id: uuid.UUID,
        version_id: uuid.UUID,
        destination: str,
        project_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        """Emit an ARTIFACT_UPDATED event for a publication."""
        try:
            event = ArtifactUpdated(
                aggregate_id=artifact_id,
                project_id=project_id or uuid.uuid4(),
                updated_fields=["state", "publication"],
                new_values={
                    "state": "published",
                    "version_id": str(version_id),
                    "destination": destination,
                },
                correlation_id=correlation_id,
            )
            self._safe_publish(event)
        except Exception:
            pass

    def emit_artifact_rolled_back(
        self,
        *,
        artifact_id: uuid.UUID,
        from_version_id: uuid.UUID,
        to_version_id: uuid.UUID,
        new_version_id: uuid.UUID,
        project_id: uuid.UUID | None = None,
        correlation_id: uuid.UUID | None = None,
    ) -> None:
        """Emit an ARTIFACT_UPDATED event for a rollback."""
        try:
            event = ArtifactUpdated(
                aggregate_id=artifact_id,
                project_id=project_id or uuid.uuid4(),
                updated_fields=["version", "rollback"],
                previous_values={
                    "version_id": str(from_version_id),
                },
                new_values={
                    "version_id": str(new_version_id),
                    "rollback_target": str(to_version_id),
                },
                correlation_id=correlation_id,
            )
            self._safe_publish(event)
        except Exception:
            pass
