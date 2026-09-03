"""Base analyzer infrastructure (Phase 18-G.3 analyzers)."""

from __future__ import annotations

import uuid
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class FindingKind(str, Enum):
    DIVISION = "division"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    DATA_DECLARATION = "data_declaration"
    PROCEDURE_CALL = "procedure_call"
    FILE_OPERATION = "file_operation"
    CONTROL_FLOW = "control_flow"
    BUSINESS_RULE = "business_rule"
    JCL_STEP = "jcl_step"
    JCL_DATASET = "jcl_dataset"
    JCL_PROCEDURE = "jcl_procedure"
    JCL_CONDITION = "jcl_condition"
    SQL_TABLE = "sql_table"
    SQL_VIEW = "sql_view"
    SQL_QUERY = "sql_query"
    SQL_PROCEDURE = "sql_procedure"
    SQL_TRIGGER = "sql_trigger"
    SQL_INDEX = "sql_index"
    SQL_CONSTRAINT = "sql_constraint"
    BMS_FIELD = "bms_field"
    BMS_MAP = "bms_map"
    BMS_ATTRIBUTE = "bms_attribute"
    CICS_COMMAND = "cics_command"
    CICS_TRANSACTION = "cics_transaction"
    STRUCTURAL = "structural"
    DEPENDENCY = "dependency"
    FUNCTION = "function"
    COPYBOOK_REF = "copybook_ref"
    UNKNOWN = "unknown"


class FindingConfidence(str, Enum):
    PROVEN = "proven"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class AnalysisFinding(BaseModel):
    finding_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    kind: FindingKind
    name: str
    location: str = ""
    description: str = ""
    detail: dict[str, Any] = Field(default_factory=dict)
    confidence: FindingConfidence = FindingConfidence.PROVEN
    evidence: list[str] = Field(default_factory=list)
    parent: str | None = None


class AnalysisResult(BaseModel):
    result_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    technology: str
    version: str | None = None
    dialect: str | None = None
    file_path: str | None = None
    analyzed_at: datetime = Field(default_factory=_utc_now)
    content_length: int = 0
    physical_lines: int = 0
    non_blank_lines: int = 0
    comment_lines: int = 0
    blank_lines: int = 0
    findings: list[AnalysisFinding] = Field(default_factory=list)
    structural_summary: dict[str, Any] = Field(default_factory=dict)
    business_findings: list[str] = Field(default_factory=list)
    dependencies: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    analysis_method: str = "deterministic"

    def total_findings(self) -> int:
        return len(self.findings)

    def findings_by_kind(self, kind: FindingKind) -> list[AnalysisFinding]:
        return [f for f in self.findings if f.kind == kind]


class TechnologyAnalyzer(ABC):
    technology: str
    supported_versions: list[str] = []

    @abstractmethod
    def analyze(self, content: str, file_path: str | None = None) -> AnalysisResult:
        raise NotImplementedError

    def count_loc(self, content: str, comment_patterns=None) -> tuple:
        lines = content.split("\n")
        physical = len(lines)
        blank = sum(1 for l in lines if not l.strip())
        comment_lines = 0
        patterns = comment_patterns or ["*", "//", "#", "/*"]
        for l in lines:
            s = l.strip()
            if any(s.startswith(p) for p in patterns):
                comment_lines += 1
        return physical, physical - blank, comment_lines, blank

    def _ev(self, line: str, lineno=None) -> list[str]:
        loc = f"L{lineno}" if lineno is not None else "?"
        return [f"{loc}: {line.strip()[:120]}"]


class AnalyzerDispatcher:
    def __init__(self):
        self._analyzers: dict = {}
        self._register_defaults()

    def _register_defaults(self) -> None:
        from autoforge_modernization.analyzers.cobol import COBOLAnalyzer
        from autoforge_modernization.analyzers.jcl import JCLAnalyzer
        from autoforge_modernization.analyzers.sql import SQLAnalyzer
        from autoforge_modernization.analyzers.bms import BMSAnalyzer
        from autoforge_modernization.analyzers.shell import ShellAnalyzer
        self.register("COBOL", COBOLAnalyzer)
        self.register("COBOL_COPYBOOK", COBOLAnalyzer)
        self.register("JCL", JCLAnalyzer)
        self.register("SQL", SQLAnalyzer)
        self.register("BMS", BMSAnalyzer)
        self.register("SHELL", ShellAnalyzer)
        self.register("BASH", ShellAnalyzer)
        self.register("KSH", ShellAnalyzer)
        self.register("ZSH", ShellAnalyzer)

    def register(self, tech: str, analyzer_cls) -> None:
        self._analyzers[tech.upper()] = analyzer_cls

    def get(self, tech: str):
        return self._analyzers.get(tech.upper())

    def analyze(self, content: str, tech: str, file_path: str | None = None):
        cls = self.get(tech)
        if cls is None:
            return None
        return cls().analyze(content, file_path)

    def is_available(self, tech: str) -> bool:
        return tech.upper() in self._analyzers

    def available_technologies(self) -> list[str]:
        return list(self._analyzers.keys())


__all__ = ["TechnologyAnalyzer", "AnalysisFinding", "AnalysisResult", "AnalyzerDispatcher", "FindingKind", "FindingConfidence"]
