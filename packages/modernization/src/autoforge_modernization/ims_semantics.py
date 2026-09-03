"""IMS DBD/PSB semantic parsing (Phase 18-G.3).

Parses IMS Database Descriptor (DBD) and Program Specification Block (PSB)
into structured representation. DBD defines segments/fields/hierarchy.
PSB defines program access via PCBs.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum


class IMSStatus(str, Enum):
    TRANSFORMABLE = "TRANSFORMABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"
    BLOCKED = "BLOCKED"


@dataclass
class IMSField:
    name: str
    line: int
    type: str = "C"  # C | P | X | binary
    start: int | None = None
    length: int | None = None


@dataclass
class IMSSegment:
    name: str
    line: int
    parent: str | None = None
    children: list[str] = field(default_factory=list)
    fields: list[IMSField] = field(default_factory=list)
    segment_length: int | None = None
class DBDParser:
    """Parse IMS DBD (Database Descriptor) into DBDatabase structure."""

    DBDNAME_RE = re.compile(r"DBD\s+NAME\s*=\s*([\w-]+)", re.IGNORECASE)
    ACCESS_RE = re.compile(r"ACCESS\s*=\s*(\w+)", re.IGNORECASE)
    SEGM_RE = re.compile(r"SEGM\s+NAME\s*=\s*([\w-]+)", re.IGNORECASE)
    PARENT_RE = re.compile(r"PARENT\s*=\s*([\w-]+)", re.IGNORECASE)
    FIELD_RE = re.compile(r"FIELD\s+NAME\s*=\s*([\w-]+)\s*,\s*TYPE\s*=\s*([CPX])\s*,\s*START\s*=\s*(\d+)\s*,\s*LENGTH\s*=\s*(\d+)", re.IGNORECASE)
    FIELD_SIMPLE_RE = re.compile(r"FIELD\s+NAME\s*=\s*([\w-]+)", re.IGNORECASE)
    SEGLEN_RE = re.compile(r"SEGLEN\s*=\s*(\d+)", re.IGNORECASE)

    def __init__(self, source: str):
        self.source = source
        self.database: DBDatabase | None = None

    def parse(self) -> DBDatabase | None:
        db: DBDatabase | None = None
        current_seg: IMSSegment | None = None
        segment_map: dict = {}

        for lineno, line in enumerate(self.source.split("\n"), 1):
            ls = line.strip()
            if not ls or ls.startswith("*"):
                continue
            if m := self.DBDNAME_RE.search(ls):
                am = self.ACCESS_RE.search(ls)
                db = DBDatabase(name=m.group(1).upper(), access_method=am.group(1).upper() if am else "UNKNOWN")
                self.database = db
                continue
            if m := self.SEGM_RE.search(ls):
                seg_name = m.group(1).upper()
                pm, sl = self.PARENT_RE.search(ls), self.SEGLEN_RE.search(ls)
                parent_name = pm.group(1).upper() if pm else None
                seg = IMSSegment(name=seg_name, line=lineno, parent=parent_name,
                                segment_length=int(sl.group(1)) if sl else None)
                segment_map[seg_name] = seg
                if db is not None:
                    db.segments.append(seg)
                if parent_name and parent_name in segment_map:
                    segment_map[parent_name].children.append(seg_name)
                current_seg = seg
                continue
            if m := self.FIELD_RE.search(ls):
                fld = IMSField(name=m.group(1).upper(), line=lineno, type=m.group(2).upper(),
                             start=int(m.group(3)), length=int(m.group(4)))
                if current_seg:
                    current_seg.fields.append(fld)
                continue
            if m := self.FIELD_SIMPLE_RE.search(ls):
                if current_seg:
                    current_seg.fields.append(IMSField(name=m.group(1).upper(), line=lineno))
        return self.database

    def summary(self) -> dict:
        if not self.database:
            return {"status": "BLOCKED", "segments": 0, "fields": 0}
        return {"name": self.database.name, "access_method": self.database.access_method,
                "segments": len(self.database.segments),
                "total_fields": sum(len(s.fields) for s in self.database.segments),
                "hierarchy": {s.name: s.parent for s in self.database.segments},
                "status": self.database.status.value}


class PSBParser:
    """Parse IMS PSB (Program Specification Block) into PCB list."""

    PCB_RE = re.compile(r"PCB\s+TYPE\s*=\s*(\w+)\s+DBFUNC\s*=\s*([\w-]+)", re.IGNORECASE)
    PROCOPT_RE = re.compile(r"PROCOPT\s*=\s*([AIGKLPRSO]+)", re.IGNORECASE)
    KEYLEN_RE = re.compile(r"KEYLEN\s*=\s*(\d+)", re.IGNORECASE)
    SEGLVL_RE = re.compile(r"SEGLVL\s*=\s*([\w-]+)", re.IGNORECASE)

    def __init__(self, source: str):
        self.source = source
        self.pcbs: list[PCB] = []

    def parse(self) -> list[PCB]:
        for lineno, line in enumerate(self.source.split("\n"), 1):
            ls = line.strip()
            if not ls or ls.startswith("*"):
                continue
            if m := self.PCB_RE.search(ls):
                pm, km = self.PROCOPT_RE.search(ls), self.KEYLEN_RE.search(ls)
                sm = self.SEGLVL_RE.search(ls)
                pc = PCB(db_name=m.group(2).upper(), proc_opt=pm.group(1) if pm else "",
                          line=lineno, key_length=int(km.group(1)) if km else None,
                          segment_level=sm.group(1) if sm else None)
                self.pcbs.append(pc)
        return self.pcbs

    def summary(self) -> dict:
        return {"pcbs": len(self.pcbs), "databases": [p.db_name for p in self.pcbs]}


__all__ = ["IMSField", "IMSSegment", "DBDatabase", "PCB", "DBDParser", "PSBParser", "IMSStatus"]
@dataclass
class DBDatabase:
    name: str
    access_method: str
    segments: list = field(default_factory=list)
    status: IMSStatus = IMSStatus.REVIEW_REQUIRED


@dataclass
class PCB:
    db_name: str
    proc_opt: str
    line: int
    segment_level: str | None = None
    key_length: int | None = None
    status: IMSStatus = IMSStatus.REVIEW_REQUIRED
