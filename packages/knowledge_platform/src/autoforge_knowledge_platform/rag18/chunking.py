"""Phase 18-D — structure-aware chunking.

Splits text into bounded chunks while preserving logical structure:

- Markdown: heading sections; oversized sections sub-split on paragraph breaks.
- Code: top-level definition boundaries (class/def/function/etc. at column 0);
  oversized bodies split on blank-line logical-block boundaries, then hard
  line splits as a last resort.
- Plain text: bounded paragraph chunks.

Each chunk records path, document type, language, source id, chunk index,
content hash and line spans.
"""

from __future__ import annotations

import re
from typing import Any

from autoforge_knowledge_platform.rag18.hashing import chunk_id_for, sha256_text
from autoforge_knowledge_platform.rag18.models import KnowledgeChunk


_CODE_BOUNDARY_RE = re.compile(
    r"^(?:"
    r"class\s+\w"
    r"|def\s+\w"
    r"|async\s+def\s+\w"
    r"|fn\s+\w"
    r"|impl\s+\w"
    r"|trait\s+\w"
    r"|enum\s+\w"
    r"|interface\s+\w"
    r"|type\s+\w"
    r"|struct\s+\w"
    r"|function\s+\w"
    r"|async\s+function\s+\w"
    r"|export\s+(?:default\s+)?(?:class|function|interface|enum|type|const|let|var|async)\b"
    r"|public\s+(?:class|interface|enum|static)\b"
    r"|private\s+(?:class|interface|enum|static)\b"
    r"|protected\s+(?:class|interface|enum|static)\b"
    r"|const\s+\w+\s*=\s*(?:async\s*)?(?:function|\(|\w)"
    r"|defmodule\s+\w"
    r")(?:\s|$)",
    re.MULTILINE,
)
_MARKDOWN_HEADING_RE = re.compile(r"^#{1,6}\s+\S", re.MULTILINE)


class StructureAwareChunker:
    """Turn one source file's text into deterministic knowledge chunks."""

    def __init__(self, *, max_chars: int = 2400, overlap_chars: int = 160) -> None:
        self._max_chars = max(400, max_chars)
        self._overlap_chars = max(0, overlap_chars)
        self._min_block_chars = min(500, self._max_chars // 2)

    def chunk(
        self,
        text: str,
        *,
        path: str,
        document_type: str,
        language: str,
        source_id: str,
        workspace_root: str = "",
        project_id: str | None = None,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        embedding_model: str = "",
        embedding_dimension: int = 0,
        embedding_version: str = "",
    ) -> list[KnowledgeChunk]:
        if document_type == "markdown":
            segments = self._chunk_markdown(text, self._max_chars)
        elif document_type.endswith("_source") or document_type in {"shell_script", "sql_source"}:
            segments = self._chunk_code(text, self._max_chars)
        else:
            segments = self._chunk_plain(text, self._max_chars)

        chunks: list[KnowledgeChunk] = []
        for index, (segment, start_line, end_line) in enumerate(segments):
            normalized = segment.strip()
            if not normalized:
                continue
            chunk_id = chunk_id_for(source_id, index)
            chunks.append(
                KnowledgeChunk(
                    knowledge_id=chunk_id,
                    source_id=source_id,
                    chunk_id=chunk_id,
                    workspace_root=workspace_root,
                    project_id=project_id,
                    workflow_id=workflow_id,
                    execution_id=execution_id,
                    path=path,
                    document_type=document_type,
                    language=language,
                    chunk_index=index,
                    content=normalized,
                    content_hash=sha256_text(normalized),
                    start_line=start_line,
                    end_line=end_line,
                    embedding_model=embedding_model,
                    embedding_dimension=embedding_dimension,
                    embedding_version=embedding_version,
                )
            )
        if not chunks and text.strip():
            fallback = KnowledgeChunk(
                knowledge_id=chunk_id_for(source_id, 0),
                source_id=source_id,
                chunk_id=chunk_id_for(source_id, 0),
                workspace_root=workspace_root,
                project_id=project_id,
                workflow_id=workflow_id,
                execution_id=execution_id,
                path=path,
                document_type=document_type,
                language=language,
                chunk_index=0,
                content=text.strip(),
                content_hash=sha256_text(text.strip()),
                start_line=1,
                end_line=max(1, len(text.splitlines())),
                embedding_model=embedding_model,
                embedding_dimension=embedding_dimension,
                embedding_version=embedding_version,
            )
            chunks.append(fallback)
        return chunks

# ── Segment algorithms ─────────────────────────────────────────────────────

    def _chunk_plain(self, text: str, max_chars: int) -> list[tuple[str, int, int]]:
        """Bounded paragraph chunks (a paragraph = blank-line separated block)."""
        lines = text.splitlines()
        paragraphs: list[list[str]] = [[]]
        for line in lines:
            if not line.strip():
                if paragraphs[-1]:
                    paragraphs.append([])
            else:
                paragraphs[-1].append(line)
        if paragraphs and not paragraphs[-1]:
            paragraphs.pop()

        segments: list[tuple[str, int, int]] = []
        buffer: list[str] = []
        buffer_start = 1
        cursor = 1
        for para in paragraphs:
            para_text = "\n".join(para)
            para_start = cursor
            para_end = cursor + len(para) - 1
            cursor = para_end + 2
            if len(para_text) > max_chars:
                if buffer:
                    segments.append(("\n".join(buffer), buffer_start, para_start - 2))
                    buffer, buffer_start = [], 0
                segments.extend(self._split_long_text(para_text, para_start, max_chars))
                continue
            if buffer and sum(len(p) + 1 for p in buffer) + len(para_text) + 1 > max_chars:
                segments.append(("\n".join(buffer), buffer_start, para_start - 2))
                buffer, buffer_start = [], para_start
            if not buffer:
                buffer_start = para_start
            buffer.append(para_text)
        if buffer:
            segments.append(("\n".join(buffer), buffer_start, cursor - 2))
        return segments

    def _chunk_markdown(self, text: str, max_chars: int) -> list[tuple[str, int, int]]:
        """Heading-section chunks; oversized sections split on paragraphs."""
        heading_matches = list(_MARKDOWN_HEADING_RE.finditer(text))
        if not heading_matches:
            return self._chunk_plain(text, max_chars)

        lines = text.splitlines()
        sections: list[tuple[str, int, int]] = []
        for i, match in enumerate(heading_matches):
            heading_start = text[: match.start()].count("\n") + 1
            section_start = heading_start
            next_start = (
                text[: heading_matches[i + 1].start()].count("\n") + 1
                if i + 1 < len(heading_matches)
                else len(lines) + 1
            )
            section_text = "\n".join(lines[heading_start - 1 : next_start - 1])
            sections.append((section_text, section_start, next_start - 1))

        segments: list[tuple[str, int, int]] = []
        for section_text, start, end in sections:
            if not section_text.strip():
                continue
            if len(section_text) <= max_chars:
                segments.append((section_text, start, end))
            else:
                parts = section_text.split("\n", maxsplit=1)
                heading = parts[0]
                body = parts[1] if len(parts) > 1 else section_text
                sub = self._chunk_plain(body if body.strip() else section_text, max_chars)
                if sub:
                    first_text, first_start, first_end = sub[0]
                    segments.append((f"{heading}\n{first_text}", start, first_end))
                    segments.extend(sub[1:])
                else:
                    segments.append((section_text, start, end))
        return segments

    def _chunk_code(self, text: str, max_chars: int) -> list[tuple[str, int, int]]:
        """Code chunks: split on top-level (column 0) definition boundaries."""
        lines = text.splitlines()
        segments: list[tuple[str, int, int]] = []
        buffer: list[str] = []
        buffer_start = 1
        buffer_len = 0

        def flush(flush_end: int) -> None:
            nonlocal buffer, buffer_start, buffer_len
            if not buffer:
                return
            joined = "\n".join(buffer)
            if len(joined) <= max_chars:
                segments.append((joined, buffer_start, flush_end))
                buffer, buffer_start, buffer_len = [], 0, 0
                return
            parts = self._split_long_text(joined, buffer_start, max_chars)
            segments.extend(parts)
            buffer, buffer_start, buffer_len = [], 0, 0

        for idx, line in enumerate(lines, start=1):
            is_boundary = bool(_CODE_BOUNDARY_RE.match(line))
            add_len = len(line) + 1
            if is_boundary and buffer and buffer_len >= self._min_block_chars:
                flush(idx - 1)
                buffer = [line]
                buffer_start = idx
                buffer_len = add_len
            elif is_boundary and not buffer:
                buffer = [line]
                buffer_start = idx
                buffer_len = add_len
            elif buffer_len + add_len > max_chars:
                flush(idx - 1)
                buffer = [line]
                buffer_start = idx
                buffer_len = add_len
            else:
                buffer.append(line)
                buffer_len += add_len

        flush(len(lines))
        return segments

    def _split_long_text(
        self, text: str, start_line: int, max_chars: int
    ) -> list[tuple[str, int, int]]:
        """Split a long text at blank-line (logical block) boundaries first."""
        lines = text.splitlines()
        parts: list[tuple[str, int, int]] = []
        buffer: list[str] = []
        buffer_start = start_line
        cursor = start_line
        for line in lines:
            is_blank = not line.strip()
            buffer.append(line)
            joined = "\n".join(buffer)
            if joined and (
                len(joined) >= max_chars
                or (is_blank and len(joined) >= self._min_block_chars)
            ):
                parts.append((joined, buffer_start, cursor))
                buffer, buffer_start = [], cursor + 1
            cursor += 1
        if buffer:
            parts.append(("\n".join(buffer), buffer_start, cursor - 1))
        if not parts:
            return [(text, start_line, start_line + max(0, len(lines) - 1))]
        return parts
        return segments
        return chunks