"""SQL semantic parser (Phase 18-G.3).

Recognizes DDL/DML via sqlparse or regex fallback.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum


class SQLKind(str, Enum):
    DDL = "ddl"; DML = "dml"; UNKNOWN = "unknown"
    CREATE_TABLE = "create_table"; CREATE_INDEX = "create_index"
    CREATE_VIEW = "create_view"; SELECT = "select"
    INSERT = "insert"; UPDATE = "update"; DELETE = "delete"
    MERGE = "merge"; DROP = "drop"


@dataclass
class SQLNode:
    kind: SQLKind; line: int = 0; name: str = ""; raw: str = ""
    attrs: dict = field(default_factory=dict)
    children: list = field(default_factory=list)
    semantic_gap: str | None = None

    def add(self, child):
        self.children.append(child); return child


@dataclass
class SemanticGap:
    construct: str; location: int; reason: str; suggested_strategy: str
"""SQL class"""

_STRIP_CHARS = str.maketrans("", "", "`\"'()[]")


def _strip_name(s):
    return s.translate(_STRIP_CHARS).strip(". ").upper()


class SQLParser:
    def __init__(self, source: str):
        self.source = source
        self.lines = source.split("\n")
        self.tree = SQLNode(kind=SQLKind.DDL, name="root")
        self.gaps = []
        self._tables = []; self._views = []; self._indexes = []
        self._procedures = []; self._referenced_tables = []

    def parse(self):
        try:
            import sqlparse as _sp
            for stmt in _sp.parse(self.source):
                s = str(stmt).strip().upper()
                if not s: continue
                u = s.upper()
                m = re.search(r"CREATE\s+TABLE\s+([\w.]+)", u)
                if m:
                    name = _strip_name(m.group(1))
                    self._tables.append(name)
                    self.tree.add(SQLNode(kind=SQLKind.CREATE_TABLE, name=name, raw=s[:80], attrs={"table": name}))
                m = re.search(r"CREATE\s+VIEW\s+([\w.]+)", u)
                if m:
                    name = _strip_name(m.group(1))
                    self._views.append(name)
                    self.tree.add(SQLNode(kind=SQLKind.CREATE_VIEW, name=name, raw=s[:80], attrs={"view": name}))
                m = re.search(r"INSERT\s+INTO\s+([\w.]+)", u)
                if m:
                    self._referenced_tables.append(_strip_name(m.group(1)))
                    self.tree.add(SQLNode(kind=SQLKind.INSERT, name="INSERT " + _strip_name(m.group(1)), raw=s[:80], attrs={"table": _strip_name(m.group(1))}))
                m = re.search(r"UPDATE\s+([\w.]+)", u)
                if m:
                    self._referenced_tables.append(_strip_name(m.group(1)))
                    self.tree.add(SQLNode(kind=SQLKind.UPDATE, name="UPDATE " + _strip_name(m.group(1)), raw=s[:80], attrs={"table": _strip_name(m.group(1))}))
                m = re.search(r"DELETE\s+FROM\s+([\w.]+)", u)
                if m:
                    self._referenced_tables.append(_strip_name(m.group(1)))
                    self.tree.add(SQLNode(kind=SQLKind.DELETE, name="DELETE " + _strip_name(m.group(1)), raw=s[:80], attrs={"table": _strip_name(m.group(1))}))
                m = re.search(r"MERGE\s+INTO\s+([\w.]+)", u)
                if m:
                    self._referenced_tables.append(_strip_name(m.group(1)))
                    self.tree.add(SQLNode(kind=SQLKind.MERGE, name="MERGE " + _strip_name(m.group(1)), raw=s[:80], attrs={"table": _strip_name(m.group(1))}))
                if re.search(r"\bSELECT\b", u):
                    frm = re.findall(r"FROM\s+([\w.]+)", u)
                    jns = re.findall(r"JOIN\s+([\w.]+)", u)
                    for t in frm + jns:
                        self._referenced_tables.append(_strip_name(t))
                    self.tree.add(SQLNode(kind=SQLKind.SELECT, name="SELECT", raw=s[:80], attrs={"tables": [_strip_name(t) for t in frm + jns]}))
        except ImportError:
            self._parse_regex()
        except Exception:
            self._parse_regex()
        return self.tree

    def _parse_regex(self):
        u = self.source.upper()
        for m in re.finditer(r"CREATE\s+TABLE\s+([\w.]+)", u):
            self._tables.append(_strip_name(m.group(1)))
            self.tree.add(SQLNode(kind=SQLKind.CREATE_TABLE, name=_strip_name(m.group(1)), raw=self._line_of(m.start())))
        for m in re.finditer(r"CREATE\s+VIEW\s+([\w.]+)", u):
            self._views.append(_strip_name(m.group(1)))
            self.tree.add(SQLNode(kind=SQLKind.CREATE_VIEW, name=_strip_name(m.group(1)), raw=self._line_of(m.start())))
        for m in re.finditer(r"INSERT\s+INTO\s+([\w.]+)", u):
            self._referenced_tables.append(_strip_name(m.group(1)))
        for m in re.finditer(r"UPDATE\s+([\w.]+)", u):
            self._referenced_tables.append(_strip_name(m.group(1)))
        for m in re.finditer(r"DELETE\s+FROM\s+([\w.]+)", u):
            self._referenced_tables.append(_strip_name(m.group(1)))
        for m in re.finditer(r"MERGE\s+INTO\s+([\w.]+)", u):
            self._referenced_tables.append(_strip_name(m.group(1)))
        if re.search(r"\bSELECT\b", u):
            frm = re.findall(r"FROM\s+([\w.]+)", u)
            jns = re.findall(r"JOIN\s+([\w.]+)", u)
            for t in frm + jns:
                self._referenced_tables.append(_strip_name(t))
            self.tree.add(SQLNode(kind=SQLKind.SELECT, name="SELECT", raw="SELECT ..."))

    def _line_of(self, pos):
        n = self.source[:pos].count("\n")
        if n < len(self.lines):
            return self.lines[n].translate(_STRIP_CHARS).strip().upper()
        return ""

    def summary(self):
        return {
            "tables": sorted(set(self._tables)),
            "views": sorted(set(self._views)),
            "indexes": sorted(set(self._indexes)),
            "procedures": self._procedures,
            "referenced_tables": sorted(set(self._referenced_tables)),
            "gaps": [{"construct": g.construct, "location": g.location, "reason": g.reason, "strategy": g.suggested_strategy} for g in self.gaps],
        }


__all__ = ["SQLNode", "SQLParser", "SQLKind", "SemanticGap"]
