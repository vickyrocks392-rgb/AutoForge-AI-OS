"""SQL Analyzer (Phase 18-G.3)."""
from __future__ import annotations
import re
from autoforge_modernization.analyzers.base import (
    TechnologyAnalyzer, AnalysisResult, AnalysisFinding, FindingKind, FindingConfidence)


class SQLAnalyzer(TechnologyAnalyzer):
    technology = "SQL"

    def analyze(self, content, file_path=None):
        result = AnalysisResult(technology=self.technology, file_path=file_path, content_length=len(content))
        p, nb, c, b = self.count_loc(content, ["--", "#", "/*"])
        result.physical_lines = p
        result.non_blank_lines = nb
        result.comment_lines = c
        result.blank_lines = b
        lines = content.split("\n")
        tokens = content.upper()
        for m in re.finditer(r"CREATE\s+TABLE\s+[`\"']?([\w.]+)[`\"']?\s*\(", tokens):
            table = m.group(1)
            line_num = content[:m.start()].count("\n") + 1
            result.findings.append(AnalysisFinding(kind=FindingKind.SQL_TABLE, name=f"TABLE: {table}", location=f"L{line_num}", evidence=self._ev(lines[min(line_num - 1, len(lines) - 1)], line_num)))
        for m in re.finditer(r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+[`\"']?([\w.]+)[`\"']?\s+ON\s+[`\"']?([\w.]+)[`\"']?", tokens):
            idx, tbl = m.group(1), m.group(2)
            line_num = content[:m.start()].count("\n") + 1
            result.findings.append(AnalysisFinding(kind=FindingKind.SQL_INDEX, name=f"INDEX: {idx} ON {tbl}", location=f"L{line_num}", evidence=self._ev(lines[min(line_num - 1, len(lines) - 1)], line_num)))
        for m in re.finditer(r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+[`\"']?([\w.]+)[`\"']?", tokens):
            view = m.group(1)
            line_num = content[:m.start()].count("\n") + 1
            result.findings.append(AnalysisFinding(kind=FindingKind.SQL_VIEW, name=f"VIEW: {view}", location=f"L{line_num}", evidence=self._ev(lines[min(line_num - 1, len(lines) - 1)], line_num)))
        for m in re.finditer(r"\bSELECT\s+", tokens):
            line_num = content[:m.start()].count("\n") + 1
            fm = re.search(r"FROM\s+[`\"']?([\w.]+)[`\"']?", tokens[m.start():m.start() + 500])
            table = fm.group(1) if fm else "unknown"
            result.findings.append(AnalysisFinding(kind=FindingKind.SQL_QUERY, name=f"SELECT from {table}", location=f"L{line_num}", detail={"operation": "SELECT", "table": table}, evidence=self._ev(lines[min(line_num - 1, len(lines) - 1)], line_num), confidence=FindingConfidence.HIGH))
        result.structural_summary.update({"tables": len(result.findings_by_kind(FindingKind.SQL_TABLE)), "views": len(result.findings_by_kind(FindingKind.SQL_VIEW)), "indexes": len(result.findings_by_kind(FindingKind.SQL_INDEX)), "queries": len(result.findings_by_kind(FindingKind.SQL_QUERY))})
        return result
