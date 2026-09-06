"""CICS semantic nodes (Phase 18-G.3).

Parses EXEC CICS statements into structured CICSNode AST with
transformation status (TRANSFORMABLE | REVIEW_REQUIRED | BLOCKED).
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum


class CICSKind(str, Enum):
    SEND_MAP = "send_map"
    RECEIVE_MAP = "receive_map"
    LINK = "link"
    XCTL = "xctl"
    RETURN = "return"
    READ = "read"
    WRITE = "write"
    REWRITE = "rewrite"
    DELETE = "delete"
    START = "start"
    SYNCPOINT = "syncpoint"
    HANDLE_AID = "handle_aid"
    UNKNOWN = "unknown"


class CICSStatus(str, Enum):
    TRANSFORMABLE = "TRANSFORMABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass
class CICSNode:
    kind: CICSKind
    line: int
    raw: str
    program: str | None = None
    mapset: str | None = None
    map_name: str | None = None
    file_name: str | None = None
    attrs: dict = field(default_factory=dict)
    transformation_status: CICSStatus = CICSStatus.REVIEW_REQUIRED


class CICSParser:
    SEND_MAP_RE = re.compile(
        r"EXEC\s+CICS\s+SEND\s+MAP\s*\(\s*['\"]?([\w-]+)['\"]?\s*\)\s+MAPSET\s*\(\s*['\"]?([\w-]+)['\"]?\s*\)",
        re.IGNORECASE,
    )
    RECEIVE_MAP_RE = re.compile(
        r"EXEC\s+CICS\s+RECEIVE\s+MAP\s*\(\s*['\"]?([\w-]+)['\"]?\s*\)\s+MAPSET\s*\(\s*['\"]?([\w-]+)['\"]?\s*\)",
        re.IGNORECASE,
    )

    LINK_RE = re.compile(r"EXEC\s+CICS\s+LINK\s*\(\s*PROGRAM\s*=\s*([\w-]+)", re.IGNORECASE)
    XCTL_RE = re.compile(r"EXEC\s+CICS\s+XCTL\s*\(\s*PROGRAM\s*=\s*([\w-]+)", re.IGNORECASE)
    RETURN_RE = re.compile(r"EXEC\s+CICS\s+RETURN(?:\s*\(\s*PROGRAM\s*=\s*([\w-]+))?", re.IGNORECASE)
    READ_RE = re.compile(r"EXEC\s+CICS\s+READ\s*(?:\(\s*FILE\s*=\s*([\w-]+))?", re.IGNORECASE)
    WRITE_RE = re.compile(r"EXEC\s+CICS\s+WRITE\s*(?:\(\s*FILE\s*=\s*([\w-]+))?", re.IGNORECASE)
    START_RE = re.compile(r"EXEC\s+CICS\s+START\s*(?:\(\s*TRANSID\s*=\s*([\w-]+))?", re.IGNORECASE)
    SYNCPOINT_RE = re.compile(r"EXEC\s+CICS\s+SYNCPOINT\b", re.IGNORECASE)
    EXEC_CICS_RE = re.compile(r"EXEC\s+CICS\s+(\w+)", re.IGNORECASE)

    def __init__(self, source: str):
        self.source = source
        self.nodes: list[CICSNode] = []
        self._transactions: set[str] = set()
        self._programs: set[str] = set()

    def parse(self) -> list[CICSNode]:
        for lineno, line in enumerate(self.source.split("\n"), 1):
            ls = line.strip()
            if not ls:
                continue
            if m := self.SEND_MAP_RE.search(ls):
                self.nodes.append(CICSNode(kind=CICSKind.SEND_MAP, line=lineno, raw=ls,
                    map_name=m.group(1).upper(), mapset=m.group(2).upper(),
                    transformation_status=CICSStatus.TRANSFORMABLE,
                    attrs={"direction": "output"}))
                continue
            if m := self.RECEIVE_MAP_RE.search(ls):
                self.nodes.append(CICSNode(kind=CICSKind.RECEIVE_MAP, line=lineno, raw=ls,
                    map_name=m.group(1).upper(), mapset=m.group(2).upper(),
                    transformation_status=CICSStatus.TRANSFORMABLE,
                    attrs={"direction": "input"}))
                continue
            if m := self.LINK_RE.search(ls):
                pgm = m.group(1).upper()
                self._programs.add(pgm)
                self.nodes.append(CICSNode(kind=CICSKind.LINK, line=lineno, raw=ls, program=pgm,
                    transformation_status=CICSStatus.REVIEW_REQUIRED))
                continue
            if m := self.XCTL_RE.search(ls):
                pgm = m.group(1).upper()
                self._programs.add(pgm)
                self.nodes.append(CICSNode(kind=CICSKind.XCTL, line=lineno, raw=ls, program=pgm,
                    transformation_status=CICSStatus.REVIEW_REQUIRED))
                continue
            if m := self.RETURN_RE.search(ls):
                pgm = m.group(1).upper() if m.group(1) else None
                self.nodes.append(CICSNode(kind=CICSKind.RETURN, line=lineno, raw=ls, program=pgm,
                    transformation_status=CICSStatus.REVIEW_REQUIRED))
                continue
            if m := self.READ_RE.search(ls):
                fname = m.group(1).upper() if m.group(1) else None
                self.nodes.append(CICSNode(kind=CICSKind.READ, line=lineno, raw=ls, file_name=fname,
                    transformation_status=CICSStatus.REVIEW_REQUIRED))
                continue
            if m := self.WRITE_RE.search(ls):
                fname = m.group(1).upper() if m.group(1) else None
                self.nodes.append(CICSNode(kind=CICSKind.WRITE, line=lineno, raw=ls, file_name=fname,
                    transformation_status=CICSStatus.REVIEW_REQUIRED))
                continue
            if m := self.START_RE.search(ls):
                tid = m.group(1).upper() if m.group(1) else None
                if tid:
                    self._transactions.add(tid)
                self.nodes.append(CICSNode(kind=CICSKind.START, line=lineno, raw=ls,
                    transformation_status=CICSStatus.REVIEW_REQUIRED,
                    attrs={"transid": tid} if tid else {}))
                continue
            if self.SYNCPOINT_RE.search(ls):
                self.nodes.append(CICSNode(kind=CICSKind.SYNCPOINT, line=lineno, raw=ls,
                    transformation_status=CICSStatus.TRANSFORMABLE))
                continue
            if self.EXEC_CICS_RE.search(ls):
                vm = self.EXEC_CICS_RE.search(ls)
                verb = vm.group(1).upper() if vm else "UNKNOWN"
                self.nodes.append(CICSNode(kind=CICSKind.UNKNOWN, line=lineno, raw=ls,
                    transformation_status=CICSStatus.BLOCKED,
                    attrs={"verb": verb}))
        return self.nodes

    def summary(self) -> dict:
        by_kind: dict = {}
        for n in self.nodes:
            by_kind.setdefault(n.kind.value, []).append(n.line)
        return {
            "total_cics_statements": len(self.nodes),
            "by_kind": {k: len(v) for k, v in by_kind.items()},
            "transformable": sum(1 for n in self.nodes if n.transformation_status == CICSStatus.TRANSFORMABLE),
            "review_required": sum(1 for n in self.nodes if n.transformation_status == CICSStatus.REVIEW_REQUIRED),
            "blocked": sum(1 for n in self.nodes if n.transformation_status == CICSStatus.BLOCKED),
            "programs": sorted(self._programs),
            "transactions": sorted(self._transactions),
        }


__all__ = ["CICSKind", "CICSStatus", "CICSNode", "CICSParser"]
