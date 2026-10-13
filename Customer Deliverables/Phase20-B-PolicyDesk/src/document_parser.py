"""
PolicyDesk Knowledge Assistant — Document Parsing and Content Normalization.
Supports PDF, Markdown, and Plain Text files with precise page/line tracking.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel


class ParsedSection(BaseModel):
    """Normalized segment of text extracted from a document."""
    text: str
    page: Optional[int] = None
    line_start: int = 1
    line_end: int = 1
    heading: str = ""


class ParsedDocument(BaseModel):
    """Complete structured output from parsing a document."""
    doc_id: str
    filename: str
    format: str
    sections: List[ParsedSection]
    raw_text: str
    total_pages: Optional[int] = None


class DocumentParser:
    """Multi-format parser engine for approved PolicyDesk customer documents."""

    @staticmethod
    def parse(file_path: Path | str, doc_id: Optional[str] = None) -> ParsedDocument:
        p = Path(file_path).resolve()
        if not p.exists():
            raise FileNotFoundError(f"Document file not found: {p}")
        
        if p.stat().st_size == 0:
            raise ValueError(f"Document file '{p.name}' is empty (0 bytes).")

        ext = p.suffix.lower().lstrip(".")
        did = doc_id or p.stem

        if ext == "pdf":
            return DocumentParser._parse_pdf(p, did)
        elif ext in ("md", "markdown"):
            return DocumentParser._parse_markdown(p, did)
        elif ext in ("txt", "text"):
            return DocumentParser._parse_text(p, did)
        else:
            raise ValueError(f"Unsupported document format: '.{ext}'. Supported formats are: pdf, md, txt.")

    @staticmethod
    def _parse_pdf(path: Path, doc_id: str) -> ParsedDocument:
        sections: List[ParsedSection] = []
        raw_chunks: List[str] = []

        try:
            import pypdf
            reader = pypdf.PdfReader(str(path))
            total_pages = len(reader.pages)
            if total_pages == 0:
                raise ValueError("PDF file contains 0 pages.")

            line_counter = 1
            for page_idx, page in enumerate(reader.pages, start=1):
                page_text = page.extract_text() or ""
                lines = page_text.splitlines()
                clean_lines = [l.strip() for l in lines if l.strip()]
                if not clean_lines:
                    continue

                page_clean_text = "\n".join(clean_lines)
                raw_chunks.append(page_clean_text)

                sections.append(
                    ParsedSection(
                        text=page_clean_text,
                        page=page_idx,
                        line_start=line_counter,
                        line_end=line_counter + len(clean_lines) - 1,
                        heading=f"Page {page_idx}",
                    )
                )
                line_counter += len(clean_lines)

        except ImportError:
            # Fallback to PyPDF2
            import PyPDF2
            with open(path, "rb") as f:
                reader = PyPDF2.PdfReader(f)
                total_pages = len(reader.pages)
                line_counter = 1
                for page_idx, page in enumerate(reader.pages, start=1):
                    page_text = page.extract_text() or ""
                    lines = page_text.splitlines()
                    clean_lines = [l.strip() for l in lines if l.strip()]
                    if not clean_lines:
                        continue
                    page_clean_text = "\n".join(clean_lines)
                    raw_chunks.append(page_clean_text)
                    sections.append(
                        ParsedSection(
                            text=page_clean_text,
                            page=page_idx,
                            line_start=line_counter,
                            line_end=line_counter + len(clean_lines) - 1,
                            heading=f"Page {page_idx}",
                        )
                    )
                    line_counter += len(clean_lines)

        if not sections:
            raise ValueError(f"Could not extract usable text from PDF '{path.name}'.")

        return ParsedDocument(
            doc_id=doc_id,
            filename=path.name,
            format="pdf",
            sections=sections,
            raw_text="\n\n".join(raw_chunks),
            total_pages=total_pages,
        )

    @staticmethod
    def _parse_markdown(path: Path, doc_id: str) -> ParsedDocument:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        if not lines or not content.strip():
            raise ValueError(f"Markdown file '{path.name}' is empty.")

        sections: List[ParsedSection] = []
        current_heading = "Overview"
        current_lines: List[str] = []
        start_line = 1

        for idx, line in enumerate(lines, start=1):
            stripped = line.strip()
            heading_match = re.match(r"^(#{1,6})\s+(.*)$", stripped)
            if heading_match:
                if current_lines:
                    text_block = "\n".join(current_lines).strip()
                    if text_block:
                        sections.append(
                            ParsedSection(
                                text=text_block,
                                page=None,
                                line_start=start_line,
                                line_end=idx - 1,
                                heading=current_heading,
                            )
                        )
                    current_lines = []
                current_heading = heading_match.group(2).strip()
                start_line = idx
            else:
                current_lines.append(line)

        if current_lines:
            text_block = "\n".join(current_lines).strip()
            if text_block:
                sections.append(
                    ParsedSection(
                        text=text_block,
                        page=None,
                        line_start=start_line,
                        line_end=len(lines),
                        heading=current_heading,
                    )
                )

        if not sections:
            # Fallback single block
            sections.append(
                ParsedSection(
                    text=content.strip(),
                    page=None,
                    line_start=1,
                    line_end=len(lines),
                    heading="Document",
                )
            )

        return ParsedDocument(
            doc_id=doc_id,
            filename=path.name,
            format="md",
            sections=sections,
            raw_text=content,
            total_pages=None,
        )

    @staticmethod
    def _parse_text(path: Path, doc_id: str) -> ParsedDocument:
        content = path.read_text(encoding="utf-8")
        lines = content.splitlines()
        if not lines or not content.strip():
            raise ValueError(f"Text file '{path.name}' is empty.")

        sections: List[ParsedSection] = [
            ParsedSection(
                text=content.strip(),
                page=None,
                line_start=1,
                line_end=len(lines),
                heading="General",
            )
        ]

        return ParsedDocument(
            doc_id=doc_id,
            filename=path.name,
            format="txt",
            sections=sections,
            raw_text=content,
            total_pages=None,
        )
