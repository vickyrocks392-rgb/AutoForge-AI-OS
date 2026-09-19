"""Autonomous Multi-Format Ingestion Pipeline for RAG Knowledge Power Engine."""

from __future__ import annotations

import os
import hashlib
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field

from autoforge_knowledge_platform.rag18.discovery import SourceDiscovery
from autoforge_knowledge_platform.rag18.parsing import classify, read_text
from autoforge_knowledge_platform.rag18.chunking import StructureAwareChunker
from autoforge_knowledge_platform.rag18.hashing import sha256_text, chunk_id_for
from autoforge_power_engines.specification import CustomerProjectSpecification, KnowledgeSourceSpec, SourceType


class KnowledgeChunkRecord(BaseModel):
    """Normalized, metadata-rich knowledge chunk."""
    chunk_id: str
    source_id: str
    file_path: str
    document_type: str
    language: str
    chunk_index: int
    content: str
    line_start: int
    line_end: int
    content_hash: str
    metadata: Dict[str, Any] = Field(default_factory=dict)
    created_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class ProcessedDocument(BaseModel):
    """Record of a parsed and indexed document."""
    source_id: str
    file_path: str
    document_type: str
    language: str
    size_bytes: int
    content_hash: str
    chunks_count: int
    parsed_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())


class IngestionReport(BaseModel):
    """Complete summary of the ingestion and indexing run."""
    project_id: str
    documents_processed: List[ProcessedDocument] = Field(default_factory=list)
    total_chunks: int = 0
    total_bytes: int = 0
    supported_formats: List[str] = Field(default_factory=lambda: [
        "pdf", "markdown", "text", "python", "typescript", "javascript", "go", "java", "json", "yaml"
    ])
    duration_ms: float = 0.0


class RAGIngestionPipeline:
    """
    Executes autonomous ingestion:
    SOURCE DISCOVERY → PARSING → NORMALIZATION → CHUNKING → METADATA PRESERVATION
    """

    def __init__(self, chunk_max_chars: int = 1800, chunk_overlap_chars: int = 150):
        self.discovery = SourceDiscovery()
        self.chunker = StructureAwareChunker(max_chars=chunk_max_chars, overlap_chars=chunk_overlap_chars)

    def process_spec_sources(
        self,
        spec: CustomerProjectSpecification,
        project_id: str,
    ) -> Tuple[List[ProcessedDocument], List[KnowledgeChunkRecord]]:
        """Processes all knowledge sources specified in customer requirements."""
        documents: List[ProcessedDocument] = []
        all_chunks: List[KnowledgeChunkRecord] = []

        for source in spec.knowledge_sources:
            if source.source_type == SourceType.INLINE_TEXT and source.content:
                docs, chunks = self._process_inline_text(source, project_id)
                documents.extend(docs)
                all_chunks.extend(chunks)
            elif source.path:
                p = Path(source.path).expanduser().resolve()
                if p.is_dir():
                    docs, chunks = self._process_directory(source.source_id, p, project_id)
                    documents.extend(docs)
                    all_chunks.extend(chunks)
                elif p.is_file():
                    docs, chunks = self._process_file(source.source_id, p, project_id)
                    documents.extend(docs)
                    all_chunks.extend(chunks)

        return documents, all_chunks

    def _process_file(
        self,
        source_id: str,
        file_path: Path,
        project_id: str,
    ) -> Tuple[List[ProcessedDocument], List[KnowledgeChunkRecord]]:
        """Parses and chunks a single file."""
        doc_type, language = classify(file_path)
        content, encoding = read_text(file_path)
        c_hash = sha256_text(content)
        size_bytes = file_path.stat().st_size

        k_chunks = self.chunker.chunk(
            content,
            path=str(file_path.name),
            document_type=doc_type,
            language=language,
            source_id=source_id,
            project_id=project_id,
        )

        records = []
        for c in k_chunks:
            rec = KnowledgeChunkRecord(
                chunk_id=c.chunk_id,
                source_id=source_id,
                file_path=str(file_path.name),
                document_type=doc_type,
                language=language,
                chunk_index=c.chunk_index,
                content=c.content,
                line_start=getattr(c, "start_line", 1) or 1,
                line_end=getattr(c, "end_line", 1) or 1,
                content_hash=c.content_hash,
                metadata={
                    "project_id": project_id,
                    "encoding": encoding,
                    "original_path": str(file_path),
                },
            )
            records.append(rec)

        doc = ProcessedDocument(
            source_id=source_id,
            file_path=str(file_path.name),
            document_type=doc_type,
            language=language,
            size_bytes=size_bytes,
            content_hash=c_hash,
            chunks_count=len(records),
        )
        return [doc], records

    def _process_directory(
        self,
        source_id: str,
        dir_path: Path,
        project_id: str,
    ) -> Tuple[List[ProcessedDocument], List[KnowledgeChunkRecord]]:
        """Discovers and processes all supported files within a directory."""
        candidates = self.discovery.discover(dir_path)
        documents: List[ProcessedDocument] = []
        all_chunks: List[KnowledgeChunkRecord] = []

        for candidate in candidates:
            f_path = Path(candidate.absolute_path)
            file_source_id = f"{source_id}-{candidate.relative_path.replace('/', '_')}"
            docs, chunks = self._process_file(file_source_id, f_path, project_id)
            documents.extend(docs)
            all_chunks.extend(chunks)

        return documents, all_chunks

    def _process_inline_text(
        self,
        source: KnowledgeSourceSpec,
        project_id: str,
    ) -> Tuple[List[ProcessedDocument], List[KnowledgeChunkRecord]]:
        """Processes raw inline text."""
        content = source.content or ""
        doc_type = "markdown" if content.startswith("#") else "plain_text"
        language = "markdown" if doc_type == "markdown" else "text"
        c_hash = sha256_text(content)

        k_chunks = self.chunker.chunk(
            content,
            path=f"{source.source_id}.txt",
            document_type=doc_type,
            language=language,
            source_id=source.source_id,
            project_id=project_id,
        )

        records = []
        for c in k_chunks:
            rec = KnowledgeChunkRecord(
                chunk_id=c.chunk_id,
                source_id=source.source_id,
                file_path=f"{source.source_id}.txt",
                document_type=doc_type,
                language=language,
                chunk_index=c.chunk_index,
                content=c.content,
                line_start=getattr(c, "start_line", 1) or 1,
                line_end=getattr(c, "end_line", 1) or 1,
                content_hash=c.content_hash,
                metadata={"project_id": project_id, "inline": True},
            )
            records.append(rec)

        doc = ProcessedDocument(
            source_id=source.source_id,
            file_path=f"{source.source_id}.txt",
            document_type=doc_type,
            language=language,
            size_bytes=len(content.encode("utf-8")),
            content_hash=c_hash,
            chunks_count=len(records),
        )
        return [doc], records
