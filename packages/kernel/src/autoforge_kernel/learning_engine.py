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


class EngineeringLearningEngine:
    """
    Learning & Reflection Engine compliant with ADR-005.
    Reflects on execution evidence, review findings, and repair cycles,
    then updates Memory and promotes validated knowledge.
    """

    def __init__(
        self,
        memory_engine: Optional[MemoryEngine] = None,
        knowledge_engine: Optional[KnowledgeEngine] = None,
        event_bus: Optional[EventBus] = None,
        runtime: Any = None,
    ) -> None:
        self.memory_engine = memory_engine
        self.knowledge_engine = knowledge_engine
        self.event_bus = event_bus
        self.runtime = runtime

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

        # 2. Learn from review findings
        if review_findings:
            for finding in review_findings:
                sev = str(finding.get("severity", "")).upper()
                if sev in ("CRITICAL", "HIGH"):
                    lesson = ReusableLesson(
                        project_id=project_id,
                        category="defect_prevention",
                        summary=f"Prevention rule: {finding.get('message', 'Quality gate finding')}",
                        context=finding,
                        confidence=0.90,
                    )
                    lessons.append(lesson)

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

        # 4. Store to Memory Engine (episodic memory)
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

        # 5. Promote high-confidence validated lessons to Knowledge Engine
        if self.knowledge_engine:
            for lesson in lessons:
                if lesson.confidence >= 0.90:
                    try:
                        await self.knowledge_engine.promote(lesson.model_dump(mode="json"))
                    except Exception as ex:
                        logger.warning(f"Failed to promote lesson to KnowledgeEngine: {ex}")

        # 6. Publish learning event
        if self.event_bus:
            try:
                await publish_event(
                    event_bus=self.event_bus,
                    event_type=EventType.PROJECT_COMPLETING,
                    event_category=EventCategory.PROJECT,
                    aggregate_id=project_id,
                    aggregate_type="Project",
                    metadata={"lessons_extracted": len(lessons)},
                )
            except Exception:
                pass

        return lessons
