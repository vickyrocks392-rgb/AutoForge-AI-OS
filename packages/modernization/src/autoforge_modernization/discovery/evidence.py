"""Multi-Provider Evidence Collection for Generalized Project Discovery.

Enforces Section 4 of the architectural mandate:
Detection must NOT depend on hardcoded:
if project == "CardDemo":
or:
if extension == ".cbl": technology = "COBOL"
as the sole mechanism.

Detection must be evidence-based across:
- File extensions & names
- Directory structure
- Language syntax & compiler directives
- Configuration files & build manifests
- SQL / JCL / CICS / BMS / IMS constructs
- Schedulers (Control-M, CA7)
"""

from __future__ import annotations

import os
import re
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.reconnaissance.models import (
    DetectionMethod,
    EvidenceKind,
    EvidenceSource,
    FactConfidence,
    TechnologyEvidence,
    _utc_now,
)


class TechnologyEvidenceRecord(BaseModel):
    """Normalized evidence record backing a technology detection."""

    technology: str
    evidence_kind: EvidenceKind
    evidence_source: EvidenceSource
    detection_method: DetectionMethod
    description: str
    file_path: str
    relative_path: str
    confidence: FactConfidence
    line_number: int | None = None
    snippet: str = ""


class EvidenceProvider(ABC):
    """Abstract provider of technology evidence."""

    provider_id: str

    @abstractmethod
    def scan_file(
        self,
        file_path: str,
        relative_path: str,
        content: str | None = None,
    ) -> list[TechnologyEvidenceRecord]:
        """Examine a file and return observed evidence of technologies."""
        raise NotImplementedError


class FileSystemEvidenceProvider(EvidenceProvider):
    """Extracts evidence from filenames, extensions, and directory structure."""

    provider_id = "evidence-filesystem"

    EXTENSION_MAP: dict[str, str] = {
        ".cbl": "COBOL",
        ".cob": "COBOL",
        ".cpy": "COBOL_COPYBOOK",
        ".jcl": "JCL",
        ".prc": "JCL",
        ".bms": "BMS",
        ".csd": "CICS",
        ".dbd": "IMS",
        ".psb": "IMS",
        ".ddl": "DB2",
        ".dcl": "DB2",
        ".sql": "SQL",
        ".ca7": "CA7",
        ".controlm": "CONTROL_M",
        ".java": "JAVA",
        ".py": "PYTHON",
        ".ts": "TYPESCRIPT",
        ".js": "JAVASCRIPT",
        ".go": "GOLANG",
        ".sh": "SHELL",
        ".bash": "SHELL",
        ".asm": "ASSEMBLER",
        ".hla": "ASSEMBLER",
    }

    def scan_file(
        self,
        file_path: str,
        relative_path: str,
        content: str | None = None,
    ) -> list[TechnologyEvidenceRecord]:
        records: list[TechnologyEvidenceRecord] = []
        ext = os.path.splitext(file_path)[1].lower()

        if ext in self.EXTENSION_MAP:
            tech = self.EXTENSION_MAP[ext]
            records.append(
                TechnologyEvidenceRecord(
                    technology=tech,
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.FILE_EXTENSION,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description=f"File extension '{ext}' indicates {tech}",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.MEDIUM,
                )
            )

        # Directory structure evidence
        rel_lower = relative_path.lower()
        if "copybook" in rel_lower or "/cpy/" in rel_lower:
            records.append(
                TechnologyEvidenceRecord(
                    technology="COBOL_COPYBOOK",
                    evidence_kind=EvidenceKind.DIRECTORY_STRUCTURE,
                    evidence_source=EvidenceSource.DIRECTORY_PATTERN,
                    detection_method=DetectionMethod.HEURISTIC,
                    description=f"Path '{relative_path}' indicates copybook catalog",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.HIGH,
                )
            )
        if "/cbl/" in rel_lower or "cobol" in rel_lower:
            records.append(
                TechnologyEvidenceRecord(
                    technology="COBOL",
                    evidence_kind=EvidenceKind.DIRECTORY_STRUCTURE,
                    evidence_source=EvidenceSource.DIRECTORY_PATTERN,
                    detection_method=DetectionMethod.HEURISTIC,
                    description=f"Path '{relative_path}' indicates COBOL source tree",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.HIGH,
                )
            )
        if "/jcl/" in rel_lower or "/proc/" in rel_lower:
            records.append(
                TechnologyEvidenceRecord(
                    technology="JCL",
                    evidence_kind=EvidenceKind.DIRECTORY_STRUCTURE,
                    evidence_source=EvidenceSource.DIRECTORY_PATTERN,
                    detection_method=DetectionMethod.HEURISTIC,
                    description=f"Path '{relative_path}' indicates JCL job/procedure tree",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.HIGH,
                )
            )

        return records


class SyntaxEvidenceProvider(EvidenceProvider):
    """Extracts evidence from language syntax, compiler directives, and statements."""

    provider_id = "evidence-syntax"

    def scan_file(
        self,
        file_path: str,
        relative_path: str,
        content: str | None = None,
    ) -> list[TechnologyEvidenceRecord]:
        records: list[TechnologyEvidenceRecord] = []
        if content is None:
            return records

        upper = content.upper()

        # COBOL Division & Program syntax
        if "IDENTIFICATION DIVISION" in upper or "PROCEDURE DIVISION" in upper:
            m = re.search(r"PROGRAM-ID\.\s*([A-Z0-9-]+)", upper)
            prog = m.group(1) if m else "UNNAMED"
            records.append(
                TechnologyEvidenceRecord(
                    technology="COBOL",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description=f"COBOL Program declaration found: PROGRAM-ID {prog}",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet=f"PROGRAM-ID: {prog}",
                )
            )

        # CICS Constructs (EXEC CICS)
        if "EXEC CICS" in upper:
            records.append(
                TechnologyEvidenceRecord(
                    technology="CICS",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Embedded CICS statement (EXEC CICS) found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet="EXEC CICS",
                )
            )

        # DB2 / Embedded SQL (EXEC SQL)
        if "EXEC SQL" in upper or "CREATE TABLE" in upper or "CREATE INDEX" in upper:
            records.append(
                TechnologyEvidenceRecord(
                    technology="DB2",
                    evidence_kind=EvidenceKind.SQL_SCRIPT,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Embedded SQL / DB2 DDL found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.HIGH,
                    snippet="EXEC SQL / DDL",
                )
            )

        # BMS Mapsets
        if "DFHMSD" in upper or "DFHMDI" in upper or "DFHMDF" in upper:
            records.append(
                TechnologyEvidenceRecord(
                    technology="BMS",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="BMS 3270 Map definition macro found (DFHMSD/DFHMDI)",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet="DFHMSD macro",
                )
            )

        # JCL Job Statements
        if re.search(r"^//\s*\w+\s+(JOB|EXEC|DD|PROC)\b", content, re.MULTILINE):
            records.append(
                TechnologyEvidenceRecord(
                    technology="JCL",
                    evidence_kind=EvidenceKind.BUILD_FILE,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="z/OS JCL card statement (// JOB/EXEC/DD) found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # IMS DBD / PSB
        if "DBD  NAME=" in upper or "PSB  NAME=" in upper or "PCB  TYPE=DB" in upper:
            records.append(
                TechnologyEvidenceRecord(
                    technology="IMS",
                    evidence_kind=EvidenceKind.DB_SCHEMA,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="IMS DBD/PSB database descriptor found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # Shell Scripts
        if content.startswith("#!/") or "set -e" in content or "export " in content:
            records.append(
                TechnologyEvidenceRecord(
                    technology="SHELL",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="POSIX / Bash Shell script directives found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.HIGH,
                )
            )

        return records
