"""Phase 18-E — Confidence Calculator (NOT statistical calibration)."""
from __future__ import annotations
from typing import Any

from autoforge_execution_18e.confidence_models import (
    ConfidenceEvidence, DiagnosisConfidence, DiagnosisEvidence, ConfidenceLevel,
)
from autoforge_execution.models import CommandResult, EvaluationResult, DiagnosisReport


class DiagnosisConfidenceCalculator:
    """Calculates confidence from evidence density. NOT statistical calibration."""

    EVIDENCE_WEIGHTS = {
        ConfidenceEvidence.ROOT_CAUSE_DETERMINED: 0.35,
        ConfidenceEvidence.AFFECTED_FILES: 0.20,
        ConfidenceEvidence.SUGGESTED_FIX: 0.20,
        ConfidenceEvidence.RAG_RETRIEVAL: 0.10,
        ConfidenceEvidence.RAG_SCORE_HIGH: 0.08,
        ConfidenceEvidence.TEST_FAILURES: 0.05,
        ConfidenceEvidence.ASSERTION_ERROR: 0.05,
        ConfidenceEvidence.FILE_CHANGES: 0.02,
        ConfidenceEvidence.FAILURE_STDERR: 0.03,
        ConfidenceEvidence.FAILURE_STDOUT: 0.03,
    }

    RAG_SCORE_THRESHOLD = 0.7

    @classmethod
    def calculate(cls, evidence):
        score = 0.0
        for ev_type in evidence.evidence_types:
            score += cls.EVIDENCE_WEIGHTS.get(ev_type, 0.0)
        if evidence.evidence_count >= 5:
            score += 0.05
        score = min(1.0, max(0.0, score))
        level = ConfidenceLevel.from_score(score)
        return DiagnosisConfidence(score=score, level=level, evidence=evidence, calibrated=False)

    @classmethod
    def build_evidence_from_failure(cls, command_results, evaluation, diagnosis=None,
                                    retrieved_knowledge=None, project_files=None):
        evidence = DiagnosisEvidence()
        stderr = chr(10).join(
            c.stderr.strip() for c in command_results
            if c.stderr and c.stderr.strip()
        )
        if stderr:
            evidence.failure_stderr = stderr[:2000]
            evidence.add_evidence(ConfidenceEvidence.FAILURE_STDERR)
        stdout = chr(10).join(
            c.stdout.strip() for c in command_results
            if c.stdout and c.stdout.strip()
        )
        if stdout:
            evidence.failure_stdout = stdout[:2000]
            evidence.add_evidence(ConfidenceEvidence.FAILURE_STDOUT)
        if evaluation.test_results:
            failures = evaluation.test_results.failure_details or []
            if failures:
                evidence.test_failures = list(failures)
                evidence.add_evidence(ConfidenceEvidence.TEST_FAILURES)
                for f in failures:
                    if "AssertionError" in f or "assert" in f.lower():
                        evidence.add_evidence(ConfidenceEvidence.ASSERTION_ERROR)
        if evaluation.failures:
            for f in evaluation.failures:
                if "AssertionError" in f or "assert" in f.lower():
                    evidence.add_evidence(ConfidenceEvidence.ASSERTION_ERROR)
        if diagnosis:
            if diagnosis.root_cause and diagnosis.root_cause.strip():
                evidence.root_cause = diagnosis.root_cause
                evidence.add_evidence(ConfidenceEvidence.ROOT_CAUSE_DETERMINED)
            if diagnosis.affected_files:
                evidence.affected_files = list(diagnosis.affected_files)
                evidence.add_evidence(ConfidenceEvidence.AFFECTED_FILES)
            if diagnosis.suggested_fix and diagnosis.suggested_fix.strip():
                evidence.suggested_fix = diagnosis.suggested_fix
                evidence.add_evidence(ConfidenceEvidence.SUGGESTED_FIX)
        if project_files and len(project_files) > 0:
            evidence.add_evidence(ConfidenceEvidence.FILE_CHANGES)
        if retrieved_knowledge:
            evidence.rag_retrieval_count = len(retrieved_knowledge)
            evidence.add_evidence(ConfidenceEvidence.RAG_RETRIEVAL)
            max_score = 0.0
            for hit in retrieved_knowledge:
                score_val = hit.get("score") if isinstance(hit, dict) else getattr(hit, "score", None)
                if score_val is not None:
                    try:
                        max_score = max(max_score, float(score_val))
                    except (TypeError, ValueError):
                        pass
            if max_score > 0:
                evidence.rag_max_score = max_score
                if max_score >= cls.RAG_SCORE_THRESHOLD:
                    evidence.add_evidence(ConfidenceEvidence.RAG_SCORE_HIGH)
        return evidence, cls.calculate(evidence)
