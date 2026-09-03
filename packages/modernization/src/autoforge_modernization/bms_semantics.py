"""BMS semantic analysis (Phase 18-G.3).

Parses BMS (Basic Mapping Support) maps into structured representation.
Converts BMS source to modern JSON screen/API definition.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from enum import Enum


class BMSStatus(str, Enum):
    TRANSFORMABLE = "TRANSFORMABLE"
    REVIEW_REQUIRED = "REVIEW_REQUIRED"


@dataclass
class BMSField:
    name: str
    line: int
    pos_row: int
    pos_col: int
    length: int
    attrs: list[str] = field(default_factory=list)
    initial: str | None = None


@dataclass
class BMSMap:
    name: str
    line: int
    size: str
    fields: list[BMSField] = field(default_factory=list)
    status: BMSStatus = BMSStatus.TRANSFORMABLE


class BMSParser:
    DFHMSD_RE = re.compile(r"DFHMSD\s+", re.IGNORECASE)
    DFHMDI_RE = re.compile(r"DFHMDI\s+([\w-]+)", re.IGNORECASE)
    DFHMDF_RE = re.compile(r"DFHMDF\s+([\w-]+)", re.IGNORECASE)
    POS_RE = re.compile(r"POS\s*=\s*\(\s*(\d+)\s*,\s*(\d+)\s*\)", re.IGNORECASE)
    LEN_RE = re.compile(r"LENGTH\s*=\s*(\d+)", re.IGNORECASE)
    ATTRB_RE = re.compile(r"ATTRB\s*=\s*\(([^)]+)\)", re.IGNORECASE)
    INIT_RE = re.compile(r"INITIAL\s*=\s*'([^']*)'", re.IGNORECASE)
    SIZE_RE = re.compile(r"SIZE\s*=\s*\(([^)]+)\)", re.IGNORECASE)

    def __init__(self, source: str):
        self.source = source
        self.lines = source.split("\n")
        self.maps: list[dict] = []

    def parse(self) -> list[dict]:
        current_map: dict | None = None
        for lineno, line in enumerate(self.lines, 1):
            ls = line.rstrip()
            if not ls or ls.startswith("*"):
                continue
            if self.DFHMSD_RE.search(ls):
                current_map = None
                continue
            nm = self.DFHMDI_RE.search(ls)
            if nm:
                sm = self.SIZE_RE.search(ls)
                current_map = {"name": nm.group(1).upper(), "line": lineno,
                               "size": sm.group(1) if sm else "80,24", "fields": []}
                self.maps.append(current_map)
                continue
            fn = self.DFHMDF_RE.search(ls)
            if fn and current_map:
                pm, lm, am, im = self.POS_RE.search(ls), self.LEN_RE.search(ls), self.ATTRB_RE.search(ls), self.INIT_RE.search(ls)
                current_map["fields"].append({
                    "name": fn.group(1).upper(), "line": lineno,
                    "pos_row": int(pm.group(1)) if pm else 1,
                    "pos_col": int(pm.group(2)) if pm else 1,
                    "length": int(lm.group(1)) if lm else 0,
                    "attrs": [a.strip() for a in am.group(1).split()] if am else [],
                    "initial": im.group(1) if im else None,
                })
        return self.maps

    def summary(self) -> dict:
        total_fields = sum(len(m.get("fields", [])) for m in self.maps)
        return {"maps": len(self.maps), "fields": total_fields,
                "status": "TRANSFORMABLE" if total_fields > 0 else "PLACEHOLDER_ONLY"}

    def to_json(self) -> dict:
        return {"apiVersion": "autoforge/bms/v1", "kind": "BMSScreenDefinition",
                "maps": [{"name": m["name"], "size": m["size"],
                          "fields": [{"name": f["name"], "pos": [f["pos_row"], f["pos_col"]],
                                      "length": f["length"], "attrs": f["attrs"]}
                                     for f in m["fields"]]} for m in self.maps]}


__all__ = ["BMSField", "BMSMap", "BMSParser", "BMSStatus"]
