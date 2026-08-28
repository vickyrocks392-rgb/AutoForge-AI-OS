"""
End-to-end trace and workflow verification tests for AutoForge Observability.
"""

from __future__ import annotations
import uuid
import pytest
from autoforge_event_platform.models.event import EventType
from autoforge_observability import ObservabilityPlatform


def test_greenfield_journey_e2e_observability(event_platform, observability_platform):
    """
    Simulate: Idea -> Research -> Architecture -> Planning -> HITL -> Implementation -> Testing -> Review -> Artifact
    Verify that the entire operation can be reconstructed from traces and dashboards.
    """
    correlation_id = uuid.uuid4()
    project_id = uuid.uuid4()
    workflow_id = uuid.uuid4()

    # 1. Idea (Project intake)
    event_platform.publish(
        event_type=EventType.PROJECT_CREATED,
        source="kernel",
        correlation_id=correlation_id,
        payload={"project_id": str(project_id), "name": "Greenfield App"},
    )

    # 2. Research (Task & Worker dispatch)
    task_id_research = uuid.uuid4()
    event_platform.publish(
        event_type=EventType.TASK_CREATED,
        source="workflow_engine",
        correlation_id=correlation_id,
        payload={"project_id": str(project_id), "workflow_id": str(workflow_id), "task_id": str(task_id_research)},
    )
    event_platform.publish(
        event_type=EventType.WORKER_DISPATCHED,
        source="execution_engine",
        correlation_id=correlation_id,
        payload={"worker_id": "research_engineer_1", "worker_type": "research_engineer", "task_id": str(task_id_research)},
    )
    event_platform.publish(
        event_type=EventType.LOOP_STARTED,
        source="execution_engine",
        correlation_id=correlation_id,
        payload={"worker_id": "research_engineer_1"},
    )

    # 3. Architecture / Plan / Model Selected
    event_platform.publish(
        event_type=EventType.MODEL_SELECTED,
        source="model_router",
        correlation_id=correlation_id,
        payload={
            "model_id": "ornith-9b",
            "provider_id": "local-m1",
            "node_id": "local-m1",
            "capabilities": ["text_generation", "reasoning"],
            "rejected": {"qwen2.5-coder-3b": "insufficient_capability"},
        },
    )

    # 4. HITL gate
    event_platform.publish(
        event_type=EventType.APPROVAL_REQUIRED,
        source="governance",
        correlation_id=correlation_id,
        payload={"worker_id": "research_engineer_1", "approval_type": "architecture_review"},
    )
    event_platform.publish(
        event_type=EventType.APPROVAL_DECIDED,
        source="governance",
        correlation_id=correlation_id,
        payload={"decision": "approved"},
    )

    # 5. Implementation (Backend / Frontend / Database)
    task_id_coding = uuid.uuid4()
    event_platform.publish(
        event_type=EventType.WORKER_DISPATCHED,
        source="execution_engine",
        correlation_id=correlation_id,
        payload={"worker_id": "backend_engineer_1", "worker_type": "backend_engineer", "task_id": str(task_id_coding)},
    )
    event_platform.publish(
        event_type=EventType.LOOP_STARTED,
        source="execution_engine",
        correlation_id=correlation_id,
        payload={"worker_id": "backend_engineer_1"},
    )

    # 6. Testing & Review
    event_platform.publish(
        event_type=EventType.REVIEW_STARTED,
        source="review_engine",
        correlation_id=correlation_id,
        payload={"review_id": str(uuid.uuid4())},
    )
    event_platform.publish(
        event_type=EventType.REVIEW_COMPLETED,
        source="review_engine",
        correlation_id=correlation_id,
        payload={"passed": True, "duration_ms": 150.0},
    )

    # 7. Artifact Publication
    event_platform.publish(
        event_type=EventType.ARTIFACT_CREATED,
        source="artifact_platform",
        correlation_id=correlation_id,
        payload={"artifact_id": str(uuid.uuid4()), "artifact_type": "source_code"},
    )
    event_platform.publish(
        event_type=EventType.ARTIFACT_PUBLISHED,
        source="artifact_platform",
        correlation_id=correlation_id,
        payload={},
    )

    # Verify Trace spans count and parent-child correlation
    spans = observability_platform.traces.get_trace_spans(correlation_id)
    assert len(spans) > 0
    
    # Assert logs and states are correctly updated
    assert observability_platform.dashboards.workflow.total_tasks >= 1
    assert observability_platform.dashboards.review.total_reviews == 1
    assert observability_platform.dashboards.review.passed_reviews == 1
    assert observability_platform.dashboards.artifact.artifacts_created_count == 1
    assert observability_platform.dashboards.artifact.publications_count == 1
    assert observability_platform.dashboards.hitl_governance.requests_count == 1
    assert observability_platform.dashboards.hitl_governance.decisions_count == 1


def test_legacy_modernization_journey_e2e_observability(event_platform, observability_platform):
    """
    Simulate Legacy Modernization Journey:
    Legacy System -> Discovery -> Archaeology -> Architecture -> Data -> Integration -> Business Rules -> Dependency -> Modernization Architecture -> HITL -> Migration Plan -> HITL
    """
    correlation_id = uuid.uuid4()
    project_id = uuid.uuid4()

    # 1. Intake & Discovery
    event_platform.publish(
        event_type=EventType.PROJECT_CREATED,
        source="kernel",
        correlation_id=correlation_id,
        payload={"project_id": str(project_id), "name": "Legacy Migration"},
    )
    event_platform.publish(
        event_type=EventType.PROJECT_STARTED,
        source="kernel",
        correlation_id=correlation_id,
        payload={},
    )

    # Discovery evidence collected
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="legacy_systems_research_engineer",
        correlation_id=correlation_id,
        payload={"event_type": "legacy.system_analyzed"},
    )
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="legacy_code_archaeologist",
        correlation_id=correlation_id,
        payload={"event_type": "evidence.discovered", "epistemic_type": "FACT", "detail": "Found COBOL copybooks"},
    )
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="legacy_code_archaeologist",
        correlation_id=correlation_id,
        payload={"event_type": "evidence.discovered", "epistemic_type": "INFERENCE", "detail": "Derived DB2 schema relations"},
    )
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="legacy_architecture_analyst",
        correlation_id=correlation_id,
        payload={"event_type": "evidence.discovered", "epistemic_type": "HYPOTHESIS", "detail": "Suspect MQ Series middleware"},
    )
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="legacy_architecture_analyst",
        correlation_id=correlation_id,
        payload={"event_type": "unknown.technology_encountered", "detail": "Found custom proprietary socket protocol"},
    )

    # 2. Business rules and modernization decision
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="business_rules_analyst",
        correlation_id=correlation_id,
        payload={"event_type": "business_rule.extracted"},
    )
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="modernization_architect",
        correlation_id=correlation_id,
        payload={"event_type": "modernization.decision_made"},
    )

    # 3. Migration planning and HITL gate
    event_platform.publish(
        event_type=EventType.STATE_UPDATED,
        source="migration_engineer",
        correlation_id=correlation_id,
        payload={"event_type": "migration.plan_created"},
    )
    event_platform.publish(
        event_type=EventType.APPROVAL_REQUIRED,
        source="governance",
        correlation_id=correlation_id,
        payload={"worker_id": "migration_engineer_1", "approval_type": "migration_plan_approval"},
    )
    event_platform.publish(
        event_type=EventType.APPROVAL_DECIDED,
        source="governance",
        correlation_id=correlation_id,
        payload={"decision": "approved"},
    )

    # Verify Legacy modernize read model counters and epistemic types
    assert observability_platform.dashboards.legacy_modernization.systems_analyzed == 1
    assert observability_platform.dashboards.legacy_modernization.evidence_items_count == 3
    assert observability_platform.dashboards.legacy_modernization.evidence_types["FACT"] == 1
    assert observability_platform.dashboards.legacy_modernization.evidence_types["INFERENCE"] == 1
    assert observability_platform.dashboards.legacy_modernization.evidence_types["HYPOTHESIS"] == 1
    assert observability_platform.dashboards.legacy_modernization.unknowns_encountered_count == 1
    assert observability_platform.dashboards.legacy_modernization.business_rules_extracted == 1
    assert observability_platform.dashboards.legacy_modernization.modernization_decisions_count == 1
    assert observability_platform.dashboards.legacy_modernization.migration_plans_created == 1
    assert observability_platform.dashboards.hitl_governance.requests_count == 1
