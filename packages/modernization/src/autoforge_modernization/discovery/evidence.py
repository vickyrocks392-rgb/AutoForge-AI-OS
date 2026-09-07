"""Multi-Provider Evidence Collection for Generalized Project Discovery.

Enforces Section 4 of the architectural mandate:
Detection must NOT depend on hardcoded:
if project == "LegacyProject":
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

    FILENAME_MAP: dict[str, str] = {
        "dockerfile": "DOCKER",
        "docker-compose.yml": "DOCKER",
        "docker-compose.yaml": "DOCKER",
        ".dockerignore": "DOCKER",
        "pom.xml": "SPRING_BOOT",
        "build.gradle": "SPRING_BOOT",
        "build.gradle.kts": "SPRING_BOOT",
        "package.json": "NODEJS",
        "tsconfig.json": "TYPESCRIPT",
        "go.mod": "GO",
        "go.sum": "GO",
        "requirements.txt": "PYTHON",
        "pyproject.toml": "PYTHON",
        "openapi.json": "REST_API",
        "openapi.yaml": "REST_API",
        "openapi.yml": "REST_API",
        "swagger.json": "REST_API",
        "swagger.yaml": "REST_API",
    }

    EXTENSION_MAP: dict[str, str] = {
        ".cbl": "COBOL",
        ".cob": "COBOL",
        ".cpy": "COBOL_COPYBOOK",
        ".copy": "COBOL_COPYBOOK",
        ".jcl": "JCL",
        ".prc": "JCL",
        ".proc": "JCL",
        ".bms": "BMS",
        ".map": "BMS",
        ".csd": "CICS",
        ".cics": "CICS",
        ".dbd": "IMS",
        ".psb": "IMS",
        ".ddl": "DB2",
        ".dcl": "DB2",
        ".sql": "SQL",
        ".kds": "VSAM",
        ".esds": "VSAM",
        ".rrds": "VSAM",
        ".ca7": "CA7",
        ".controlm": "CONTROL_M",
        ".java": "JAVA",
        ".py": "PYTHON",
        ".ts": "TYPESCRIPT",
        ".js": "NODEJS",
        ".jsx": "REACT",
        ".tsx": "REACT",
        ".go": "GO",
        ".sh": "SHELL",
        ".bash": "SHELL",
        ".asm": "ASSEMBLER",
        ".hla": "ASSEMBLER",
        ".s": "ASSEMBLER",
        ".mac": "ASSEMBLER",
    }

    def scan_file(
        self,
        file_path: str,
        relative_path: str,
        content: str | None = None,
    ) -> list[TechnologyEvidenceRecord]:
        records: list[TechnologyEvidenceRecord] = []
        base_name = os.path.basename(file_path).lower()
        ext = os.path.splitext(file_path)[1].lower()

        # Filename matching
        if base_name in self.FILENAME_MAP:
            tech = self.FILENAME_MAP[base_name]
            records.append(
                TechnologyEvidenceRecord(
                    technology=tech,
                    evidence_kind=EvidenceKind.BUILD_FILE,
                    evidence_source=EvidenceSource.DIRECTORY_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description=f"Standard file '{base_name}' indicates {tech}",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # Extension matching
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
        if "/bms/" in rel_lower or "/maps/" in rel_lower:
            records.append(
                TechnologyEvidenceRecord(
                    technology="BMS",
                    evidence_kind=EvidenceKind.DIRECTORY_STRUCTURE,
                    evidence_source=EvidenceSource.DIRECTORY_PATTERN,
                    detection_method=DetectionMethod.HEURISTIC,
                    description=f"Path '{relative_path}' indicates BMS screen map catalog",
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

        # VSAM Constructs
        if ("ORGANIZATION IS INDEXED" in upper or "ORGANIZATION IS SEQUENTIAL" in upper or
            "RECORD KEY IS" in upper or "DEFINE CLUSTER" in upper):
            records.append(
                TechnologyEvidenceRecord(
                    technology="VSAM",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="VSAM dataset organization / IDCAMS cluster definition found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet="VSAM cluster/file definition",
                )
            )

        # DB2 / Embedded SQL (EXEC SQL) & SQL DDL
        if "EXEC SQL" in upper:
            records.append(
                TechnologyEvidenceRecord(
                    technology="DB2",
                    evidence_kind=EvidenceKind.SQL_SCRIPT,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Embedded SQL / DB2 statement (EXEC SQL) found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet="EXEC SQL",
                )
            )
            records.append(
                TechnologyEvidenceRecord(
                    technology="SQL",
                    evidence_kind=EvidenceKind.SQL_SCRIPT,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="SQL relational queries found inside embedded SQL block",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.HIGH,
                )
            )
        elif "CREATE TABLE" in upper or "CREATE INDEX" in upper or "ALTER TABLE" in upper:
            records.append(
                TechnologyEvidenceRecord(
                    technology="SQL",
                    evidence_kind=EvidenceKind.SQL_SCRIPT,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Relational SQL DDL statements found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet="CREATE TABLE/INDEX",
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

        # Copybooks
        if re.search(r"\bCOPY\s+[\"']?[\w.-]+[\"']?", upper) or (file_path.endswith((".cpy", ".copy")) and "01 " in upper):
            records.append(
                TechnologyEvidenceRecord(
                    technology="COBOL_COPYBOOK",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="COBOL COPY statement or copybook record structure found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
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

        # Batch and Transaction Dependencies
        if (re.search(r"EXEC\s+PGM=\w+", upper) or
            re.search(r"EXEC\s+CICS\s+(LINK|XCTL|START)", upper) or
            re.search(r"\bCALL\s+['\"][\w-]+['\"]", upper)):
            records.append(
                TechnologyEvidenceRecord(
                    technology="DEPENDENCIES",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Batch job step or transaction invocation linkage found",
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

        # Assembler (HLASM)
        if (re.search(r"^\s*\w+\s+(CSECT|DSECT|START)\b", content, re.MULTILINE) or
            "USING *" in upper or "BALR " in upper or "MACRO\n" in upper):
            records.append(
                TechnologyEvidenceRecord(
                    technology="ASSEMBLER",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="IBM High Level Assembler (HLASM) CSECT/DSECT/macro statement found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # Spring Boot / Java
        if "@SpringBootApplication" in content or "@RestController" in content or "@Service" in content:
            records.append(
                TechnologyEvidenceRecord(
                    technology="SPRING_BOOT",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Spring Boot framework annotation found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                    snippet="@SpringBootApplication / @RestController",
                )
            )
            records.append(
                TechnologyEvidenceRecord(
                    technology="JAVA",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Java source file backing Spring Boot service",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )
            if "@GetMapping" in content or "@PostMapping" in content or "@RequestMapping" in content:
                records.append(
                    TechnologyEvidenceRecord(
                        technology="REST_API",
                        evidence_kind=EvidenceKind.SOURCE_PATTERN,
                        evidence_source=EvidenceSource.SOURCE_PATTERN,
                        detection_method=DetectionMethod.DETERMINISTIC,
                        description="REST API mapping annotation found in Java controller",
                        file_path=file_path,
                        relative_path=relative_path,
                        confidence=FactConfidence.PROVEN,
                    )
                )

        # Python / FastAPI
        if "from fastapi import" in content or "import fastapi" in content or "FastAPI(" in content:
            records.append(
                TechnologyEvidenceRecord(
                    technology="FASTAPI",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="FastAPI framework application or router found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )
            records.append(
                TechnologyEvidenceRecord(
                    technology="PYTHON",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Python runtime backing FastAPI application",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )
            records.append(
                TechnologyEvidenceRecord(
                    technology="REST_API",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="REST API route endpoints declared in FastAPI app",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # Node.js / Express
        if "express()" in content or "from 'express'" in content or 'from "express"' in content or "require('express')" in content:
            records.append(
                TechnologyEvidenceRecord(
                    technology="EXPRESS",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Express.js web application routing found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )
            records.append(
                TechnologyEvidenceRecord(
                    technology="NODEJS",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Node.js runtime environment backing Express service",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )
            records.append(
                TechnologyEvidenceRecord(
                    technology="REST_API",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="REST API route declared in Express application",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # React
        if ("import React" in content or "from 'react'" in content or 'from "react"' in content or
            "useState(" in content or "useEffect(" in content or
            re.search(r"export\s+default\s+function\s+\w+\s*\(.*?\)\s*:\s*JSX\.Element", content)):
            records.append(
                TechnologyEvidenceRecord(
                    technology="REACT",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="React component with hooks / JSX found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # TypeScript
        if (re.search(r"\b(interface|type)\s+[A-Z]\w*\b", content) or
            re.search(r":\s*(string|number|boolean|any|void)\b", content)):
            records.append(
                TechnologyEvidenceRecord(
                    technology="TYPESCRIPT",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="TypeScript type annotations / interface declarations found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # Go
        if (re.search(r"^package\s+\w+", content, re.MULTILINE) and
            re.search(r"\bfunc\s+(?:\(\w+\s+\*?\w+\)\s+)?\w+\s*\(", content)):
            records.append(
                TechnologyEvidenceRecord(
                    technology="GO",
                    evidence_kind=EvidenceKind.SOURCE_PATTERN,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Go package and function declaration found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # Docker
        if (re.search(r"^FROM\s+[\w./:-]+", content, re.MULTILINE) or
            (re.search(r"^\s*services:\s*$", content, re.MULTILINE) and "version:" in content)):
            records.append(
                TechnologyEvidenceRecord(
                    technology="DOCKER",
                    evidence_kind=EvidenceKind.BUILD_FILE,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="Docker container definition (Dockerfile / Compose) found",
                    file_path=file_path,
                    relative_path=relative_path,
                    confidence=FactConfidence.PROVEN,
                )
            )

        # OpenAPI / REST API Specification
        if "openapi:" in content or '"openapi":' in content or '"swagger":' in content or "swagger:" in content:
            records.append(
                TechnologyEvidenceRecord(
                    technology="REST_API",
                    evidence_kind=EvidenceKind.BUILD_FILE,
                    evidence_source=EvidenceSource.SOURCE_PATTERN,
                    detection_method=DetectionMethod.DETERMINISTIC,
                    description="OpenAPI / Swagger REST contract specification found",
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
