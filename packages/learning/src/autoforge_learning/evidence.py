"""Authoritative experience collection — Phase 19B-1 (Gate 3).

Experience is constructed **only** from real authoritative systems:

* the durable artifact catalog (``DurableArtifactState`` content hashes),
* the completion gate result (``finalize_project``),
* the deterministic validation truth captured by the completion module,
* the review verdict reported by the final review gate.

Two rules are load-bearing:

1. **No fabrication.** When evidence is missing the corresponding field is
   ``None`` / ``UNAVAILABLE``. A missing test count is never reported as zero
   successes, and an absent validation port is never reported as a pass.
2. **No model self-report as evidence.** Model text, if supplied, lands in
   ``model_annotation``, which is typed non-authoritative and contributes to
   nothing.

On Gate 19B-1 Gate 4 (``kernel.py:538`` reads
``validation_result.get("findings", [])`` although ``completion.py`` never
populates a ``findings`` key): this module does **not** invent that field. It
consumes the authoritative structures that already exist —
``final_review.validation`` (the real deterministic validation truth),
``final_review.approved`` (the real review verdict) and
``final_review.evidence_files`` (real durable artifact count). The dead read is
repaired at the call site, not by fabricating parallel validation data.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Mapping, Optional, Sequence

from autoforge_learning.models import (
    EvidenceRef,
    EvidenceSource,
    ExperienceRecord,
    LearningScope,
    LearningScopeKind,
    TestOutcome,
    ValidationSummary,
    ValidationTruth,
)

logger = logging.getLogger("autoforge.learning.evidence")


def _hashable(value: Any) -> Any:
    """Best-effort conversion of a nested structure into JSON-safe data."""
    if isinstance(value, Mapping):
        return {str(k): _hashable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_hashable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _find_validation(finalize_result: Mapping[str, Any]) -> Any:
    """Locate the real deterministic validation mapping, if present.

    ``finalize_project`` reports validation in different places depending on
    which gate stopped the project. We read whichever real structure is
    present; we never synthesize one.
    """
    final_review = finalize_result.get("final_review")
    if isinstance(final_review, Mapping) and final_review.get("validation") is not None:
        return final_review["validation"]
    if finalize_result.get("validation") is not None:
        return finalize_result["validation"]
    return None


class EvidenceCollector:
    """Builds :class:`ExperienceRecord` objects from authoritative inputs.

    The collector performs no inference and holds no policy. It is a pure
    translator from existing system state into an immutable, evidence-linked
    record.
    """

    def collect(
        self,
        *,
        project_id: uuid.UUID,
        finalize_result: Mapping[str, Any] | None,
        workflow_id: str | None = None,
        correlation_id: str | None = None,
        duration_seconds: float | None = None,
        durable_artifacts: Sequence[Any] | None = None,
        model_annotation: str | None = None,
    ) -> ExperienceRecord:
        """Assemble one experience record from authoritative inputs."""
        scope = LearningScope(
            kind=LearningScopeKind.PROJECT,
            project_id=project_id,
            workflow_id=workflow_id,
        )

        evidence: list[EvidenceRef] = []
        artifact_hashes: list[str] = []

        for artifact in durable_artifacts or ():
            content_hash = getattr(artifact, "content_hash", "") or ""
            artifact_id = str(getattr(artifact, "artifact_id", "unknown"))
            if content_hash:
                artifact_hashes.append(content_hash)
            evidence.append(
                EvidenceRef.from_payload(
                    source=EvidenceSource.DURABLE_ARTIFACT,
                    source_ref=f"artifact:{artifact_id}",
                    payload={
                        "artifact_id": artifact_id,
                        "content_hash": content_hash,
                        "status": str(getattr(artifact, "status", "")),
                        "workflow_id": str(getattr(artifact, "workflow_id", "")),
                    },
                )
            )

        completion_succeeded: Optional[bool] = None
        review_approved: Optional[bool] = None

        if finalize_result is not None:
            success = finalize_result.get("success")
            if isinstance(success, bool):
                completion_succeeded = success

            final_review = finalize_result.get("final_review")
            if isinstance(final_review, Mapping):
                approved = final_review.get("approved")
                if isinstance(approved, bool):
                    review_approved = approved
                evidence.append(
                    EvidenceRef.from_payload(
                        source=EvidenceSource.REVIEW_ENGINE,
                        source_ref=f"final_review:{project_id}",
                        payload=_hashable(final_review),
                    )
                )

        validation = self._collect_validation(finalize_result, evidence)

        if finalize_result is not None:
            evidence.append(
                EvidenceRef.from_payload(
                    source=EvidenceSource.COMPLETION_GATE,
                    source_ref=f"finalize:{project_id}",
                    payload=_hashable(finalize_result),
                )
            )

        return ExperienceRecord(
            scope=scope,
            correlation_id=correlation_id,
            validation=validation,
            completion_succeeded=completion_succeeded,
            review_approved=review_approved,
            artifact_count=len(artifact_hashes) if durable_artifacts is not None else None,
            artifact_hashes=tuple(artifact_hashes),
            duration_seconds=duration_seconds,
            evidence=tuple(evidence),
            model_annotation=model_annotation,
        )

    # ── validation ──────────────────────────────────────────────────────────

    def _collect_validation(
        self,
        finalize_result: Mapping[str, Any] | None,
        evidence: list[EvidenceRef],
    ) -> ValidationSummary:
        """Read the real deterministic validation truth, if one exists.

        ``CompletionModule._collect_validation_evidence`` returns either
        ``None`` (no deterministic validation applies) or a mapping with
        ``required``/``passed``. ``None`` maps to ``UNAVAILABLE`` here — the
        not-applicable/failed distinction is preserved rather than collapsed.

        Both completion-result shapes are handled, because
        ``finalize_project`` reports differently on the two paths:

        * success:  ``{"success": True,  "final_review": {"validation": ...}}``
        * failure:  ``{"success": False, "validation": ...}``
        """
        if finalize_result is None:
            return ValidationSummary.unavailable("no completion result available")

        validation = _find_validation(finalize_result)

        if validation is None:
            return ValidationSummary.unavailable(
                "completion result carried no deterministic validation evidence"
            )

        if not isinstance(validation, Mapping):
            return ValidationSummary.unavailable(
                "deterministic validation evidence was not a mapping"
            )

        required = validation.get("required")
        passed = validation.get("passed")

        evidence.append(
            EvidenceRef.from_payload(
                source=EvidenceSource.DETERMINISTIC_VALIDATION,
                source_ref=f"validation:{validation.get('reason', 'result')}",
                payload=_hashable(validation),
            )
        )

        if not required:
            truth = ValidationTruth.NOT_APPLICABLE
        elif passed is True:
            truth = ValidationTruth.PASSED
        elif passed is False:
            truth = ValidationTruth.FAILED
        else:
            truth = ValidationTruth.UNAVAILABLE

        return ValidationSummary(
            truth=truth,
            test_outcome=self._test_outcome(validation.get("test_results")),
            reason=str(validation.get("reason", "")),
        )

    @staticmethod
    def _test_outcome(raw: Any) -> TestOutcome:
        """Convert real parsed test counts, or report unavailable.

        Only a mapping (or an object exposing the same attributes) is accepted.
        A string, a number, or an absent value yields ``TestOutcome()`` with
        every count ``None`` — never a fabricated zero.
        """
        if raw is None:
            return TestOutcome.unavailable()

        def _read(*names: str) -> int | None:
            for name in names:
                value: Any = None
                if isinstance(raw, Mapping):
                    value = raw.get(name)
                else:
                    value = getattr(raw, name, None)
                if isinstance(value, int) and not isinstance(value, bool):
                    return value
            return None

        return TestOutcome(
            total=_read("total_tests", "total"),
            passed=_read("passed_tests", "passed"),
            failed=_read("failed_tests", "failed"),
            errors=_read("error_tests", "errors"),
            skipped=_read("skipped_tests", "skipped"),
        )


__all__ = ["EvidenceCollector"]