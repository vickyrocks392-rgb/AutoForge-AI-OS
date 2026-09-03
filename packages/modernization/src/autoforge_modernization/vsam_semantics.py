"""VSAM semantic analysis (Phase 18-G.3).

Detects VSAM file operations from COBOL source:
- FD declarations with VSAM-specific organization
- OPEN/READ/WRITE/REWRITE/DELETE operations
- Key positions and record structures
Maps to modern file/persistence abstractions.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class VSAMStatus(str, Enum):
    TRANSFORMABLE = "TRANSFORMABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass
class VSAMDataset:
    name: str
    organization: str  # SEQUENTIAL | INDEXED | RELATIVE
    access_mode: str  # SEQUENTIAL | RANDOM | DYNAMIC
    key_position: int | None = None
    key_length: int | None = None
    key_field: str | None = None
    record_length: int | None = None
    status: VSAMStatus = VSAMStatus.REVIEW_REQUIRED


@dataclass
class VSAMOperation:
    verb: str
    dataset: str
    line: int
    raw: str
    status: VSAMStatus = VSAMStatus.REVIEW_REQUIRED
    ridfld: str | None = None
    key_field: str | None = None


class VSAMAnalyzer:
    """Analyze VSAM file operations from COBOL source."""

    FD_RE = re.compile(r"\bFD\s+([\w-]+)", re.IGNORECASE)
    ORGANIZATION_RE = re.compile(r"\bORGANIZATION\s+IS\s+(INDEXED|SEQUENTIAL|RELATIVE)", re.IGNORECASE)
    ACCESS_MODE_RE = re.compile(r"\bACCESS\s+MODE\s+IS\s+(SEQUENTIAL|RANDOM|DYNAMIC)", re.IGNORECASE)
    RECORD_KEY_RE = re.compile(r"\bRECORD\s+KEY\s+IS\s+([\w-]+)", re.IGNORECASE)
    OPEN_RE = re.compile(r"\bOPEN\s+(INPUT|OUTPUT|I-O|EXTEND)\s+([\w-]+)", re.IGNORECASE)
    READ_RE = re.compile(r"\bREAD\s+([\w-]+)", re.IGNORECASE)
    WRITE_RE = re.compile(r"\bWRITE\s+([\w-]+)", re.IGNORECASE)
    REWRITE_RE = re.compile(r"\bREWRITE\s+([\w-]+)", re.IGNORECASE)
    DELETE_RE = re.compile(r"\bDELETE\s+([\w-]+)", re.IGNORECASE)
    START_RE = re.compile(r"\bSTART\s+([\w-]+)", re.IGNORECASE)
    CLOSE_RE = re.compile(r"\bCLOSE\s+([\w-]+)", re.IGNORECASE)

    def __init__(self, source: str):
        self.source = source
        self.datasets: dict[str, VSAMDataset] = {}
        self.operations: list[VSAMOperation] = []
        self._current_fd: str | None = None

    def analyze(self) -> dict:
        for lineno, line in enumerate(self.source.split("\n"), 1):
            ls = line.strip()
            if m := self.FD_RE.search(ls):
                name = m.group(1).upper()
                self._current_fd = name
                if name not in self.datasets:
                    self.datasets[name] = VSAMDataset(name=name, organization="INDEXED", access_mode="SEQUENTIAL")
                continue
            if self._current_fd and (m := self.ORGANIZATION_RE.search(ls)):
                self.datasets[self._current_fd].organization = m.group(1).upper()
                continue
            if self._current_fd and (m := self.ACCESS_MODE_RE.search(ls)):
                self.datasets[self._current_fd].access_mode = m.group(1).upper()
                continue
            if self._current_fd and (m := self.RECORD_KEY_RE.search(ls)):
                self.datasets[self._current_fd].key_position = m.group(1).upper()
                continue
            if m := self.OPEN_RE.search(ls):
                self.operations.append(VSAMOperation(verb=f"OPEN-{m.group(1).upper()}",
                    dataset=m.group(2).upper(), line=lineno, raw=ls, status=VSAMStatus.TRANSFORMABLE))
                continue
            if m := self.READ_RE.search(ls):
                self.operations.append(VSAMOperation(verb="READ", dataset=m.group(1).upper(), line=lineno, raw=ls))
                continue
            if m := self.WRITE_RE.search(ls):
                self.operations.append(VSAMOperation(verb="WRITE", dataset=m.group(1).upper(), line=lineno, raw=ls))
                continue
            if m := self.REWRITE_RE.search(ls):
                self.operations.append(VSAMOperation(verb="REWRITE", dataset=m.group(1).upper(), line=lineno, raw=ls))
                continue
            if m := self.DELETE_RE.search(ls):
                self.operations.append(VSAMOperation(verb="DELETE", dataset=m.group(1).upper(), line=lineno, raw=ls))
                continue
            if m := self.START_RE.search(ls):
                self.operations.append(VSAMOperation(verb="START", dataset=m.group(1).upper(), line=lineno, raw=ls))
                continue
            if m := self.CLOSE_RE.search(ls):
                self.operations.append(VSAMOperation(verb="CLOSE", dataset=m.group(1).upper(), line=lineno, raw=ls,
                    status=VSAMStatus.TRANSFORMABLE))
        by_verb: dict = {}
        for op in self.operations:
            by_verb.setdefault(op.verb, []).append(op.line)
        return {
            "datasets": [
                {"name": ds.name, "org": ds.organization, "access": ds.access_mode, "key_field": ds.key_field}
                for ds in self.datasets.values()
            ],
            "operations": len(self.operations),
            "by_verb": {k: len(v) for k, v in by_verb.items()},
            "transformable": sum(1 for o in self.operations if o.status == VSAMStatus.TRANSFORMABLE),
            "review_required": sum(1 for o in self.operations if o.status == VSAMStatus.REVIEW_REQUIRED),
        }


__all__ = ["VSAMDataset", "VSAMOperation", "VSAMAnalyzer", "VSAMStatus"]
