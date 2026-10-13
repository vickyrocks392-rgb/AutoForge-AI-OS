"""
PolicyDesk Knowledge Assistant — Core Application Service.
Coordinates document ingestion, vector persistence, retrieval, conflict resolution, and answer generation.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Optional

from config import PolicyDeskConfig, resolve_and_validate_paths
from models import (
    ComponentStatus,
    DocumentListResponse,
    DocumentUploadResponse,
    HealthResponse,
    QueryRequest,
    QueryResponse,
)
from embeddings import PolicyDeskEmbeddingProvider
from vector_store import PolicyDeskVectorStore
from ingestion_service import PolicyDeskIngestionService
from retriever import PolicyDeskRetriever
from conflict_detector import PolicyConflictDetector
from generator import PolicyDeskAnswerGenerator

logger = logging.getLogger("policydesk.service")


class PolicyDeskService:
    """Core enterprise knowledge service for PolicyDesk."""

    def __init__(self, config: Optional[PolicyDeskConfig] = None):
        self.config = config or resolve_and_validate_paths()
        
        # Initialize components
        self.embedding_provider = PolicyDeskEmbeddingProvider()
        self.vector_store = PolicyDeskVectorStore(
            persist_dir=self.config.vector_db_dir,
            collection_name=self.config.vector_collection_name,
            embedding_provider=self.embedding_provider,
        )
        self.ingestion_service = PolicyDeskIngestionService(
            vector_store=self.vector_store,
            ingestion_dir=self.config.ingestion_dir,
            chunk_size=self.config.max_chunk_chars,
            chunk_overlap=self.config.chunk_overlap_chars,
        )
        self.retriever = PolicyDeskRetriever(
            vector_store=self.vector_store,
            min_similarity_threshold=self.config.min_similarity_threshold,
        )
        self.generator = PolicyDeskAnswerGenerator(
            base_url=self.config.llm_base_url,
            model=self.config.llm_model,
            timeout=self.config.llm_timeout_seconds,
            temperature=self.config.llm_temperature,
        )

    def query(self, req: QueryRequest) -> QueryResponse:
        """Process natural language question against the persistent knowledge base."""
        t0 = time.perf_counter()

        # 1. Retrieve evidence
        matched_chunks, citations, is_insufficient = self.retriever.retrieve(
            query=req.query,
            top_k=req.top_k,
        )

        # 2. Detect policy conflicts / versioning issues
        conflict_info = PolicyConflictDetector.detect_conflicts(
            query=req.query,
            retrieved_chunks=matched_chunks,
        )

        # 3. Generate grounded answer
        answer, is_grounded, grounding_score, abstained = self.generator.generate(
            query=req.query,
            matched_chunks=matched_chunks,
            citations=citations,
            conflict=conflict_info,
            is_insufficient=is_insufficient,
        )

        duration_ms = (time.perf_counter() - t0) * 1000.0

        return QueryResponse(
            query=req.query,
            answer=answer,
            citations=citations,
            is_grounded=is_grounded,
            grounding_score=grounding_score,
            abstained=abstained,
            conflict=conflict_info,
            latency_ms=round(duration_ms, 2),
            model_used=self.config.llm_model,
        )

    def upload_document(
        self,
        file_path: Path | str,
        doc_id: Optional[str] = None,
        force_reindex: bool = False,
    ) -> DocumentUploadResponse:
        return self.ingestion_service.ingest_file(
            file_path=file_path,
            doc_id=doc_id,
            force_reindex=force_reindex,
        )

    def delete_document(self, doc_id: str) -> bool:
        return self.ingestion_service.delete_document(doc_id)

    def list_documents(self) -> DocumentListResponse:
        docs = self.ingestion_service.list_documents()
        total_chunks = self.vector_store.count_chunks()
        return DocumentListResponse(
            total_documents=len(docs),
            total_chunks=total_chunks,
            documents=docs,
        )

    def get_health(self) -> HealthResponse:
        total_chunks = self.vector_store.count_chunks()
        total_docs = len(self.ingestion_service.list_documents())
        llm_online = self.generator.check_health()

        components = {
            "vector_store": ComponentStatus(
                status="healthy",
                details=f"ChromaDB persistent store active with {total_chunks} chunks indexed.",
            ),
            "persistence": ComponentStatus(
                status="healthy",
                details=f"External host storage at {self.config.data_dir}.",
            ),
            "embedding_engine": ComponentStatus(
                status="healthy",
                details=f"{self.config.embedding_model} ({self.config.embedding_dimensions} dims).",
            ),
            "generation_runtime": ComponentStatus(
                status="healthy" if llm_online else "degraded",
                details=f"Endpoint {self.config.llm_base_url} is {'reachable' if llm_online else 'offline (extractive grounding fallback enabled)'}.",
            ),
        }

        return HealthResponse(
            status="healthy",
            project_name=self.config.project_name,
            data_directory=str(self.config.data_dir),
            vector_store="ChromaDB Persistent (DuckDB/Parquet)",
            collection_name=self.config.vector_collection_name,
            embedding_model=self.config.embedding_model,
            embedding_dimensions=self.config.embedding_dimensions,
            generation_provider=self.config.llm_provider,
            generation_model=self.config.llm_model,
            generation_available=llm_online,
            indexed_documents_count=total_docs,
            indexed_chunks_count=total_chunks,
            components=components,
        )

    def reset_knowledge_base(self) -> None:
        self.ingestion_service.reset()
