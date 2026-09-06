"""Canonical Capability Models for Generalized Autonomous Capability Expansion.

Establishes the first-class taxonomy of capabilities across:
- SOURCE_UNDERSTANDING
- SEMANTIC_KNOWLEDGE
- TARGET_GENERATION
- TARGET_VERIFICATION
- SUPPORTING_TOOLING

And their lifecycle states:
- AVAILABLE
- QUALIFIED
- ACQUIRABLE
- PARTIAL
- SPECIALIST_REQUIRED
- UNAVAILABLE
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class CapabilityClass(str, Enum):
    """Fundamentally different capability categories in AutoForge."""

    SOURCE_UNDERSTANDING = "source_understanding"
    """Capabilities required to understand an input project (parsers, AST, copybooks, call graphs)."""

    SEMANTIC_KNOWLEDGE = "semantic_knowledge"
    """Capabilities that operate across technologies (normalization, business rules, architecture)."""

    TARGET_GENERATION = "target_generation"
    """Capabilities required to emit a target implementation (code generation, project layout)."""

    TARGET_VERIFICATION = "target_verification"
    """Capabilities required to verify target artifacts (compilers, typecheckers, test harnesses)."""

    SUPPORTING_TOOLING = "supporting_tooling"
    """Supporting tools (linters, formatters, database clients, emulators, transcoders)."""


class CapabilityState(str, Enum):
    """Canonical lifecycle state of a capability."""

    AVAILABLE = "available"
    """Capability already exists and is qualified on the host."""

    QUALIFIED = "qualified"
    """Capability has been deterministically verified via executable qualification fixture."""

    ACQUIRABLE = "acquirable"
    """A known free/open-source provider can obtain/install it safely."""

    PARTIAL = "partial"
    """Some functionality exists but feature coverage is incomplete."""

    SPECIALIST_REQUIRED = "specialist_required"
    """The system can detect/represent the requirement but cannot safely automate it without a specialist."""

    UNAVAILABLE = "unavailable"
    """No known safe free/open-source implementation/provider currently exists."""

    @classmethod
    def is_operational(cls, state: CapabilityState) -> bool:
        """Return True if capability is ready for execution."""
        return state in (cls.AVAILABLE, cls.QUALIFIED)

    @classmethod
    def is_blocking(cls, state: CapabilityState) -> bool:
        """Return True if capability blocks execution without remediation."""
        return state in (cls.SPECIALIST_REQUIRED, cls.UNAVAILABLE, cls.ACQUIRABLE)


class CapabilityLevel(str, Enum):
    """Depth of capability provided."""

    NONE = "none"
    DETECT = "detect"
    ANALYZE = "analyze"
    PARTIAL_TRANSFORM = "partial_transform"
    FULL_TRANSFORM = "full_transform"
    VERIFY = "verify"
    EQUIVALENCE_CHECK = "equivalence_check"


class CapabilityProvenance(BaseModel):
    """Provenance tracking where a capability originated and how it was verified."""

    provider_id: str
    source_url: str = ""
    license_type: str = "open_source"
    installed_at: datetime = Field(default_factory=_utc_now)
    installed_version: str = ""
    platform: str = ""
    verification_hash: str = ""
    is_free_open_source: bool = True


class CapabilityQualificationFixture(BaseModel):
    """Deterministic test fixture executed to qualify a provider capability."""

    fixture_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    description: str
    input_payload: str
    expected_output_pattern: str | None = None
    assertion_type: str = "exit_code_zero"  # exit_code_zero | output_match | ast_node_count
    timeout_seconds: float = 15.0


class CapabilityQualificationRecord(BaseModel):
    """Proof that a capability was qualified by executing a real fixture."""

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    provider_id: str
    capability_name: str
    technology: str
    qualified_version: str = ""
    qualified_at: datetime = Field(default_factory=_utc_now)
    passed: bool
    execution_time_ms: float = 0.0
    command_executed: str | None = None
    fixture_name: str = ""
    output_snippet: str = ""
    error_message: str | None = None
    evidence: list[str] = Field(default_factory=list)


class CapabilityRequirement(BaseModel):
    """A requirement for a specific capability demanded by a technology or target."""

    requirement_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology: str
    capability_class: CapabilityClass
    capability_name: str
    description: str = ""
    mandatory: bool = True
    minimum_level: CapabilityLevel = CapabilityLevel.ANALYZE
    constraints: dict[str, Any] = Field(default_factory=dict)
    remediation_hint: str = ""


class QualifiedCapability(BaseModel):
    """A verified, qualified capability ready for workflow composition."""

    capability_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    capability_class: CapabilityClass
    technology: str
    version: str = ""
    state: CapabilityState = CapabilityState.QUALIFIED
    level: CapabilityLevel = CapabilityLevel.ANALYZE
    provider_id: str
    provenance: CapabilityProvenance
    qualification_record: CapabilityQualificationRecord
    limitations: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
