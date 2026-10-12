"""Workload Accounting and Deterministic Source NLOC Ledger for AutoForge Modernization.

Establishes truthful, reproducible, customer-workload-based modernization throughput
using REAL SOURCE CODE LINES PROCESSED BY AUTOFORGE ITSELF.

Invariants:
1. Discovered NLOC != Transformed NLOC when only a subset is transformed.
2. Canonical commercial throughput numerator is transformed_source_nloc.
3. Repetitions, retries, and repairs do NOT double-count transformed_source_nloc.
4. Timing measures full end-to-end wall-clock time from customer ingress to sealed delivery.
5. External/coding-agent tokens (Gemini/Cline) and model tokens never influence NLOC/hour.
6. Technology-aware line and non-comment line (NLOC) calculation.
"""

from __future__ import annotations

import hashlib
from pathlib import Path
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from pydantic import BaseModel, Field


def compute_file_sha256(path: Path) -> str:
    """Compute SHA-256 digest of a file."""
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError:
        return ""


def detect_file_language(path: Path) -> str:
    """Detect source language from filename and suffix."""
    name = path.name.lower()
    suffix = path.suffix.lower()

    if suffix in (".cbl", ".cob"):
        return "COBOL"
    if suffix == ".cpy":
        return "COBOL_COPYBOOK"
    if suffix in (".java",):
        return "JAVA"
    if suffix in (".py",):
        return "PYTHON"
    if suffix in (".sh", ".bash", ".zsh"):
        return "SHELL"
    if suffix in (".jcl",):
        return "JCL"
    if suffix in (".sql", ".ddl"):
        return "SQL_DDL"
    if suffix in (".s", ".asm"):
        return "ASSEMBLER"
    if suffix in (".kt", ".kts"):
        return "KOTLIN"
    if suffix in (".json",):
        return "JSON"
    if suffix in (".xml", ".pom"):
        return "XML"
    if suffix in (".yaml", ".yml"):
        return "YAML"
    if suffix in (".md", ".txt"):
        return "DOCUMENTATION"
    if suffix in (".bms",):
        return "BMS_MAP"
    if suffix in (".csd",):
        return "CICS_CSD"
    if suffix in (".dbd",):
        return "IMS_DBD"
    if suffix in (".dat", ".ps"):
        return "DATASET"
    if suffix in (".png", ".jpg", ".jpeg", ".gif", ".ico", ".bmp", ".jar", ".zip", ".gz", ".tar", ".pdf", ".bin", ".exe"):
        return "BINARY_ASSET"
    return "UNKNOWN"


def count_source_lines(path: Path, content: Optional[str] = None, language: Optional[str] = None) -> Tuple[int, int]:
    """
    Technology-aware LOC and NLOC (non-comment non-blank line) counter.
    Returns (physical_loc, nloc).
    """
    lang = language or detect_file_language(path)
    if lang == "BINARY_ASSET":
        return 0, 0

    if content is None:
        try:
            content = path.read_text(encoding="utf-8", errors="replace")
        except OSError:
            return 0, 0

    lines = content.splitlines()
    phys = len(lines)
    nloc = 0

    in_block_comment = False

    for ln in lines:
        s = ln.strip()
        if not s:
            continue

        if lang in ("COBOL", "COBOL_COPYBOOK"):
            # Check fixed-format indicator area (column 7, 0-indexed index 6)
            if len(ln) >= 7 and ln[6] in ("*", "/"):
                continue
            # Check free-format floating comments
            if s.startswith("*>") or s.startswith("*") or s.startswith("//"):
                continue
            nloc += 1

        elif lang in ("JAVA", "KOTLIN", "GO"):
            if in_block_comment:
                if "*/" in s:
                    in_block_comment = False
                continue
            if s.startswith("/*"):
                if "*/" not in s:
                    in_block_comment = True
                continue
            if s.startswith("//"):
                continue
            nloc += 1

        elif lang in ("PYTHON", "SHELL", "YAML"):
            if s.startswith("#"):
                continue
            nloc += 1

        elif lang == "JCL":
            if s.startswith("//*"):
                continue
            nloc += 1

        elif lang == "SQL_DDL":
            if s.startswith("--") or s.startswith("//"):
                continue
            if in_block_comment:
                if "*/" in s:
                    in_block_comment = False
                continue
            if s.startswith("/*"):
                if "*/" not in s:
                    in_block_comment = True
                continue
            nloc += 1

        elif lang == "ASSEMBLER":
            if s.startswith("*") or s.startswith(";"):
                continue
            nloc += 1

        else:
            # General fallback: check common comment prefixes
            if s.startswith("#") or s.startswith("//") or s.startswith(";") or s.startswith("*"):
                continue
            nloc += 1

    return phys, nloc


class SourceUnitRecord(BaseModel):
    """Deterministic record of a single source unit entering the modernization pipeline."""

    source_path: str
    relative_path: str = ""
    language: str
    physical_loc: int = 0
    nloc: int = 0
    project_role: str = "LEGACY_SOURCE"
    processing_status: str = "ANALYZED_ONLY"  # PROCESSED, ANALYZED_ONLY, UNSUPPORTED, EXCLUDED_WITH_EXPLICIT_REASON, FAILED, GENERATED, VALIDATED
    exclusion_reason: str = ""
    selected_for_modernization: bool = False
    analyzed: bool = False
    transformed: bool = False
    transformation_status: str = "NOT_SELECTED"  # NOT_SELECTED, SUCCESS, FAILED, SKIPPED
    target_artifacts: List[str] = Field(default_factory=list)
    validation_status: str = "NOT_VALIDATED"  # NOT_VALIDATED, PASSED, FAILED
    workload_identity: str = ""
    sha256: str = ""
    source_hash: str = ""
    reprocessed_count: int = 0


class WorkloadAccountingLedger:
    """
    Authoritative commercial workload accounting ledger.
    Guarantees:
    - Unique work unit identity prevents double-counting across analysis, transformation, repair, and validation.
    - Canonical numerator is transformed_source_nloc.
    - Distinguishes discovered, selected, analyzed, transformed, and delivered scopes.
    - Deterministic whole-project accounting: Every discovered file has an explicit disposition.
    """

    def __init__(
        self,
        repository: str = "",
        commit: str = "",
        source_root: Optional[Path] = None,
    ) -> None:
        self.repository = repository
        self.commit = commit
        self.source_root = source_root
        self._units: Dict[str, SourceUnitRecord] = {}  # keyed by relative source_path
        self._transformed_ids: Set[str] = set()       # workload_identity set to ensure uniqueness
        self.repair_count: int = 0
        self.reprocessed_nloc: int = 0
        self.repaired_source_units: List[str] = []
        self.repair_wall_clock_seconds: float = 0.0

    def compute_identity(self, rel_path: str, file_sha256: str) -> str:
        """Create deterministic workload identity for work unit."""
        return f"{self.repository}:{self.commit}:{rel_path}:{file_sha256}"

    def register_discovered_file(self, file_path: Path, root: Optional[Path] = None) -> SourceUnitRecord:
        """Register a discovered project file into the ledger with deterministic disposition."""
        base = root or self.source_root or file_path.parent
        try:
            rel = str(file_path.relative_to(base))
        except ValueError:
            rel = str(file_path.name)

        if rel in self._units:
            return self._units[rel]

        lang = detect_file_language(file_path)
        phys, nloc = count_source_lines(file_path, language=lang)
        digest = compute_file_sha256(file_path)
        ident = self.compute_identity(rel, digest)

        # Deterministic project role, processing status, and exclusion classification
        project_role = "LEGACY_SOURCE"
        processing_status = "ANALYZED_ONLY"
        exclusion_reason = ""

        lower_rel = rel.lower()
        if "dailypost" in lower_rel and lower_rel.endswith((".cbl", ".cob")):
            project_role = "PRIMARY_COBOL_PROGRAM"
            processing_status = "ANALYZED_ONLY"
        elif lower_rel.endswith((".cpy",)):
            project_role = "COBOL_COPYBOOK"
            processing_status = "ANALYZED_ONLY"
        elif lower_rel.startswith("data/") and lower_rel.endswith(".dat"):
            project_role = "APPLICATION_DATASET"
            processing_status = "ANALYZED_ONLY"
        elif lower_rel.startswith("out/") and lower_rel.endswith(".dat"):
            project_role = "GOLDEN_MASTER_REFERENCE"
            processing_status = "VALIDATED"
        elif lower_rel.startswith("rewrite/kotlin/"):
            project_role = "REFERENCE_IMPLEMENTATION"
            processing_status = "EXCLUDED_WITH_EXPLICIT_REASON"
            exclusion_reason = "Pre-existing manual reference Kotlin implementation provided by repository author; excluded from legacy COBOL input scope"
        elif lower_rel.startswith("docs/") or lower_rel.endswith((".puml", ".png")):
            project_role = "ANCILLARY_DOCUMENTATION"
            processing_status = "EXCLUDED_WITH_EXPLICIT_REASON"
            exclusion_reason = "Ancillary documentation and architecture diagrams; non-executable specification"
        elif lower_rel.startswith(("readme", "license", ".git")) or lower_rel in ("readme.md", "license", ".gitignore"):
            project_role = "REPOSITORY_METADATA"
            processing_status = "EXCLUDED_WITH_EXPLICIT_REASON"
            exclusion_reason = "Repository metadata and guidance; non-executable"
        elif lower_rel.endswith((".bms", ".csd", ".dbd")):
            project_role = "UNSUPPORTED_MAINFRAME_SPEC"
            processing_status = "UNSUPPORTED"
            exclusion_reason = "BMS/CSD/DBD mainframe specifications not supported by batch modernisation pipeline"
        elif lower_rel.endswith((".sh", ".bash")) or lower_rel in ("makefile", "build.sh", "run.sh"):
            project_role = "BUILD_AND_VERIFICATION_SPEC"
            processing_status = "ANALYZED_ONLY"
        elif lower_rel.startswith("scripts/"):
            project_role = "VERIFICATION_SCRIPT"
            processing_status = "ANALYZED_ONLY"
        elif lower_rel.startswith("formal/"):
            project_role = "FORMAL_SPECIFICATION"
            processing_status = "ANALYZED_ONLY"

        rec = SourceUnitRecord(
            source_path=rel,
            relative_path=rel,
            language=lang,
            physical_loc=phys,
            nloc=nloc,
            project_role=project_role,
            processing_status=processing_status,
            exclusion_reason=exclusion_reason,
            selected_for_modernization=False,
            analyzed=False,
            transformed=False,
            transformation_status="NOT_SELECTED",
            target_artifacts=[],
            validation_status="NOT_VALIDATED",
            workload_identity=ident,
            sha256=digest,
            source_hash=digest,
            reprocessed_count=0,
        )
        self._units[rel] = rec
        return rec

    def mark_selected(self, rel_path: str) -> None:
        """Mark a source unit as selected for modernization scope."""
        if rel_path in self._units:
            self._units[rel_path].selected_for_modernization = True

    def mark_analyzed(self, rel_path: str) -> None:
        """Mark a source unit as analyzed."""
        if rel_path in self._units:
            self._units[rel_path].analyzed = True

    def mark_processed(self, rel_path: str, target_artifacts: Optional[List[str]] = None) -> None:
        """Mark an artifact as processed."""
        rec = self._units.get(rel_path)
        if rec:
            rec.processing_status = "PROCESSED"
            if target_artifacts:
                for art in target_artifacts:
                    if art not in rec.target_artifacts:
                        rec.target_artifacts.append(art)

    def mark_transformed(
        self,
        rel_path: str,
        target_artifacts: Optional[List[str]] = None,
        success: bool = True,
    ) -> None:
        """
        Record transformation of a source unit.
        Ensures idempotent tracking; duplicate transformation calls do NOT double count.
        """
        rec = self._units.get(rel_path)
        if not rec:
            return

        rec.transformed = True
        rec.processing_status = "PROCESSED"
        rec.transformation_status = "SUCCESS" if success else "FAILED"
        if target_artifacts:
            for art in target_artifacts:
                if art not in rec.target_artifacts:
                    rec.target_artifacts.append(art)

        self._transformed_ids.add(rec.workload_identity)

    def mark_validated(self, rel_path: str, passed: bool) -> None:
        """Record validation outcome for a source unit."""
        if rel_path in self._units:
            self._units[rel_path].validation_status = "PASSED" if passed else "FAILED"
            if passed and self._units[rel_path].processing_status == "ANALYZED_ONLY":
                self._units[rel_path].processing_status = "VALIDATED"

    def record_repair_cycle(self, target_unit: str, reprocessed_units: List[str], duration_sec: float) -> None:
        """
        Record a repair cycle.
        Tracks repair count, duration, and reprocessed NLOC separately from the primary numerator.
        """
        self.repair_count += 1
        self.repair_wall_clock_seconds += duration_sec
        if target_unit not in self.repaired_source_units:
            self.repaired_source_units.append(target_unit)

        for u in reprocessed_units:
            if u in self._units:
                self._units[u].reprocessed_count += 1
                self.reprocessed_nloc += self._units[u].nloc

    # ── Metric Aggregations ───────────────────────────────────────────────────

    @property
    def discovered_files(self) -> int:
        return len(self._units)

    @property
    def processed_files(self) -> int:
        return sum(1 for u in self._units.values() if u.processing_status in ("PROCESSED", "GENERATED") or u.transformed)

    @property
    def analyzed_only_files(self) -> int:
        return sum(1 for u in self._units.values() if u.processing_status == "ANALYZED_ONLY")

    @property
    def unsupported_files(self) -> int:
        return sum(1 for u in self._units.values() if u.processing_status == "UNSUPPORTED")

    @property
    def excluded_files(self) -> int:
        return sum(1 for u in self._units.values() if u.processing_status == "EXCLUDED_WITH_EXPLICIT_REASON")

    @property
    def failed_files(self) -> int:
        return sum(1 for u in self._units.values() if u.processing_status == "FAILED")

    @property
    def validated_files(self) -> int:
        return sum(1 for u in self._units.values() if u.processing_status == "VALIDATED" or u.validation_status == "PASSED")

    @property
    def discovered_project_physical_loc(self) -> int:
        return sum(u.physical_loc for u in self._units.values())

    @property
    def discovered_project_nloc(self) -> int:
        return sum(u.nloc for u in self._units.values())

    @property
    def processed_project_physical_loc(self) -> int:
        return sum(u.physical_loc for u in self._units.values() if u.transformed or u.processing_status == "PROCESSED")

    @property
    def processed_project_nloc(self) -> int:
        return sum(u.nloc for u in self._units.values() if u.transformed or u.processing_status == "PROCESSED")

    @property
    def selected_files(self) -> int:
        return sum(1 for u in self._units.values() if u.selected_for_modernization)

    @property
    def selected_modernization_scope_physical_loc(self) -> int:
        return sum(u.physical_loc for u in self._units.values() if u.selected_for_modernization)

    @property
    def selected_modernization_scope_nloc(self) -> int:
        return sum(u.nloc for u in self._units.values() if u.selected_for_modernization)

    @property
    def analyzed_files(self) -> int:
        return sum(1 for u in self._units.values() if u.analyzed)

    @property
    def analyzed_source_physical_loc(self) -> int:
        return sum(u.physical_loc for u in self._units.values() if u.analyzed)

    @property
    def analyzed_source_nloc(self) -> int:
        return sum(u.nloc for u in self._units.values() if u.analyzed)

    @property
    def transformed_files(self) -> int:
        # Sum of unique units that were transformed
        return sum(1 for u in self._units.values() if u.transformed)

    @property
    def transformed_source_physical_loc(self) -> int:
        return sum(u.physical_loc for u in self._units.values() if u.transformed)

    @property
    def transformed_source_nloc(self) -> int:
        """
        AUTHORITATIVE COMMERCIAL NUMERATOR.
        Represents unique source NLOC physically transformed by AutoForge.
        """
        return sum(u.nloc for u in self._units.values() if u.transformed)

    @property
    def validated_source_nloc(self) -> int:
        return sum(u.nloc for u in self._units.values() if u.validation_status == "PASSED")

    def export_unit_records(self) -> List[Dict[str, Any]]:
        """Export all source unit records for manifest and telemetry inclusion."""
        return [rec.model_dump() for rec in self._units.values()]
