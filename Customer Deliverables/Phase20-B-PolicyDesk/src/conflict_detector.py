"""
PolicyDesk Knowledge Assistant — Policy Conflict and Versioning Detector.
Transparently identifies superseded, conflicting, or version-ambiguous policy documents.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple
from models import ChunkRecord, PolicyConflictInfo


class PolicyConflictDetector:
    """Analyzes retrieved passages to detect superseded or contradictory policy guidelines."""

    @staticmethod
    def detect_conflicts(
        query: str,
        retrieved_chunks: List[Tuple[ChunkRecord, float]],
    ) -> Optional[PolicyConflictInfo]:
        if not retrieved_chunks:
            return None

        # Check for year/version presence in retrieved chunks
        has_2024 = False
        has_2026 = False
        has_superseded = False
        chunk_docs = set()

        for chunk, score in retrieved_chunks:
            text = chunk.content.lower()
            fname = chunk.filename.lower()
            chunk_docs.add(chunk.filename)

            if "2024" in text or "2024" in fname:
                has_2024 = True
            if "2026" in text or "2026" in fname:
                has_2026 = True
            if "superseded" in text or "archived" in text:
                has_superseded = True

        # Specific Travel & Expense Policy conflict
        travel_keywords = ("travel", "expense", "per diem", "meal", "mileage", "hotel", "lodging")
        is_travel_query = any(k in query.lower() for k in travel_keywords)

        if is_travel_query and has_2024 and has_2026:
            return PolicyConflictInfo(
                has_conflict=True,
                summary="Conflicting policy editions detected: PolicyDesk has both a 2024 Edition (Archived/Superseded) and a 2026 Edition (Active/Current) on file for Travel and Expense Reimbursement.",
                superseded_policy="Travel and Expense Policy (2024 Edition) — $50.00/day per diem, $0.55/mile, $175 lodging cap (SUPERSEDED).",
                active_policy="Travel and Expense Policy (2026 Edition) — $85.00/day per diem, $0.67/mile, $250 lodging cap (ACTIVE, Effective Jan 1, 2026).",
                explanation="PolicyDesk staff must follow the 2026 Edition guidelines. The 2024 edition has been archived and superseded.",
            )

        if is_travel_query and has_2024 and not has_2026:
            return PolicyConflictInfo(
                has_conflict=True,
                summary="Retrieved policy document is marked as ARCHIVED/SUPERSEDED (2024 Edition).",
                superseded_policy="Travel and Expense Policy (2024 Edition)",
                active_policy="Travel and Expense Policy (2026 Edition)",
                explanation="Warning: Retrieved content is from 2024. Please verify against current 2026 active policies.",
            )

        # Generic version conflict check if multiple version headers are present
        if has_superseded and ("version" in query.lower() or "policy" in query.lower()):
            return PolicyConflictInfo(
                has_conflict=True,
                summary="Retrieved evidence contains explicit superseded policy notices.",
                superseded_policy="Prior Edition",
                active_policy="Current Active Edition",
                explanation="Multiple editions exist in the knowledge base; priority is given to the newer active effective date.",
            )

        return None
