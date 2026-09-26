"""
Canonical Context Item — Minimum Sufficient Context (MSC) representation.

Implements the Gate 2 design (§2, §7) for 18-L Context Engineering. Adheres to
ADR-003: this module is a *representation*, not a retrieval, trust, memory, or
storage authority. It attributes what a capability provider supplied so that every
delivered context item is explainable and governable.

Design notes (Gate 2 §2.7): ``context_id`` is content-derived, not random. That one
choice makes deduplication, deterministic tie-breaking, dependency edges, and
provenance references all reproducible: identical inputs yield identical ids.

Ordering is deliberately *derived* (Gate 2 §2.5) rather than stored, so it cannot
drift out of sync with the rank function.
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from enum import Enum
from typing import Iterable

# Gate 2 §2.1: ranking uses a fixed category order so ties never fall to chance.
# Order is significant: it IS the category_rank component of the sort key.
CATEGORY_ORDER: tuple[str, ...] = (
    "system",
    "project",
    "task",
    "dependency",
    "evidence",
    "decision",
    "verification",
    "execution",
    "tool",
    "runtime_state",
    "git",
    "test_output",
)

#: Category ranks keyed by value, built once from CATEGORY_ORDER.
CATEGORY_RANK: dict[str, int] = {name: i for i, name in enumerate(CATEGORY_ORDER)}


class ContextCategory(str, Enum):
    """Context categories, aligned to ADR-003's consumed-capability table."""

    SYSTEM = "system"
    PROJECT = "project"
    TASK = "task"
    DEPENDENCY = "dependency"
    EVIDENCE = "evidence"
    DECISION = "decision"
    VERIFICATION = "verification"
    EXECUTION = "execution"
    TOOL = "tool"
    RUNTIME_STATE = "runtime_state"
    GIT = "git"
    TEST_OUTPUT = "test_output"


class ContextCacheability(str, Enum):
    """Provider-neutral cacheability metadata (Gate 2 section 7).

    A local classification only. It never asserts that a provider performed or will
    perform caching, and no provider cache-control directive is emitted here.
    """

    STABLE_SYSTEM = "stable_system"
    STABLE_PROJECT = "stable_project"
    TASK_DYNAMIC = "task_dynamic"
    VOLATILE = "volatile"


def normalize_content(content: str) -> str:
    """Normalize text for identity comparison (Gate 2 §2.6).

    NFKC -> strip trailing whitespace per line -> collapse blank-line runs ->
    casefold. Deterministic and dependency-free.
    """
    text = unicodedata.normalize("NFKC", content)
    lines = [line.rstrip() for line in text.splitlines()]
    # Collapse runs of blank lines entirely (Gate 2 2.6): "a\n\n\nb" -> "a\nb".
    collapsed = [line for line in lines if line]
    return "\n".join(collapsed).strip().casefold()


def content_digest(content: str) -> str:
    """Stable digest of normalized content, used for dedup and identity."""
    return hashlib.sha256(normalize_content(content).encode("utf-8")).hexdigest()


def make_context_id(
    category: str,
    source_kind: str,
    source_ref: str,
    content: str,
) -> str:
    """Derive a deterministic context id (Gate 2 §2.7).

    ``ctx_`` + first 16 hex chars of sha256 over category|source|ref|normalized
    content. Content-derived (not random) so repeated assembly of the same task
    produces the same ids, which is what makes dedup, tie-breaks, dependency
    edges, and provenance references deterministic.
    """
    payload = "|".join(
        (str(category), str(source_kind), str(source_ref), normalize_content(content))
    )
    return "ctx_" + hashlib.sha256(payload.encode("utf-8")).hexdigest()[:16]


@dataclass(frozen=True)
class ContextSource:
    """Where a context item came from (structured, not a free-text blob)."""

    kind: str
    ref: str = ""

    def describe(self) -> str:
        return f"{self.kind}:{self.ref}" if self.ref else str(self.kind)


@dataclass(frozen=True)
class ContextProvenance:
    """ADR-003 §6 provenance: the audit trail for one context item.

    Content-free: it identifies the *source*, never the payload, so it is safe to
    log (Gate 2 §5, §8).
    """

    acquired_from: str
    source_ref: str = ""
    provider: str = ""
    acquired_at: str = ""
    #: True when provenance was back-filled from the gathering source rather than
    #: supplied by the provider (Gate 2 §9, "missing provenance" row).
    inferred: bool = False


@dataclass
class ContextItem:
    """One attributable, governable unit of context (Gate 2 §2.1).

    ``required=True`` marks mandatory context: it is never dropped and never
    truncated. The protection is a whitelist of sources, not a heuristic, so
    selection stays deterministic.
    """

    content: str
    category: ContextCategory
    source: ContextSource
    relevance: float = 0.0
    required: bool = False
    required_for: tuple[str, ...] = ()
    depends_on: tuple[str, ...] = ()
    provenance: ContextProvenance | None = None
    estimated_tokens: int = 0
    cacheability: ContextCacheability = ContextCacheability.TASK_DYNAMIC
    context_id: str = ""
    dependency_depth: int = 0
    exclusion_reason: str | None = None

    def __post_init__(self) -> None:
        if not self.context_id:
            self.context_id = make_context_id(
                self.category.value, self.source.kind, self.source.ref, self.content
            )
        if self.provenance is None:
            # Optional items may carry inferred provenance (flagged); mandatory
            # items are validated by the engine before delivery.
            self.provenance = ContextProvenance(
                acquired_from=self.source.kind,
                source_ref=self.source.ref,
                inferred=True,
            )
        if not 0.0 <= float(self.relevance) <= 1.0:
            raise ValueError(f"relevance must be within [0, 1], got {self.relevance!r}")

    @property
    def content_digest(self) -> str:
        return content_digest(self.content)

    @property
    def category_rank(self) -> int:
        return CATEGORY_RANK.get(self.category.value, len(CATEGORY_ORDER))

    def rank_key(self) -> tuple:
        """Total order over context items (Gate 2 §2.3).

        ``required`` first, then fixed category rank, then descending relevance,
        then shallower dependency depth, then ``context_id`` as the final
        deterministic tie-break. No ties remain.
        """
        return (
            0 if self.required else 1,
            self.category_rank,
            -float(self.relevance),
            int(self.dependency_depth),
            self.context_id,
        )


def sort_context_items(items: Iterable[ContextItem]) -> list[ContextItem]:
    """Return items in canonical deterministic order (Gate 2 §2.5)."""
    return sorted(items, key=lambda item: item.rank_key())
