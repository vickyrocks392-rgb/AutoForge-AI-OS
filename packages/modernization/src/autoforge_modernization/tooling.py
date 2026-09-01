"""
Specialist Tooling Contract and Inventory.

Defines the interface through which later 18-G stages register and use
specialist tooling (parsers, compilers, analyzers, refactoring engines).

This is NOT a package installer. It defines the tool registration model
and the inventory state. Actual toolchain installation is triggered by
the CapabilityGap workflow in G.2+.

Reuses:
- capability_registry: TechnologyCapabilityRegistry
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


# ── Tool Purpose ──────────────────────────────────────────────────────────────


class ToolPurpose(str, Enum):
    """What a specialist tool is used for."""

    PARSER = "parser"
    AST_TOOLING = "ast_tooling"
    COMPILER_INTERPRETER = "compiler_interpreter"
    STATIC_ANALYZER = "static_analyzer"
    REFACTORING_ENGINE = "refactoring_engine"
    MIGRATION_ASSISTANT = "migration_assistant"
    DEPENDENCY_ANALYZER = "dependency_analyzer"
    SQL_PARSER = "sql_parser"
    ARCHITECTURE_ANALYZER = "architecture_analyzer"
    VERIFICATION_TOOL = "verification_tool"


class ToolCapability(str, Enum):
    """What a tool can do in the modernization pipeline."""

    ANALYSIS = "analysis"
    TRANSFORMATION = "transformation"
    VERIFICATION = "verification"


class ToolDeterminism(str, Enum):
    """Whether the tool produces deterministic or heuristic results."""

    DETERMINISTIC = "deterministic"
    HEURISTIC = "heuristic"


class InstallationState(str, Enum):
    """State of a tool's installation."""

    NOT_FOUND = "not_found"
    FOUND = "found"
    VERIFIED = "verified"
    FAILED = "failed"


# ── Specialist Tool Record ──────────────────────────────────────────────────


class SpecialistTool(BaseModel):
    """
    Canonical record of a registered specialist tool.

    Each tool registration includes its purpose, capability, installation
    state, and limitations. Tools are registered by G.2+ tooling inventory.
    """

    tool_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    name: str
    version: str | None = None
    technology: str

    purpose: list[ToolPurpose]
    capability: list[ToolCapability]
    determinism: ToolDeterminism = ToolDeterminism.DETERMINISTIC

    license_type: str = "unknown"
    license_notes: str = ""

    local_offline_capable: bool = True
    requires_network: bool = False

    installation_state: InstallationState = InstallationState.NOT_FOUND
    installed_at: datetime | None = None
    verified_at: datetime | None = None
    verification_error: str | None = None

    verification_command: str | None = None
    expected_version_pattern: str | None = None

    limitations: list[str] = Field(default_factory=list)
    resource_requirements: dict[str, Any] = Field(default_factory=dict)

    registered_at: datetime = Field(default_factory=_utc_now)
    registered_by: str = "autoforge-core"
    source: str = ""

    def is_installed(self) -> bool:
        return self.installation_state in (
            InstallationState.FOUND,
            InstallationState.VERIFIED,
        )

    def is_verified(self) -> bool:
        return self.installation_state == InstallationState.VERIFIED

    def mark_verified(self) -> None:
        self.installation_state = InstallationState.VERIFIED
        self.verified_at = _utc_now()

    def mark_failed(self, error: str) -> None:
        self.installation_state = InstallationState.FAILED
        self.verified_at = _utc_now()
        self.verification_error = error


# ── Specialist Tooling Inventory ─────────────────────────────────────────────


class SpecialistToolingInventory(BaseModel):
    """
    Inventory of all registered specialist tools.

    This is the central registry of tooling. It supports:
    - Tool registration (by G.2+ tooling discovery)
    - Tool verification (G.2+ installation workflow)
    - Capability gap resolution (G.1 contract)
    - Tool lookup by technology or purpose

    This is NOT a package installer. It tracks tool state.
    """

    inventory_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    tools: dict[str, SpecialistTool] = Field(default_factory=dict)
    last_updated: datetime = Field(default_factory=_utc_now)

    def register(self, tool: SpecialistTool) -> None:
        """Register a new tool or update an existing one."""
        self.tools[tool.name] = tool
        self.last_updated = _utc_now()

    def get(self, tool_name: str) -> SpecialistTool | None:
        """Get a tool by name."""
        return self.tools.get(tool_name)

    def find_by_technology(self, technology: str) -> list[SpecialistTool]:
        """Find all tools that handle a specific technology."""
        return [t for t in self.tools.values() if t.technology == technology]

    def find_by_purpose(self, purpose: ToolPurpose) -> list[SpecialistTool]:
        """Find all tools with a specific purpose."""
        return [t for t in self.tools.values() if purpose in t.purpose]

    def find_by_capability(self, capability: ToolCapability) -> list[SpecialistTool]:
        """Find all tools with a specific capability."""
        return [t for t in self.tools.values() if capability in t.capability]

    def verified_tools(self) -> list[SpecialistTool]:
        """Return all verified tools."""
        return [t for t in self.tools.values() if t.is_verified()]

    def unverified_tools(self) -> list[SpecialistTool]:
        """Return all tools that are not verified."""
        return [t for t in self.tools.values() if not t.is_verified()]
