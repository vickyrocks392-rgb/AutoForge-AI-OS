"""JCL Analyzer (Phase 18-G.3)."""
from __future__ import annotations
import re
from autoforge_modernization.analyzers.base import (
    TechnologyAnalyzer, AnalysisResult, AnalysisFinding, FindingKind)


class JCLAnalyzer(TechnologyAnalyzer):
    technology = "JCL"

    def analyze(self, content, file_path=None):
        result = AnalysisResult(technology=self.technology, file_path=file_path, content_length=len(content))
        p, nb, c, b = self.count_loc(content, ["//*", "#"])
        result.physical_lines = p
        result.non_blank_lines = nb
        result.comment_lines = c
        result.blank_lines = b
        lines = content.split("\n")
        job_pat = re.compile(r"//(\w+)\s+JOB\s", re.IGNORECASE)
        exec_pat = re.compile(r"//(\w+)\s+EXEC\s+(\S+)", re.IGNORECASE)
        dsn_pat = re.compile(r"//(\w+)\s+DD\s+DSN=([^\s,]+)", re.IGNORECASE)
        proc_pat = re.compile(r"//(\w+)\s+PROC\s*=", re.IGNORECASE)
        job_name = None
        steps = []
        datasets = []
        for lineno, line in enumerate(lines, 1):
            ls = line.strip()
            if not ls or ls.startswith("//*"):
                continue
            m = job_pat.match(ls)
            if m:
                job_name = m.group(1)
                result.findings.append(AnalysisFinding(kind=FindingKind.STRUCTURAL, name=f"JOB: {job_name}", location=f"L{lineno}", description=f"JCL Job: {job_name}", evidence=self._ev(ls, lineno)))
                continue
            m = exec_pat.match(ls)
            if m:
                sname, prog = m.group(1), m.group(2)
                result.findings.append(AnalysisFinding(kind=FindingKind.JCL_STEP, name=f"STEP: {sname} -> {prog}", location=f"L{lineno}", detail={"step": sname, "program": prog}, evidence=self._ev(ls, lineno)))
                steps.append({"name": sname, "program": prog, "line": lineno})
                continue
            m = proc_pat.match(ls)
            if m:
                result.findings.append(AnalysisFinding(kind=FindingKind.JCL_PROCEDURE, name=f"PROC: {m.group(1)}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                continue
            for dm in dsn_pat.finditer(ls):
                dsn = dm.group(2)
                result.findings.append(AnalysisFinding(kind=FindingKind.JCL_DATASET, name=f"DSN: {dsn}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                datasets.append(dsn)
        result.structural_summary.update({"job_name": job_name, "steps": len(steps), "step_list": steps, "datasets": len(datasets)})
        return result
