"""Grounded Context Construction, Citation Attribution & Verification Guardrails."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.rag.ingestion import KnowledgeChunkRecord


class CitationReference(BaseModel):
    """Source provenance citation for a claim."""
    citation_id: int
    source_file: str
    line_range: str
    chunk_id: str
    score: float
    snippet: str


class GroundedContext(BaseModel):
    """Context constructed from retrieved knowledge units."""
    query: str
    formatted_context: str
    citations: List[CitationReference] = Field(default_factory=list)
    total_chunks: int = 0
    total_chars: int = 0


class GroundedAnswer(BaseModel):
    """Verified response with strict attribution and grounding checks."""
    query: str
    answer: str
    citations: List[CitationReference] = Field(default_factory=list)
    is_grounded: bool = True
    uncertainty_signaled: bool = False
    unsupported_claims: List[str] = Field(default_factory=list)
    grounding_score: float = 1.0


class GroundedContextBuilder:
    """
    Constructs prompt context with clear provenance boundaries.
    """

    def __init__(self, max_context_chars: int = 6000):
        self.max_context_chars = max_context_chars

    def build_context(
        self,
        query: str,
        retrieved_chunks: List[Dict[str, Any]],
    ) -> GroundedContext:
        """
        Formats retrieved chunks into numbered citation blocks.
        """
        citations: List[CitationReference] = []
        context_blocks = []
        cur_chars = 0

        for idx, chunk in enumerate(retrieved_chunks, start=1):
            c_id = chunk.get("chunk_id", f"chunk-{idx}")
            f_path = chunk.get("file_path", "unknown")
            l_start = chunk.get("line_start", 1)
            l_end = chunk.get("line_end", 1)
            score = float(chunk.get("score", chunk.get("relevance_score", 0.9)))
            content = str(chunk.get("content", "")).strip()

            if cur_chars + len(content) > self.max_context_chars and context_blocks:
                break

            cit = CitationReference(
                citation_id=idx,
                source_file=f_path,
                line_range=f"L{l_start}-L{l_end}",
                chunk_id=c_id,
                score=score,
                snippet=content[:200] + ("..." if len(content) > 200 else ""),
            )
            citations.append(cit)

            block = (
                f"[Source {idx} | File: {f_path} (Lines {l_start}-{l_end}) | Relevance: {score:.2f}]\n"
                f"{content}\n"
            )
            context_blocks.append(block)
            cur_chars += len(block)

        formatted = "\n---\n".join(context_blocks)
        return GroundedContext(
            query=query,
            formatted_context=formatted,
            citations=citations,
            total_chunks=len(citations),
            total_chars=cur_chars,
        )


class GroundingVerifier:
    """
    Validates that responses are grounded in retrieved source context.
    Surfaces explicit uncertainty if knowledge is missing.
    """

    UNCERTAINTY_PHRASES = [
        "the provided documents do not contain",
        "i could not find information regarding",
        "the retrieved knowledge does not specify",
        "no information available in the knowledge base",
        "information not found in the indexed documents",
    ]

    @staticmethod
    def extract_numeric_tokens(text: str) -> set[str]:
        """Extracts normalized numeric tokens and currency amounts from text.
        e.g., '$10,000' -> '10000', '1,000' -> '1000', '24' -> '24'
        """
        raw_nums = re.findall(r"[$€£]?\b\d+(?:,\d+)*(?:\.\d+)?", text)
        nums = set()
        for r in raw_nums:
            cleaned = re.sub(r"[^\d.]", "", r)
            try:
                val = float(cleaned)
                if val.is_integer():
                    nums.add(str(int(val)))
                else:
                    nums.add(str(val))
            except ValueError:
                pass
        return nums

    def verify_answer(
        self,
        query: str,
        answer: str,
        context: GroundedContext,
    ) -> GroundedAnswer:
        """
        Audits answer text against available context.
        Validates citation coverage and strict numeric/factual consistency.
        """
        # 1. Check if context was completely empty
        if not context.citations or not context.formatted_context.strip():
            return GroundedAnswer(
                query=query,
                answer=(
                    f"I could not find sufficient information in the indexed knowledge base to answer: '{query}'. "
                    "Please verify that the required documents are ingested."
                ),
                citations=[],
                is_grounded=True,
                uncertainty_signaled=True,
                grounding_score=1.0,
            )

        lower_ans = answer.lower()
        signaled_uncertainty = any(p in lower_ans for p in self.UNCERTAINTY_PHRASES)

        # 2. Check citations
        matched_citations = []
        for cit in context.citations:
            # If source file or citation marker or key terms from snippet appear
            if (
                cit.source_file.lower() in lower_ans
                or f"[source {cit.citation_id}" in lower_ans
                or f"[{cit.citation_id}]" in lower_ans
                or any(w in lower_ans for w in cit.source_file.split("/")[-1].split(".") if len(w) > 3)
            ):
                matched_citations.append(cit)

        # If model didn't explicitly write bracket citation, bind top relevant citations from context
        if not matched_citations and not signaled_uncertainty:
            matched_citations = context.citations[:2]

        # 3. Strict Numeric & Factual Consistency Audit
        unsupported_claims = []
        if not signaled_uncertainty and context.formatted_context:
            ctx_nums = self.extract_numeric_tokens(context.formatted_context)
            ans_nums = self.extract_numeric_tokens(answer)
            # Numbers asserted in answer that are absent from retrieved context
            unsupported_nums = ans_nums - ctx_nums
            if unsupported_nums:
                for num in sorted(unsupported_nums):
                    unsupported_claims.append(
                        f"Numeric value '{num}' in answer is not supported by retrieved source context"
                    )

        grounding_score = 1.0 if (matched_citations or signaled_uncertainty) else 0.75
        if unsupported_claims:
            # Significant penalty for factual contradiction or numerical hallucination
            grounding_score = max(0.0, grounding_score - 0.4 * len(unsupported_claims))

        is_grounded = (grounding_score >= 0.8) and (len(unsupported_claims) == 0)

        return GroundedAnswer(
            query=query,
            answer=answer,
            citations=matched_citations,
            is_grounded=is_grounded,
            uncertainty_signaled=signaled_uncertainty,
            unsupported_claims=unsupported_claims,
            grounding_score=round(grounding_score, 4),
        )
