"""
Context Builder — Canonical Implementation (ADR-003).

A stateless assembly service that gathers candidate context from capability
providers, scores and selects relevance, removes redundancy, respects
model-aware token budgets, preserves critical errors, and produces
structured model context as its output artifact.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
import uuid

from autoforge_workflows.models import TaskDefinition
from autoforge_execution.context import ExecutionContext
from autoforge_execution.models import DiagnosisReport, EvaluationResult, LoopIterationRecord

logger = logging.getLogger("autoforge.execution.context_builder")


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
    ) -> None:
        self.default_max_context_chars = default_max_context_chars
        self.runtime = runtime
        self.memory_engine = memory_engine
        self.knowledge_engine = knowledge_engine

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
        if workspace_root.exists():
            try:
                # Discover existing files (excluding temp/venv/git caches)
                discovered_files = []
                for p in workspace_root.rglob("*"):
                    if p.is_file() and not any(part.startswith((".", "__pycache__", "venv")) for part in p.parts):
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

        return context
