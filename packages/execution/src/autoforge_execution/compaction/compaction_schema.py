"""
Context Compaction — Data Contract (18-L Gate 3).

Implements the Gate 2 design (CONTEXT_COMPACTION_DESIGN_REPORT.md §9, §12).

Design properties carried from Gate 2:

* **Content-free provenance.** Like ``ContextProvenance`` and
  ``ContextAssemblyRecord``, this module's observability types have no field that
  can hold a context payload, so they are safe to log.
* **Deterministic identity.** ``compaction_id`` is derived exactly the way
  ``context_id`` is (``make_context_id``), so identical sources always produce an
  identical id and compaction is idempotent by construction.
* **Reuses existing identity.** Items stay ordinary ``ContextItem`` objects, so
  ``select_context`` and ``prompt_assembly`` require no change (Gate 2 §21).
* **Reuses 18-J conflict semantics.** ``DurableArtifactState`` documents that an
  existing key reused with a differing hash is rejected with a conflict error
  unless it is a legitimate new version; ``CompactionRecord`` follows the same
  rule via ``logical_version`` (Gate 2 §19, §20).

Gate 3 scope: deterministic only. ``CompactionMethod.MODEL_MEDIATED`` exists in
the contract for forward compatibility but is NOT implemented, and no model,
provider or runtime is referenced anywhere in this package (Gate 3 §17, §18).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
    normalize_content,
)


class CompactionMethod(str, Enum):
    """How a compacted representation was produced (Gate 2 §9)."""

    DETERMINISTIC = "deterministic"
    HYBRID = "hybrid"
    MODEL_MEDIATED = "model_mediated"


class PreservationClass(str, Enum):
    """Information preservation classes (Gate 2 §6).

    The mapping from real AutoForge state onto these classes is implemented in
    :mod:`autoforge_execution.compaction.compaction_policy`; these names are the
    contract, not the mapping.
    """

    IRREPLACEABLE = "irreplaceable"
    RECONSTRUCTABLE = "reconstructable"
    EPHEMERAL = "ephemeral"
    HISTORICAL = "historical"


class ValidationStatus(str, Enum):
    """Validation outcome (Gate 2 §9, §17)."""

    PENDING = "pending"
    VALID = "valid"
    REJECTED = "rejected"


class CompactionTrigger(str, Enum):
    """Deterministic trigger reasons (Gate 2 §7, §16)."""

    ITERATION_BOUNDARY = "iteration_boundary"
    BUDGET_PRESSURE = "budget_pressure"
    CANDIDATE_PRESSURE = "candidate_pressure"
    MANUAL = "manual"


# ── Durable references (Gate 2 §12) ───────────────────────────────────────


@dataclass(frozen=True)
class DurableRef:
    """A resolvable reference to authoritative durable content.

    **Reference only — never the content itself** (Gate 2 §8, §12). A compacted
    representation that inlined artifact bodies would defeat the purpose and
    would lose the hash-verification guarantee that makes reference substitution
    lossless.
    """

    artifact_id: str
    content_hash: str
    logical_version: int = 1
    artifact_type: str = "generic"
    source_ref: str = ""

    def describe(self) -> str:
        """Content-free description, safe for observability."""
        return f"{self.artifact_type}:{self.source_ref or self.artifact_id}@{self.content_hash[:12]}"


# ── Provenance (Gate 2 §12) ──────────────────────────────────────────────


@dataclass(frozen=True)
class CompactionProvenance:
    """Content-free audit trail for one compaction (Gate 2 §12).

    Structurally incapable of holding a payload: it carries only identifiers,
    enumerations and booleans.
    """

    acquired_from: str
    source_ref: str
    provider: str = ""
    acquired_at: str = ""
    inferred: bool = False
    source_context_ids: tuple[str, ...] = ()
    source_artifact_refs: tuple[str, ...] = ()
    compaction_method: str = CompactionMethod.DETERMINISTIC.value
    policy_version: int = 1

    def as_dict(self) -> dict[str, Any]:
        """Serializable, content-free view for observability."""
        return {
            "acquired_from": self.acquired_from,
            "source_ref": self.source_ref,
            "provider": self.provider,
            "acquired_at": self.acquired_at,
            "inferred": self.inferred,
            "source_context_ids": list(self.source_context_ids),
            "source_artifact_refs": list(self.source_artifact_refs),
            "compaction_method": self.compaction_method,
            "policy_version": self.policy_version,
        }


# ── Identity (Gate 2 §9, §19) ────────────────────────────────────────────

COMPACTION_ID_PREFIX = "cmp_"


def make_compaction_id(source_scope: str, request_fingerprint: str) -> str:
    """Derive a deterministic compaction id.

    Deliberately the same shape as ``make_context_id`` (Gate 2 E-2): identity is
    *derived from content*, not random, so the same sources always produce the same
    id. That is what makes compaction idempotent without extra state.
    """
    payload = "|".join((str(source_scope), str(request_fingerprint)))
    return COMPACTION_ID_PREFIX + hashlib.sha256(
        payload.encode("utf-8")
    ).hexdigest()[:16]


def make_request_fingerprint(
    source_ids: list[str],
    source_hashes: list[str],
    policy_version: int,
    *,
    scope: str = "",
) -> str:
    """Derive the request fingerprint for idempotency (Gate 2 §19).

    Mirrors ``IdempotentOperationState.request_fingerprint`` (Gate 2 E-14): a
    deterministic SHA-256 over the canonicalized source. Same sources + same
    policy ⇒ same fingerprint ⇒ reuse the existing record. A different policy
    version yields a different fingerprint ⇒ a new ``logical_version``.

    Gate 4 fix: ``scope`` (the logical idempotency key) participates in the
    fingerprint. Without it, two different tasks whose iteration numbering
    matched produced the same fingerprint and therefore the same
    ``compaction_id`` — and, because the durable artifact name derives from that
    id, their records would collide in the artifact catalog.
    """
    parts: list[str] = []
    if scope:
        parts.append(f"scope:{scope}")
    parts += list(sorted(str(s) for s in source_ids))
    parts += [f"h:{h}" for h in sorted(str(h) for h in source_hashes)]
    parts.append(f"policy:{int(policy_version)}")
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


def make_idempotency_key(
    source_scope: str, task_id: str, execution_id: str | None
) -> str:
    """Derive the logical compaction key (Gate 2 §19)."""
    return f"compact:{source_scope}:{task_id}:{execution_id or '-'}"


#: Fields that describe WHEN and HOW an operation executed, not WHAT it
#: produced. They are genuine audit information and are therefore still
#: PERSISTED (18-L §13: never delete provenance merely to stabilise a hash) —
#: they are simply excluded from the record's LOGICAL IDENTITY.
#:
#: Deliberately tiny. Anything not named here is identity-bearing, so the
#: identity fails safe: adding a field can only make it stricter.
RUNTIME_ONLY_FIELDS: frozenset[str] = frozenset({
    "duration_ms",   # wall-clock cost of the operation
    "acquired_at",   # when the compaction record was produced
})


#: Self-referential bookkeeping: the persisted ``logical_identity`` field is the
#: *result* of the digest, so it must never be an input to it.
_IDENTITY_FIELD = "logical_identity"


def _sha256_of_stripped(payload: dict[str, Any]) -> str:
    """Canonical digest of a serialized record.

    Excludes :data:`RUNTIME_ONLY_FIELDS` (at any depth) and the
    ``logical_identity`` field itself, which is this digest's own output.
    """
    material = {
        k: v for k, v in _strip_runtime_fields(payload).items()
        if k != _IDENTITY_FIELD
    }
    return hashlib.sha256(
        json.dumps(material, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()


def _strip_runtime_fields(value: Any) -> Any:
    """Recursively drop :data:`RUNTIME_ONLY_FIELDS` from a serialized record.

    Depth-recursive because the volatile provenance timestamp is nested inside
    the ``provenance`` object rather than sitting at the top level.
    """
    if isinstance(value, dict):
        return {
            k: _strip_runtime_fields(v)
            for k, v in value.items()
            if k not in RUNTIME_ONLY_FIELDS
        }
    if isinstance(value, list):
        return [_strip_runtime_fields(v) for v in value]
    return value


# ── The compact record (Gate 2 §9) ────────────────────────────────────────


@dataclass
class CompactedContextRecord:
    """The canonical compacted-context representation.

    Deliberately **not** a ``StateModel``: Gate 2 §9 recommended artifact-backed
    storage precisely so no new entity type or durable-state-model change is
    needed. This dataclass is the serializable payload stored as a durable
    artifact, which supplies content-hash integrity and 18-J idempotent replay.
    """

    # identity
    compaction_id: str
    idempotency_key: str
    request_fingerprint: str
    compaction_schema_version: int = 1

    # scope
    task_id: str = ""
    source_scope: str = ""
    execution_id: str | None = None
    workflow_id: str | None = None
    correlation_id: str | None = None

    # versioning (Gate 2 §20)
    policy_version: int = 1
    logical_version: int = 1
    supersedes: str | None = None

    # content (bounded)
    items: list[ContextItem] = field(default_factory=list)
    durable_refs: list[DurableRef] = field(default_factory=list)

    # classification (Gate 2 §6)
    preservation_breakdown: dict[str, int] = field(default_factory=dict)
    loss_classification: str = "lossless_by_reference"
    completeness: str = "complete"

    # method + provenance (content-free)
    compaction_method: str = CompactionMethod.DETERMINISTIC.value
    provenance: CompactionProvenance | None = None
    trigger: str = CompactionTrigger.ITERATION_BOUNDARY.value

    # validation (Gate 2 §17)
    validation_status: str = ValidationStatus.PENDING.value
    validation_reasons: list[str] = field(default_factory=list)

    # cost accounting (Gate 2 §27) — estimated, never a tokenizer guarantee
    estimated_tokens: int = 0
    source_estimated_tokens: int = 0
    duration_ms: float = 0.0

    @property
    def item_count(self) -> int:
        return len(self.items)

    @property
    def reference_count(self) -> int:
        return len(self.durable_refs)

    @property
    def reduction_ratio(self) -> float:
        """Fraction of estimated tokens removed. Reported, never optimised for."""
        if self.source_estimated_tokens <= 0:
            return 0.0
        saved = self.source_estimated_tokens - self.estimated_tokens
        return max(0.0, round(saved / self.source_estimated_tokens, 4))

    @property
    def reconstructability(self) -> float:
        """Fraction of references carrying a verifiable content hash."""
        if not self.durable_refs:
            return 1.0
        verifiable = [r for r in self.durable_refs if r.content_hash]
        return round(len(verifiable) / len(self.durable_refs), 4)

    def content_digest(self) -> str:
        """Deterministic digest of the record's *content* (Gate 2 V-8)."""
        parts = [
            f"{self.compaction_id}|{self.policy_version}|{self.logical_version}",
            *[
                f"{i.category.value}:{i.context_id}:{normalize_content(i.content)}"
                for i in self.items
            ],
            *[
                f"ref:{r.artifact_id}:{r.content_hash}:{r.logical_version}"
                for r in self.durable_refs
            ],
        ]
        return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()

    def logical_identity(self) -> str:
        """Digest of the record's LOGICAL IDENTITY (18-L P1 repair).

        This is a different question from :meth:`content_digest` and from the
        catalog's physical ``content_hash``, and conflating the three was the P1
        defect:

        ==========================  ======================================
        Concept                     Question it answers
        ==========================  ======================================
        ``logical_identity()``      "Which compaction RESULT is this?"
        ``content_digest()``        "What does its compacted content hash to?"
        catalog ``content_hash``    "Were the stored BYTES modified?"
        ==========================  ======================================

        The store must decide *idempotent replay vs conflict* on logical
        identity, because that is the question the caller is actually asking.
        It previously decided it on raw serialized bytes, so two logically
        identical records differing only in runtime metadata (a duration, a
        clock reading) were rejected as a conflict — violating the store's own
        documented contract that identical content reuses the artifact.

        Implementation is deliberately **fail-safe**: the digest covers every
        serialized field *except* those explicitly declared runtime-only, at any
        depth. A newly added field is therefore identity-bearing by default, so
        the identity can only ever become stricter, never looser by accident.
        """
        return _sha256_of_stripped(self.as_dict())


    def as_dict(self) -> dict[str, Any]:
        """Serializable view.

        Items keep their content (this *is* the payload); provenance and every
        derived observability field stay content-free.

        ``logical_identity`` is carried in the payload so a committed record
        states which compaction result it holds. It is a DERIVED field: the store
        never trusts it on its own, and :meth:`from_dict` recomputes the value
        from the persisted fields on every load.
        """
        payload = {
            "compaction_id": self.compaction_id,
            "idempotency_key": self.idempotency_key,
            "request_fingerprint": self.request_fingerprint,
            "compaction_schema_version": self.compaction_schema_version,
            "task_id": self.task_id,
            "source_scope": self.source_scope,
            "execution_id": self.execution_id,
            "workflow_id": self.workflow_id,
            "correlation_id": self.correlation_id,
            "policy_version": self.policy_version,
            "logical_version": self.logical_version,
            "supersedes": self.supersedes,
            "items": [
                {
                    "context_id": i.context_id,
                    "category": i.category.value,
                    "source_kind": i.source.kind,
                    "source_ref": i.source.ref,
                    "content": i.content,
                    "required": i.required,
                    "required_for": list(i.required_for),
                    "depends_on": list(i.depends_on),
                    "relevance": i.relevance,
                    "provenance": (
                        {
                            "acquired_from": i.provenance.acquired_from,
                            "source_ref": i.provenance.source_ref,
                            "provider": i.provenance.provider,
                            "inferred": i.provenance.inferred,
                        }
                        if i.provenance
                        else None
                    ),
                }
                for i in self.items
            ],
            "durable_refs": [
                {
                    "artifact_id": r.artifact_id,
                    "content_hash": r.content_hash,
                    "logical_version": r.logical_version,
                    "artifact_type": r.artifact_type,
                    "source_ref": r.source_ref,
                }
                for r in self.durable_refs
            ],
            "preservation_breakdown": dict(self.preservation_breakdown),
            "loss_classification": self.loss_classification,
            "completeness": self.completeness,
            "compaction_method": self.compaction_method,
            "provenance": self.provenance.as_dict() if self.provenance else None,
            "trigger": self.trigger,
            "validation_status": self.validation_status,
            "validation_reasons": list(self.validation_reasons),
            "estimated_tokens": self.estimated_tokens,
            "source_estimated_tokens": self.source_estimated_tokens,
            "duration_ms": round(self.duration_ms, 3),
            "item_count": self.item_count,
            "reference_count": self.reference_count,
            "reduction_ratio": self.reduction_ratio,
            "reconstructability": self.reconstructability,
        }
        # 18-L P1: the logical identity travels with the record. Computed from
        # `payload` (not from `self`) so it is exactly the value the store will
        # recompute from these persisted fields.
        payload[_IDENTITY_FIELD] = _sha256_of_stripped(payload)
        return payload
        # 18-L P1: the logical identity travels with the record. Derived from
        # `payload` (not from `self`) so it is exactly the value the store will
        # recompute from these persisted fields.
        payload["logical_identity"] = _sha256_of_stripped(payload)
        return payload


    @classmethod
    def from_dict(cls, payload: dict[str, Any]) -> "CompactedContextRecord":
        """Rebuild a record from its serialized form (restart-safe, Gate 2 §29)."""
        items = [
            ContextItem(
                content=raw["content"],
                category=ContextCategory(raw["category"]),
                source=ContextSource(raw["source_kind"], raw.get("source_ref", "")),
                relevance=float(raw.get("relevance", 0.0)),
                required=bool(raw.get("required", False)),
                required_for=tuple(raw.get("required_for", ())),
                depends_on=tuple(raw.get("depends_on", ())),
                provenance=(
                    ContextProvenance(
                        acquired_from=raw["provenance"]["acquired_from"],
                        source_ref=raw["provenance"].get("source_ref", ""),
                        provider=raw["provenance"].get("provider", ""),
                        inferred=bool(raw["provenance"].get("inferred", False)),
                    )
                    if raw.get("provenance")
                    else None
                ),
                context_id=raw.get("context_id", ""),
            )
            for raw in payload.get("items", [])
        ]
        prov_raw = payload.get("provenance")
        return cls(
            compaction_id=payload["compaction_id"],
            idempotency_key=payload["idempotency_key"],
            request_fingerprint=payload["request_fingerprint"],
            compaction_schema_version=int(payload.get("compaction_schema_version", 1)),
            task_id=payload["task_id"],
            source_scope=payload["source_scope"],
            execution_id=payload.get("execution_id"),
            workflow_id=payload.get("workflow_id"),
            correlation_id=payload.get("correlation_id"),
            policy_version=int(payload.get("policy_version", 1)),
            logical_version=int(payload.get("logical_version", 1)),
            supersedes=payload.get("supersedes"),
            items=items,
            durable_refs=[
                DurableRef(
                    artifact_id=r["artifact_id"],
                    content_hash=r["content_hash"],
                    logical_version=int(r.get("logical_version", 1)),
                    artifact_type=r.get("artifact_type", "generic"),
                    source_ref=r.get("source_ref", ""),
                )
                for r in payload.get("durable_refs", [])
            ],
            preservation_breakdown=dict(payload.get("preservation_breakdown", {})),
            loss_classification=payload.get(
                "loss_classification", "lossless_by_reference"
            ),
            completeness=payload.get("completeness", "complete"),
            compaction_method=payload.get(
                "compaction_method", CompactionMethod.DETERMINISTIC.value
            ),
            provenance=(
                CompactionProvenance(
                    acquired_from=prov_raw["acquired_from"],
                    source_ref=prov_raw.get("source_ref", ""),
                    provider=prov_raw.get("provider", ""),
                    acquired_at=prov_raw.get("acquired_at", ""),
                    inferred=bool(prov_raw.get("inferred", False)),
                    source_context_ids=tuple(prov_raw.get("source_context_ids", ())),
                    source_artifact_refs=tuple(prov_raw.get("source_artifact_refs", ())),
                    compaction_method=prov_raw.get(
                        "compaction_method", CompactionMethod.DETERMINISTIC.value
                    ),
                    policy_version=int(prov_raw.get("policy_version", 1)),
                )
                if prov_raw
                else None
            ),
            trigger=payload.get("trigger", CompactionTrigger.ITERATION_BOUNDARY.value),
            validation_status=payload.get(
                "validation_status", ValidationStatus.PENDING.value
            ),
            validation_reasons=list(payload.get("validation_reasons", [])),
            estimated_tokens=int(payload.get("estimated_tokens", 0)),
            source_estimated_tokens=int(payload.get("source_estimated_tokens", 0)),
            duration_ms=float(payload.get("duration_ms", 0.0)),
        )


# ── Content-free observability (Gate 2 §25) ──────────────────────────────


@dataclass
class CompactionAssemblyRecord:
    """Content-free record of one compaction (Gate 2 §25).

    Structurally incapable of holding a context payload — it carries only
    counts, identifiers, enumerations and ratios, exactly like
    ``ContextAssemblyRecord``.
    """

    compaction_id: str
    task_id: str
    source_scope: str
    trigger: str
    policy_version: int
    compaction_method: str

    source_item_count: int = 0
    retained_item_count: int = 0
    compacted_item_count: int = 0
    reference_count: int = 0

    source_estimated_tokens: int = 0
    estimated_tokens: int = 0
    reduction_ratio: float = 0.0
    reconstructability: float = 1.0
    preservation_breakdown: dict[str, int] = field(default_factory=dict)
    loss_classification: str = "lossless_by_reference"
    completeness: str = "complete"
    validation_status: str = ValidationStatus.PENDING.value
    validation_reasons: list[str] = field(default_factory=list)
    duration_ms: float = 0.0

    def as_dict(self) -> dict[str, Any]:
        return {
            "compaction_id": self.compaction_id,
            "task_id": self.task_id,
            "source_scope": self.source_scope,
            "trigger": self.trigger,
            "policy_version": self.policy_version,
            "compaction_method": self.compaction_method,
            "source_item_count": self.source_item_count,
            "retained_item_count": self.retained_item_count,
            "compacted_item_count": self.compacted_item_count,
            "reference_count": self.reference_count,
            "source_estimated_tokens": self.source_estimated_tokens,
            "estimated_tokens": self.estimated_tokens,
            "reduction_ratio": self.reduction_ratio,
            "reconstructability": self.reconstructability,
            "preservation_breakdown": dict(self.preservation_breakdown),
            "loss_classification": self.loss_classification,
            "completeness": self.completeness,
            "validation_status": self.validation_status,
            "validation_reasons": list(self.validation_reasons),
            "duration_ms": round(self.duration_ms, 3),
        }


__all__ = [
    "COMPACTION_ID_PREFIX",
    "CompactedContextRecord",
    "CompactionAssemblyRecord",
    "CompactionMethod",
    "CompactionProvenance",
    "CompactionTrigger",
    "DurableRef",
    "PreservationClass",
    "ValidationStatus",
    "make_compaction_id",
    "make_idempotency_key",
    "make_request_fingerprint",
]
