"""
Checkpoint Contracts for Modernization.

Establishes the data model for ModernizationCheckpoint — the immutable
snapshot that enables:
- Resuming from the last checkpoint without restarting
- Tracking exact progress (wave, unit, LOC processed)
- Integrity verification (checksum)
- Evidence tracking

Checkpointing in 18-G builds on autoforge_runtime's CheckpointManager.
This module defines the ModernizationCheckpoint data model.

Reuses:
- autoforge_runtime: Checkpoint (canonical runtime checkpoint)
- units: MigrationUnit, MigrationWave
"""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CheckpointType(str, Enum):
    """Type of modernization checkpoint."""

    WAVE_START = "wave_start"
    """Checkpoint at the start of a migration wave."""

    UNIT_BOUNDARY = "unit_boundary"
    """Checkpoint after completing a migration unit."""

    PRE_TRANSFORMATION = "pre_transformation"
    """Checkpoint before transformation (planning gate passed)."""

    POST_TRANSFORMATION = "post_transformation"
    """Checkpoint after transformation."""

    PERIODIC = "periodic"
    """Periodic checkpoint during long-running transformation."""

    EMERGENCY = "emergency"
    """Emergency checkpoint on process interruption."""


class CheckpointState(str, Enum):
    """State of a checkpoint."""

    CREATED = "created"
    """Checkpoint data is complete but not yet persisted."""

    PERSISTED = "persisted"
    """Checkpoint is written to the persistence layer."""

    VERIFIED = "verified"
    """Checkpoint integrity has been verified."""

    CORRUPTED = "corrupted"
    """Checkpoint integrity check failed."""


class ModernizationCheckpoint(BaseModel):
    """
    An immutable snapshot of the modernization state.

    Enables resume from exact position without restarting the entire project.
    Each checkpoint captures:
    - Current position (job, wave, unit, component, file)
    - LOC accounting (processed, remaining)
    - Artifact IDs produced so far
    - Evidence collected
    - State snapshot for full reconstruction
    """

    checkpoint_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str

    # Position
    wave_index: int
    wave_id: str
    unit_id: str | None = None
    component_id: str | None = None
    current_operation: str = ""

    # LOC accounting at checkpoint time
    loc_processed: int = 0
    loc_remaining: int = 0
    files_processed: int = 0
    files_remaining: int = 0

    # Produced artifacts
    artifacts_created: list[str] = Field(default_factory=list)
    evidence_collected: list[str] = Field(default_factory=list)

    # State snapshot (serialized state needed for resume)
    state_snapshot: dict[str, Any] = Field(default_factory=dict)

    # Type and state
    checkpoint_type: CheckpointType = CheckpointType.PERIODIC
    state: CheckpointState = CheckpointState.CREATED

    # Integrity
    checksum: str = ""
    """SHA-256 of the serialized state for integrity verification."""

    # Timing
    created_at: datetime = Field(default_factory=_utc_now)
    previous_checkpoint_id: str | None = None

    def compute_checksum(self, serialized_state: str) -> str:
        """Compute SHA-256 checksum of the checkpoint state."""
        self.checksum = hashlib.sha256(serialized_state.encode()).hexdigest()
        return self.checksum

    def verify(self, serialized_state: str) -> bool:
        """Verify the checkpoint integrity."""
        expected = hashlib.sha256(serialized_state.encode()).hexdigest()
        return self.checksum == expected


class CheckpointedProgress(BaseModel):
    """
    The progress that has been checkpointed.

    This is the resume position — what has been done and what remains.
    """

    checkpoint_id: str
    project_id: str
    job_id: str

    wave_index: int
    unit_id: str | None = None

    loc_processed: int = 0
    loc_remaining: int = 0
    files_processed: int = 0

    artifacts_created: list[str] = Field(default_factory=list)
    evidence_collected: list[str] = Field(default_factory=list)

    checkpointed_at: datetime | None = None
    checkpoint_type: CheckpointType = CheckpointType.PERIODIC
