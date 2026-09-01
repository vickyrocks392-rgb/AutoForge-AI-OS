"""
RAG/Knowledge Integration Boundary.

Defines the boundary for RAG/Knowledge consumption by the modernization engine.

RAG is NOT an execution-engine-only facility. It must be usable by:
- Research
- Planning
- Architecture/Design
- Coding
- Modernization
- Diagnosis
- Repair
- Verification

This module defines the contract using the existing 18-D RAG infrastructure.
It does NOT create a second vector database or RAG engine.

Reuses:
- autoforge_knowledge_platform.rag18: KnowledgeRAGEngine (duck-typed protocol)
- autoforge_execution.models: RAGRetrievalEngine (runtime_checkable protocol)
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class ModernizationRAGRetrievalEngine(Protocol):
    """
    Protocol for a RAG-enabled knowledge retrieval engine in the modernization context.

    Matches the interface of
    ``autoforge_knowledge_platform.rag18.facade.KnowledgeRAGEngine``.

    The modernization engine depends only on this protocol — no runtime import
    of the knowledge platform is required.

    Implementations must provide::

        await engine.retrieve_for_context(
            query: str,
            *,
            project_id: str | None = None,
            workflow_id: str | None = None,
            execution_id: str | None = None,
            workspace_root: str | None = None,
            top_k: int | None = None,
            score_threshold: float | None = None,
        ) -> Any

    The returned value is duck-typed: it must have ``.hits`` or ``.results``
    (a list of retrieval hits).
    """

    async def retrieve_for_context(
        self,
        query: str,
        *,
        project_id: str | None = None,
        workflow_id: str | None = None,
        execution_id: str | None = None,
        workspace_root: str | None = None,
        top_k: int | None = None,
        score_threshold: float | None = None,
    ) -> Any: ...


# ── RAG Integration Points ───────────────────────────────────────────────────────


class RAGIntegrationScope:
    """
    Enumerates the specific places in the modernization pipeline
    where RAG knowledge retrieval is applicable.
    """

    # Research phase
    RESEARCH = "research"
    """Technology evaluation, migration paths, market research."""

    # Planning phase
    PLANNING = "planning"
    """Migration strategy, wave planning, effort estimation."""

    # Architecture/Design phase
    ARCHITECTURE = "architecture"
    """Target architecture, patterns, anti-patterns."""

    # Coding phase
    CODING = "coding"
    """Code generation, best practices, language idioms."""

    # Modernization phase
    MODERNIZATION = "modernization"
    """Legacy code patterns, equivalent modern constructs."""

    # Diagnosis phase
    DIAGNOSIS = "diagnosis"
    """Failure diagnosis, root cause analysis."""

    # Repair phase
    REPAIR = "repair"
    """Remediation patterns, fix strategies."""

    # Verification phase
    VERIFICATION = "verification"
    """Test strategies, verification criteria."""

    @classmethod
    def all(cls) -> list[str]:
        return [
            cls.RESEARCH,
            cls.PLANNING,
            cls.ARCHITECTURE,
            cls.CODING,
            cls.MODERNIZATION,
            cls.DIAGNOSIS,
            cls.REPAIR,
            cls.VERIFICATION,
        ]
