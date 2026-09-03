"""Shell Analyzer (Phase 18-G.3)."""
from __future__ import annotations
import re
from autoforge_modernization.analyzers.base import (
    TechnologyAnalyzer, AnalysisResult, AnalysisFinding, FindingKind)


class ShellAnalyzer(TechnologyAnalyzer):
    technology = "SHELL"

    def analyze(self, content, file_path=None):
        result = AnalysisResult(technology=self.technology, file_path=file_path, content_length=len(content))
        p, nb, c, b = self.count_loc(content, ["#"])
        result.physical_lines = p
        result.non_blank_lines = nb
        result.comment_lines = c
        result.blank_lines = b
        lines = content.split("\n")
        if lines and lines[0].startswith("#!"):
            result.structural_summary["shebang"] = lines[0]
            result.structural_summary["shell_type"] = "bash" if "bash" in lines[0] else "sh"
        func_pat = re.compile(r"^(?:function\s+)?(\w[\w-]*)\s*(?:\(\)|\{)")
        src_pat1 = re.compile(r"^\s*\.\s+(\S+)", re.IGNORECASE)
        src_pat2 = re.compile(r"^\s*source\s+(\S+)", re.IGNORECASE)
        pipe_pat = re.compile(r"\|(\w+)")
        for lineno, line in enumerate(lines, 1):
            ls = line.strip()
            if ls.startswith("#"):
                continue
            m = func_pat.match(ls)
            if m:
                result.findings.append(AnalysisFinding(kind=FindingKind.FUNCTION, name=f"function: {m.group(1)}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                continue
            for pat in [src_pat1, src_pat2]:
                m = pat.match(ls)
                if m:
                    dep = m.group(1)
                    result.findings.append(AnalysisFinding(kind=FindingKind.DEPENDENCY, name=f"source: {dep}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                    result.dependencies.append(dep)
                    break
            for pm in pipe_pat.finditer(ls):
                result.business_findings.append(f"pipe: {pm.group(1)}")
        result.structural_summary.update({"functions": len(result.findings_by_kind(FindingKind.FUNCTION)), "dependencies": len(result.dependencies)})
        return result
