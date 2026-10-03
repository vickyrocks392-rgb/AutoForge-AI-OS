"""Real experience capture — Phase 19B-3 (Gate 2).

Gate 19A documented GAP-03 and GAP-04: the kernel's learning call site read a
``findings`` key that ``completion.py`` never populates, and never supplied
``repair_records``. 19B-1 repaired that specific dead read. This module
completes the pipeline so that every source named in Gate 2 has a real,
non-manufactured capture path.

Three rules, each testable:

1. **No manufacture.** ``capture_from_execution`` only emits an
   :class:`~autoforge_learning.models.ExecutionObservation` for a source that
   actually appears in the authoritative payload. A source that did not happen
   produces no observation — never a zero-valued one.
2. **Provenance is mandatory.** Every observation carries a content hash of the
   authoritative record it summarises. An observation without one cannot be
   constructed (``content_hash`` has a minimum length).
3. **Model text is enrichment, never evidence.** A ``model_annotation`` may be
   attached, but it is typed ``Literal[False]`` for authority and contributes to
   no metric, no confidence and no verdict anywhere in this package.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from typing import Any, Mapping, Optional, Sequence

from autoforge_learning.models import (
    EvidenceRef,
    EvidenceSource,
    ExecutionObservation,
    ExperienceSource,
    LearningScope,
    LearningScopeKind,
    ValidationTruth,
)

logger = logging.getLogger("autoforge.learning.experience")

__test__ = False  # declares a collector, not tests


#: Maps an authoritative event name to the source class it represents. Only
#: names on this map can ever produce an observation, so the permitted source
#: set is closed by construction rather than by convention.
SOURCE_BY_EVENT: dict[str, ExperienceSource] = {
    "task_execution": ExperienceSource.TASK_EXECUTION,
    "validation": ExperienceSource.VALIDATION,
    "review": ExperienceSource.REVIEW,
    "artifact_generation": ExperienceSource.ARTIFACT_GENERATION,
    "repair_attempt": ExperienceSource.REPAIR_ATTEMPT,
    "execution_failed": ExperienceSource.FAILURE,
    "task_retry": ExperienceSource.RETRY,
    "execution_latency": ExperienceSource.EXECUTION_LATENCY,
    "resource_behaviour": ExperienceSource.RESOURCE_BEHAVIOUR,
    "tool_outcome": ExperienceSource.TOOL_OUTCOME,
    "model_call": ExperienceSource.MODEL_OUTCOME,
    "user_feedback": ExperienceSource.USER_FEEDBACK,
    "project_outcome": ExperienceSource.PROJECT_OUTCOME,
    "modernization": ExperienceSource.MODERNIZATION,
    "migration": ExperienceSource.MIGRATION,
    "rag_retrieval": ExperienceSource.RAG_RETRIEVAL,
    "agent_task_outcome": ExperienceSource.AGENT_TASK_OUTCOME,
    "automation_outcome": ExperienceSource.AUTOMATION_OUTCOME,
}

#: Evidence source used to hash each experience kind. Chosen from the certified
#: ``EvidenceSource`` ladder so a captured experience inherits the correct
#: quality tier rather than asserting one.
EVIDENCE_SOURCE_FOR: dict[ExperienceSource, EvidenceSource] = {
    ExperienceSource.TASK_EXECUTION: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.VALIDATION: EvidenceSource.DETERMINISTIC_VALIDATION,
    ExperienceSource.REVIEW: EvidenceSource.REVIEW_ENGINE,
    ExperienceSource.ARTIFACT_GENERATION: EvidenceSource.DURABLE_ARTIFACT,
    ExperienceSource.REPAIR_ATTEMPT: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.FAILURE: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.RETRY: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.EXECUTION_LATENCY: EvidenceSource.TELEMETRY,
    ExperienceSource.RESOURCE_BEHAVIOUR: EvidenceSource.TELEMETRY,
    ExperienceSource.TOOL_OUTCOME: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.MODEL_OUTCOME: EvidenceSource.TELEMETRY,
    ExperienceSource.USER_FEEDBACK: EvidenceSource.TELEMETRY,
    ExperienceSource.PROJECT_OUTCOME: EvidenceSource.COMPLETION_GATE,
    ExperienceSource.MODERNIZATION: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.MIGRATION: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.RAG_RETRIEVAL: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.AGENT_TASK_OUTCOME: EvidenceSource.CANONICAL_EVENT,
    ExperienceSource.AUTOMATION_OUTCOME: EvidenceSource.CANONICAL_EVENT,
}


def _canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _hashable(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(k): _hashable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_hashable(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _as_float(value: Any) -> Optional[float]:
    """Return a float only when the source really measured a number.

    ``0`` is a legitimate measurement; ``None``/``""``/``"n/a"`` are absences.
    Collapsing the two is the fabrication 19A found in the confidence constant.
    """
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    return None


class ExperienceCollector:
    """Turns real AutoForge execution records into immutable observations.

    The collector is a pure translator. It performs no inference, holds no
    policy, and cannot decide whether an outcome is good or bad — that is the
    signal extractor's job, working from the same evidence.
    """

    def capture_from_execution(
        self,
        *,
        project_id: uuid.UUID,
        execution_events: Mapping[str, Any] | None,
        workflow_id: str | None = None,
        correlation_id: str | None = None,
        model_annotation: str | None = None,
    ) -> tuple[ExecutionObservation, ...]:
        """Capture every *actually present* execution source.

        ``execution_events`` maps a name from :data:`SOURCE_BY_EVENT` to the
        authoritative record for that event. A name that is absent, or whose
        value is ``None``, produces no observation at all — the tuple comes back
        shorter, never fuller.
        """
        if not execution_events:
            return ()

        scope = LearningScope(
            kind=LearningScopeKind.PROJECT,
            project_id=project_id,
            workflow_id=workflow_id,
        )

        observations: list[ExecutionObservation] = []
        for name, record in execution_events.items():
            source = SOURCE_BY_EVENT.get(name)
            if source is None:
                # An unknown source is never coerced into a known one.
                logger.debug("ignoring unrecognised execution source %r", name)
                continue
            if record is None:
                continue

            payload = _hashable(record)
            observations.append(
                ExecutionObservation(
                    scope=scope,
                    source=source,
                    subject_ref=self._subject_ref(payload, name),
                    content_hash=hashlib.sha256(
                        _canonical(payload).encode("utf-8")
                    ).hexdigest(),
                    outcome=self._outcome(source, payload),
                    duration_ms=(
                        _as_float(payload.get("duration_ms"))
                        if isinstance(payload, Mapping)
                        else None
                    ),
                    resource_units=(
                        _as_float(payload.get("resource_units"))
                        if isinstance(payload, Mapping)
                        else None
                    ),
                    correlation_id=correlation_id,
                    model_annotation=model_annotation,
                )
            )
        return tuple(observations)

    def evidence_for(self, observation: ExecutionObservation) -> EvidenceRef:
        """The content-addressed reference for one observation.

        A signal may only cite evidence; an observation without a corresponding
        ``EvidenceRef`` cannot support one, so this is the mandatory bridge.
        """
        return EvidenceRef(
            source=EVIDENCE_SOURCE_FOR[observation.source],
            source_ref=(
                f"experience:{observation.source.value}:{observation.subject_ref}"
            ),
            content_hash=observation.content_hash,
            observed_at=observation.observed_at,
        )

    def observations_to_evidence(
        self, observations: Sequence[ExecutionObservation]
    ) -> tuple[EvidenceRef, ...]:
        return tuple(self.evidence_for(o) for o in observations)

    # ── internals ────────────────────────────────────────────────────────────

    @staticmethod
    def _subject_ref(payload: Any, fallback: str) -> str:
        if isinstance(payload, Mapping):
            for key in (
                "task_id",
                "artifact_id",
                "model_call_id",
                "tool_name",
                "review_id",
                "feedback_id",
                "execution_id",
                "workflow_id",
            ):
                value = payload.get(key)
                if value:
                    return f"{key}:{value}"
        digest = hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()[:16]
        return f"{fallback}:{digest}"

    @staticmethod
    def _outcome(source: ExperienceSource, payload: Any) -> str:
        """Derive the outcome token from the real record.

        Only fields the source genuinely produced are consulted. An absent
        verdict yields ``"unmeasured"`` rather than a guess — an unmeasured
        outcome must never be optimizable.
        """
        if not isinstance(payload, Mapping):
            return "recorded"
        for key in ("outcome", "status", "result", "verdict"):
            value = payload.get(key)
            if isinstance(value, str) and value:
                return value
        if source is ExperienceSource.VALIDATION:
            passed = payload.get("passed")
            if isinstance(passed, bool):
                return (
                    ValidationTruth.PASSED.value
                    if passed
                    else ValidationTruth.FAILED.value
                )
        approved = payload.get("approved")
        if isinstance(approved, bool):
            return "approved" if approved else "rejected"
        succeeded = payload.get("succeeded", payload.get("success"))
        if isinstance(succeeded, bool):
            return "succeeded" if succeeded else "failed"
        return "unmeasured"


__all__ = [
    "EVIDENCE_SOURCE_FOR",
    "SOURCE_BY_EVENT",
    "ExperienceCollector",
]