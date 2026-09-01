"""
Machine-readable AutoForge Technology Capability Registry.

Establishes the authoritative registry of what AutoForge can and cannot
process for legacy modernization. Each technology has an explicit
capability state — not just "supported" but the specific capability
level and what's required to reach a higher level.

This is NOT a package installer. It defines the capability model.
Actual toolchain installation is handled by SpecialistToolingInventory
in later 18-G stages after the capability gap is identified.

Reuses:
- autoforge_workforce: LegacySystemModel (for technology detection results)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Capability State ────────────────────────────────────────────────────────


class CapabilityState(str, Enum):
    """
    The current capability level for a given technology.

    These states form a progression. AutoForge should never claim a
    technology is SUPPORTED if it cannot actually process it.
    """

    UNKNOWN = "unknown"
    """Technology has not been evaluated yet."""

    SUPPORTED = "supported"
    """AutoForge has verified analysis, transformation, and verification capability."""

    PARTIALLY_SUPPORTED = "partially_supported"
    """AutoForge can analyze or partially transform, but not fully verify."""

    TOOL_REQUIRED = "tool_required"
    """A specialist tool is needed to reach SUPPORTED. Tool not yet installed."""

    ENVIRONMENT_REQUIRED = "environment_required"
    """A specific runtime environment is needed."""

    MODEL_REQUIRED = "model_required"
    """A specific model capability or fine-tune is needed."""

    UNSUPPORTED = "unsupported"
    """AutoForge cannot modernize this technology with current tooling."""

    @classmethod
    def is_sufficient(cls, state: CapabilityState) -> bool:
        """Return True if the state is sufficient for transformation."""
        return state in (cls.SUPPORTED, cls.PARTIALLY_SUPPORTED)

    @classmethod
    def is_blocking(cls, state: CapabilityState) -> bool:
        """Return True if the state blocks transformation."""
        return state in (
            cls.TOOL_REQUIRED,
            cls.ENVIRONMENT_REQUIRED,
            cls.MODEL_REQUIRED,
            cls.UNSUPPORTED,
            cls.UNKNOWN,
        )


# ── Capability Level ─────────────────────────────────────────────────────────


class CapabilityLevel(str, Enum):
    """
    What AutoForge can actually do with a technology.
    """

    NONE = "none"
    """Cannot detect or analyze."""

    DETECT = "detect"
    """Can detect the technology exists (extension/content heuristics)."""

    ANALYZE = "analyze"
    """Can extract symbols, structure, dependencies (requires parser/AST)."""

    PARTIAL_TRANSFORM = "partial_transform"
    """Can transform some code patterns but not all."""

    FULL_TRANSFORM = "full_transform"
    """Can transform the full language feature set."""

    VERIFY = "verify"
    """Can verify transformed code (compilation, tests, behavioral)."""

    EQUIVALENCE_CHECK = "equivalence_check"
    """Can check behavioral equivalence between source and target."""


# ── Technology Capability Record ────────────────────────────────────────────


class TechnologyCapability(BaseModel):
    """
    Canonical record of AutoForge's capability for a single technology.

    This is the fundamental unit of the technology capability registry.
    Each record is self-contained and versioned.
    """

    capability_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology_name: str
    version: str | None = None
    language_family: str | None = None

    # Capability state
    state: CapabilityState = CapabilityState.UNKNOWN
    level: CapabilityLevel = CapabilityLevel.NONE

    # What is actually possible
    can_analyze: bool = False
    can_transform: bool = False
    can_verify: bool = False
    can_check_equivalence: bool = False

    # Requirements to reach higher capability
    required_tool: str | None = None
    required_environment: str | None = None
    required_model_capability: str | None = None
    resource_requirements: dict[str, Any] = Field(default_factory=dict)

    # Local/offline support
    local_offline_capable: bool = True

    # Limitations
    limitations: list[str] = Field(default_factory=list)
    known_gaps: list[str] = Field(default_factory=list)

    # Confidence in this assessment
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    assessment_method: str = "manual"

    # Provenance
    assessed_at: datetime = Field(default_factory=_utc_now)
    assessed_by: str = "autoforge-core"
    evidence: list[str] = Field(default_factory=list)

    # Tooling links
    registered_tool_name: str | None = None

    # Version tracking
    version_note: str = ""

    def requires_action(self) -> bool:
        """Return True if this capability requires human action to improve."""
        return self.state in (
            CapabilityState.TOOL_REQUIRED,
            CapabilityState.ENVIRONMENT_REQUIRED,
            CapabilityState.MODEL_REQUIRED,
            CapabilityState.UNSUPPORTED,
            CapabilityState.UNKNOWN,
        )

    def can_proceed(self) -> bool:
        """Return True if modernization can proceed at current capability level."""
        return self.state in (
            CapabilityState.SUPPORTED,
            CapabilityState.PARTIALLY_SUPPORTED,
        )



# ── Technology Capability Registry ────────────────────────────────────────────


class TechnologyCapabilityRegistry(BaseModel):
    """
    The authoritative registry of AutoForge's technology capabilities.

    This is the central source of truth for what AutoForge can and cannot
    process. It is NOT a package manager — it defines the model that
    later stages use to determine what to install and how to proceed.
    """

    registry_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    version: str = "1.0.0"
    capabilities: dict[str, TechnologyCapability] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=_utc_now)
    total_technologies: int = 0

    def register(self, capability: TechnologyCapability) -> None:
        """Register or update a technology capability."""
        key = self._make_key(capability.technology_name, capability.version)
        self.capabilities[key] = capability
        self._recalc_total()

    def get(
        self,
        technology: str,
        version: str | None = None,
    ) -> TechnologyCapability | None:
        """Get the capability record for a technology."""
        key = self._make_key(technology, version)
        if key in self.capabilities:
            return self.capabilities[key]
        return self.capabilities.get(technology)

    def get_state(
        self,
        technology: str,
        version: str | None = None,
    ) -> CapabilityState:
        """Get the capability state for a technology (UNKNOWN if not found)."""
        cap = self.get(technology, version)
        return cap.state if cap else CapabilityState.UNKNOWN

    def all_unsupported(self) -> list[TechnologyCapability]:
        """Return all technologies that are blocking transformation."""
        return [
            cap for cap in self.capabilities.values()
            if CapabilityState.is_blocking(cap.state)
        ]

    def all_gap_technologies(self) -> list[TechnologyCapability]:
        """Return all technologies that require action."""
        return [
            cap for cap in self.capabilities.values()
            if cap.requires_action()
        ]

    def _make_key(self, technology: str, version: str | None) -> str:
        return f"{technology}:{version}" if version else technology

    def _recalc_total(self) -> None:
        self.total_technologies = len(self.capabilities)
        self.last_updated = _utc_now()