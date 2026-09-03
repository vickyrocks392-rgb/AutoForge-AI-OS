"""Real technology analyzers (Phase 18-G.3 expansion).

Each analyzer performs deterministic, real extraction of structure, syntax,
and business semantics from a source file. No fabrication. No fake ASTs.

Public API:
    TechnologyAnalyzer  -- abstract base
    COBOLAnalyzer       -- divisions, sections, paragraphs, data, PERFORM, CALL
    JCLAnalyzer         -- JOB, EXEC, DD, datasets, procedures
    BMSAnalyzer         -- maps, fields, screen definitions
    SQLAnalyzer         -- schemas, tables, queries, embedded SQL
    ShellAnalyzer       -- shell script structure extraction
    AnalyzerDispatcher  -- routes content -> analyzer by technology
"""

from autoforge_modernization.analyzers.base import (
    TechnologyAnalyzer,
    AnalysisFinding,
    AnalysisResult,
    AnalyzerDispatcher,
    FindingKind,
    FindingConfidence,
)

__all__ = [
    "TechnologyAnalyzer",
    "AnalysisFinding",
    "AnalysisResult",
    "AnalyzerDispatcher",
    "FindingKind",
    "FindingConfidence",
]
