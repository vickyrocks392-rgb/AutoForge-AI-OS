"""
PolicyDesk Knowledge Assistant — Retrieval and Citation Assembly Engine.
Evaluates vector relevance, builds verifiable citations, and identifies abstention conditions.
"""

from __future__ import annotations

import logging
from typing import List, Optional, Tuple
from models import ChunkRecord, Citation
from vector_store import PolicyDeskVectorStore

logger = logging.getLogger("policydesk.retriever")


class PolicyDeskRetriever:
    """Retrieves grounded evidence from the persistent vector index."""

    def __init__(
        self,
        vector_store: PolicyDeskVectorStore,
        min_similarity_threshold: float = 0.25,
    ):
        self.vector_store = vector_store
        self.min_similarity_threshold = min_similarity_threshold

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
    ) -> Tuple[List[Tuple[ChunkRecord, float]], List[Citation], bool]:
        """
        Retrieves matching chunks and builds verifiable citations.
        Returns:
            - matched_chunks: List of (ChunkRecord, score)
            - citations: List of Citation
            - is_insufficient: bool indicating whether retrieval failed to find adequate evidence.
        """
        raw_results = self.vector_store.query(query, top_k=top_k)
        if not raw_results:
            return [], [], True

        # Check top score against threshold
        top_score = raw_results[0][1]
        if top_score < self.min_similarity_threshold:
            logger.info(f"Top retrieval score {top_score:.4f} is below threshold {self.min_similarity_threshold}. Abstention recommended.")
            # Still return low-score citations for auditability if needed, but flag as insufficient
            citations = self._build_citations(raw_results)
            return raw_results, citations, True

        # Filter chunks that meet minimum threshold
        filtered_results = [r for r in raw_results if r[1] >= (self.min_similarity_threshold * 0.8)]
        if not filtered_results:
            filtered_results = [raw_results[0]]

        citations = self._build_citations(filtered_results)
        return filtered_results, citations, False

    def _build_citations(self, results: List[Tuple[ChunkRecord, float]]) -> List[Citation]:
        citations: List[Citation] = []
        for chunk, score in results:
            lines = f"L{chunk.line_start}-L{chunk.line_end}" if chunk.line_start != chunk.line_end else f"L{chunk.line_start}"
            # Extract snippet
            passage_snippet = chunk.content[:240].strip()
            if len(chunk.content) > 240:
                passage_snippet += "..."

            version = "2.0" if "2026" in chunk.filename else ("1.0" if "2024" in chunk.filename else "1.0")
            effective = "2026-01-01" if "2026" in chunk.filename else ("2024-01-01" if "2024" in chunk.filename else None)

            citations.append(
                Citation(
                    doc_id=chunk.doc_id,
                    filename=chunk.filename,
                    page=chunk.page,
                    line_range=lines,
                    chunk_id=chunk.chunk_id,
                    score=score,
                    passage=passage_snippet,
                    version=version,
                    effective_date=effective,
                )
            )
        return citations
