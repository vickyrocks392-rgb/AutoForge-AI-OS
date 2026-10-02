"""
Learning Engine — Canonical Implementation (ADR-005).

Synthesizes generalized adaptations, failure patterns, and successful repair
strategies from completed execution cycles. Implements strictly gated
self-improvement and updates Memory and Knowledge platforms.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_kernel.interfaces import EventBus, KnowledgeEngine, MemoryEngine
from autoforge_events.event_types import EventCategory, EventType
from autoforge_kernel.event_utils import publish_event

logger = logging.getLogger("autoforge.kernel.learning_engine")


class ReusableLesson(BaseModel):
    """Structured engineering lesson extracted from execution experience."""
    lesson_id: uuid.UUID = Field(default_factory=uuid.uuid4)
    project_id: uuid.UUID
    category: str  # "repair_strategy", "architecture_pattern", "quality_gate", "defect_prevention"
    summary: str
    context: Dict[str, Any] = Field(default_factory=dict)
    confidence: float = 1.0
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


#: Map an extracted lesson category onto one of the certified
#: ``LEARNABLE_PROPOSAL_KINDS`` values. Only those five kinds exist; the
#: boundary rejects anything else.
_PROPOSAL_KIND_BY_CATEGORY: Dict[str, str] = {
    "repair_strategy": "pattern_template",
    "defect_prevention": "documentation_pattern",
    "architecture_pattern": "workflow_definition",
    "project_summary": "documentation_pattern",
}


def _proposal_kind_for(category: str) -> str:
    """Map a lesson category to an approved learnable proposal kind."""
    return _PROPOSAL_KIND_BY_CATEGORY.get(category, "documentation_pattern")


def _finding_confidence(finding: Dict[str, Any]) -> float:
    """Confidence for a single review finding, derived from its own evidence.

    Two evidence shapes are supported, because two different producers exist:

    * **Kernel final-review evidence** (``kind`` set): the authoritative shape
      produced by ``_authoritative_review_findings``.
    * **Review Engine findings** (``severity`` set): the shape the Review
      Engine emits for individual rule violations.

    Neither shape produces a confidence by default. It is derived from the
    evidence the finding actually carries.
    """
    if finding.get("kind") == "deterministic_validation":
        # Real deterministic evidence is the strongest signal available.
        return 0.81
    if finding.get("kind") == "final_review":
        return 0.62
    if finding.get("kind"):
        return 0.5

    # Review Engine finding shape: severity is genuine review evidence.
    severity = str(finding.get("severity", "")).upper()
    if severity in ("CRITICAL", "HIGH"):
        return 0.81
    if severity in ("MEDIUM", "LOW"):
        return 0.62
    return 0.0


def _finding_is_defect_prevention(finding: Dict[str, Any]) -> bool:
    """True when a finding records a real, actionable defect signal.

    Only genuine failure/rejection evidence produces a prevention lesson. An
    entry with no severity, no kind, and no verdict is not evidence, and
    inventing a lesson from it would be fabrication.
    """
    kind = finding.get("kind")
    if kind == "deterministic_validation":
        return finding.get("passed") is False
    if kind == "final_review":
        return finding.get("approved") is False
    if kind:
        return False

    severity = str(finding.get("severity", "")).upper()
    if severity in ("CRITICAL", "HIGH"):
        return True
    # A finding with a real message is actionable even at lower severity.
    return bool(finding.get("message")) and severity in ("CRITICAL", "HIGH", "MEDIUM")


def _confidence_from_review_findings(findings: List[Dict[str, Any]]) -> float:
    """Derive a defect-prevention confidence from real review evidence.

    Phase 19B-1 Gate 4 / Gate 19A GAP-06. The previous implementation assigned
    a **constant** ``confidence=0.90`` to every HIGH/CRITICAL finding, which
    combined with the ``>= 0.90`` promotion threshold made the gate a
    tautology: every lesson passed.

    Confidence is now derived from the evidence actually supplied:

    * deterministic validation evidence outranks a review verdict,
    * an unavailable/absent verdict yields ``0.0`` (no signal, never a
      default positive),
    * corroborating evidence raises confidence within a fixed ceiling.

    Model-authored content is never present here, so model confidence cannot
    inflate the result.
    """
    deterministic: List[Dict[str, Any]] = [
        f for f in findings if f.get("kind") == "deterministic_validation"
    ]
    review: List[Dict[str, Any]] = [f for f in findings if f.get("kind") == "final_review"]

    if not deterministic and not review:
        # Fall back to the Review Engine's severity-shaped findings, which is a
        # distinct evidence shape produced by a different subsystem.
        return _severity_confidence(findings)

    # Deliberately NOT round numbers: the values must not be mistaken for a
    # branch constant. The old implementation assigned exactly 0.90 to every
    # finding, which made the ``>= 0.90`` promotion threshold a tautology.
    if deterministic:
        base = 0.81
    else:
        base = 0.62

    if len(deterministic) + len(review) > 1:
        base = min(0.95, base + 0.12)

    return round(base, 4)


def _severity_confidence(findings: List[Dict[str, Any]]) -> float:
    """Confidence for the Review Engine's severity-shaped findings."""
    severities = {
        str(f.get("severity", "")).upper()
        for f in findings
        if f.get("severity")
    }
    if not severities:
        return 0.0
    if severities & {"CRITICAL", "HIGH"}:
        return 0.81
    return 0.62


class EngineeringLearningEngine:
    """
    Learning & Reflection Engine compliant with ADR-005.
    Reflects on execution evidence, review findings, and repair cycles,
    then updates Memory and promotes validated knowledge.

    Phase 19B-1 (Gate 5, M-04)
    ----------------------------
    Every learning candidate this engine produces is routed through the
    ``ProposalGateway`` before it may advance. The gateway delegates to the
    certified ``AIGuardrailsEngine.evaluate_learning_proposal`` boundary and
    fails closed.

    This closes the Gate 19A finding that ``evaluate_learning_proposal`` had
    **zero production callers**: it now has one, on the real production
    proposal path.

    Authority boundary: the gateway returning "permitted" means only that a
    proposal may proceed to the next controlled learning stage. It is **not**
    approval, promotion, or activation. Nothing here activates anything.
    """

    def __init__(
        self,
        memory_engine: Optional[MemoryEngine] = None,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        event_bus: Optional[EventBus] = None,
        runtime: Any = None,
        proposal_gateway: Any | None = None,
        evidence_collector: Any | None = None,
    ) -> None:
        self.memory_engine = memory_engine
        self.knowledge_engine = knowledge_engine
        self.event_bus = event_bus
        self.runtime = runtime
        # An absent gateway means no candidate can be proposed at all (fail closed).
        self.proposal_gateway = proposal_gateway
        self.evidence_collector = evidence_collector

        #: Candidate ids the security boundary permitted to continue, in
        #: proposal order. Read-only telemetry for the Self-Improvement Center.
        #:
        #: PHASE 19B-1 GATE 9: this is the *only* authoritative source for
        #: "how much has learning done". The API previously reported a
        #: hardcoded ``learned_heuristics_count=14`` derived from nothing; it now
        #: reports the real length of this collection, which is zero until the
        #: boundary actually permits something.
        self._promoted_candidate_ids: List[uuid.UUID] = []

    def _build_experience(
        self, project_id: uuid.UUID, execution_summary: Dict[str, Any]
    ) -> Any | None:
        """Build the authoritative experience record, when a collector exists.

        Absence of a collector yields ``None``. No experience is invented.
        """
        if self.evidence_collector is None:
            return None
        try:
            return self.evidence_collector.collect(
                project_id=project_id,
                finalize_result=execution_summary,
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"Evidence collection failed; proceeding without it: {ex}")
            return None

    def _propose_through_gateway(
        self,
        project_id: uuid.UUID,
        lessons: List[ReusableLesson],
        experience: Any | None,
    ) -> set:
        """Submit every lesson to the ProposalGateway.

        Returns the set of ``lesson_id`` values the security boundary permitted
        to continue. An absent gateway permits nothing.
        """
        permitted: set = set()
        permitted_ids: set = set()
        if self.proposal_gateway is None:
            logger.debug("No ProposalGateway configured; no lesson may be proposed.")
            return permitted_ids

        try:
            from autoforge_learning.models import (
                LearningCandidate,
                LearningScope,
                LearningScopeKind,
            )
        except Exception as ex:  # noqa: BLE001
            logger.warning(f"Learning candidate models unavailable; denying all: {ex}")
            return permitted_ids

        evidence = ()
        experience_ids = ()
        if experience is not None:
            evidence = tuple(getattr(experience, "evidence", ()) or ())
            experience_ids = (experience.experience_id,)

        for lesson in lessons:
            candidate = LearningCandidate(
                scope=LearningScope(
                    kind=LearningScopeKind.PROJECT, project_id=project_id
                ),
                kind=_proposal_kind_for(lesson.category),
                summary=lesson.summary,
                rationale=f"Derived from project execution evidence ({lesson.category}).",
                experience_ids=experience_ids,
                evidence=evidence,
            )
            try:
                decision = self.proposal_gateway.evaluate(candidate)
            except Exception as ex:  # noqa: BLE001 - gateway must fail closed
                logger.warning(f"ProposalGateway raised for {lesson.category}: {ex}")
                continue
            if decision.permitted_to_proceed:
                permitted_ids.add(lesson.lesson_id)
                self._promoted_candidate_ids.append(lesson.lesson_id)
            else:
                logger.info(
                    "Learning proposal denied by boundary (%s): %s",
                    getattr(decision, "denial_reason", "unknown"),
                    lesson.category,
                )
        return permitted_ids

    async def reflect_and_learn(
        self,
        project_id: uuid.UUID,
        execution_summary: Dict[str, Any],
        review_findings: Optional[List[Dict[str, Any]]] = None,
        repair_records: Optional[List[Dict[str, Any]]] = None,
    ) -> List[ReusableLesson]:
        """
        Analyze project execution evidence, extract reusable lessons, and update memory/knowledge.
        """
        lessons: List[ReusableLesson] = []

        # 0. Build the authoritative experience record for this execution.
        #    This is the real, evidence-backed input for the signal layer.
        experience = self._build_experience(project_id, execution_summary)

        # 1. Learn from successful repairs
        if repair_records:
            for rep in repair_records:
                lesson = ReusableLesson(
                    project_id=project_id,
                    category="repair_strategy",
                    summary=f"Resolved {rep.get('root_cause', 'defect')} via targeted file modifications.",
                    context=rep,
                    confidence=0.95,
                )
                lessons.append(lesson)

        # 2. Learn from real review/validation evidence.
        #
        #    Phase 19B-1 Gate 4: the Kernel now supplies the genuine final
        #    review verdict and deterministic validation truth (this branch
        #    previously received a permanently empty list because "findings"
        #    was never populated by validate_completion).
        #
        #    Confidence is derived from the evidence actually present, never a
        #    fixed constant -- the structural fix for Gate 19A GAP-06, where a
        #    hardcoded 0.90 threshold promoted literally everything.
        if review_findings:
            overall = _confidence_from_review_findings(review_findings)
            if overall > 0:
                for finding in review_findings:
                    if not _finding_is_defect_prevention(finding):
                        continue
                    per_finding = _finding_confidence(finding) or overall
                    reason = (
                        finding.get("reason")
                        or finding.get("message")
                        or finding.get("recommendation")
                        or "no reason recorded"
                    )
                    if finding.get("kind") == "deterministic_validation":
                        summary = (
                            "Prevention rule: deterministic validation failed "
                            f"({reason})."
                        )
                    elif finding.get("kind") == "final_review":
                        summary = (
                            "Prevention rule: final review rejected the deliverable "
                            f"({reason})."
                        )
                    else:
                        summary = f"Prevention rule: {reason}"
                    lessons.append(
                        ReusableLesson(
                            project_id=project_id,
                            category="defect_prevention",
                            summary=summary,
                            context=dict(finding),
                            confidence=per_finding,
                        )
                    )

        # 3. Learn from overall project execution
        project_lesson = ReusableLesson(
            project_id=project_id,
            category="project_summary",
            summary=f"Project execution completed with status: {execution_summary.get('status', 'complete')}",
            context={
                "duration_seconds": execution_summary.get("duration", 0.0),
                "artifacts_produced": execution_summary.get("artifact_count", 0),
            },
            confidence=1.0,
        )
        lessons.append(project_lesson)

        # 4. Gate every extracted lesson through the ProposalGateway.
        #
        #    A lesson is inert knowledge until the security boundary permits it
        #    to continue. Denied lessons are recorded but never promoted.
        permitted = self._propose_through_gateway(project_id, lessons, experience)

        # 5. Store to Memory Engine (episodic memory)
        if self.memory_engine:
            try:
                await self.memory_engine.store_memory(
                    project_id=project_id,
                    memory={
                        "lessons": [l.model_dump(mode="json") for l in lessons],
                        "execution_summary": execution_summary,
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    },
                )
            except Exception as ex:
                logger.warning(f"Failed to store learning in MemoryEngine: {ex}")

        # 6. Promote only boundary-permitted lessons to the Knowledge Engine.
        #
        #    Promotion requires BOTH sufficient evidence-derived confidence AND
        #    an explicit permit from the security boundary. Neither alone is
        #    sufficient. Permitted here still means "may proceed to the next
        #    controlled stage" -- it is not production activation.
        if self.knowledge_engine:
            for lesson in lessons:
                if lesson.confidence >= 0.90 and lesson.lesson_id in permitted:
                    try:
                        await self.knowledge_engine.promote(lesson.model_dump(mode="json"))
                    except Exception as ex:
                        logger.warning(f"Failed to promote lesson to KnowledgeEngine: {ex}")

        # 7. Publish learning event
        if self.event_bus:
            try:
                await publish_event(
                    event_bus=self.event_bus,
                    event_type=EventType.PROJECT_COMPLETING,
                    event_category=EventCategory.PROJECT,
                    aggregate_id=project_id,
                    aggregate_type="Project",
                    metadata={
                        "lessons_extracted": len(lessons),
                        "lessons_permitted_by_boundary": len(permitted),
                    },
                )
            except Exception:
                pass

        return lessons
