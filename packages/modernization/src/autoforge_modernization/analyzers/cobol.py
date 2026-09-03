"""COBOL Source Analyzer (Phase 18-G.3)."""
from __future__ import annotations
import re
from autoforge_modernization.analyzers.base import TechnologyAnalyzer, AnalysisResult, AnalysisFinding, FindingKind, FindingConfidence

class COBOLAnalyzer(TechnologyAnalyzer):
    technology = "COBOL"

    def analyze(self, content, file_path=None):
        result = AnalysisResult(technology=self.technology, file_path=file_path, content_length=len(content))
        p, nb, c, b = self.count_loc(content, ["*", "/"])
        result.physical_lines, result.non_blank_lines, result.comment_lines, result.blank_lines = p, nb, c, b
        lines = content.split("\n")
        in_div = None
        div_findings, section_findings, para_findings = [], [], []
        # COBOL fixed format: col 1-6 sequence/area A, col 7 indicator, col 8-72 area B
        # Allow 6-char sequence area (digits, spaces, or nothing) before divisions
        seq_area = r"(?:\d{1,6}\s+|       ?|\s{0,7})"
        div_pat = re.compile(r"^" + seq_area + r"(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION\s*\.?")
        sec_pat = re.compile(r"^" + seq_area + r"(\w[\w-]*)\s+SECTION\s*\.", re.IGNORECASE)
        # Paragraph: word at col 8 (after 7-char area), followed by period
        para_pat = re.compile(r"^" + seq_area + r"(\w[\w-]*)\s*\.\s*$", re.IGNORECASE)
        data_pat = re.compile(r"^" + seq_area + r"(01|05|77|88)\s+([\w-]+)")
        copy_pat = re.compile(r"\b(?:COPY|COPYBOOK)\s+([\'\"]?)([\w.-]+)\1", re.IGNORECASE)
        sel_pat = re.compile(r"^" + seq_area + r"SELECT\s+(\w[\w-]*)", re.IGNORECASE)
        perf_pat = re.compile(r"\bPERFORM\s+(\w[\w-]*)(?:\s+(?:THRU|THROUGH)\s+(\w[\w-]*))?", re.IGNORECASE)
        call_pat = re.compile(r"\bCALL\s+([\'\"]?)([\w.-]+)\1", re.IGNORECASE)
        cics_pat = re.compile(r"EXEC\s+CICS\s+(\w+)", re.IGNORECASE)
        sql_pat = re.compile(r"EXEC\s+SQL", re.IGNORECASE)
        br_pats = [
            (re.compile(r"\bIF\s+.*\s+THEN", re.IGNORECASE), "conditional_logic"),
            (re.compile(r"\bEVALUATE\s+", re.IGNORECASE), "case_logic"),
            (re.compile(r"\bPERFORM\s+\w+\s+UNTIL", re.IGNORECASE), "loop_logic"),
            (re.compile(r"\bCOMPUTE\s+\w+\s*=", re.IGNORECASE), "calculation"),
            (re.compile(r"\bADD\s+.*\s+TO\s+\w+", re.IGNORECASE), "arithmetic"),
            (re.compile(r"\bSUBTRACT\s+.*\s+FROM", re.IGNORECASE), "arithmetic"),
        ]
        has_cics = has_sql = False
        for lineno, line in enumerate(lines, 1):
            ls = line.rstrip()
            if not ls or (len(ls) > 6 and ls[6:7] in ("*", "/", "D", "d")):
                continue
            m = div_pat.match(ls)
            if m:
                in_div = m.group(1).upper()
                div_findings.append(AnalysisFinding(kind=FindingKind.DIVISION, name=f"{in_div} DIVISION", location=f"L{lineno}", description=f"COBOL division: {in_div}", evidence=self._ev(ls, lineno)))
                continue
            if in_div == "PROCEDURE":
                m = sec_pat.match(ls)
                if m:
                    section_findings.append(AnalysisFinding(kind=FindingKind.SECTION, name=f"{m.group(1)} SECTION", location=f"L{lineno}", parent=div_findings[-1].finding_id if div_findings else None, evidence=self._ev(ls, lineno)))
                    continue
                m = para_pat.match(ls)
                if m:
                    para_findings.append(AnalysisFinding(kind=FindingKind.PARAGRAPH, name=m.group(1), location=f"L{lineno}", parent=section_findings[-1].finding_id if section_findings else (div_findings[-1].finding_id if div_findings else None), evidence=self._ev(ls, lineno)))
                    continue
            if in_div == "DATA":
                m = data_pat.match(ls)
                if m:
                    result.findings.append(AnalysisFinding(kind=FindingKind.DATA_DECLARATION, name=m.group(2), location=f"L{lineno}", detail={"level": m.group(1)}, evidence=self._ev(ls, lineno)))
                    continue
            m = copy_pat.search(ls)
            if m:
                result.findings.append(AnalysisFinding(kind=FindingKind.COPYBOOK_REF, name=m.group(2), location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                result.dependencies.append(m.group(2))
                continue
            m = sel_pat.match(ls)
            if m:
                result.findings.append(AnalysisFinding(kind=FindingKind.FILE_OPERATION, name=f"SELECT: {m.group(1)}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
                continue
            for pm in perf_pat.finditer(ls):
                result.findings.append(AnalysisFinding(kind=FindingKind.PROCEDURE_CALL, name=f"PERFORM: {pm.group(1)}", location=f"L{lineno}", detail={"target": pm.group(1), "thru": pm.group(2)}, evidence=self._ev(ls, lineno)))
                result.dependencies.append(pm.group(1))
            for cm in call_pat.finditer(ls):
                result.findings.append(AnalysisFinding(kind=FindingKind.PROCEDURE_CALL, name=f"CALL: {cm.group(2)}", location=f"L{lineno}", detail={"target": cm.group(2)}, evidence=self._ev(ls, lineno)))
                result.dependencies.append(cm.group(2))
            if cics_pat.search(ls):
                has_cics = True
                result.findings.append(AnalysisFinding(kind=FindingKind.CICS_COMMAND, name=f"CICS: {cics_pat.search(ls).group(1)}", location=f"L{lineno}", evidence=self._ev(ls, lineno)))
            if sql_pat.search(ls):
                has_sql = True
            for pat, rtype in br_pats:
                if pat.search(ls):
                    result.findings.append(AnalysisFinding(kind=FindingKind.BUSINESS_RULE, name=f"Business rule: {rtype}", location=f"L{lineno}", detail={"rule_type": rtype}, evidence=self._ev(ls, lineno), confidence=FindingConfidence.MEDIUM))
                    result.business_findings.append(f"{rtype} at L{lineno}")
                    break
        result.findings.extend(div_findings + section_findings + para_findings)
        result.structural_summary.update({"divisions": [f.name for f in div_findings], "sections": len(section_findings), "paragraphs": len(para_findings), "has_cics": has_cics, "has_sql": has_sql, "has_copybooks": any(f.kind == FindingKind.COPYBOOK_REF for f in result.findings)})
        return result
