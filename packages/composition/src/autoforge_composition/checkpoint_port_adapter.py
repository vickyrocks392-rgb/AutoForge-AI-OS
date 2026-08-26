"""Runtime checkpoint port adapter.

Adapts :class:`autoforge_runtime.RuntimeStateManager` to the
:class:`autoforge_ai_infrastructure.RuntimeCheckpointPort` protocol.

This is the dependency-inversion boundary that lets the Execution Continuity
Manager delegate durable checkpoint operations to the frozen Runtime State
Manager (ADR-002: Runtime remains authoritative for durable state). The adapter
translates between the string-based port contract and the Runtime's enum-based
API.

No second checkpoint system is created here — the Runtime is the sole authority.
"""

from __future__ import annotations

import uuid
from typing import Any

from autoforge_runtime.models import CheckpointType, RestoreType


class RuntimeCheckpointAdapter:
    """Structural adapter: Runtime State Manager → ``RuntimeCheckpointPort``."""

    def __init__(self, runtime: Any) -> None:
        self._runtime = runtime

    def create_checkpoint(
        self,
        project_id: uuid.UUID,
        checkpoint_type: str,
        label: str | None = None,
        description: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> uuid.UUID:
        """Delegate to the Runtime's ``create_checkpoint``."""
        cp = self._runtime.create_checkpoint(
            project_id,
            CheckpointType(checkpoint_type),
            label=label,
            description=description,
            metadata=metadata,
        )
        return getattr(cp, "checkpoint_id", cp)

    def restore_checkpoint(
        self,
        checkpoint_id: uuid.UUID,
        restore_type: str = "full",
    ) -> Any:
        """Delegate to the Runtime's ``restore_checkpoint``."""
        result = self._runtime.restore_checkpoint(
            checkpoint_id,
            RestoreType(restore_type),
        )
        return result

    def get_checkpoint_history(self, project_id: uuid.UUID) -> list[Any]:
        """Delegate to the Runtime's ``get_checkpoint_history``."""
        return self._runtime.get_checkpoint_history(project_id)