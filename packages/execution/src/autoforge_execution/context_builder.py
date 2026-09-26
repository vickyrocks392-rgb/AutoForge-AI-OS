"""
Context Builder — Canonical Implementation (ADR-003).

A stateless assembly service that gathers candidate context from capability
providers, scores and selects relevance, removes redundancy, respects
model-aware token budgets, preserves critical errors, and produces
structured model context as its output artifact.

Context Engineering rollout (18-L Gate 3, globally enabled at Gate 4B): the full
Minimum-Sufficient-Context pipeline is gated behind ``enable_context_engineering``,
which now defaults to **True**.

Gate 4B made Context Engineering the canonical default behaviour of AutoForge
production execution, so the constructor default flipped from False to True. A
directly constructed builder therefore runs the MSC pipeline, exactly like the
one the composition root builds.

The flag remains available and is NOT deleted: ``enable_context_engineering=False``
is the supported **rollback / compatibility mode** for controlled rollback and
for tests that must pin the pre-Gate-3 additive behaviour. With the flag off this
class behaves exactly as it did before Gate 3 — additive assembly, identical
signature, identical return type — so rollback is a single constructor argument
and requires no data migration, state change, or redeploy.
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from autoforge_workflows.models import TaskDefinition
from autoforge_execution.context import ExecutionContext
from autoforge_execution.context_budget import (
    CONSERVATIVE_DEFAULT_OUTPUT_RESERVE_TOKENS,
    CONSERVATIVE_DEFAULT_WINDOW_TOKENS,
    BudgetSource,
    ContextWindowBudget,
    ModelAllocationPort,
    ModelWindow,
)
from autoforge_execution.context_items import (
    ContextCategory,
    ContextCacheability,
    ContextItem,
    ContextProvenance,
    ContextSource,
)
from autoforge_execution.context_observability import (
    ContextAssemblyRecord,
    build_record,
)
from autoforge_execution.context_selection import (
    SelectionPolicy,
    assign_token_costs,
    select_context,
)
from autoforge_execution.errors import MissingProvenanceError
from autoforge_execution.models import DiagnosisReport, EvaluationResult, LoopIterationRecord
from autoforge_execution.token_estimator import TokenEstimator

logger = logging.getLogger("autoforge.execution.context_builder")


def _optional_id(value: Any) -> str | None:
    """Return a string id, or ``None`` when absent/unusable.

    Gate 3: the execution id is optional on ``ExecutionContext`` (it lives in
    model requirements metadata, Gate 2 E-16), so identity is read defensively
    rather than assumed.
    """
    if value is None:
        return None
    text = str(value).strip()
    return text or None


class EngineeringContextBuilder:
    """
    Stateless Context Assembly Service compliant with ADR-003.
    Composes Knowledge, Memory, Workspace, Git, and Failure Evidence into
    structured ExecutionContext without becoming a second storage authority.
    """

    def __init__(
        self,
        default_max_context_chars: int = 16000,
        runtime: Any = None,
        memory_engine: Any = None,
        knowledge_engine: Any = None,
        *,
        # Gate 4B: Context Engineering is the canonical production default, so the
        # default is True. Passing False remains the supported rollback /
        # compatibility mode (single-argument rollback, no migration).
        enable_context_engineering: bool = True,
        selection_policy: SelectionPolicy | None = None,
        model_allocator: ModelAllocationPort | None = None,
        token_estimator: TokenEstimator | None = None,
        # ── Gate 3: Context Compaction ────────────────────────────────────
        # Additive, optional, and OFF by default (Gate 3 §29/§30). Context
        # Engineering remains globally ON; this is an independent, separately
        # reversible capability. ``None`` means compaction is not wired at all,
        # which keeps the pre-Gate-3 behaviour byte-for-byte.
        compactor: Any | None = None,
        # ── C-1: production durable store for compact records ──────────────
        # Injected by the composition root over the SAME DurableArtifactCatalog
        # and PhysicalArtifactStore the rest of the system uses. It is additive
        # and independent of ``compactor``: holding a store does not enable
        # compaction. Persistence only ever happens on a record that already
        # passed validation, and a persistence failure is contained (it must
        # never fail engineering work — Gate 3 §23).
        compaction_store: Any | None = None,
    ) -> None:
        self.default_max_context_chars = default_max_context_chars
        self.runtime = runtime
        self.memory_engine = memory_engine
        self.knowledge_engine = knowledge_engine
        # Gate 3: the compactor and the most recent compact record, for
        # observability. Both stay None until compaction actually runs.
        self.compactor = compactor
        self.last_compaction_record: Any | None = None
        # C-1: the production durable store for compact records, plus the
        # artifact id of the most recent successful persist (observability).
        self.compaction_store = compaction_store
        self.last_compaction_artifact_id: Optional[str] = None
        # Gate 3 rollout boundary, flipped to the canonical default at Gate 4B.
        # Explicit False is still honoured and is the rollback path.
        self.enable_context_engineering = bool(enable_context_engineering)
        self.selection_policy = selection_policy or SelectionPolicy()
        # Gate 4 §7: optional Pass-1/Pass-2 seam over the existing Model Router.
        # Absent it, budgeting falls back to the conservative default and says so
        # on the observability record. It is a Protocol, so no runtime, provider
        # or router class is imported by the Context Engineering layer.
        self.model_allocator = model_allocator
        # Gate 4: injectable estimator; defaults to the conservative heuristic.
        self.token_estimator = token_estimator

    async def assemble_context(
        self,
        task_def: TaskDefinition,
        workspace_root: Path,
        *,
        workflow_id: Optional[uuid.UUID] = None,
        project_id: Optional[uuid.UUID] = None,
        correlation_id: Optional[uuid.UUID] = None,
        attempt_number: int = 1,
        memory_engine: Any = None,
        knowledge_engine: Any = None,
        rag_engine: Any = None,
        prior_iterations: Optional[List[LoopIterationRecord]] = None,
        last_evaluation: Optional[EvaluationResult] = None,
        last_diagnosis: Optional[DiagnosisReport] = None,
        effective_model_requirements: Optional[Dict[str, Any]] = None,
        # --- Context Engineering (18-L Gate 3) -----------------------------
        # All optional and defaulted, so existing call sites are unchanged.
        stage: str = "",
        context_window_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        model_id: Optional[str] = None,
    ) -> ExecutionContext:
        """
        Assemble rich task-specific engineering context from all canonical sources.
        """
        # 1. Base Context initialization
        context = ExecutionContext.from_task_definition(
            task_def=task_def,
            workspace_root=workspace_root,
            workflow_id=workflow_id,
            project_id=project_id,
            correlation_id=correlation_id,
            attempt_number=attempt_number,
            effective_model_requirements=effective_model_requirements,
        )

        # 2. Workspace Filesystem scanning
        #
        # 18-L C-3 — boundary isolation. Context Compaction persists its durable
        # records under `<workspace>/artifacts`, the same tree this scan walks.
        # Those records are compaction's own bookkeeping, not engineering inputs,
        # so they must not re-enter the canonical candidate-discovery path and
        # perturb the candidate set (and therefore the compaction fingerprint)
        # between iterations.
        #
        # The exclusion is deliberately the narrowest possible: a single filename
        # predicate, evaluated at *eligibility* time. Ordinary engineering
        # artifacts stored in the same directory — and the directory itself — are
        # untouched, and nothing downstream (ranking, budgeting, prompt assembly)
        # changes. The predicate is imported from the module that defines the
        # naming, so writer and reader cannot drift.
        #
        # Imported outside the try below on purpose: an import failure must be
        # loud rather than silently emptying the file inventory.
        from autoforge_execution.compaction.storage import (
            is_compaction_bookkeeping_artifact,
        )

        if workspace_root.exists():
            try:
                # Discover existing files (excluding temp/venv/git caches)
                discovered_files = []
                for p in workspace_root.rglob("*"):
                    if not p.is_file():
                        continue
                    if any(
                        part.startswith((".", "__pycache__", "venv"))
                        for part in p.parts
                    ):
                        continue
                    if is_compaction_bookkeeping_artifact(p.name):
                        continue
                    rel = str(p.relative_to(workspace_root))
                    discovered_files.append(rel)
                context.project_files = discovered_files[:50]  # Cap file inventory
            except Exception as ex:
                logger.debug(f"Workspace file scan error: {ex}")

        # 3. Retrieve Relevant Project Memory (if memory engine provided)
        mem_eng = memory_engine or self.memory_engine
        if mem_eng and hasattr(mem_eng, "retrieve_memory"):
            try:
                query = f"{task_def.name} {task_def.task_type}"
                memories = await mem_eng.retrieve_memory(query, limit=5)
                if memories:
                    context.metadata["relevant_memories"] = memories
            except Exception as ex:
                logger.debug(f"Memory retrieval non-fatal error: {ex}")

        # 4. Retrieve Domain Knowledge / RAG Evidence (if available)
        retrieved_hits: list[dict[str, Any]] = []
        kn_eng = knowledge_engine or self.knowledge_engine
        if rag_engine and hasattr(rag_engine, "retrieve"):
            try:
                query = f"{task_def.name} {task_def.description}"
                hits = await rag_engine.retrieve(query, limit=3)
                for h in hits:
                    retrieved_hits.append(
                        h if isinstance(h, dict) else (h.model_dump() if hasattr(h, "model_dump") else {"content": str(h)})
                    )
            except Exception as ex:
                logger.debug(f"RAG retrieval non-fatal error: {ex}")
        elif kn_eng and hasattr(kn_eng, "query"):
            try:
                k_items = await kn_eng.query(task_def.name, filters=None)
                for ki in k_items[:3]:
                    retrieved_hits.append(ki if isinstance(ki, dict) else {"content": str(ki)})
            except Exception as ex:
                logger.debug(f"Knowledge query non-fatal error: {ex}")

        if retrieved_hits:
            context.retrieved_knowledge = retrieved_hits

        # 5. History and Failure Evidence Preservation (ADR-003: critical errors never dropped)
        if prior_iterations:
            context.prior_iterations = list(prior_iterations)
        if last_evaluation:
            context.last_evaluation = last_evaluation
        if last_diagnosis:
            context.last_diagnosis = last_diagnosis

        if self.enable_context_engineering:
            self._apply_context_engineering(
                context,
                task_def,
                stage=stage,
                correlation_id=correlation_id,
                attempt_number=attempt_number,
                context_window_tokens=context_window_tokens,
                max_output_tokens=max_output_tokens,
                model_id=model_id,
            )

        return context

    # -- Context Engineering (18-L Gate 3) -----------------------------------
    # The following is used only when ``enable_context_engineering`` is True.

    def _build_candidates(
        self,
        context: ExecutionContext,
        task_def: TaskDefinition,
    ) -> list[ContextItem]:
        """Convert gathered sources into attributable, governable context items.

        Mandatory sources are the whitelist from Gate 2 section 2.2: the task
        objective, prior failure evidence, and orchestrator-attached knowledge.
        Everything else is optional.

        Gate 4 fix (D1): items now carry real ``depends_on`` edges and real
        provenance. At Gate 3 the builder emitted *no* edges, which made
        ``expand_dependencies`` unreachable dead code on the canonical path, so
        dependency expansion, cycle handling and the bound were never exercised
        in production. The edges below are the defensible ones for the sources
        this builder actually gathers: a diagnosis explains observed failures, so
        it depends on them, and both are mandatory, so expansion cannot silently
        drop either.
        """
        candidates: list[ContextItem] = []
        gathered_from = "engineering_context_builder"

        task_item = ContextItem(
            content=(
                f"Task: {task_def.name}\n"
                f"Type: {task_def.task_type}\n"
                f"Description: {task_def.description}"
            ),
            category=ContextCategory.TASK,
            source=ContextSource("task", task_def.task_id),
            required=True,
            required_for=("task_objective",),
            relevance=1.0,
            cacheability=ContextCacheability.TASK_DYNAMIC,
            provenance=ContextProvenance(
                acquired_from="task_definition",
                source_ref=task_def.task_id,
                provider="workflow_engine",
                inferred=False,
            ),
        )
        candidates.append(task_item)

        if context.project_files:
            candidates.append(
                ContextItem(
                    content="Workspace files:\n" + "\n".join(context.project_files),
                    category=ContextCategory.PROJECT,
                    source=ContextSource("workspace", str(context.workspace_root)),
                    required=False,
                    required_for=("project_awareness",),
                    relevance=0.5,
                    cacheability=ContextCacheability.TASK_DYNAMIC,
                    provenance=ContextProvenance(
                        acquired_from="workspace_filesystem",
                        source_ref=str(context.workspace_root),
                        provider="workspace",
                        inferred=False,
                    ),
                )
            )

        diagnosis_item: ContextItem | None = None
        evaluation_item: ContextItem | None = None

        if context.last_diagnosis is not None:
            d = context.last_diagnosis
            diagnosis_item = ContextItem(
                content=(
                    f"Root cause: {d.root_cause}\n"
                    f"Mechanism: {d.failure_mechanism}\n"
                    f"Affected: {d.affected_files}\n"
                    f"Suggested fix: {d.suggested_fix}"
                ),
                category=ContextCategory.VERIFICATION,
                source=ContextSource("diagnosis", str(context.attempt_number)),
                required=True,
                required_for=("verification_evidence", "prior_failure"),
                relevance=1.0,
                cacheability=ContextCacheability.VOLATILE,
                provenance=ContextProvenance(
                    acquired_from="verification_diagnosis",
                    source_ref=f"attempt-{context.attempt_number}",
                    provider=gathered_from,
                    inferred=False,
                ),
            )

        if context.last_evaluation is not None:
            evaluation_item = ContextItem(
                content=f"Evaluation failures: {context.last_evaluation.failures}",
                category=ContextCategory.VERIFICATION,
                source=ContextSource("evaluation", str(context.attempt_number)),
                required=True,
                required_for=("verification_evidence",),
                relevance=1.0,
                cacheability=ContextCacheability.VOLATILE,
                provenance=ContextProvenance(
                    acquired_from="verification_evaluation",
                    source_ref=f"attempt-{context.attempt_number}",
                    provider=gathered_from,
                    inferred=False,
                ),
            )

        # Gate 4 (D1): a diagnosis explains observed failures, so it depends on
        # them. Both are mandatory, so expansion cannot silently drop either.
        if diagnosis_item is not None and evaluation_item is not None:
            diagnosis_item.depends_on = (evaluation_item.context_id,)
        if evaluation_item is not None:
            candidates.append(evaluation_item)
        if diagnosis_item is not None:
            candidates.append(diagnosis_item)

        for index, hit in enumerate(context.retrieved_knowledge or []):
            content = hit.get("content") if isinstance(hit, dict) else str(hit)
            if not content:
                continue
            score = 0.0
            if isinstance(hit, dict):
                try:
                    score = float(hit.get("score", 0.0))
                except (TypeError, ValueError):
                    score = 0.0
            candidates.append(
                ContextItem(
                    content=str(content),
                    category=ContextCategory.EVIDENCE,
                    source=ContextSource("knowledge", f"hit-{index}"),
                    required=False,
                    required_for=("task_evidence",),
                    relevance=max(0.0, min(1.0, score)),
                    cacheability=ContextCacheability.TASK_DYNAMIC,
                    provenance=ContextProvenance(
                        acquired_from="knowledge_retrieval",
                        source_ref=f"hit-{index}",
                        provider=(
                            str(hit.get("source") or "rag_engine")
                            if isinstance(hit, dict)
                            else "rag_engine"
                        ),
                        inferred=not isinstance(hit, dict),
                    ),
                )
            )

        # ── Gate 3: Context Compaction (pre-selection stage) ───────────────
        # This is the SINGLE integration point (Gate 2 §21): compaction runs
        # here, *after* live task/workspace/knowledge/verification items are
        # built and *before* select_context. Therefore select_context remains
        # the only ranker, ContextWindowBudget the only budgeter, and
        # prompt_assembly the only prompt builder. Compaction emits ordinary
        # ContextItems, so none of those layers need to change.
        #
        # Compaction is OFF by default (Gate 3 §29/§30). When disabled — or when
        # no compactor is injected — this is a no-op and behaviour is byte-for-byte
        # the pre-Gate-3 path.
        compaction_record = None
        if self.compactor is not None and self.compactor.enabled:
            try:
                compaction_record = self._apply_compaction(
                    candidates,
                    context=context,
                    task_def=task_def,
                )
                if compaction_record is not None:
                    candidates = compaction_record.items
            except Exception as exc:  # noqa: BLE001 - compaction is fail-safe
                # Gate 3 §23: compaction failure must never fail engineering work.
                # The uncompacted candidates are used unchanged.
                logger.warning(
                    "context compaction failed; continuing with uncompacted "
                    "candidates: %s",
                    exc,
                )
                compaction_record = None

        # Gate 4 (D3): every mandatory item must be attributable (ADR-003 §6).
        # Gate 3 defined MissingProvenanceError but never raised it, so mandatory
        # context silently shipped with inferred-only provenance. Enforce it here.
        for item in candidates:
            if not item.required:
                continue
            provenance = item.provenance
            if provenance is None or not provenance.acquired_from:
                raise MissingProvenanceError(
                    "mandatory context item has no attributable provenance",
                    details={
                        "context_id": item.context_id,
                        "category": item.category.value,
                        "source_kind": item.source.kind,
                    },
                )

        return candidates

    def _apply_compaction(
        self,
        candidates: List[ContextItem],
        *,
        context: ExecutionContext,
        task_def: TaskDefinition,
    ) -> Any:
        """Run deterministic compaction over the candidate pool.

        Returns the compact record, or ``None`` when the policy does not trigger,
        in which case the caller keeps the original candidates untouched.

        Trigger evaluation is deterministic: it reads only the history already on
        the ``ExecutionContext`` plus the live candidate count — never a model and
        never a wall clock (Gate 2 §16).
        """
        prior_iterations = list(getattr(context, "prior_iterations", None) or [])
        should, trigger = self.compactor.policy.should_compact(
            iteration_count=len(prior_iterations),
            candidate_count=len(candidates),
            remaining_budget_tokens=None,
        )
        if not should:
            return None

        record = self.compactor.compact(
            task_id=context.task_id,
            prior_iterations=prior_iterations,
            existing_items=list(candidates),
            # ExecutionContext carries workflow/project/correlation identity; the
            # execution id (when present) rides in effective_model_requirements
            # metadata, so it is read defensively rather than assumed.
            execution_id=_optional_id(
                context.effective_model_requirements.get("execution_id")
            ),
            workflow_id=(
                str(context.workflow_id) if context.workflow_id else None
            ),
            correlation_id=(
                str(context.correlation_id) if context.correlation_id else None
            ),
            trigger=trigger or "iteration_boundary",
        )

        # Validation is the only promotion gate (Gate 2 §8 step 10). An invalid
        # record is rejected and the uncompacted candidates are used.
        from autoforge_execution.compaction.compaction_validation import (
            apply_validation,
        )

        if not apply_validation(record, policy=self.compactor.policy):
            logger.info(
                "context compaction record %s rejected (%s); keeping uncompacted "
                "candidates",
                record.compaction_id,
                ",".join(record.validation_reasons) or "unknown",
            )
            return None

        self.last_compaction_record = record

        # C-1: persist the VALIDATED record through the production store.
        #
        # This runs only after `apply_validation` has promoted the record, so an
        # invalid record is never written. The store is the existing
        # `CompactionRecordStore` over the canonical artifact substrate — no new
        # storage architecture, no duplicated persistence logic, and 18-J's
        # idempotent-replay contract decides retries (identical content reuses the
        # artifact; different content raises ArtifactConflictError).
        #
        # Containment is deliberate: a durability problem must never fail
        # engineering work (Gate 3 §23). The in-memory record stays usable and
        # the next iteration re-derives.
        if self.compaction_store is not None:
            try:
                artifact_id = self.compaction_store.save(record)
                self.last_compaction_artifact_id = (
                    str(artifact_id) if artifact_id is not None else None
                )
                logger.info(
                    "context compaction record %s persisted as artifact %s",
                    record.compaction_id,
                    self.last_compaction_artifact_id,
                )
            except Exception as exc:  # noqa: BLE001 - durability must not fail work
                logger.warning(
                    "context compaction record %s could not be persisted (%s); "
                    "continuing with the in-memory record",
                    record.compaction_id,
                    exc,
                )

        logger.info(
            "context compaction complete: id=%s history=%d items=%d refs=%d "
            "reduction=%.3f trigger=%s duration_ms=%.2f",
            record.compaction_id,
            len(prior_iterations),
            record.item_count,
            record.reference_count,
            record.reduction_ratio,
            record.trigger,
            record.duration_ms,
        )
        return record

    def _resolve_budget(
        self,
        *,
        context_window_tokens: Optional[int],
        max_output_tokens: Optional[int],
        model_id: Optional[str],
        candidates: list[ContextItem],
        requirements: Optional[Dict[str, Any]] = None,
    ) -> ContextWindowBudget:
        """Two-pass window resolution (Gate 2 §1.4, verified Gate 4 §7).

        Pass 1 declares the window this operation genuinely needs from the
        candidate set. Model allocation then runs against that declaration, and
        Pass 2 applies the window the *allocated model* actually guarantees.

        Gate 4 fix (D2): at Gate 3 this method could only ever return
        ``CALLER`` or ``CONSERVATIVE_DEFAULT`` — ``MODEL_METADATA`` was dead. It
        never consulted the Model Router, so "model-aware budgeting" was a
        documented intention rather than behaviour. The injected
        :class:`ModelAllocationPort` closes that gap without introducing a
        dependency on any runtime: Context Engineering still never sees
        llama.cpp, MLX, or a provider, only the window the chosen model promises.

        Precedence is explicit and observable:
        caller window -> allocated model metadata -> conservative default.
        """
        assign_token_costs(candidates, self.token_estimator)
        declared = (
            sum(item.estimated_tokens for item in candidates)
            + CONSERVATIVE_DEFAULT_OUTPUT_RESERVE_TOKENS
        )

        if context_window_tokens and context_window_tokens > 0:
            source = BudgetSource.CALLER
            window = int(context_window_tokens)
        else:
            # Pass 1 -> allocate -> Pass 2.
            window = 0
            allocated: Optional[ModelWindow] = None
            if self.model_allocator is not None:
                try:
                    allocated = self.model_allocator.allocate_model_window(
                        min_context_window_tokens=declared,
                        model_id=model_id or None,
                        requirements=requirements or {},
                    )
                except Exception as exc:  # noqa: BLE001 - allocation must not mask
                    # a genuine budget failure with an allocator bug; the
                    # conservative default below is the documented fallback.
                    logger.warning(
                        "model allocation for context budgeting failed: %s", exc
                    )
                    allocated = None

            if allocated is not None and allocated.context_window_tokens > 0:
                source = BudgetSource.MODEL_METADATA
                window = int(allocated.context_window_tokens)
                # The allocated model wins over a bare model_id hint.
                model_id = allocated.model_id or model_id
                if not max_output_tokens and allocated.max_output_tokens:
                    max_output_tokens = int(allocated.max_output_tokens)
            else:
                source = BudgetSource.CONSERVATIVE_DEFAULT
                window = CONSERVATIVE_DEFAULT_WINDOW_TOKENS

        reserve = (
            int(max_output_tokens)
            if max_output_tokens and max_output_tokens > 0
            else CONSERVATIVE_DEFAULT_OUTPUT_RESERVE_TOKENS
        )
        if reserve >= window:
            reserve = window // 4

        return ContextWindowBudget(
            model_context_window_tokens=window,
            reserved_for_output_tokens=reserve,
            budget_source=source,
            model_id=model_id or "",
            declared_required_window_tokens=declared,
        )

    def _apply_context_engineering(
        self,
        context: ExecutionContext,
        task_def: TaskDefinition,
        *,
        stage: str,
        correlation_id: Optional[uuid.UUID],
        attempt_number: int,
        context_window_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        model_id: Optional[str] = None,
    ) -> None:
        """Run the MSC pipeline and attach the structured result to ``context``."""
        started = time.perf_counter()
        candidates = self._build_candidates(context, task_def)
        budget = self._resolve_budget(
            context_window_tokens=context_window_tokens,
            max_output_tokens=max_output_tokens,
            model_id=model_id,
            candidates=candidates,
            # The task's own model requirements are the Pass-1 routing input, so
            # the allocator can honour a preference the caller already declared.
            requirements=context.effective_model_requirements or {},
        )

        result = select_context(candidates, budget, self.selection_policy)
        duration_ms = (time.perf_counter() - started) * 1000.0

        record: ContextAssemblyRecord = build_record(
            task_id=context.task_id,
            stage=stage,
            correlation_id=str(correlation_id or ""),
            attempt_number=attempt_number,
            budget=budget,
            selected=result.selected,
            excluded=result.excluded,
            considered_count=result.considered_count,
            deduplicated_count=result.deduplicated_count,
            expansion_depth_reached=result.expansion_depth_reached,
            expansion_items_added=result.expansion_items_added,
            expansion_truncated_by_bound=result.expansion_truncated_by_bound,
            construction_duration_ms=duration_ms,
        )

        # Attach the attributable selection. Existing fields are left intact so any
        # current consumer keeps working unchanged.
        context.selected_context_items = result.selected
        context.excluded_context_items = list(result.excluded)
        context.context_assembly_record = record

        # The record is content-free, so logging it is safe by construction.
        logger.info(
            "context assembly complete: selected=%d excluded=%d mandatory_tokens=%d "
            "optional_tokens=%d window=%d source=%s duration_ms=%.2f",
            record.selected_count,
            record.excluded_count,
            record.mandatory_tokens,
            record.optional_tokens,
            record.context_window_tokens,
            record.budget_source,
            record.construction_duration_ms,
        )

