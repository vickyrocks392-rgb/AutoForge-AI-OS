"""
Context Assembler

Assembles context for knowledge retrieval as defined in the Knowledge Platform Specification v1.0.

Scoped specialization (18-L Gate 2, section 6.2). Per ADR-003's Consequences
clause, "the Knowledge Platform's existing assembler remains the knowledge-scoped
slice; the Context Engine composes it rather than replacing it". Behaviour is
unchanged; the only Gate 3 change is that the two previously ``Any``-typed
collaborators are now described by ``Protocol`` contracts. ``None``/falsy values
remain acceptable so no existing caller breaks.
"""

from __future__ import annotations

from typing import Any, Dict, List, Protocol, Sequence, runtime_checkable

from autoforge_knowledge_platform.interfaces.knowledge_interfaces import IContextAssembler
from autoforge_knowledge_platform.models import KnowledgeItem, RetrievalResult


@runtime_checkable
class RelevanceRankerPort(Protocol):
    """Ranks knowledge items for a query."""

    async def rank(
        self, items: Sequence[KnowledgeItem], query: Dict[str, Any]
    ) -> List[KnowledgeItem]: ...


@runtime_checkable
class ContextWindowFitterPort(Protocol):
    """Fits ranked items into an available context window."""

    async def fit(
        self, items: Sequence[KnowledgeItem], context_window: int
    ) -> List[KnowledgeItem]: ...


class ContextAssembler(IContextAssembler):
    """
    Assembles context for knowledge retrieval.
    
    As defined in Knowledge Platform Specification v1.0, Section 7.9.
    """
    
    def __init__(
        self,
        citation_manager: Any = None,
        context_window_manager: ContextWindowFitterPort | None = None,
        relevance_ranker: RelevanceRankerPort | None = None,
    ):
        """Initialize Context Assembler with dependencies.

        All three remain optional so the knowledge slice keeps working when they are
        absent; the canonical Context Engine owns the global budget.
        """
        self.citation_manager = citation_manager
        self.context_window_manager = context_window_manager
        self.relevance_ranker = relevance_ranker
    
    async def assemble_context(
        self,
        retrieval_results: List[RetrievalResult],
        query: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Assemble context from retrieval results.
        
        Context assembly:
        - Rank by relevance
        - Filter by trust threshold
        - Remove duplicates
        - Assemble citations
        - Manage context window
        
        Args:
            retrieval_results: List of retrieval results
            query: Query parameters
            
        Returns:
            Assembled context
        """
        # Flatten results
        all_items = []
        for result in retrieval_results:
            all_items.extend(result.knowledge_items)
        
        # Rank by relevance
        ranked_items = await self.relevance_ranker.rank(all_items, query)
        
        # Filter by trust threshold
        min_trust = query.get("min_trust", 0.0)
        filtered_items = [item for item in ranked_items if item.trust_score >= min_trust]
        
        # Remove duplicates
        deduplicated_items = await self._remove_duplicates(filtered_items)
        
        # Assemble citations
        citations = await self._assemble_citations(deduplicated_items)
        
        # Manage context window
        context_window = query.get("context_window", 4000)
        final_items = await self.context_window_manager.fit(deduplicated_items, context_window)
        
        return {
            "knowledge_items": final_items,
            "citations": citations,
            "total_items": len(final_items),
            "context_utilization": len(final_items) / max(len(deduplicated_items), 1),
        }
    
    async def _remove_duplicates(self, items: List[KnowledgeItem]) -> List[KnowledgeItem]:
        """Remove duplicate items."""
        seen = set()
        unique = []
        for item in items:
            if item.id not in seen:
                seen.add(item.id)
                unique.append(item)
        return unique
    
    async def _assemble_citations(self, items: List[KnowledgeItem]) -> List[Dict[str, Any]]:
        """Assemble citations for items."""
        citations = []
        for item in items:
            for source_id in item.sources:
                citations.append({
                    "knowledge_item_id": item.id,
                    "source_id": source_id,
                })
        return citations