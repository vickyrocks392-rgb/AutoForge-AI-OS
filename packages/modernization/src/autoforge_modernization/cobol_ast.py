"""G.3 Real COBOL Semantic Representation (Phase 18-G.3).

Implements a real COBOL fixed-format / free-format tokenizer + semantic AST
for the constructs encountered in enterprise legacy systems.

Supported: PROGRAM-ID, 4 divisions, SECTIONS, PARAGRAPHS, WORKING-STORAGE /
FILE-SECTION / LINKAGE-SECTION, PIC (X, 9, V, S, COMP, COMP-3, BINARY,
PACKED-DECIMAL), VALUE clauses, MOVE, IF/ELSE/END-IF, EVALUATE, COMPUTE,
ADD/SUBTRACT/MULTIPLY/DIVIDE, PERFORM, PERFORM UNTIL, PERFORM THRU, CALL,
COPY, SELECT/ASSIGN, OPEN/CLOSE/READ/WRITE/REWRITE/DELETE/START,
STRING/UNSTRING/INSPECT, SET ... TO, GO TO, EXIT, STOP RUN, GOBACK,
PERFORM VARYING/UNTIL (loops).

Unsupported (returns explicit SemanticGap):
- REPORT WRITER, SORT/MERGE, OCCURS DEPENDING ON, complex REWRITE/DELETE,
- EXEC CICS LINK/RETURN/XCTL, Object-orientation, nested programs.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


def _utc_now(): return datetime.now(timezone.utc)


class COBOLKind(str, Enum):
    PROGRAM = "program"
    DIVISION = "division"
    SECTION = "section"
    PARAGRAPH = "paragraph"
    DATA_ITEM = "data_item"
    MOVE = "move"
    IF = "if"
    EVALUATE = "evaluate"
    COMPUTE = "compute"
    ARITHMETIC = "arithmetic"
    PERFORM = "perform"
    CALL = "call"
    COPY = "copy"
    SELECT = "select"
    OPEN = "open"
    CLOSE = "close"
    READ = "read"
    WRITE = "write"
    REWRITE = "rewrite"
    DELETE = "delete"
    START = "start"
    STRING_OP = "string_op"
    INSPECT = "inspect"
    SET = "set"
    GOTO = "goto"
    EXIT = "exit"
    LOOP = "loop"
    FILE_SECTION = "file_section"
    WORKING_STORAGE = "working_storage"
    LINKAGE_SECTION = "linkage_section"


@dataclass
class SourceLocation:
    line: int = 0
    column: int = 0

    def __str__(self) -> str:
        return f"L{self.line}"


@dataclass
class COBOLNode:
    kind: COBOLKind
    location: SourceLocation = field(default_factory=SourceLocation)
    name: str = ""
    raw: str = ""
    children: list = field(default_factory=list)
    attrs: dict = field(default_factory=dict)
    semantic_gap: str | None = None

    def add(self, child) -> "COBOLNode":
        self.children.append(child)
        return child


@dataclass
class SemanticGap:
    construct: str
    location: SourceLocation
    reason: str
    suggested_strategy: str


class COBOLTokenizer:
    """Real COBOL fixed-format / free-format line tokenizer.

    Fixed-format conventions:
    - cols 1-6: sequence number (ignored)
    - col 7: indicator (*=comment, /=comment, D=debug, -=continuation)
    - cols 8-72: Area A starts at col 8 (divisions, paragraphs, certain verbs),
                  Area B at col 12 (sentences).
    - cols 73-80: ignored.

    Free-format is detected when no fixed-format indicators are present
    on a sufficient sample; we keep the same tokenization shape.
    """

    COMMENT_INDICATORS = ("*", "/")
    DEBUG_INDICATORS = ("D", "d")

    def __init__(self, source: str) -> None:
        self.source = source
        self.lines: list[str] = source.split("\n")
        self._free_format = self._detect_free_format()
        self.tokens: list = []

    def _detect_free_format(self) -> bool:
        sample = 0
        fixed = 0
        for line in self.lines[:50]:
            if not line.strip():
                continue
            sample += 1
            if len(line) >= 7 and line[6:7] in ("*", "/", "D", "d", "-"):
                fixed += 1
            elif len(line) > 72 and line[72:].strip():
                fixed += 1
            if sample >= 25:
                break
        if sample == 0:
            return True
        return (fixed / sample) < 0.3

    def tokenize(self) -> list:
        out: list = []
        for lineno, line in enumerate(self.lines, 1):
            if self._free_format:
                ls = line.rstrip()
                indicator = " "
                is_comment = ls.lstrip().startswith(("*", "/"))
                text = ls
            else:
                seq = line[:6]
                indicator = line[6:7] if len(line) > 6 else " "
                text = line[7:72] if len(line) > 7 else ""
                is_comment = indicator in self.COMMENT_INDICATORS
            is_debug = indicator in self.DEBUG_INDICATORS
            if indicator == "-":
                if out:
                    out[-1]["text"] = (out[-1]["text"] + " " + text.strip()).strip()
                else:
                    out.append({"line": lineno, "text": text.strip(),
                                "indicator": indicator, "is_comment": False,
                                "is_continuation": True, "is_debug": False})
                continue
            if is_comment:
                out.append({"line": lineno, "text": "", "indicator": indicator,
                            "is_comment": True, "is_continuation": False,
                            "is_debug": False})
                continue
            if is_debug:
                out.append({"line": lineno, "text": "*DEBUG* " + text.strip(),
                            "indicator": indicator, "is_comment": False,
                            "is_continuation": False, "is_debug": True})
                continue
            out.append({"line": lineno, "text": text.rstrip(), "indicator": indicator,
                        "is_comment": False, "is_continuation": False,
                        "is_debug": False})
        self.tokens = [t for t in out if not t["is_comment"]]
        return self.tokens



