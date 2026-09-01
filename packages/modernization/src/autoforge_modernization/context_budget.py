"""
Context Optimization and Budget Models.

Establishes explicit context-management contracts for constrained local hardware.
The modernization engine must be able to use hierarchical summaries, symbol-level
retrieval, semantic chunking, context caching, prompt compression, evidence
prioritization, and token budgets.

The foundation allows context/token usage to become observable.
The foundation does NOT feed an entire large repository to an LLM.

Reuses:
- jobs: ModernizationJob (via job_id)
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class ChunkingStrategy(str, Enum):
    """Strategy for chunking code for context."""

    SEMANTIC = "semantic"
    """Chunk by semantic boundaries (functions, classes, programs)."""

    STRUCTURAL = "structural"
    """Chunk by file/line structure."""

    HYBRID = "hybrid"
    """Combine semantic and structural."""

    AST_BASED = "ast_based"
    """Chunk by AST nodes (for languages with parsers)."""


class ContextOptimization(str, Enum):
    """Specific optimization technique."""

    HIERARCHICAL_SUMMARY = "hierarchical_summary"
    """Use repository > module > function summaries."""

    SYMBOL_LEVEL = "symbol_level"
    """Retrieve at symbol (function/procedure) level."""

    DEPENDENCY_AWARE = "dependency_aware"
    """Retrieve with dependency awareness."""

    AST_DERIVED = "ast_derived"
    """Derive context from AST analysis."""

    RELEVANT_FILE = "relevant_file"
    """Retrieve only relevant files."""

    SEMANTIC_CHUNKING = "semantic_chunking"
    """Use semantic/structural chunking."""

    CONTEXT_CACHING = "context_caching"
    """Cache retrieved context."""

    PROMPT_COMPRESSION = "prompt_compression"
    """Apply prompt compression."""

    EVIDENCE_PRIORITIZATION = "evidence_prioritization"
    """Prioritize high-confidence evidence."""

    DEDUPLICATION = "deduplication"
    """Deduplicate context content."""


class ContextBudget(BaseModel):
    """
    Token budget for a modernization context window.

    Tracks usage against the budget and exposes what techniques are enabled.
    """

    budget_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str | None = None
    unit_id: str | None = None

    # Budget limits
    model_context_window_tokens: int = 0
    reserved_for_system_prompt: int = 0
    reserved_for_response: int = 0
    available_for_context: int = 0
    """The usable context after system prompt + response buffer."""

    # Current usage
    current_usage_tokens: int = 0
    peak_usage_tokens: int = 0
    remaining_tokens: int = 0

    # Optimization techniques enabled
    enabled_optimizations: list[ContextOptimization] = Field(default_factory=list)

    # Chunking
    chunking_strategy: ChunkingStrategy = ChunkingStrategy.STRUCTURAL
    chunk_size_tokens: int = 0

    # Tracking
    token_accounting_enabled: bool = True
    usage_observable: bool = True

    last_updated: datetime = Field(default_factory=_utc_now)

    # Per-level budgets
    repository_summary_tokens: int = 0
    module_summary_tokens: int = 0
    symbol_level_tokens: int = 0

    def reserve(self, tokens: int, purpose: str) -> bool:
        """
        Attempt to reserve tokens for a purpose.

        Returns True if reservation succeeds, False if over budget.
        """
        if self.remaining_tokens >= tokens:
            self.current_usage_tokens += tokens
            self.remaining_tokens -= tokens
            self.peak_usage_tokens = max(self.peak_usage_tokens, self.current_usage_tokens)
            return True
        return False

    def release(self, tokens: int) -> None:
        """Release reserved tokens back to the pool."""
        self.current_usage_tokens = max(0, self.current_usage_tokens - tokens)
        self.remaining_tokens = min(
            self.available_for_context,
            self.remaining_tokens + tokens,
        )

    def is_over_budget(self) -> bool:
        """Return True if current usage exceeds available context."""
        return self.current_usage_tokens > self.available_for_context


class ContextUsageRecord(BaseModel):
    """
    A record of context usage for a single operation.

    Makes token usage observable and auditable.
    """

    record_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_id: str
    job_id: str | None = None
    unit_id: str | None = None
    operation: str

    input_tokens: int = 0
    output_tokens: int = 0
    total_tokens: int = 0
    context_tokens: int = 0

    technique: ContextOptimization | None = None

    timestamp: datetime = Field(default_factory=_utc_now)
    notes: str = ""
