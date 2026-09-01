"""Phase 18-E — RAG-Integrated Failure Diagnoser."""
from __future__ import annotations
import logging
from typing import Any, Protocol, runtime_checkable

from autoforge_execution.context import ExecutionContext
from autoforge_execution.diagnosis import FailureDiagnoser
from autoforge_execution.models import (
    CommandResult, DiagnosisReport, EvaluationResult,
)
from autoforge_execution_18e.confidence_models import DiagnosisEvidence
from autoforge_execution_18e.confidence import DiagnosisConfidenceCalculator

logger = logging.getLogger(__name__)


@runtime_checkable
class KnowledgeRAGEngineProtocol(Protocol):
    """Protocol matching the 18-D KnowledgeRAGEngine interface."""
    async def retrieve_for_context(
        self, query: str, *,
        project_id=None, workflow_id=None, execution_id=None,
        workspace_root=None, top_k=None, score_threshold=None,
    ) -> Any:
        ...


class RAGIntegratedDiagnoser:
    """
    Wraps the existing FailureDiagnoser and augments it with scoped RAG
    retrieval from the 18-D KnowledgeRAGEngine (local Qdrant path).
    """

    def __init__(self, diagnoser, rag_engine=None, *, retrieval_query_fn=None,
                 score_threshold=None) -> None:
        self._diagnoser = diagnoser
        self._rag_engine = rag_engine
        self._retrieval_query_fn = retrieval_query_fn
        self._score_threshold = score_threshold
        self._retrieve_calls = 0

    @property
    def retrieve_calls(self) -> int:
        return self._retrieve_calls

    def _build_retrieval_query(self, evaluation, command_results, context):
        if self._retrieval_query_fn is not None:
            query = self._retrieval_query_fn(evaluation, command_results, context)
            if query and query.strip():
                return query
        parts = []
        if context.task_name:
            parts.append(context.task_name)
        if context.task_description:
            parts.append(context.task_description[:200])
        if evaluation.failures:
            parts.append(evaluation.failures[0][:200])
        return " ".join(parts) if parts else (context.task_name or "repair")

    async def diagnose_with_rag(self, context, evaluation, command_results):
        """Returns: (diagnosis_report, retrieved_knowledge, confidence)"""
        retrieved_knowledge = []
        rag_error = None

        if self._rag_engine is not None:
            try:
                query = self._build_retrieval_query(evaluation, command_results, context)
                scope_kwargs = {}
                if context.project_id:
                    scope_kwargs["project_id"] = context.project_id
                if context.workflow_id:
                    scope_kwargs["workflow_id"] = context.workflow_id
                if context.correlation_id:
                    scope_kwargs["execution_id"] = context.correlation_id
                if context.workspace_root:
                    scope_kwargs["workspace_root"] = str(context.workspace_root)

                result = await self._rag_engine.retrieve_for_context(
                    query=query, top_k=10,
                    score_threshold=self._score_threshold,
                    **scope_kwargs,
                )
                self._retrieve_calls += 1

                hits = getattr(result, "hits", None)
                if hits is None and hasattr(result, "results"):
                    hits = result.results
                if hits is None and isinstance(result, dict):
                    hits = result.get("hits", result.get("results", []))

                if hits:
                    retrieved_knowledge = [
                        hit.model_dump() if hasattr(hit, "model_dump") else
                        (dict(hit) if not isinstance(hit, dict) else hit)
                        for hit in hits
                    ]
            except Exception as e:
                rag_error = str(e)
                logger.warning(f"RAG retrieval failed: {e}")

        context.retrieved_knowledge = retrieved_knowledge if retrieved_knowledge else None

        evidence, _ = DiagnosisConfidenceCalculator.build_evidence_from_failure(
            command_results=command_results,
            evaluation=evaluation,
            diagnosis=None,
            retrieved_knowledge=retrieved_knowledge if retrieved_knowledge else None,
            project_files=context.project_files,
        )

        try:
            diagnosis = await self._diagnoser.diagnose(context, evaluation, command_results)
        except Exception as e:
            logger.error(f"Diagnosis failed: {e}")
            diagnosis = DiagnosisReport(
                root_cause=f"Diagnosis error: {str(e)[:200]}",
                failure_mechanism=f"Error during diagnosis: {e}",
                affected_files=context.project_files,
                suggested_fix="Manual investigation required",
                confidence_score=0.1,
            )

        evidence, confidence = DiagnosisConfidenceCalculator.build_evidence_from_failure(
            command_results=command_results,
            evaluation=evaluation,
            diagnosis=diagnosis,
            retrieved_knowledge=retrieved_knowledge if retrieved_knowledge else None,
            project_files=context.project_files,
        )

        return diagnosis, retrieved_knowledge, confidence

    async def diagnose(self, context, evaluation, command_results):
        diagnosis, _, _ = await self.diagnose_with_rag(context, evaluation, command_results)
        return diagnosis
