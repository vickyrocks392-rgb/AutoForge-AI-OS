"""
Context Compaction — deterministic core (18-L Gate 3, implementing Gate 2 §5, §6,
§8, §10, §13, §15).

What this does, and nothing more:

* projects each superseded ``LoopIterationRecord`` into a small, attributed,
  dependency-linked ``ContextItem`` (Gate 2 §10 — this is the G-1 fix);
* records a **durable reference** for the Reconstructable payload instead of
  inlining it (Gate 2 §8), which is what makes compaction lossless;
* preserves dependency and supersession edges structurally (Gate 2 §11, §13);
* never touches Irreplaceable material (Gate 2 §6).

**No model is involved, and none is available here** (Gate 2 §15, Gate 3 §17).
The module imports no runtime, provider or model: it operates purely on
structured AutoForge state, so it is provider-neutral by construction (Gate 3
§18). ``CompactionMethod.MODEL_MEDIATED`` exists in the contract for forward
compatibility only.

Authority discipline (Gate 3 §12): a *model's* opinion is never promoted to a
verified fact. Statements the repository represents as *observed* (evaluation
status, deterministic checks) are marked as such; anything a diagnosis *claims*
is carried as a claim, attributed to its source, and never restated as proof.
"""

from __future__ import annotations

import logging
import time
from datetime import datetime, timezone
from typing import Any, Protocol, Sequence

from autoforge_execution.context_items import (
    ContextCategory,
    ContextItem,
    ContextProvenance,
    ContextSource,
)
from autoforge_execution.compaction.compaction_policy import (
    CompactionPolicy,
    classify_items,
)
from autoforge_execution.compaction.compaction_schema import (
    CompactedContextRecord,
    CompactionAssemblyRecord,
    CompactionMethod,
    CompactionProvenance,
    DurableRef,
    make_compaction_id,
    make_idempotency_key,
    make_request_fingerprint,
)
from autoforge_execution.token_estimator import TokenEstimator, estimate_tokens

logger = logging.getLogger("autoforge.execution.compaction")

#: Source kind for compacted iteration items (Gate 2 §10). Reuses the existing
#: ``ContextSource`` convention rather than inventing an identity system.
ITERATION_SOURCE_KIND = "iteration"


class DurableReferenceResolver(Protocol):
    """Read-only lookup from a logical source ref to a durable artifact ref.

    Implemented at the composition root over the existing
    ``DurableArtifactCatalog`` (Gate 2 §8, §12). Optional: when absent, the
    compactor still runs, it simply records the reference as unresolvable rather
    than fabricating content (Gate 3 §23).
    """

    def resolve(self, source_ref: str) -> DurableRef | None:
        ...


# ── Iteration projection (Gate 2 §10 — the G-1 fix) ─────────────────────


def _authority_marker(evaluation: Any) -> str:
    """Report the *authority* of an evaluation, never a model's opinion of it.

    Gate 3 §12: an outcome the repository verified is stated as observed; nothing
    is upgraded to "verified" because a model said so. ``EvaluationResult``
    already guarantees "Deterministic checks ALWAYS take precedence over model
    confidence" (Gate 2 E-12), and this preserves that distinction rather than
    collapsing it.
    """
    if evaluation is None:
        return "no_evaluation"
    status = getattr(evaluation, "status", None)
    value = getattr(status, "value", status)
    checks = getattr(evaluation, "deterministic_checks", None) or []
    if checks:
        return f"observed_by_deterministic_checks:{value}"
    return f"observed:{value}"


def project_iteration(record: Any, *, is_latest: bool) -> ContextItem:
    """Project one ``LoopIterationRecord`` into a compact ``ContextItem``.

    Deterministic: identical input always yields an identical item (and therefore
    an identical ``context_id``, because ``ContextItem`` derives it from content).

    The projection answers, for the next operation, what Gate 2 §10 requires:
    what was attempted, what happened, what was learned, what changed, and what
    remains unresolved — as *structure*, not prose.
    """
    evaluation = getattr(record, "evaluation", None)
    diagnosis = getattr(record, "diagnosis", None)
    changed = list(getattr(record, "changed_files", None) or [])
    failures = list(getattr(evaluation, "failures", None) or []) if evaluation else []
    passed = bool(getattr(record, "passed", False))

    lines = [
        f"iteration: {record.iteration}",
        f"action_plan: {getattr(record, 'action_plan', '') or ''}",
        f"changed_files: {', '.join(changed) if changed else 'none'}",
        f"result: {'passed' if passed else 'failed'}",
        f"authority: {_authority_marker(evaluation)}",
    ]
    if failures:
        lines.append("observed_failures: " + "; ".join(failures))
    if diagnosis is not None:
        # A diagnosis is a *proposed* cause, not a verified one (Gate 3 §12).
        lines.append(f"proposed_root_cause: {getattr(diagnosis, 'root_cause', '')}")
        lines.append(
            f"proposed_correction: {getattr(diagnosis, 'suggested_fix', '')}"
        )
    lines.append(
        "status: current" if is_latest else f"status: superseded by iter-{record.iteration + 1}"
    )

    return ContextItem(
        content="\n".join(lines),
        category=(
            ContextCategory.VERIFICATION if not passed else ContextCategory.EXECUTION
        ),
        source=ContextSource(ITERATION_SOURCE_KIND, f"iter-{record.iteration}"),
        # Only the newest iteration is mandatory: it carries the active failure the
        # next operation must act on. Older ones are optional, so MSC can still
        # exclude them under budget pressure (Gate 2 §6, §21).
        required=is_latest,
        required_for=("iteration_continuity",) if is_latest else (),
        relevance=1.0 if is_latest else 0.4,
        provenance=ContextProvenance(
            acquired_from="engineering_loop",
            source_ref=f"iter-{record.iteration}",
            provider="deterministic",
            acquired_at=datetime.now(timezone.utc).isoformat(),
            inferred=False,
        ),
    )


def link_iteration_chain(items: Sequence[ContextItem]) -> None:
    """Link each iteration item to its predecessor (Gate 2 §10, §11).

    ``depends_on`` is an existing ``ContextItem`` field, so the causal chain uses
    the established identity and dependency machinery rather than a parallel one.
    """
    ordered = sorted(
        (i for i in items if i.source.kind == ITERATION_SOURCE_KIND),
        key=lambda i: int(i.source.ref.split("-", 1)[-1]),
    )
    for previous, current in zip(ordered, ordered[1:]):
        current.depends_on = (previous.context_id,)
        # A dependency pulled in by an explicit link is required for the chain to
        # make sense, mirroring expand_dependencies' treatment (Gate 2 E-7).
        if current.required:
            previous.required = True


# ── The deterministic compactor (Gate 2 §8 lifecycle) ───────────────────


class ContextCompactor:
    """Deterministic, provider-neutral context compaction.

    Implements the Gate 2 §8 lifecycle for the deterministic path only. The
    caller (Context Engineering) decides *when* to invoke this — compaction is a
    pre-selection stage, so ``select_context`` remains the single owner of
    ranking, budgeting and mandatory admission (Gate 2 §21).
    """

    def __init__(
        self,
        policy: CompactionPolicy | None = None,
        *,
        resolver: DurableReferenceResolver | None = None,
        estimator: TokenEstimator | None = None,
    ) -> None:
        self.policy = policy or CompactionPolicy()
        self.resolver = resolver
        self.estimator = estimator

    @property
    def enabled(self) -> bool:
        return bool(self.policy.enabled)

    def compaction_candidates(
        self, prior_iterations: Sequence[Any] | None
    ) -> list[ContextItem]:
        """Project the iterations outside the retention window.

        Recent iterations stay inline because the builder already receives them
        through the canonical path; only superseded ones are compacted (Gate 2 §7).
        """
        records = list(prior_iterations or [])
        total = len(records)
        retain = self.policy.iterations_to_retain(total)
        older = records[: max(0, total - retain)]
        latest_index = total - 1
        return [
            project_iteration(record, is_latest=(index == latest_index))
            for index, record in enumerate(older, start=1)
        ]

    def _resolve_refs(self, items: Sequence[ContextItem]) -> list[DurableRef]:
        """Resolve a durable reference per compacted iteration (Gate 2 §8).

        A reference that cannot be resolved is **not** replaced by fabricated
        content (Gate 3 §23); the item carries no ref and validation marks the
        record ``partial_unresolvable``.
        """
        refs: list[DurableRef] = []
        if self.resolver is None:
            return refs
        for item in items:
            if item.source.kind != ITERATION_SOURCE_KIND:
                continue
            try:
                ref = self.resolver.resolve(item.source.ref)
            except Exception as exc:  # noqa: BLE001 - a hint must never break compaction
                logger.debug(
                    "reference resolution failed for %s: %s", item.source.ref, exc
                )
                ref = None
            if ref is not None:
                refs.append(ref)
        return refs


    def compact(
        self,
        *,
        task_id: str,
        prior_iterations: Sequence[Any] | None = None,
        existing_items: Sequence[ContextItem] | None = None,
        execution_id: str | None = None,
        workflow_id: str | None = None,
        correlation_id: str | None = None,
        trigger: str = "iteration_boundary",
        supersedes: str | None = None,
        logical_version: int = 1,
    ) -> CompactedContextRecord:
        """Produce a compact record for the given accumulated history."""
        started = time.perf_counter()
        source_iterations = list(prior_iterations or [])

        # GATHER -> EXTRACT
        candidates = self.compaction_candidates(source_iterations)
        link_iteration_chain(candidates)

        # Irreplaceable material is carried through untouched (Gate 2 §6): never
        # summarised, never referenced away, never dropped.
        candidates.extend(existing_items or [])
        link_iteration_chain(candidates)

        # RESOLVE
        refs = self._resolve_refs(candidates)

        # Identity (Gate 2 §19): content/policy-derived, so retries are idempotent.
        #
        # Gate 4 fix: the logical SCOPE is part of the fingerprint. The scope
        # (source_scope + task_id + execution_id) is part of the
        # ``idempotency_key`` already, so omitting it from the fingerprint let two
        # different tasks whose iteration numbering happened to match derive the
        # same ``compaction_id`` — and because the durable artifact name is
        # derived from that id, their records would collide in the catalog.
        source_scope = "prior_iterations"
        idempotency_key = make_idempotency_key(source_scope, task_id, execution_id)
        source_ids = [
            f"iter-{getattr(r, 'iteration', i)}"
            for i, r in enumerate(source_iterations, 1)
        ] + [i.context_id for i in (existing_items or [])]
        fingerprint = make_request_fingerprint(
            source_ids,
            [r.content_hash for r in refs],
            self.policy.policy_version,
            scope=idempotency_key,
        )
        compaction_id = make_compaction_id(source_scope, fingerprint)

        # Cost accounting through the existing estimator seam (Gate 2 E-8).
        source_tokens = sum(
            estimate_tokens(r.model_dump_json(indent=2), self.estimator)
            for r in source_iterations
            if hasattr(r, "model_dump_json")
        )
        record_tokens = sum(
            estimate_tokens(i.content, self.estimator) for i in candidates
        )

        record = CompactedContextRecord(
            compaction_id=compaction_id,
            idempotency_key=make_idempotency_key(
                "prior_iterations", task_id, execution_id
            ),
            request_fingerprint=fingerprint,
            task_id=task_id,
            source_scope="prior_iterations",
            execution_id=execution_id,
            workflow_id=workflow_id,
            correlation_id=correlation_id,
            policy_version=self.policy.policy_version,
            logical_version=logical_version,
            supersedes=supersedes,
            items=candidates,
            durable_refs=refs,
            preservation_breakdown=classify_items(candidates),
            compaction_method=CompactionMethod.DETERMINISTIC.value,
            provenance=CompactionProvenance(
                acquired_from="engineering_loop",
                source_ref="prior_iterations",
                provider="deterministic",
                acquired_at=datetime.now(timezone.utc).isoformat(),
                inferred=False,
                source_context_ids=tuple(source_ids),
                source_artifact_refs=tuple(r.artifact_id for r in refs),
                compaction_method=CompactionMethod.DETERMINISTIC.value,
                policy_version=self.policy.policy_version,
            ),
            trigger=trigger,
            estimated_tokens=record_tokens,
            source_estimated_tokens=source_tokens or record_tokens,
        )
        record.duration_ms = (time.perf_counter() - started) * 1000.0
        return record

    def assembly_record(
        self,
        record: CompactedContextRecord,
        *,
        source_item_count: int,
    ) -> CompactionAssemblyRecord:
        """Build the content-free observability record (Gate 2 §25)."""
        return CompactionAssemblyRecord(
            compaction_id=record.compaction_id,
            task_id=record.task_id,
            source_scope=record.source_scope,
            trigger=record.trigger,
            policy_version=record.policy_version,
            compaction_method=record.compaction_method,
            source_item_count=source_item_count,
            retained_item_count=record.item_count,
            compacted_item_count=max(0, source_item_count - record.item_count),
            reference_count=record.reference_count,
            source_estimated_tokens=record.source_estimated_tokens,
            estimated_tokens=record.estimated_tokens,
            reduction_ratio=record.reduction_ratio,
            reconstructability=record.reconstructability,
            preservation_breakdown=dict(record.preservation_breakdown),
            loss_classification=record.loss_classification,
            completeness=record.completeness,
            validation_status=record.validation_status,
            validation_reasons=list(record.validation_reasons),
            duration_ms=record.duration_ms,
        )


__all__ = [
    "ITERATION_SOURCE_KIND",
    "ContextCompactor",
    "DurableReferenceResolver",
    "link_iteration_chain",
    "project_iteration",
]
