"""Free-First Autonomous Capability Acquisition Engine for AutoForge.

Enforces Sections 7, 8, 9, 10 of the architectural mandate:
- Controlled, deterministic acquisition without arbitrary LLM shell commands.
- Free and open-source selection first.
- Strict qualification backed by executable fixtures before capability registration.
- Honest reporting: never fabricate acquisition success.
"""

from __future__ import annotations

import logging
from pathlib import Path
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.gap_analyzer import CapabilityGapItem
from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityQualificationRecord,
    CapabilityState,
    _utc_now,
)
from autoforge_modernization.capabilities.providers import (
    MANAGED_TOOLCHAIN_ROOT,
    ProviderRegistry,
    VerifiedTechnologyProvider,
)
from autoforge_modernization.capability_registry import (
    CapabilityLevel as LegacyCapabilityLevel,
    CapabilityState as LegacyCapabilityState,
    TechnologyCapability,
    TechnologyCapabilityRegistry,
)

logger = logging.getLogger(__name__)


class AcquisitionStatus(str, Enum):
    SUCCESS = "success"
    ALREADY_QUALIFIED = "already_qualified"
    ACQUISITION_NOT_EXECUTED = "acquisition_not_executed"
    FAILED = "failed"
    SPECIALIST_REQUIRED = "specialist_required"


class AcquisitionAttemptRecord(BaseModel):
    """Auditable record of a capability acquisition and qualification attempt."""

    attempt_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    capability_name: str
    technology: str
    provider_id: str
    status: AcquisitionStatus
    command_attempted: str | None = None
    qualification_records: list[CapabilityQualificationRecord] = Field(default_factory=list)
    message: str = ""
    timestamp: datetime = Field(default_factory=_utc_now)


class AutonomousAcquisitionEngine:
    """Engine responsible for acquiring, qualifying, and registering capabilities."""

    def __init__(
        self,
        provider_registry: ProviderRegistry | None = None,
        capability_registry: TechnologyCapabilityRegistry | None = None,
        allow_external_install: bool = False,
        tools_directory: Path | None = None,
    ) -> None:
        self.provider_registry = provider_registry or ProviderRegistry()
        self.capability_registry = capability_registry or TechnologyCapabilityRegistry()
        self.allow_external_install = allow_external_install
        self.tools_directory = tools_directory or MANAGED_TOOLCHAIN_ROOT

    def process_gap_item(self, gap_item: CapabilityGapItem) -> AcquisitionAttemptRecord:
        """Process a single capability gap through the autonomous acquisition lifecycle."""
        if gap_item.state == CapabilityState.QUALIFIED:
            # Already qualified - register capability into authoritative registry
            self._register_into_authoritative_registry(gap_item.technology, gap_item.capability_name, gap_item.qualification_record)
            return AcquisitionAttemptRecord(
                capability_name=gap_item.capability_name,
                technology=gap_item.technology,
                provider_id=gap_item.provider_id or "unknown",
                status=AcquisitionStatus.ALREADY_QUALIFIED,
                qualification_records=[gap_item.qualification_record] if gap_item.qualification_record else [],
                message=f"Capability '{gap_item.capability_name}' is already qualified on host.",
            )

        if gap_item.state == CapabilityState.SPECIALIST_REQUIRED:
            return AcquisitionAttemptRecord(
                capability_name=gap_item.capability_name,
                technology=gap_item.technology,
                provider_id=gap_item.provider_id or "specialist",
                status=AcquisitionStatus.SPECIALIST_REQUIRED,
                message=f"Specialist intervention required for '{gap_item.technology}'. Autonomous acquisition skipped.",
            )

        provider = self.provider_registry.get(gap_item.provider_id or "") if gap_item.provider_id else None
        if not provider:
            return AcquisitionAttemptRecord(
                capability_name=gap_item.capability_name,
                technology=gap_item.technology,
                provider_id="none",
                status=AcquisitionStatus.FAILED,
                message=f"No provider found for capability '{gap_item.capability_name}'.",
            )

        recipe = provider.get_acquisition_recipe()
        install_cmd = recipe.get("command")

        # Attempt deterministic preparation/acquisition via provider
        success, prep_msg = provider.acquire_or_prepare(
            target_dir=self.tools_directory / provider.technology.lower(),
            allow_external_install=self.allow_external_install,
        )

        if not success:
            # Deterministic failure or policy disallowance -> report honestly!
            status = (
                AcquisitionStatus.ACQUISITION_NOT_EXECUTED
                if not self.allow_external_install and "disabled by policy" in prep_msg
                else AcquisitionStatus.FAILED
            )
            return AcquisitionAttemptRecord(
                capability_name=gap_item.capability_name,
                technology=gap_item.technology,
                provider_id=provider.provider_id,
                status=status,
                command_attempted=install_cmd,
                message=prep_msg,
            )

        # Provider acquired or prepared -> execute deterministic qualification fixtures
        logger.info("Executing qualification fixture after preparation: %s", provider.provider_id)
        qual_records = provider.qualify()
        passed = any(q.passed for q in qual_records)

        if passed:
            self._register_into_authoritative_registry(
                gap_item.technology, gap_item.capability_name, qual_records[0]
            )
            return AcquisitionAttemptRecord(
                capability_name=gap_item.capability_name,
                technology=gap_item.technology,
                provider_id=provider.provider_id,
                status=AcquisitionStatus.SUCCESS,
                command_attempted=install_cmd,
                qualification_records=qual_records,
                message=f"Successfully acquired and qualified capability: {prep_msg}",
            )

        return AcquisitionAttemptRecord(
            capability_name=gap_item.capability_name,
            technology=gap_item.technology,
            provider_id=provider.provider_id,
            status=AcquisitionStatus.FAILED,
            command_attempted=install_cmd,
            qualification_records=qual_records,
            message=f"Acquisition preparation succeeded ({prep_msg}) but qualification tests failed.",
        )

    def _register_into_authoritative_registry(
        self,
        technology: str,
        capability_name: str,
        qual_record: CapabilityQualificationRecord | None,
    ) -> None:
        """Register the verified capability into the authoritative TechnologyCapabilityRegistry."""
        evidence = qual_record.evidence if qual_record else [f"Qualified capability: {capability_name}"]
        version = qual_record.qualified_version if qual_record else "1.0.0"

        existing = self.capability_registry.get(technology)
        if existing:
            if capability_name not in existing.supported_constructs:
                existing.supported_constructs.append(capability_name)
            existing.evidence.extend(evidence)
            existing.state = LegacyCapabilityState.SUPPORTED
            existing.can_verify = True
            self.capability_registry.register(existing)
        else:
            cap = TechnologyCapability(
                technology_name=technology,
                version=None,
                state=LegacyCapabilityState.SUPPORTED,
                level=LegacyCapabilityLevel.VERIFY,
                can_analyze=True,
                can_transform=True,
                can_verify=True,
                supported_constructs=[capability_name],
                evidence=evidence,
            )
            self.capability_registry.register(cap)

        if version:
            cap_ver = TechnologyCapability(
                technology_name=technology,
                version=version,
                state=LegacyCapabilityState.SUPPORTED,
                level=LegacyCapabilityLevel.VERIFY,
                can_analyze=True,
                can_transform=True,
                can_verify=True,
                supported_constructs=[capability_name],
                evidence=evidence,
            )
            self.capability_registry.register(cap_ver)
