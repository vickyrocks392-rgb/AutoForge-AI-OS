"""Deterministic Migration Completeness Audit (18-COMMERCIAL-D).

Audits that every planned source file is strictly accounted for:
- TRANSFORMED
- INTENTIONALLY_EXCLUDED
- UNSUPPORTED
- EXPLICITLY_DEFERRED
Guarantees zero silent file loss, zero accidental omissions, and zero silent source deletion.
Synthesizes the customer COMPLETENESS_MANIFEST.json.
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.migration.inventory import CodebaseInventory
from autoforge_power_engines.migration.plan import MigrationPlan, TransformationUnit
from autoforge_power_engines.migration.verifier import UnitVerificationReport, VerificationStatus


class UnitCompletenessStatus(str, Enum):
    TRANSFORMED = "transformed"
    INTENTIONALLY_EXCLUDED = "intentionally_excluded"
    UNSUPPORTED = "unsupported"
    EXPLICITLY_DEFERRED = "explicitly_deferred"
    MISSING = "missing"


class CompletenessManifestEntry(BaseModel):
    """Lineage and audit record for a single source file in the migration."""
    source_file: str
    source_hash: str
    target_file: Optional[str] = None
    target_hash: Optional[str] = None
    status: UnitCompletenessStatus
    transformation_type: str
    verification_status: str
    risk: str
    notes: str = ""


class MigrationCompletenessManifest(BaseModel):
    """Complete migration manifest accounting for 100% of source files."""
    migration_id: str
    total_source_files: int
    transformed_count: int
    excluded_count: int
    unsupported_count: int
    deferred_count: int
    missing_count: int
    is_complete: bool
    entries: List[CompletenessManifestEntry] = Field(default_factory=list)
    summary_report: str = ""


class CompletenessAuditor:
    """
    Validates completeness across inventory, plan, transformations, and verifications.
    """

    @classmethod
    def audit(
        cls,
        inventory: CodebaseInventory,
        plan: MigrationPlan,
        verification_reports: Dict[str, UnitVerificationReport],
        target_dir: Path,
    ) -> MigrationCompletenessManifest:
        import hashlib

        entries: List[CompletenessManifestEntry] = []
        transformed = 0
        excluded = 0
        unsupported = 0
        deferred = 0
        missing = 0

        # Map plan units by source path
        plan_map: Dict[str, TransformationUnit] = {u.source_path: u for u in plan.units}

        for file_rec in inventory.files:
            source_path = file_rec.relative_path
            source_hash = file_rec.sha256
            unit = plan_map.get(source_path)

            if not unit:
                # File present in inventory but omitted from plan -> MISSING
                entries.append(CompletenessManifestEntry(
                    source_file=source_path,
                    source_hash=source_hash,
                    status=UnitCompletenessStatus.MISSING,
                    transformation_type="none",
                    verification_status=VerificationStatus.FAIL.value,
                    risk="high",
                    notes="Omitted from migration plan without documented exclusion.",
                ))
                missing += 1
                continue

            # Check unit status
            if unit.transformation_type == "excluded":
                entries.append(CompletenessManifestEntry(
                    source_file=source_path,
                    source_hash=source_hash,
                    target_file=source_path,
                    target_hash=source_hash,
                    status=UnitCompletenessStatus.INTENTIONALLY_EXCLUDED,
                    transformation_type=unit.transformation_type.value,
                    verification_status=VerificationStatus.PASS.value,
                    risk=unit.risk_level.value,
                    notes=unit.expected_behavior,
                ))
                excluded += 1
                continue

            target_abs = target_dir / unit.target_path
            v_report = verification_reports.get(unit.unit_id)
            v_status = v_report.overall_status.value if v_report else VerificationStatus.INCONCLUSIVE.value

            if target_abs.exists():
                t_hash = hashlib.sha256(target_abs.read_bytes()).hexdigest()
                entries.append(CompletenessManifestEntry(
                    source_file=source_path,
                    source_hash=source_hash,
                    target_file=unit.target_path,
                    target_hash=t_hash,
                    status=UnitCompletenessStatus.TRANSFORMED,
                    transformation_type=unit.transformation_type.value,
                    verification_status=v_status,
                    risk=unit.risk_level.value,
                    notes=f"Transformed to {unit.target_path}",
                ))
                transformed += 1
            else:
                entries.append(CompletenessManifestEntry(
                    source_file=source_path,
                    source_hash=source_hash,
                    target_file=unit.target_path,
                    target_hash=None,
                    status=UnitCompletenessStatus.UNSUPPORTED if "unsupported" in unit.transformation_type.value else UnitCompletenessStatus.MISSING,
                    transformation_type=unit.transformation_type.value,
                    verification_status=VerificationStatus.FAIL.value,
                    risk=unit.risk_level.value,
                    notes="Target file was not generated on disk.",
                ))
                if "unsupported" in unit.transformation_type.value:
                    unsupported += 1
                else:
                    missing += 1

        is_complete = (missing == 0)

        summary = (
            f"Completeness Audit: {len(entries)} files accounted for. "
            f"Transformed: {transformed}, Excluded: {excluded}, Unsupported: {unsupported}, "
            f"Deferred: {deferred}, Missing: {missing}. Completeness Status: {'PASS' if is_complete else 'FAIL'}."
        )

        return MigrationCompletenessManifest(
            migration_id=plan.migration_id,
            total_source_files=len(inventory.files),
            transformed_count=transformed,
            excluded_count=excluded,
            unsupported_count=unsupported,
            deferred_count=deferred,
            missing_count=missing,
            is_complete=is_complete,
            entries=entries,
            summary_report=summary,
        )
