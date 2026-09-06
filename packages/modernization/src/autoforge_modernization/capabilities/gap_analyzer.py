"""Generalized Capability Gap Analyzer for AutoForge.

Enforces Section 6 of the architectural mandate:
PROJECT REQUIREMENTS -> REQUIRED CAPABILITIES -> AVAILABLE CAPABILITIES -> CAPABILITY GAP

Every required capability resolves to an honest, evidence-backed state:
- AVAILABLE
- QUALIFIED
- ACQUIRABLE
- PARTIAL
- SPECIALIST_REQUIRED
- UNAVAILABLE

Do NOT falsely claim capability support.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityQualificationRecord,
    CapabilityRequirement,
    CapabilityState,
    _utc_now,
)
from autoforge_modernization.capabilities.providers import (
    ProviderRegistry,
    SpecialistTechnologyProvider,
    VerifiedTechnologyProvider,
)


class CapabilityGapItem(BaseModel):
    """Evaluation record of a single required capability against available providers."""

    item_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology: str
    capability_class: CapabilityClass
    capability_name: str
    description: str
    state: CapabilityState
    level: CapabilityLevel = CapabilityLevel.NONE
    mandatory: bool = True
    provider_id: str | None = None
    provider_name: str | None = None
    version_detected: str | None = None
    remediation_hint: str = ""
    is_blocking: bool = False
    evidence: list[str] = Field(default_factory=list)
    qualification_record: CapabilityQualificationRecord | None = None


class CapabilityGapAnalysisReport(BaseModel):
    """The complete capability gap assessment for a project and target specification."""

    report_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    target_technology: str = ""
    generated_at: datetime = Field(default_factory=_utc_now)
    items: list[CapabilityGapItem] = Field(default_factory=list)

    @property
    def has_blocking_gaps(self) -> bool:
        return any(item.is_blocking for item in self.items)

    @property
    def operational_capabilities(self) -> list[CapabilityGapItem]:
        return [item for item in self.items if CapabilityState.is_operational(item.state)]

    @property
    def acquirable_capabilities(self) -> list[CapabilityGapItem]:
        return [item for item in self.items if item.state == CapabilityState.ACQUIRABLE]

    @property
    def specialist_required_capabilities(self) -> list[CapabilityGapItem]:
        return [item for item in self.items if item.state == CapabilityState.SPECIALIST_REQUIRED]

    @property
    def unavailable_capabilities(self) -> list[CapabilityGapItem]:
        return [item for item in self.items if item.state == CapabilityState.UNAVAILABLE]

    def summary(self) -> dict[str, Any]:
        return {
            "total_requirements": len(self.items),
            "operational": len(self.operational_capabilities),
            "acquirable": len(self.acquirable_capabilities),
            "specialist_required": len(self.specialist_required_capabilities),
            "unavailable": len(self.unavailable_capabilities),
            "has_blocking_gaps": self.has_blocking_gaps,
        }


class CapabilityGapAnalyzer:
    """Evaluates required capabilities against registered verified providers."""

    def __init__(self, provider_registry: ProviderRegistry | None = None) -> None:
        self.provider_registry = provider_registry or ProviderRegistry()

    def analyze(
        self,
        requirements: list[CapabilityRequirement],
        project_id: str = "project-default",
        target_technology: str = "",
    ) -> CapabilityGapAnalysisReport:
        items: list[CapabilityGapItem] = []

        for req in requirements:
            item = self._evaluate_requirement(req)
            items.append(item)

        return CapabilityGapAnalysisReport(
            project_id=project_id,
            target_technology=target_technology,
            items=items,
        )

    def _evaluate_requirement(self, req: CapabilityRequirement) -> CapabilityGapItem:
        candidate_providers = self.provider_registry.find_for_requirement(req)

        if not candidate_providers:
            # Check if this technology is inherently a specialist technology
            if req.technology.upper() in ("IMS", "ASSEMBLER", "HLASM"):
                return CapabilityGapItem(
                    technology=req.technology,
                    capability_class=req.capability_class,
                    capability_name=req.capability_name,
                    description=req.description,
                    state=CapabilityState.SPECIALIST_REQUIRED,
                    level=CapabilityLevel.DETECT,
                    mandatory=req.mandatory,
                    remediation_hint="Requires specialist intervention; cannot automate safely with current open-source tooling.",
                    is_blocking=req.mandatory,
                    evidence=["No automated provider registered for specialist technology"],
                )

            return CapabilityGapItem(
                technology=req.technology,
                capability_class=req.capability_class,
                capability_name=req.capability_name,
                description=req.description,
                state=CapabilityState.UNAVAILABLE,
                level=CapabilityLevel.NONE,
                mandatory=req.mandatory,
                remediation_hint=req.remediation_hint or "No known provider available for this requirement.",
                is_blocking=req.mandatory,
                evidence=["No provider registered"],
            )

        # Evaluate candidate providers
        for provider in candidate_providers:
            if isinstance(provider, SpecialistTechnologyProvider):
                return CapabilityGapItem(
                    technology=req.technology,
                    capability_class=req.capability_class,
                    capability_name=req.capability_name,
                    description=req.description,
                    state=CapabilityState.SPECIALIST_REQUIRED,
                    level=CapabilityLevel.DETECT,
                    mandatory=req.mandatory,
                    provider_id=provider.provider_id,
                    provider_name=provider.display_name,
                    remediation_hint=provider.rationale,
                    is_blocking=req.mandatory,
                    evidence=[provider.description, provider.rationale],
                )

            # Check if physical tool is discovered on host
            if not provider.is_tool_discovered():
                recipe = provider.get_acquisition_recipe()
                return CapabilityGapItem(
                    technology=req.technology,
                    capability_class=req.capability_class,
                    capability_name=req.capability_name,
                    description=req.description,
                    state=CapabilityState.ACQUIRABLE,
                    level=CapabilityLevel.NONE,
                    mandatory=req.mandatory,
                    provider_id=provider.provider_id,
                    provider_name=provider.display_name,
                    remediation_hint=f"Acquirable via: {recipe.get('command', 'open-source installer')}",
                    is_blocking=req.mandatory,
                    evidence=[f"Tool not discovered on PATH. Acquisition recipe available: {recipe.get('source_url', '')}"],
                )

            # Tool is discovered! Run deterministic qualification fixtures
            qualification_records = provider.qualify()
            matching_record = next(
                (r for r in qualification_records if r.capability_name == req.capability_name),
                qualification_records[0] if qualification_records else None,
            )

            if matching_record and matching_record.passed:
                # Fully qualified and operational!
                return CapabilityGapItem(
                    technology=req.technology,
                    capability_class=req.capability_class,
                    capability_name=req.capability_name,
                    description=req.description,
                    state=CapabilityState.QUALIFIED,
                    level=req.minimum_level,
                    mandatory=req.mandatory,
                    provider_id=provider.provider_id,
                    provider_name=provider.display_name,
                    version_detected=matching_record.qualified_version or provider.get_version(),
                    is_blocking=False,
                    evidence=matching_record.evidence or [f"Qualified via fixture: {matching_record.fixture_name}"],
                    qualification_record=matching_record,
                )
            else:
                # Tool exists on disk but failed qualification (e.g., macOS /usr/bin/javac shim)
                err = matching_record.error_message if matching_record else "Qualification failed"
                recipe = provider.get_acquisition_recipe()
                return CapabilityGapItem(
                    technology=req.technology,
                    capability_class=req.capability_class,
                    capability_name=req.capability_name,
                    description=req.description,
                    state=CapabilityState.ACQUIRABLE,
                    level=CapabilityLevel.NONE,
                    mandatory=req.mandatory,
                    provider_id=provider.provider_id,
                    provider_name=provider.display_name,
                    version_detected=provider.get_version(),
                    remediation_hint=f"Tool present but failed qualification: {err}. Re-acquire or configure via: {recipe.get('command', '')}",
                    is_blocking=req.mandatory,
                    evidence=[f"Discovered but unverified: {err}"],
                    qualification_record=matching_record,
                )

        return CapabilityGapItem(
            technology=req.technology,
            capability_class=req.capability_class,
            capability_name=req.capability_name,
            description=req.description,
            state=CapabilityState.UNAVAILABLE,
            level=CapabilityLevel.NONE,
            mandatory=req.mandatory,
            is_blocking=req.mandatory,
            evidence=["All candidate providers failed qualification"],
        )
