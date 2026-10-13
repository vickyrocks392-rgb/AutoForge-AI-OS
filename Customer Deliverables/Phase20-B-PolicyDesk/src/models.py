"""
PolicyDesk Knowledge Assistant — Data Transfer Objects & Domain Models.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DocumentMetadata(BaseModel):
    """Metadata record for an ingested customer document."""
    doc_id: str
    filename: str
    format: str
    size_bytes: int
    sha256: str
    chunks_count: int = 0
    ingested_at: str = Field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    version: str = "1.0"
    effective_date: Optional[str] = None
    status: str = "indexed"  # "indexed", "failed", "pending"
    error_message: Optional[str] = None


class ChunkRecord(BaseModel):
    """Granular text chunk and its precise provenance coordinates."""
    chunk_id: str
    doc_id: str
    filename: str
    format: str
    page: Optional[int] = None  # 1-indexed page number for PDFs
    line_start: int = 1
    line_end: int = 1
    section: str = ""
    content: str
    content_hash: str


class Citation(BaseModel):
    """Verifiable attribution pointing directly to source passage."""
    doc_id: str
    filename: str
    page: Optional[int] = None
    line_range: str = "L1"
    chunk_id: str
    score: float = 0.0  # Cosine similarity score
    passage: str
    version: Optional[str] = None
    effective_date: Optional[str] = None


class PolicyConflictInfo(BaseModel):
    """Information detailing conflicting or superseded policy versions."""
    has_conflict: bool = False
    summary: str = ""
    superseded_policy: Optional[str] = None
    active_policy: Optional[str] = None
    explanation: Optional[str] = None


class QueryRequest(BaseModel):
    """Customer natural language query request."""
    query: str = Field(..., min_length=1, description="Question in plain English")
    top_k: int = Field(default=5, ge=1, le=20, description="Max relevant passages to consider")


class QueryResponse(BaseModel):
    """Retrieval-grounded assistant response."""
    query: str
    answer: str
    citations: List[Citation] = Field(default_factory=list)
    is_grounded: bool = True
    grounding_score: float = 1.0
    abstained: bool = False
    conflict: Optional[PolicyConflictInfo] = None
    latency_ms: float = 0.0
    model_used: str = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"


class DocumentUploadResponse(BaseModel):
    """Result of uploading and processing a document."""
    doc_id: str
    filename: str
    status: str
    chunks_count: int
    message: str
    is_duplicate: bool = False


class DocumentListResponse(BaseModel):
    """List of all documents registered in the knowledge base."""
    total_documents: int
    total_chunks: int
    documents: List[DocumentMetadata]


class ComponentStatus(BaseModel):
    status: str
    details: str


class HealthResponse(BaseModel):
    """Operational health and configuration status."""
    status: str = "healthy"
    project_name: str
    data_directory: str
    vector_store: str
    collection_name: str
    embedding_model: str
    embedding_dimensions: int
    generation_provider: str
    generation_model: str
    generation_available: bool
    indexed_documents_count: int
    indexed_chunks_count: int
    components: Dict[str, ComponentStatus] = Field(default_factory=dict)
