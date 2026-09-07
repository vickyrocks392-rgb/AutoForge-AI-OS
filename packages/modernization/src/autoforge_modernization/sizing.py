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


def calculate_source_nloc_accounting(files: list[Any]) -> dict[str, Any]:
    """Authoritative, unified NLOC accounting engine adhering to language standards."""
    import hashlib
    from pathlib import Path

    file_records = []
    total_physical_loc = 0
    total_blank_loc = 0
    total_comment_loc = 0
    total_executable_nloc = 0
    total_declarative_nloc = 0

    for file_item in files:
        f_path = Path(file_item) if isinstance(file_item, (str, Path)) else Path(getattr(file_item, "path", str(file_item)))
        content = f_path.read_text(errors="ignore") if f_path.exists() else ""
        lines = content.splitlines()
        ext = f_path.suffix.lower()

        phys_loc = len(lines)
        blank_loc = 0
        comment_loc = 0
        exec_nloc = 0
        decl_nloc = 0
        in_procedure = False

        for line in lines:
            s = line.strip()
            if not s:
                blank_loc += 1
                continue
            if ext in (".cobol", ".cbl", ".cob"):
                if (len(line) >= 7 and line[6] in ("*", "/")) or s.startswith(("*", "/", "*>")):
                    comment_loc += 1
                    continue
                if "PROCEDURE DIVISION" in line.upper():
                    in_procedure = True
                    decl_nloc += 1
                    continue
                if in_procedure:
                    exec_nloc += 1
                else:
                    decl_nloc += 1
            elif ext in (".jcl", ".job"):
                if s.startswith("//*"):
                    comment_loc += 1
                elif s.startswith("//"):
                    exec_nloc += 1
                else:
                    decl_nloc += 1
            else:
                if s.startswith(("#", "//", "--", "/*")):
                    comment_loc += 1
                else:
                    exec_nloc += 1

        tot_nloc = exec_nloc + decl_nloc
        sha = hashlib.sha256(content.encode("utf-8")).hexdigest()

        file_records.append({
            "file": f_path.name,
            "path": str(f_path),
            "physical_loc": phys_loc,
            "comment_loc": comment_loc,
            "blank_loc": blank_loc,
            "executable_nloc": exec_nloc,
            "declarative_nloc": decl_nloc,
            "total_nloc": tot_nloc,
            "sha256": sha,
        })

        total_physical_loc += phys_loc
        total_blank_loc += blank_loc
        total_comment_loc += comment_loc
        total_executable_nloc += exec_nloc
        total_declarative_nloc += decl_nloc

    return {
        "files": file_records,
        "total_files": len(files),
        "total_physical_loc": total_physical_loc,
        "total_blank_loc": total_blank_loc,
        "total_comment_loc": total_comment_loc,
        "total_executable_nloc": total_executable_nloc,
        "total_declarative_nloc": total_declarative_nloc,
        "total_nloc": total_executable_nloc + total_declarative_nloc,
    }

