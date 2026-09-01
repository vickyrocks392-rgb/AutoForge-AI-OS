"""
Project Sizing and LOC Metrics Models.

Establishes machine-readable project sizing models. These are NOT just `wc -l`
output — they allow multiple counting methods, source-of-truth tracking,
and hierarchical decomposition (by language, component, module).

Reuses:
- jobs: ModernizationJob (via job_id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class LOCCountingMethod(str, Enum):
    """
    Method used to count lines of code.

    Different methods produce different results. The contract requires
    multiple methods and source-of-truth designation.
    """

    PHYSICAL_LINES = "physical_lines"
    """Count all non-empty, non-comment lines. Standard wc -l."""

    LOGICAL_LINES = "logical_lines"
    """Count executable statements (language-dependent)."""

    LOGICAL_COBOL = "logical_cobol"
    """COBOL logical statements (paragraphs/sections)."""

    GENERATED_EXCLUDED = "generated_excluded"
    """Physical lines excluding generated code."""

    COPYBOOK_INCLUDED = "copybook_included"
    """Physical lines including COBOL copybooks."""

    COPYBOOK_EXCLUDED = "copybook_excluded"
    """Physical lines excluding COBOL copybooks."""

    JCL_PROCEDURES = "jcl_procedures"
    """JCL procedure steps (EXEC PGM=)."""

    DBTABLED = "dbtable_ed"
    """DB2 DDL statements."""

    MANUAL_AUDIT = "manual_audit"
    """Manually audited LOC count."""

    SEMANTIC_UNITS = "semantic_units"
    """Abstract semantic units (functions, programs, screens)."""

    UNKNOWN = "unknown"


class LOCMetrics(BaseModel):
    """
    Machine-readable LOC and sizing metrics for a modernization project.

    This is NOT a simple line count. It tracks:
    - Multiple counting methods
    - Breakdown by language and component
    - Whether this is the authoritative source
    - How it was derived
    """

    metrics_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str | None = None

    # Summary counts
    total_physical_loc: int = 0
    logical_loc: int | None = None
    active_loc: int | None = None  # Excluding generated, boilerplate
    generated_loc: int | None = None
    test_loc: int | None = None
    comments_loc: int | None = None
    blank_lines: int | None = None

    # Counts
    total_files: int = 0
    total_modules: int = 0
    total_components: int = 0

    # Breakdown
    loc_by_language: dict[str, int] = Field(default_factory=dict)
    loc_by_component: dict[str, int] = Field(default_factory=dict)

    # Dependency complexity
    dependency_complexity_score: float = 0.0  # e.g., cyclomatic complexity average

    # Counting method used for primary count
    primary_counting_method: LOCCountingMethod = LOCCountingMethod.UNKNOWN

    # Is this the authoritative source-of-truth?
    is_source_of_truth: bool = False
    source_of_truth_method: LOCCountingMethod | None = None
    source_of_truth_notes: str = ""

    # Accounting details
    copybook_loc: int | None = None
    jcl_proc_loc: int | None = None
    sql_loc: int | None = None
    db2_ddl_loc: int | None = None
    screens_forms_loc: int | None = None

    # Provenance
    counting_method: LOCCountingMethod = LOCCountingMethod.UNKNOWN
    counted_at: datetime = Field(default_factory=_utc_now)
    counted_by: str = "autoforge-core"
    source_artifact_id: str | None = None

    # Confidence
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    notes: str = ""

    def cross_validate(
        self,
        other_method: LOCCountingMethod,
        other_count: int,
        tolerance_percent: float = 10.0,
    ) -> bool:
        """
        Check if another LOC count is within tolerance of this one.

        Used to detect inconsistent counting methods.
        """
        if self.total_physical_loc == 0:
            return False
        diff_pct = abs(self.total_physical_loc - other_count) / self.total_physical_loc * 100
        return diff_pct <= tolerance_percent
