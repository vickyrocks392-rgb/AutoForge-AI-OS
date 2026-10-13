"""
PolicyDesk Knowledge Assistant — Document Chunking Engine.
Splits parsed sections into semantically bounded, overlapping passages with complete provenance.
"""

from __future__ import annotations

import hashlib
import re
from typing import List
from models import ChunkRecord
from document_parser import ParsedDocument, ParsedSection


class DocumentChunker:
    """Chunks structured document sections with provenance tracking."""

    def __init__(self, chunk_size: int = 500, overlap: int = 60):
        self.chunk_size = chunk_size
        self.overlap = overlap

    def chunk_document(self, parsed: ParsedDocument) -> List[ChunkRecord]:
        chunks: List[ChunkRecord] = []
        chunk_idx = 1

        for sec in parsed.sections:
            sec_text = sec.text.strip()
            if not sec_text:
                continue

            if len(sec_text) <= self.chunk_size:
                cid = f"{parsed.doc_id}-c{chunk_idx:03d}"
                chash = hashlib.sha256(sec_text.encode("utf-8")).hexdigest()
                chunks.append(
                    ChunkRecord(
                        chunk_id=cid,
                        doc_id=parsed.doc_id,
                        filename=parsed.filename,
                        format=parsed.format,
                        page=sec.page,
                        line_start=sec.line_start,
                        line_end=sec.line_end,
                        section=sec.heading,
                        content=sec_text,
                        content_hash=chash,
                    )
                )
                chunk_idx += 1
            else:
                # Split large section into overlapping windows
                paragraphs = [p.strip() for p in sec_text.split("\n\n") if p.strip()]
                current_window: List[str] = []
                current_len = 0
                lines_in_sec = sec_text.splitlines()

                for p in paragraphs:
                    if current_len + len(p) + 2 > self.chunk_size and current_window:
                        window_text = "\n\n".join(current_window).strip()
                        cid = f"{parsed.doc_id}-c{chunk_idx:03d}"
                        chash = hashlib.sha256(window_text.encode("utf-8")).hexdigest()
                        chunks.append(
                            ChunkRecord(
                                chunk_id=cid,
                                doc_id=parsed.doc_id,
                                filename=parsed.filename,
                                format=parsed.format,
                                page=sec.page,
                                line_start=sec.line_start,
                                line_end=sec.line_end,
                                section=sec.heading,
                                content=window_text,
                                content_hash=chash,
                            )
                        )
                        chunk_idx += 1
                        # Retain overlap
                        current_window = [current_window[-1], p] if len(current_window) > 1 else [p]
                        current_len = sum(len(x) for x in current_window) + 2
                    else:
                        current_window.append(p)
                        current_len += len(p) + 2

                if current_window:
                    window_text = "\n\n".join(current_window).strip()
                    cid = f"{parsed.doc_id}-c{chunk_idx:03d}"
                    chash = hashlib.sha256(window_text.encode("utf-8")).hexdigest()
                    chunks.append(
                        ChunkRecord(
                            chunk_id=cid,
                            doc_id=parsed.doc_id,
                            filename=parsed.filename,
                            format=parsed.format,
                            page=sec.page,
                            line_start=sec.line_start,
                            line_end=sec.line_end,
                            section=sec.heading,
                            content=window_text,
                            content_hash=chash,
                        )
                    )
                    chunk_idx += 1

        return chunks
