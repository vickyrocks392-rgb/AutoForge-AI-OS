"""Real COBOL semantic parser (Phase 18-G.3).

State-machine, line-oriented parser producing a typed COBOLNode AST.
Supported: PROGRAM-ID, 4 divisions, SECTIONS, PARAGRAPHS, WORKING-STORAGE,
FILE/LINKAGE sections, PIC (X/9/V/S/COMP/COMP-3/BINARY), VALUE, MOVE,
IF/EVALUATE/COMPUTE, ADD/SUB/MUL/DIV, PERFORM(THRU/VARYING/UNTIL), CALL,
COPY, SELECT/ASSIGN, OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START,
STRING/UNSTRING/INSPECT, SET/GO TO/EXIT/STOP RUN/GOBACK.
"""
from __future__ import annotations
import re
from autoforge_modernization.cobol_ast import COBOLNode, COBOLKind, SourceLocation


class COBOLParser:
    DIVISION_RE = re.compile(r"^\s*(IDENTIFICATION|ENVIRONMENT|DATA|PROCEDURE)\s+DIVISION", re.IGNORECASE)
    SECTION_RE = re.compile(r"^\s*([A-Z0-9][\w-]*)\s+SECTION\s*\.\s*$", re.IGNORECASE)
    PARA_RE = re.compile(r"^\s*([A-Z0-9][\w-]*)\s*\.\s*$", re.IGNORECASE)
    DATA_RE = re.compile(r"^\s*(0?\d|77|88)\s+([A-Z0-9-]+)(?:\s+REDEFINES\s+([A-Z0-9-]+))?(?:\s+PIC\s+(\S+))?(?:\s+VALUE\s+(\S+))?", re.IGNORECASE)
    SELECT_RE = re.compile(r"^\s*SELECT\s+([A-Z0-9-]+)\s+ASSIGN\s+TO\s+([\w\s\-\.$\(\)]+?)\s*\.", re.IGNORECASE)
    COPY_RE = re.compile(r"\bCOPY\s+([\"']?)([\w.-]+)\1", re.IGNORECASE)
    CALL_RE = re.compile(r"\bCALL\s+([\"']?)([\w.-]+)\1", re.IGNORECASE)
    PERFORM_RE = re.compile(r"\bPERFORM\s+([\w-]+)(?:\s+THRU\s+([\w-]+))?(?:\s+(VARYING|UNTIL)\s+(\S+))?", re.IGNORECASE)
    MOVE_RE = re.compile(r"\bMOVE\s+(.+?)\s+TO\s+([A-Z0-9-]+(?:\s+[A-Z0-9-]+)*)", re.IGNORECASE)
    COMPUTE_RE = re.compile(r"\bCOMPUTE\s+([A-Z0-9-]+)\s*=\s*(.+)", re.IGNORECASE)
    IF_RE = re.compile(r"\bIF\s+(.+?)\s+THEN\b", re.IGNORECASE)
    EVALUATE_RE = re.compile(r"\bEVALUATE\s+(.+)", re.IGNORECASE)
    ADD_RE = re.compile(r"\bADD\s+(.+?)\s+TO\s+([A-Z0-9-]+)", re.IGNORECASE)
    SUB_RE = re.compile(r"\bSUBTRACT\s+(.+?)\s+FROM\s+([A-Z0-9-]+)", re.IGNORECASE)
    MUL_RE = re.compile(r"\bMULTIPLY\s+(.+?)\s+BY\s+([A-Z0-9-]+)", re.IGNORECASE)
    DIV_RE = re.compile(r"\bDIVIDE\s+(.+?)\s+INTO\s+([A-Z0-9-]+)", re.IGNORECASE)
    IO_VERB_RE = re.compile(r"^\s*(OPEN|CLOSE|READ|WRITE|REWRITE|DELETE|START)\b", re.IGNORECASE)
    WS_HDR_RE = re.compile(r"\bWORKING-STORAGE\s+SECTION\b", re.IGNORECASE)
    LS_HDR_RE = re.compile(r"\bLINKAGE-SECTION\b", re.IGNORECASE)
    FS_HDR_RE = re.compile(r"\bFILE-SECTION\b", re.IGNORECASE)
    FD_RE = re.compile(r"\bFD\s+([A-Z0-9-]+)", re.IGNORECASE)
    PROG_ID_RE = re.compile(r"\bPROGRAM-ID\.\s*([A-Z0-9][\w-]*)", re.IGNORECASE)
    VERBS = ("MOVE", "IF", "EVALUATE", "COMPUTE", "ADD", "SUBTRACT", "MULTIPLY", "DIVIDE", "PERFORM", "CALL", "COPY", "OPEN", "CLOSE", "READ", "WRITE", "REWRITE", "DELETE", "START", "STRING", "UNSTRING", "INSPECT", "SET", "GO", "EXIT", "STOP", "GOBACK")
    VERB_RE = re.compile(r"^\s*(" + "|".join(VERBS) + r")\b", re.IGNORECASE)

    def __init__(self, tokens):
        self.tokens = tokens
        self.tree = COBOLNode(kind=COBOLKind.PROGRAM)
        self.gaps = []
        self._copybook_refs = []
        self._external_calls = []
        self._pic_map = {}
        self._paragraphs = []
        self._performed_targets = []
        self._files = []

    def _is_verb(self, ls):
        return bool(self.VERB_RE.match(ls))

    def _pic_to_java(self, pic):
        if not pic:
            return "String", '""'
        p = pic.upper().strip()
        if "COMP-3" in p or "PACKED-DECIMAL" in p:
            return "BigDecimal", "BigDecimal.ZERO"
        if "COMP" in p or "BINARY" in p:
            return "long" if "S" in p else "int", "0L" if "S" in p else "0"
        if p.startswith("X") or p.startswith("X("):
            return "String", '""'
        if p.startswith("S9") or "S9(" in p:
            return "long", "0L"
        if p.startswith("9") or p.startswith("9("):
            digits = p.count("9")
            if "V" in p: return "BigDecimal", "BigDecimal.ZERO"
            if digits > 9: return "BigDecimal", "BigDecimal.ZERO"
            if digits > 5: return "long", "0L"
            return "int", "0"
        return "String", '""'
    def parse(self):
        in_div = None; in_data = None; current_para = None; i = 0
        while i < len(self.tokens):
            tok = self.tokens[i]; text = tok["text"]; line = tok["line"]; ls = text.strip()
            if not ls: i += 1; continue
            m = self.PROG_ID_RE.search(ls)
            if m and not self.tree.name:
                self.tree.name = m.group(1).upper(); self.tree.location = SourceLocation(line=line); i += 1; continue
            m = self.DIVISION_RE.match(ls)
            if m:
                in_div = m.group(1).upper()
                self.tree.add(COBOLNode(kind=COBOLKind.DIVISION, name=f"{in_div} DIVISION", location=SourceLocation(line=line), raw=ls))
                if in_div == "PROCEDURE": in_data = None
                i += 1; continue
            m = self.SECTION_RE.match(ls)
            if m and in_div == "PROCEDURE":
                current_para = None
                self.tree.children[-1].add(COBOLNode(kind=COBOLKind.SECTION, name=f"{m.group(1).upper()} SECTION", location=SourceLocation(line=line), raw=ls)); i += 1; continue
            if in_div == "DATA":
                if self.WS_HDR_RE.search(ls): in_data = "WS"; self.tree.children[-1].add(COBOLNode(kind=COBOLKind.WORKING_STORAGE, name="WORKING-STORAGE SECTION", location=SourceLocation(line=line), raw=ls)); i += 1; continue
                if self.FS_HDR_RE.search(ls): in_data = "FS"; self.tree.children[-1].add(COBOLNode(kind=COBOLKind.FILE_SECTION, name="FILE SECTION", location=SourceLocation(line=line), raw=ls)); i += 1; continue
                if self.LS_HDR_RE.search(ls): in_data = "LS"; self.tree.children[-1].add(COBOLNode(kind=COBOLKind.LINKAGE_SECTION, name="LINKAGE SECTION", location=SourceLocation(line=line), raw=ls)); i += 1; continue
                m = self.FD_RE.search(ls)
                if m: self.tree.children[-1].add(COBOLNode(kind=COBOLKind.SELECT, name=f"FD: {m.group(1)}", location=SourceLocation(line=line), raw=ls, attrs={"fd": m.group(1)})); i += 1; continue
                m = self.DATA_RE.match(ls)
                if m and in_data:
                    level, name, redef, pic, value = m.group(1), m.group(2).upper(), m.group(3), m.group(4), m.group(5)
                    jtype, default = self._pic_to_java(pic or ""); self._pic_map[name] = (jtype, default)
                    parent = self.tree.children[-1]
                    for c in reversed(parent.children):
                        if c.kind in (COBOLKind.WORKING_STORAGE, COBOLKind.FILE_SECTION, COBOLKind.LINKAGE_SECTION):
                            c.add(COBOLNode(kind=COBOLKind.DATA_ITEM, name=name, location=SourceLocation(line=line), raw=ls, attrs={"level": level, "pic": pic or "", "value": value or "", "redefines": redef or "", "java_type": jtype, "default": default})); break
                    i += 1; continue
                i += 1; continue
            m = self.SELECT_RE.match(ls)
            if m and in_div == "ENVIRONMENT":
                fname, assign = m.group(1).upper(), m.group(2).strip(); self._files.append({"name": fname, "assign": assign})
                self.tree.add(COBOLNode(kind=COBOLKind.SELECT, name=f"SELECT {fname}", location=SourceLocation(line=line), raw=ls, attrs={"file": fname, "assign": assign})); i += 1; continue
            if in_div == "PROCEDURE":
                m = self.PARA_RE.match(ls)
                if m and not self._is_verb(ls):
                    name = m.group(1).upper(); current_para = self.tree.children[-1].add(COBOLNode(kind=COBOLKind.PARAGRAPH, name=name, location=SourceLocation(line=line), raw=ls)); self._paragraphs.append(name); i += 1; continue
            node = current_para if current_para else self.tree
            m = self.COPY_RE.search(ls)
            if m: self._copybook_refs.append(m.group(2)); node.add(COBOLNode(kind=COBOLKind.COPY, name=m.group(2), location=SourceLocation(line=line), raw=ls, attrs={"book": m.group(2)})); i += 1; continue
            m = self.CALL_RE.search(ls)
            if m: tgt = m.group(2).upper(); self._external_calls.append(tgt); node.add(COBOLNode(kind=COBOLKind.CALL, name=tgt, location=SourceLocation(line=line), raw=ls, attrs={"target": tgt})); i += 1; continue
            m = self.PERFORM_RE.search(ls)
            if m:
                tgt, thru, loop, cond = m.group(1).upper(), m.group(2), m.group(3), m.group(4)
                self._performed_targets.append(tgt)
                if thru: self._performed_targets.append(thru)
                attrs = {"target": tgt, "thru": thru or ""}
                if loop: attrs["loop"] = loop; attrs["condition"] = cond or ""
                node.add(COBOLNode(kind=COBOLKind.PERFORM, name=f"PERFORM {tgt}", location=SourceLocation(line=line), raw=ls, attrs=attrs)); i += 1; continue
            m = self.MOVE_RE.search(ls)
            if m: node.add(COBOLNode(kind=COBOLKind.MOVE, name=f"MOVE TO {m.group(2)}", location=SourceLocation(line=line), raw=ls, attrs={"source": m.group(1).strip(), "targets": [d.strip() for d in m.group(2).split()]})); i += 1; continue
            m = self.COMPUTE_RE.search(ls)
            if m: node.add(COBOLNode(kind=COBOLKind.COMPUTE, name=m.group(1).upper(), location=SourceLocation(line=line), raw=ls, attrs={"target": m.group(1).upper(), "expression": m.group(2).strip().rstrip(".")})); i += 1; continue
            m = self.IF_RE.search(ls)
            if m: node.add(COBOLNode(kind=COBOLKind.IF, name="IF", location=SourceLocation(line=line), raw=ls, attrs={"condition": m.group(1).strip()})); i += 1; continue
            m = self.EVALUATE_RE.search(ls)
            if m: node.add(COBOLNode(kind=COBOLKind.EVALUATE, name="EVALUATE", location=SourceLocation(line=line), raw=ls, attrs={"subject": m.group(1).strip()})); i += 1; continue
            handled = False
            for pat, op in ((self.ADD_RE, "ADD"), (self.SUB_RE, "SUBTRACT"), (self.MUL_RE, "MULTIPLY"), (self.DIV_RE, "DIVIDE")):
                m = pat.search(ls)
                if m: node.add(COBOLNode(kind=COBOLKind.ARITHMETIC, name=f"{op} -> {m.group(2)}", location=SourceLocation(line=line), raw=ls, attrs={"op": op, "operands": m.group(1).strip(), "target": m.group(2).strip()})); handled = True; break
            if not handled:
                m = self.IO_VERB_RE.match(ls)
                if m: verb = m.group(1).upper(); node.add(COBOLNode(kind=COBOLKind(verb.lower()), name=verb, location=SourceLocation(line=line), raw=ls, attrs={"rest": ls[len(verb):].strip()})); handled = True
            if not handled:
                for kw, kind in (("STRING", "STRING_OP"), ("UNSTRING", "STRING_OP"), ("INSPECT", "INSPECT"), ("SET", "SET"), ("GO TO", "GOTO"), ("EXIT PROGRAM", "EXIT"), ("GOBACK", "EXIT"), ("EXIT", "EXIT"), ("STOP RUN", "EXIT")):
                    if re.match(r"^\s*" + kw + r"\b", ls, re.IGNORECASE): node.add(COBOLNode(kind=COBOLKind(kind.lower()), name=kw.upper(), location=SourceLocation(line=line), raw=ls)); break
            i += 1
        return self.tree

    def summary(self):
        return {
            "program_id": self.tree.name,
            "copybooks": sorted(set(self._copybook_refs)),
            "external_calls": sorted(set(self._external_calls)),
            "performed_targets": sorted(set(self._performed_targets)),
            "paragraphs": self._paragraphs,
            "files": self._files,
            "data_items": list(self._pic_map.keys()),
            "data_types": dict(self._pic_map),
            "gaps": [{"construct": g.construct, "location": str(g.location), "reason": g.reason, "strategy": g.suggested_strategy} for g in self.gaps],
        }


__all__ = ["COBOLParser"]
