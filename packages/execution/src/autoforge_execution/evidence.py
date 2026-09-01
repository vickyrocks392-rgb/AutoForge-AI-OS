"""Phase 18-D: Retrieved Knowledge Evidence Assembly.

Provides ``assemble_evidence()`` which serialises a list of
``RetrievalResultHit`` dicts (populated by the orchestrator's RAG pipeline)
into a human-readable block injected into AI prompts as
[RETRIEVED KNOWLEDGE / EVIDENCE].
"""

from __future__ import annotations

from typing import Any


def assemble_evidence(
    hits: list[dict[str, Any]] | None,
    *,
    max_hits: int = 5,
    max_content_chars: int = 800,
) -> str:
    """Return a formatted evidence block string, or \"\" when no hits.

    Args:
        hits: Serialised RetrievalResultHit list from ExecutionContext.retrieved_knowledge.
        max_hits: Cap on how many hits to surface.
        max_content_chars: Truncate each chunk content to this length.

    Returns:
        A string like::

            [RETRIEVED KNOWLEDGE / EVIDENCE]
            (rank 1 | score 0.91 | python_source | src/foo.py:12-24)
            Project uses Pydantic models for config; prefer BaseModel over dataclass.

            (rank 2 | score 0.87 | markdown | README.md:1-8)
            ...
            [/RETRIEVED KNOWLEDGE]
    """
    if not hits:
        return ""

    lines: list[str] = ["[RETRIEVED KNOWLEDGE / EVIDENCE]"]
    for hit in hits[:max_hits]:
        path = hit.get("path", "?")
        doc_type = hit.get("document_type", "?")
        lang = hit.get("language", "?")
        score = hit.get("score")
        start = hit.get("start_line", "?")
        end = hit.get("end_line", "?")
        content = hit.get("content", "")

        if len(content) > max_content_chars:
            content = content[:max_content_chars] + " [...truncated...]"

        rank = hit.get("rank", "?")
        score_str = f"{score:.3f}" if isinstance(score, float) else str(score)
        meta = f"(rank {rank} | score {score_str} | {doc_type} | {path}:{start}-{end})"

        lines.append("")
        lines.append(meta)
        lines.append(content.strip())

    lines.append("")
    lines.append("[/RETRIEVED KNOWLEDGE]")
    return "\n".join(lines)