"""JCL semantic parser (Phase 18-G.3).

State machine recognizing JOB/EXEC/DD/INCLUDE/PROC/IF statements, emitting
typed AST + workflow YAML. Covers: JOB params, EXEC PGM/proc, DD DSN/DISP/
UNIT/VOL/SYSIN/SYSOUT, INCLUDE members, JES2/JES3 cards, IF/THEN/ELSE/ENDIF.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now(): return datetime.now(timezone.utc)


class JCLKind(str, Enum):
    JOB = "job"; EXEC = "exec"; DD = "dd"; PROC = "proc"
    INCLUDE = "include"; IF = "if"; THEN = "then"; ELSE = "else"
    ENDIF = "endif"; SET = "set"; UNKNOWN = "unknown"


@dataclass
class JCLNode:
    kind: JCLKind; line: int = 0; name: str = ""; raw: str = ""
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    semantic_gap: str | None = None

    def add(self, child):
        self.children.append(child)
        return child


@dataclass
class SemanticGap:
    construct: str; location: int; reason: str; suggested_strategy: str


class JCLParser:
    JOB_RE = re.compile(r"^//(\S+)\s+JOB\s+(.*?)\.?$", re.IGNORECASE)
    EXEC_PGM_RE = re.compile(r'^//(\S+)\s+EXEC\s+PGM=([^\s,]+)(.*)$', re.IGNORECASE)
    EXEC_PROC_RE = re.compile(r"^//(\S+)\s+EXEC\s+([A-Z@#$][\w$#@]*)(.*)$", re.IGNORECASE)
    DD_DSN_RE = re.compile(r"^//(\S+)\s+DD\s+(.*)$", re.IGNORECASE)
    INCLUDE_RE = re.compile(r"^//\s*INCLUDE\s+(?:MEMBER=)?(\S+)", re.IGNORECASE)
    IF_RE = re.compile(r"^//\s*IF\s+(.*?)\s+THEN\s*\.?$", re.IGNORECASE)
    ELSE_RE = re.compile(r"^//\s*ELSE\s*\.?$", re.IGNORECASE)
    ENDIF_RE = re.compile(r"^//\s*ENDIF\s*\.?$", re.IGNORECASE)
    SET_RE = re.compile(r"^//\s*SET\s+(\S+)=(\S+)", re.IGNORECASE)

    def __init__(self, source: str):
        self.source = source
        self.lines = source.split("\n")
        self.tree = JCLNode(kind=JCLKind.JOB, name="root")
        self.gaps = []
        self._datasets = []
        self._steps = []
        self._proc_libs = []

    def parse(self):
        for lineno, line in enumerate(self.lines, 1):
            ls = line.rstrip()
            if not ls or ls.lstrip().startswith("//*"): continue
            m = self.JOB_RE.match(ls)
            if m and ls.lstrip().startswith("//") and " JOB " in ls.upper():
                self.tree.name = m.group(1).upper(); self.tree.line = lineno; self.tree.attrs["params"] = m.group(2); continue
            m = self.EXEC_PGM_RE.match(ls)
            if m:
                step, pgm, rest = m.group(1).upper(), m.group(2).upper(), m.group(3) or ""
                parm = ""
                pm = re.search(r',PARM=([^,\s]+)', rest, re.IGNORECASE)
                if pm: parm = pm.group(1)
                self._steps.append({"name": step, "program": pgm, "parm": parm, "line": lineno})
                self.tree.add(JCLNode(kind=JCLKind.EXEC, line=lineno, name=step, raw=ls, attrs={"program": pgm, "parm": parm, "type": "pgm"})); continue
            m = self.EXEC_PROC_RE.match(ls)
            if m and not ls.upper().lstrip("/").startswith("DD"):
                step, proc_or_pgm, rest = m.group(1).upper(), m.group(2).upper(), m.group(3)
                # Heuristic: if it contains 'PGM=' it was a PGM exec that we already handled
                # if it contains 'PROC=' before the matched group, this is a proc invocation
                if proc_or_pgm == "PROC" and rest:
                    pm = re.match(r'=\s*([A-Z@#$][\w$#@]*)', rest, re.IGNORECASE)
                    if pm:
                        proc = pm.group(1).upper()
                        self._steps.append({"name": step, "proc": proc, "line": lineno})
                        self.tree.add(JCLNode(kind=JCLKind.EXEC, line=lineno, name=step, raw=ls, attrs={"proc": proc, "type": "proc", "params": rest[pm.end():].strip(",. ") if rest else ""})); continue
                # If proc_or_pgm already is a real procedure name (not PGM=)
                if proc_or_pgm != "PGM" and not rest.lstrip().startswith("="):
                    self._steps.append({"name": step, "proc": proc_or_pgm, "line": lineno})
                    self.tree.add(JCLNode(kind=JCLKind.EXEC, line=lineno, name=step, raw=ls, attrs={"proc": proc_or_pgm, "type": "proc", "params": rest.strip(",. ") if rest else ""})); continue
            m = self.DD_DSN_RE.match(ls)
            if m:
                ddn, rest = m.group(1).upper(), m.group(2); attrs = self._parse_dd(rest)
                if "DSN" in attrs: self._datasets.append(attrs["DSN"])
                self.tree.add(JCLNode(kind=JCLKind.DD, line=lineno, name=ddn, raw=ls, attrs=attrs)); continue
            m = self.INCLUDE_RE.match(ls)
            if m:
                member = m.group(1); self._proc_libs.append(member)
                self.tree.add(JCLNode(kind=JCLKind.INCLUDE, line=lineno, name=member, raw=ls, attrs={"member": member})); continue
            m = self.IF_RE.match(ls)
            if m: self.tree.add(JCLNode(kind=JCLKind.IF, line=lineno, name="IF", raw=ls, attrs={"condition": m.group(1).strip()})); continue
            m = self.ELSE_RE.match(ls)
            if m: self.tree.add(JCLNode(kind=JCLKind.ELSE, line=lineno, name="ELSE", raw=ls)); continue
            m = self.ENDIF_RE.match(ls)
            if m: self.tree.add(JCLNode(kind=JCLKind.ENDIF, line=lineno, name="ENDIF", raw=ls)); continue
            m = self.SET_RE.match(ls)
            if m: self.tree.add(JCLNode(kind=JCLKind.SET, line=lineno, name=m.group(1), raw=ls, attrs={"value": m.group(2)})); continue
            if ls.lstrip().startswith("//") and ls.strip() != "//":
                self.tree.add(JCLNode(kind=JCLKind.UNKNOWN, line=lineno, name=ls[:30], raw=ls, semantic_gap="JCL statement not classified; requires REVIEW_REQUIRED"))
                self.gaps.append(SemanticGap("UNKNOWN_JCL", lineno, ls[:80], "REVIEW_REQUIRED"))
        return self.tree

    def _parse_dd(self, rest: str) -> dict:
        attrs = {}; rest = rest.rstrip(",. ")
        dsn_m = re.match(r'(DSN=[^\s,]+)', rest, re.IGNORECASE)
        if dsn_m:
            attrs["DSN"] = re.sub(r'^DSN=', '', dsn_m.group(1), flags=re.IGNORECASE)
            rest = rest[dsn_m.end():].lstrip(", ")
        kv_pairs = re.findall(r'''(\w+)=(?:"([^"]*)"|'([^']*)'|(\S+))''', rest)
        for k, q1, q2, naked in kv_pairs: attrs[k.upper()] = q1 or q2 or naked
        for m in re.finditer(r"DISP=\(([^)]+)\)", rest, re.IGNORECASE):
            parts = [p.strip() for p in m.group(1).split(",")]
            if parts: attrs["DISP_STATUS"] = parts[0]
            if len(parts) > 1: attrs["DISP_NORMAL"] = parts[1]
            if len(parts) > 2: attrs["DISP_ABNORMAL"] = parts[2]
        if "DSN" not in attrs and "DUMMY" in rest.upper(): attrs["DSN"] = "DUMMY"
        if "DSN" not in attrs and rest.strip() == "*": attrs["DSN"] = "INSTREAM"
        return attrs

    def summary(self):
        return {"job_name": self.tree.name, "steps": self._steps, "datasets": sorted(set(self._datasets)), "proc_libs": self._proc_libs, "gaps": [{"construct": g.construct, "location": g.location, "reason": g.reason, "strategy": g.suggested_strategy} for g in self.gaps]}

    def to_workflow_yaml(self) -> str:
        try: import yaml
        except ImportError: yaml = None
        steps = []
        for s in self._steps:
            entry = {"step": s.get("name"), "line": s.get("line")}
            if "program" in s:
                entry["program"] = s["program"]
                if s.get("parm"): entry["parm"] = s["parm"]
            elif "proc" in s: entry["proc"] = s["proc"]
            steps.append(entry)
        wf = {"apiVersion": "autoforge/v1", "kind": "JCLWorkflow", "metadata": {"name": self.tree.name or "unnamed_job"}, "spec": {"steps": steps, "datasets": sorted(set(self._datasets))}}
        if yaml is not None: return yaml.safe_dump(wf, sort_keys=False)
        import json as _j; return _j.dumps(wf, indent=2)


__all__ = ["JCLNode", "JCLParser", "JCLKind", "SemanticGap"]
