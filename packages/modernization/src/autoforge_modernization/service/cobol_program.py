"""Assemble a complete COBOL program model for Phase 20 transformation.

Combines the DATA DIVISION (records, working storage, copybooks), the
ENVIRONMENT DIVISION (``SELECT``/``ASSIGN`` file definitions) and the
PROCEDURE DIVISION paragraphs into one model the code generator consumes.

``COPY`` statements are resolved against the real copybook files found in the
legacy source tree, so a record layout is only ever built from source that
actually shipped in the workload.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from autoforge_modernization.service.cobol_ir import (
    RecordLayout,
    UnsupportedConstruct,
    build_record_layout,
    looks_fixed_format,
    parse_data_entries,
    source_lines,
)
from autoforge_modernization.service.cobol_proc import Stmt, parse_procedure

__all__ = ["FileDefinition", "ProgramModel", "build_program_model"]

_SELECT_RE = re.compile(
    r"^\s*SELECT\s+([A-Za-z0-9\-]+)\s+"
    r"(?:ASSIGN\s+TO\s+(?P<assign>\"[^\"]*\"|'[^']*'|[\w\-.]+))?"
    r"(?:\s+ORGANIZATION\s+IS\s+(?P<organization>[\w\-]+))?"
    r"(?:\s+ACCESS\s+MODE\s+IS\s+(?P<access>[\w\-]+))?"
    r"(?:\s+RECORD\s+KEY\s+IS\s+(?P<key>[\w\-()\s]+?))?"
    r"(?:\s+FILE\s+STATUS\s+IS\s+(?P<status>[\w\-()\s]+?))?\s*$",
    re.IGNORECASE,
)

_SELECT_LOOSE_RE = (
    r"^\s*SELECT\s+([A-Za-z0-9\-]+)\s+"
    r"(?:ASSIGN\s+TO\s+(?P<assign>\"[^\"]*\"|'[^']*'|[\w\-./]+))?"
    r"(?P<rest>.*)$"
)
_SELECT_LOOSE = re.compile(_SELECT_LOOSE_RE, re.IGNORECASE)

_PROGRAM_ID_RE = re.compile(
    r"\bPROGRAM-ID\s*\.\s*([A-Za-z0-9][\w\-]*)", re.IGNORECASE
)
_COPY_RE = re.compile(r'\bCOPY\s+["\']?([\w.\-]+)["\']?', re.IGNORECASE)
_FD_RE = re.compile(r"^\s*FD\s+([A-Za-z0-9\-]+)", re.IGNORECASE)


@dataclass
class FileDefinition:
    """One ``SELECT`` entry from the ENVIRONMENT DIVISION."""

    name: str
    assign: str | None = None
    organization: str = "SEQUENTIAL"
    access: str = "SEQUENTIAL"
    record_key: str | None = None
    file_status: str | None = None
    record_name: str | None = None
    record_size: int = 0

    @property
    def is_indexed(self) -> bool:
        return self.organization.upper() == "INDEXED"

    def as_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "assign": self.assign,
            "organization": self.organization,
            "access": self.access,
            "record_key": self.record_key,
            "file_status": self.file_status,
            "record_name": self.record_name,
            "record_size": self.record_size,
        }


@dataclass
class ProgramModel:
    """Everything the code generator needs about one legacy program."""

    program_id: str
    source_path: str = ""
    source_format: str = "free"
    records: dict[str, RecordLayout] = field(default_factory=dict)
    working_storage: dict[str, RecordLayout] = field(default_factory=dict)
    files: dict[str, FileDefinition] = field(default_factory=dict)
    paragraphs: dict[str, list[Stmt]] = field(default_factory=dict)
    calls: set[str] = field(default_factory=set)
    copybooks: list[str] = field(default_factory=list)
    gaps: list[UnsupportedConstruct] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        return {
            "program_id": self.program_id,
            "source_path": self.source_path,
            "source_format": self.source_format,
            "records": {
                name: {"size": layout.size, "fields": len(layout.fields)}
                for name, layout in sorted(self.records.items())
            },
            "working_storage": {
                name: layout.size
                for name, layout in sorted(self.working_storage.items())
            },
            "files": {name: fd.as_dict() for name, fd in sorted(self.files.items())},
            "paragraphs": sorted(self.paragraphs),
            "calls": sorted(self.calls),
            "copybooks": sorted(set(self.copybooks)),
            "gaps": [gap.as_dict() for gap in self.gaps],
        }
def _resolve_copybook(name: str, search_dirs: list[Path]) -> str | None:
    """Find a copybook by name (case-insensitive) in the search path.

    Real COBOL ``COPY CVACT01Y.`` names a *stem*; the file on disk is
    ``CVACT01Y.cpy``. Matching is therefore on the stem, case-insensitively,
    after trying the literal name first.
    """
    wanted = name.lower()
    for directory in search_dirs:
        if not directory.is_dir():
            continue
        for candidate in sorted(directory.iterdir()):
            if not candidate.is_file():
                continue
            filename = candidate.name.lower()
            if filename == wanted or Path(filename).stem == wanted:
                return candidate.read_text(errors="replace")
    return None


def _scan_file_control(model: ProgramModel, lines: list[tuple[int, str]]) -> None:
    """Collect ``SELECT`` entries from the ENVIRONMENT DIVISION.

    A ``SELECT`` spans several lines in real fixed-format sources, so clauses
    are accumulated until the terminating period before the entry is parsed.
    """
    inside = False
    buffer: list[str] = []
    for _, code in lines:
        if "FILE-CONTROL" in code.upper():
            inside = True
            continue
        if not inside or not code.strip():
            continue
        buffer.append(code.strip())
        if not code.strip().endswith("."):
            continue
        joined = " ".join(buffer)
        buffer = []
        select = _SELECT_RE.match(joined)
        if not select:
            select = _SELECT_LOOSE.match(joined)
        if select:
            rest = select.groupdict().get("rest") or ""
            organization = select.groupdict().get("organization")
            access = select.groupdict().get("access")
            key = select.groupdict().get("key")
            status = select.groupdict().get("status")
            rest_upper = _mask_text(rest).upper()
            if organization is None:
                organization = _clause_value(rest_upper, "ORGANIZATION", "SEQUENTIAL")
            if access is None:
                access = _clause_value(rest_upper, "ACCESS\\s+MODE", "SEQUENTIAL")
            if key is None:
                key = _clause_value(rest_upper, "RECORD\\s+KEY", "")
            if status is None:
                status = _clause_value(rest_upper, "FILE\\s+STATUS", "")
            model.files[select.group(1).upper()] = FileDefinition(
                name=select.group(1).upper(),
                assign=(select.group("assign") or "").strip("\"'") or None,
                organization=organization or "SEQUENTIAL",
                access=access or "SEQUENTIAL",
                record_key=(key or "").strip() or None,
                file_status=(status or "").strip() or None,
            )


def _clause_value(text: str, clause: str, default: str) -> str:
    """Extract the token following a clause keyword in a joined SELECT."""
    match = re.search(clause + r"\s+(?:IS\s+)?([A-Za-z0-9\-]+)", text)
    return match.group(1) if match else default


def _mask_text(text: str) -> str:
    from autoforge_modernization.service.cobol_proc import _mask_literals

    return _mask_literals(text)


def _layouts_from_entries(
    entries: list[Any], gaps: list[UnsupportedConstruct]
) -> list[RecordLayout]:
    """Split entries into one layout per 01/77 root item."""
    starts = [
        (index, entry.name)
        for index, entry in enumerate(entries)
        if entry.level in (1, 77) and entry.name
    ]
    layouts: list[RecordLayout] = []
    for position, (index, name) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(entries)
        local: list[UnsupportedConstruct] = []
        layouts.append(
            build_record_layout(entries[index:end], record_name=name, gaps=local)
        )
        gaps.extend(local)
    return layouts


def _build_sections(model: ProgramModel, lines: list[tuple[int, str]]) -> None:
    """Split the DATA DIVISION into records and working storage."""
    section: str | None = None
    pending: list[tuple[int, str]] = []
    current_fd: str | None = None

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        target = model.working_storage if section in ("WS", "LINKAGE") else model.records
        entries, gaps = parse_data_entries(pending)
        model.gaps.extend(gaps)
        layouts = _layouts_from_entries(entries, model.gaps)
        for layout in layouts:
            target[layout.record_name] = layout
        if section == "FILE" and current_fd and layouts:
            definition = model.files.get(current_fd)
            if definition is not None:
                definition.record_name = layouts[0].record_name
                definition.record_size = layouts[0].size
        pending = []

    for number, code in lines:
        upper = code.upper()
        if "FILE SECTION" in upper:
            flush()
            section = "FILE"
            continue
        if "WORKING-STORAGE SECTION" in upper:
            flush()
            section = "WS"
            continue
        if "LINKAGE SECTION" in upper:
            flush()
            section = "LINKAGE"
            continue
        if "PROCEDURE DIVISION" in upper:
            flush()
            section = None
            continue
        if section == "FILE":
            fd_match = _FD_RE.match(code)
            if fd_match:
                flush()
                fd_name = fd_match.group(1).upper()
                pending = [(number, code)]
                current_fd = fd_name
                continue
            pending.append((number, code))
            continue
        if section in ("WS", "LINKAGE"):
            pending.append((number, code))
            continue
        if section is None and re.match(r"^\s*\d{1,2}\s+[A-Za-z0-9]", code):
            section = "FILE"
            pending.append((number, code))
    flush()
def build_program_model(
    text: str,
    *,
    source_path: str = "",
    source_format: str | None = None,
    copybook_dirs: list[Path] | None = None,
) -> ProgramModel:
    """Parse one real COBOL program into a :class:`ProgramModel`."""
    resolved_format = source_format or ("fixed" if looks_fixed_format(text) else "free")
    program_id_match = _PROGRAM_ID_RE.search(text)
    model = ProgramModel(
        program_id=program_id_match.group(1).upper() if program_id_match else "UNNAMED",
        source_path=source_path,
        source_format=resolved_format,
    )

    copybook_dirs = copybook_dirs or []
    copybook_cache: dict[str, str | None] = {}

    # Expand COPY statements so the data dictionary sees real layouts.
    expanded: list[tuple[int, str]] = []
    for number, code in source_lines(text, source_format=resolved_format):
        copy_match = _COPY_RE.search(code)
        if copy_match:
            name = copy_match.group(1).rstrip(".")
            model.copybooks.append(name)
            if name not in copybook_cache:
                copybook_cache[name] = _resolve_copybook(name, copybook_dirs)
            content = copybook_cache[name]
            if content is None:
                model.gaps.append(
                    UnsupportedConstruct(
                        construct="copybook", line=number,
                        text=code.strip()[:160],
                        reason=f"copybook {name!r} was not found in the legacy source tree",
                    )
                )
                continue
            expanded.extend(source_lines(content))
            continue
        expanded.append((number, code))

    _scan_file_control(model, expanded)
    _build_sections(model, expanded)

    paragraphs, proc_gaps = parse_procedure(text, source_format=resolved_format)
    model.paragraphs = paragraphs
    model.gaps.extend(proc_gaps)
    for statements in paragraphs.values():
        for statement in statements:
            if statement.kind == "call":
                model.calls.add(str(statement.attrs.get("target", "")).strip("\"'"))
    return model