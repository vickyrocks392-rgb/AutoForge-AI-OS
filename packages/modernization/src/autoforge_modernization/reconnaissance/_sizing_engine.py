"""Real file-content LOC accounting for the reconnaissance engine.

Replaces approximate bytes-per-line counting with real file-content
accounting. This module walks each non-binary, non-generated file and
computes physical LOC, blank LOC, and comment LOC with provenance.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from autoforge_modernization.reconnaissance.models import (
    CountingMethodology, FactConfidence, SizingSource,
)

# ── Comment strippers ────────────────────────────────────────────────────────────
_PYTHON_STRIP = re.compile(r"#[^\n]*")
_PYTHON_TRIPLE = re.compile(
    r'"""[\s\S]*?"""|' + r"'''[\s\S]*?'''", re.MULTILINE
)
_JS_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_JS_LINE = re.compile(r"//[^\n]*")
_SHELL = re.compile(r"#[^\n]*")
_HTML_BLOCK = re.compile(r"<!--[\s\S]*?-->")
_SQL_BLOCK = re.compile(r"/\*[\s\S]*?\*/")
_SQL_LINE = re.compile(r"--[^\n]*")


def _blank(line: str) -> bool:
    return not line.strip()


@dataclass
class FileSizing:
    physical_loc: int = 0
    blank_loc: int = 0
    comment_loc: int = 0
    active_loc: int = 0
    methodology: CountingMethodology = CountingMethodology.PHYSICAL
    confidence: FactConfidence = FactConfidence.HIGH


def _strip_python(text: str) -> str:
    text = _PYTHON_TRIPLE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return _PYTHON_STRIP.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _strip_c_style(text: str) -> str:
    text = _JS_BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return _JS_LINE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _strip_shell(text: str) -> str:
    return _SHELL.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _strip_sql(text: str) -> str:
    text = _SQL_BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)
    return _SQL_LINE.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _strip_html(text: str) -> str:
    return _HTML_BLOCK.sub(lambda m: re.sub(r"[^\n]", " ", m.group(0)), text)


def _strip_cobol(text: str) -> str:
    lines = text.split("\n")
    out = []
    for line in lines:
        if len(line) >= 7 and line[6] == "*":
            out.append(" " * len(line))
        else:
            out.append(line)
    return "\n".join(out)


def measure_text(text: str, language: str | None) -> FileSizing:
    """Compute LOC metrics for a single file's text content."""
    if not text:
        return FileSizing(physical_loc=0, confidence=FactConfidence.HIGH)
    raw_lines = text.split("\n")
    physical = sum(1 for ln in raw_lines if not _blank(ln))
    blank = sum(1 for ln in raw_lines if _blank(ln))
    if language == "python":
        stripped = _strip_python(text)
    elif language in (
        "java", "kotlin", "scala", "javascript", "typescript",
        "go", "rust", "c", "cpp", "csharp",
    ):
        stripped = _strip_c_style(text)
    elif language in ("shell", "ruby"):
        stripped = _strip_shell(text)
    elif language == "sql":
        stripped = _strip_sql(text)
    elif language in ("html", "xml", "markdown", "rst"):
        stripped = _strip_html(text)
    elif language == "cobol":
        stripped = _strip_cobol(text)
    elif language == "yaml":
        stripped = _strip_shell(text)
    else:
        stripped = text
    s_lines = stripped.split("\n")
    comment = active = 0
    for raw, stripped_line in zip(raw_lines, s_lines):
        if _blank(raw):
            continue
        if _blank(stripped_line):
            comment += 1
        else:
            active += 1
    return FileSizing(
        physical_loc=physical,
        blank_loc=blank,
        comment_loc=comment,
        active_loc=active,
        methodology=CountingMethodology.PHYSICAL,
        confidence=FactConfidence.HIGH if physical > 0 else FactConfidence.UNKNOWN,
    )


def aggregate_sizings(
    sizings: list[FileSizing],
    language_counts: dict[str, int],
    total_files: int,
) -> dict[str, object]:
    """Aggregate per-file measurements into a dict for ProjectSizing."""
    sizings = list(sizings)
    total_physical = sum(s.physical_loc for s in sizings)
    return {
        "total_physical_loc": total_physical,
        "blank_loc": sum(s.blank_loc for s in sizings),
        "comments_loc": sum(s.comment_loc for s in sizings),
        "active_loc": sum(s.active_loc for s in sizings),
        "test_loc": 0,
        "generated_loc": 0,
        "total_files": total_files,
        "loc_by_language": dict(language_counts),
        "methodologies_used": [CountingMethodology.PHYSICAL],
        "sources": [SizingSource.FILE_SYSTEM],
        "primary_methodology": CountingMethodology.PHYSICAL,
        "is_generated_excluded": False,
        "confidence": (
            FactConfidence.HIGH
            if total_physical > 0
            else FactConfidence.UNKNOWN
        ),
    }
