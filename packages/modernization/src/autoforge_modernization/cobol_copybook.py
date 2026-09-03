"""COPYBOOK resolution (Phase 18-G.3).

Resolves COBOL COPY statements against known copybook libraries.
Supports nested COPY, tracks resolution provenance, and builds
a COPYBOOK dependency graph.
"""
from __future__ import annotations
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _utc_now():
    return datetime.now(timezone.utc)


@dataclass
class CopybookEntry:
    member: str
    resolved: bool
    path: str | None = None
    content: str | None = None
    nested_copybooks: list[str] = field(default_factory=list)
    line_start: int = 0
    line_end: int = 0
    error: str | None = None


class CopybookResolver:
    """Resolve COBOL COPY members to source files.

    Strategy: search standard copybook directories in priority order.
    Support nested COPY (COPY inside copybook).
    Track resolution provenance; do NOT blindly inline.
    """

    COPY_RE = re.compile(r"\bCOPY\s+([\"']?)([\w.-]+)\1", re.IGNORECASE)

    def __init__(self, search_paths: list[str] | None = None):
        self.search_paths = search_paths or []
        self._cache: dict[str, CopybookEntry] = {}
        self._resolution_log: list[dict] = []
        self._nested_re = re.compile(r"\bCOPY\s+([\"']?)([\w.-]+)\1", re.IGNORECASE)

    def resolve(self, member: str, context_path: str | None = None) -> CopybookEntry:
        member_upper = member.upper().strip()
        if member_upper in self._cache:
            return self._cache[member_upper]

        entry = CopybookEntry(member=member_upper, resolved=False)
        self._cache[member_upper] = entry

        for search_dir in self.search_paths:
            for ext in ("", ".CPY", ".COPY", ".cbl"):
                candidate = Path(search_dir) / (member_upper + ext)
                if candidate.exists():
                    entry.resolved = True
                    entry.path = str(candidate)
                    try:
                        entry.content = candidate.read_text()
                        entry.nested_copybooks = [
                            m.group(2).upper()
                            for m in self._nested_re.finditer(entry.content)
                        ]
                    except Exception as e:
                        entry.error = str(e)
                    break
            if entry.resolved:
                break

        self._resolution_log.append({
            "member": member_upper,
            "resolved": entry.resolved,
            "path": entry.path,
            "timestamp": _utc_now().isoformat(),
        })
        return entry

    def resolve_all(self, members: list[str]) -> dict[str, CopybookEntry]:
        return {m: self.resolve(m) for m in members}

    def get_dependency_graph(self) -> dict:
        """Build COPYBOOK dependency map for the graph."""
        nodes = []
        edges = []
        for member, entry in self._cache.items():
            nodes.append({
                "name": member,
                "kind": "COPYBOOK",
                "resolved": entry.resolved,
                "path": entry.path,
                "nested": entry.nested_copybooks,
            })
        return {"nodes": nodes, "edges": edges}

    def get_metrics(self) -> dict:
        total = len(self._cache)
        resolved = sum(1 for e in self._cache.values() if e.resolved)
        return {
            "total_copybooks": total,
            "resolved": resolved,
            "unresolved": total - resolved,
            "resolution_rate": resolved / max(1, total),
        }


__all__ = ["CopybookEntry", "CopybookResolver"]
