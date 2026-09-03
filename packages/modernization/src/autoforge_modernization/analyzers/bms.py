"""BMS Analyzer (Phase 18-G.3)."""
from __future__ import annotations
import re
from autoforge_modernization.analyzers.base import (
    TechnologyAnalyzer, AnalysisResult, AnalysisFinding, FindingKind)


class BMSAnalyzer(TechnologyAnalyzer):
    technology = "BMS"

    def analyze(self, content, file_path=None):
        result = AnalysisResult(technology=self.technology, file_path=file_path, content_length=len(content))
        p, nb, c, b = self.count_loc(content, ["*", "//"])
        result.physical_lines = p
        result.non_blank_lines = nb
        result.comment_lines = c
        result.blank_lines = b
        lines = content.split("\n")
        current_map = None
        map_start_pat = re.compile(r"^\s*DFHMSD\s+TYPE=\s*(&)?\s*MAP", re.IGNORECASE)
        map_name_pat = re.compile(r"MAP=\s*([\"']?)([\w-]+)\1", re.IGNORECASE)
        field_pat = re.compile(r"^\s*DFHMDF\s+POS=\s*(\d+).*?ATTRB=\s*\(([^)]+)\)", re.IGNORECASE)
        field_name_pat = re.compile(r"FIELD=\s*([\"']?)([\w-]+)\1", re.IGNORECASE)
        for lineno, line in enumerate(lines, 1):
            ls = line.strip()
            m = map_start_pat.match(ls)
            if m:
                nm = map_name_pat.search(ls)
                if nm:
                    current_map = nm.group(2)
                    result.findings.append(AnalysisFinding(kind=FindingKind.BMS_MAP, name=f"MAP: {current_map}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                continue
            if current_map:
                m = field_pat.match(ls)
                if m:
                    pos, attr = m.group(1), m.group(2)
                    nm2 = field_name_pat.search(ls)
                    fname = nm2.group(2) if nm2 else f"POS_{pos}"
                    result.findings.append(AnalysisFinding(kind=FindingKind.BMS_FIELD, name=f"{current_map}.{fname}", location=f"L{lineno}", detail={"position": pos, "attributes": attr}, evidence=self._ev(ls, lineno)))
        result.structural_summary.update({"maps": len(result.findings_by_kind(FindingKind.BMS_MAP)), "fields": len(result.findings_by_kind(FindingKind.BMS_FIELD))})
        return result
