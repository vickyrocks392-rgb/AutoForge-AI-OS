"""
Workforce Worker Definitions for Greenfield and Legacy Engineering.
"""

from __future__ import annotations
from typing import Any
import uuid
from datetime import datetime, timezone

from autoforge_ai_infrastructure.metadata import CapabilityIds
from autoforge_execution.worker import EngineeringWorker
from autoforge_execution.models import WorkerType as BaseWorkerType, WorkerStatus
from autoforge_execution.environment import WorkspaceEnvironment
from autoforge_execution import AIEngineeringProvider
from autoforge_execution.artifacts import ArtifactPipeline
from autoforge_execution.governance import ExecutionGovernance
from autoforge_execution.models import LoopConfig, ArtifactRecord, EvaluationResult

from autoforge_workforce.capabilities import ExpertiseModel, Permission, WorkerModelProfile
from autoforge_workforce.registry import WORKER_REGISTRY


class WorkforceWorker(EngineeringWorker):
    """
    Subclass of EngineeringWorker that adds capabilities, permissions, model profiles, and specialized loop mapping.
    """
    specialized_type: str = "general"
    base_type: BaseWorkerType = BaseWorkerType.GENERAL
    expertise: ExpertiseModel = ExpertiseModel(worker_type="general")

    def __init__(
        self,
        worker_id: str,
        environment: WorkspaceEnvironment,
        ai_provider: AIEngineeringProvider,
        *,
        artifact_pipeline: ArtifactPipeline | None = None,
        governance: ExecutionGovernance | None = None,
        loop_config: LoopConfig | None = None,
        event_sink: Any = None,
        rag_engine: Any | None = None,
    ) -> None:
        super().__init__(
            worker_id=worker_id,
            worker_type=self.base_type,
            environment=environment,
            ai_provider=ai_provider,
            artifact_pipeline=artifact_pipeline,
            governance=governance,
            loop_config=loop_config,
            event_sink=event_sink,
        )
        self._rag_engine = rag_engine

    @property
    def model_profile(self) -> WorkerModelProfile:
        return self.expertise.model_profile

    def check_permission(self, operation: str, resource: str) -> bool:
        return self.expertise.validates_permissions(operation, resource)

    async def execute_task(
        self,
        context: Any,
    ) -> tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        if self._state.status != WorkerStatus.READY:
            self.prepare(
                context.task_id,
                workflow_id=context.workflow_id,
                correlation_id=context.correlation_id,
                attempt_number=context.attempt_number,
            )

        self._state.status = WorkerStatus.RUNNING
        self._state.started_at = datetime.now(timezone.utc)

        # Build specialized loop
        from autoforge_workforce.loops import get_loop_class
        loop_cls = get_loop_class(self.expertise.default_loop_type)
        loop = loop_cls(
            environment=self._env,
            ai_provider=self._ai,
            artifact_pipeline=self._artifacts,
            governance=self._governance,
            config=self._loop_config,
            on_iteration_callback=self._on_loop_iteration,
            rag_engine=self._rag_engine,
        )

        # Extract verification commands from context input_data
        verification_commands = None
        if hasattr(context, 'input_data') and context.input_data:
            verification_commands = context.input_data.get("verification_commands")

        try:
            passed, artifacts, last_eval = await loop.run(
                context=context,
                worker_id=self._worker_id,
                verification_commands=verification_commands,
                is_cancelled=self.is_cancelled,
            )
            self._state.produced_artifacts.extend(artifacts)
            self._state.last_evaluation = last_eval
            self._state.finished_at = datetime.now(timezone.utc)

            if self._cancellation_flag:
                self._state.status = WorkerStatus.CANCELLED
            elif passed:
                self._state.status = WorkerStatus.COMPLETED
            else:
                self._state.status = WorkerStatus.FAILED
                if last_eval and last_eval.failures:
                    self._state.last_error_message = "; ".join(last_eval.failures[:3])

            return passed, artifacts, last_eval

        except Exception as exc:
            self._state.status = WorkerStatus.FAILED
            self._state.last_error_message = str(exc)
            self._state.finished_at = datetime.now(timezone.utc)
            raise


# ── Greenfield Workers ────────────────────────────────────────────────────────

class ResearchEngineer(WorkforceWorker):
    specialized_type = "research_engineer"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="research_engineer",
        capabilities=["research", "literature_search"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write"])],
        tool_access=["search_web", "view_file"],
        expected_artifacts=["research_brief"],
        default_loop_type="research",
        model_profile=WorkerModelProfile(
            worker_type="research_engineer",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
            min_context_window_tokens=16384,
            reasoning_required=True,
            quality_priority=3,
            latency_priority="medium",
            privacy_policy="local_only",
        ),
    )

class ArchitectureEngineer(WorkforceWorker):
    specialized_type = "architecture_engineer"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="architecture_engineer",
        capabilities=["architecture_design", "tradeoff_analysis"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write"])],
        expected_artifacts=["architecture_proposal"],
        default_loop_type="architecture",
        model_profile=WorkerModelProfile(
            worker_type="architecture_engineer",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            reasoning_required=True,
            structured_output_required=True,
            quality_priority=4,
            privacy_policy="local_only",
        ),
    )

class PlanningEngineer(WorkforceWorker):
    specialized_type = "planning_engineer"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="planning_engineer",
        capabilities=["planning", "workflow_generation"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write"])],
        expected_artifacts=["work_breakdown_structure"],
        default_loop_type="planning",
        model_profile=WorkerModelProfile(
            worker_type="planning_engineer",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            reasoning_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class UIDesigner(WorkforceWorker):
    specialized_type = "ui_designer"
    base_type = BaseWorkerType.GENERAL
    expertise = ExpertiseModel(
        worker_type="ui_designer",
        capabilities=["ui_design", "accessibility_audit"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write"])],
        expected_artifacts=["ui_design_specification"],
        default_loop_type="ui_design",
        model_profile=WorkerModelProfile(
            worker_type="ui_designer",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=8192,
            structured_output_required=True,
            quality_priority=2,
            privacy_policy="local_only",
        ),
    )

class BackendEngineer(WorkforceWorker):
    specialized_type = "backend_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="backend_engineer",
        capabilities=["backend_coding", "rest_api_design"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["source_code"],
        default_loop_type="backend",
        model_profile=WorkerModelProfile(
            worker_type="backend_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=32768,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class FrontendEngineer(WorkforceWorker):
    specialized_type = "frontend_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="frontend_engineer",
        capabilities=["frontend_coding", "ui_implementation"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write"])],
        expected_artifacts=["source_code"],
        default_loop_type="frontend",
        model_profile=WorkerModelProfile(
            worker_type="frontend_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class DatabaseEngineer(WorkforceWorker):
    specialized_type = "database_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="database_engineer",
        capabilities=["database_design", "schema_definition"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["db_schema"],
        default_loop_type="database",
        model_profile=WorkerModelProfile(
            worker_type="database_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class MLEngineer(WorkforceWorker):
    specialized_type = "ml_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="ml_engineer",
        capabilities=["ml_inference_design", "data_pipeline"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["ml_inference_plan"],
        default_loop_type="ml",
        model_profile=WorkerModelProfile(
            worker_type="ml_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.TOOL_USE, CapabilityIds.REASONING],
            min_context_window_tokens=16384,
            coding_required=True,
            tool_use_required=True,
            reasoning_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class InfrastructureEngineer(WorkforceWorker):
    specialized_type = "infrastructure_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="infrastructure_engineer",
        capabilities=["iac_generation", "deployment_topology"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["infrastructure_code"],
        default_loop_type="infrastructure",
        model_profile=WorkerModelProfile(
            worker_type="infrastructure_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class DevOpsEngineer(WorkforceWorker):
    specialized_type = "devops_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="devops_engineer",
        capabilities=["cicd_automation", "deployment_workflows"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["cicd_workflow"],
        default_loop_type="devops",
        model_profile=WorkerModelProfile(
            worker_type="devops_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class QAEngineer(WorkforceWorker):
    specialized_type = "qa_engineer"
    base_type = BaseWorkerType.TESTING
    expertise = ExpertiseModel(
        worker_type="qa_engineer",
        capabilities=["test_automation", "test_execution"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["test_report"],
        default_loop_type="qa",
        model_profile=WorkerModelProfile(
            worker_type="qa_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.TOOL_USE],
            min_context_window_tokens=16384,
            coding_required=True,
            tool_use_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class SecurityEngineer(WorkforceWorker):
    specialized_type = "security_engineer"
    base_type = BaseWorkerType.REVIEW
    expertise = ExpertiseModel(
        worker_type="security_engineer",
        capabilities=["vulnerability_scanning", "security_hardening"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["security_report"],
        default_loop_type="security",
        model_profile=WorkerModelProfile(
            worker_type="security_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.REASONING, CapabilityIds.TOOL_USE],
            min_context_window_tokens=32768,
            coding_required=True,
            reasoning_required=True,
            tool_use_required=True,
            quality_priority=4,
            privacy_policy="local_only",
        ),
    )

class PerformanceEngineer(WorkforceWorker):
    specialized_type = "performance_engineer"
    base_type = BaseWorkerType.REVIEW
    expertise = ExpertiseModel(
        worker_type="performance_engineer",
        capabilities=["benchmarking", "profile_analysis"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["performance_report"],
        default_loop_type="performance",
        model_profile=WorkerModelProfile(
            worker_type="performance_engineer",
            required_capabilities=[CapabilityIds.REASONING, CapabilityIds.TOOL_USE],
            min_context_window_tokens=16384,
            reasoning_required=True,
            tool_use_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class DocumentationEngineer(WorkforceWorker):
    specialized_type = "documentation_engineer"
    base_type = BaseWorkerType.GENERAL
    expertise = ExpertiseModel(
        worker_type="documentation_engineer",
        capabilities=["technical_writing", "api_doc_generation"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write"])],
        expected_artifacts=["technical_documentation"],
        default_loop_type="documentation",
        model_profile=WorkerModelProfile(
            worker_type="documentation_engineer",
            required_capabilities=[CapabilityIds.TEXT_GENERATION],
            min_context_window_tokens=16384,
            quality_priority=2,
            latency_priority="high",
            privacy_policy="local_only",
        ),
    )


# ── Legacy Modernization Workers ──────────────────────────────────────────────

class LegacySystemsResearchEngineer(WorkforceWorker):
    specialized_type = "legacy_systems_research_engineer"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="legacy_systems_research_engineer",
        capabilities=["legacy_research", "history_extraction"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["legacy_research_brief"],
        default_loop_type="legacy_discovery",
        model_profile=WorkerModelProfile(
            worker_type="legacy_systems_research_engineer",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
            min_context_window_tokens=16384,
            reasoning_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class LegacyCodeArchaeologist(WorkforceWorker):
    specialized_type = "legacy_code_archaeologist"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="legacy_code_archaeologist",
        capabilities=["code_archaeology", "dead_code_detection"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["code_archaeology_finding"],
        default_loop_type="legacy_code_archaeology",
        model_profile=WorkerModelProfile(
            worker_type="legacy_code_archaeologist",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.TEXT_GENERATION],
            min_context_window_tokens=32768,
            coding_required=True,
            quality_priority=4,
            privacy_policy="local_only",
        ),
    )

class LegacyArchitectureAnalyst(WorkforceWorker):
    specialized_type = "legacy_architecture_analyst"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="legacy_architecture_analyst",
        capabilities=["architecture_reconstruction", "boundary_analysis"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["architecture_reconstruction_proposal"],
        default_loop_type="legacy_architecture_reconstruction",
        model_profile=WorkerModelProfile(
            worker_type="legacy_architecture_analyst",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            reasoning_required=True,
            structured_output_required=True,
            quality_priority=4,
            privacy_policy="local_only",
        ),
    )

class LegacyDataEngineer(WorkforceWorker):
    specialized_type = "legacy_data_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="legacy_data_engineer",
        capabilities=["legacy_schema_extraction", "lineage_analysis"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["legacy_schema_report"],
        default_loop_type="legacy_data_analysis",
        model_profile=WorkerModelProfile(
            worker_type="legacy_data_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class LegacyIntegrationEngineer(WorkforceWorker):
    specialized_type = "legacy_integration_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="legacy_integration_engineer",
        capabilities=["integration_discovery", "api_mapping"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["legacy_integration_map"],
        default_loop_type="legacy_integration_analysis",
        model_profile=WorkerModelProfile(
            worker_type="legacy_integration_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            coding_required=True,
            structured_output_required=True,
            quality_priority=3,
            privacy_policy="local_only",
        ),
    )

class BusinessRulesAnalyst(WorkforceWorker):
    specialized_type = "business_rules_analyst"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="business_rules_analyst",
        capabilities=["business_rule_extraction", "conflict_detection"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["business_rules_list"],
        default_loop_type="business_rule_extraction",
        model_profile=WorkerModelProfile(
            worker_type="business_rules_analyst",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            reasoning_required=True,
            structured_output_required=True,
            quality_priority=4,
            privacy_policy="local_only",
        ),
    )

class DependencyImpactAnalyst(WorkforceWorker):
    specialized_type = "dependency_impact_analyst"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="dependency_impact_analyst",
        capabilities=["dependency_graph_traversal", "impact_analysis"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["impact_analysis_report"],
        default_loop_type="dependency_impact_analysis",
        model_profile=WorkerModelProfile(
            worker_type="dependency_impact_analyst",
            required_capabilities=[CapabilityIds.REASONING, CapabilityIds.STRUCTURED_OUTPUT, CapabilityIds.TOOL_USE],
            min_context_window_tokens=16384,
            reasoning_required=True,
            structured_output_required=True,
            tool_use_required=True,
            quality_priority=4,
            privacy_policy="local_only",
        ),
    )

class ModernizationArchitect(WorkforceWorker):
    specialized_type = "modernization_architect"
    base_type = BaseWorkerType.RESEARCH
    expertise = ExpertiseModel(
        worker_type="modernization_architect",
        capabilities=["modernization_strategy", "tradeoff_analysis"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read"])],
        expected_artifacts=["modernization_proposal"],
        default_loop_type="modernization_architecture",
        model_profile=WorkerModelProfile(
            worker_type="modernization_architect",
            required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=16384,
            reasoning_required=True,
            structured_output_required=True,
            quality_priority=5,
            privacy_policy="local_only",
        ),
    )

class MigrationEngineer(WorkforceWorker):
    specialized_type = "migration_engineer"
    base_type = BaseWorkerType.CODING
    expertise = ExpertiseModel(
        worker_type="migration_engineer",
        capabilities=["migration_planning", "sequencing"],
        permissions=[Permission(permission_id="fs", resource="*", allowed_operations=["read", "write", "execute"])],
        expected_artifacts=["migration_plan"],
        default_loop_type="migration_planning",
        model_profile=WorkerModelProfile(
            worker_type="migration_engineer",
            required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.TOOL_USE, CapabilityIds.STRUCTURED_OUTPUT],
            min_context_window_tokens=32768,
            coding_required=True,
            tool_use_required=True,
            structured_output_required=True,
            quality_priority=4,
            reliability_minimum=0.98,
            privacy_policy="local_only",
        ),
    )


# ── Register all workers into WORKER_REGISTRY ────────────────────────────────

WORKER_CLASSES = [
    # Greenfield
    ResearchEngineer,
    ArchitectureEngineer,
    PlanningEngineer,
    UIDesigner,
    BackendEngineer,
    FrontendEngineer,
    DatabaseEngineer,
    MLEngineer,
    InfrastructureEngineer,
    DevOpsEngineer,
    QAEngineer,
    SecurityEngineer,
    PerformanceEngineer,
    DocumentationEngineer,
    # Legacy
    LegacySystemsResearchEngineer,
    LegacyCodeArchaeologist,
    LegacyArchitectureAnalyst,
    LegacyDataEngineer,
    LegacyIntegrationEngineer,
    BusinessRulesAnalyst,
    DependencyImpactAnalyst,
    ModernizationArchitect,
    MigrationEngineer,
]

def register_all_workers():
    workers_meta = [
        # Greenfield
        (ResearchEngineer, "research_engineer", ["research", "general"]),
        (ArchitectureEngineer, "architecture_engineer", ["architecture", "research"]),
        (PlanningEngineer, "planning_engineer", ["planning", "plan", "research"]),
        (UIDesigner, "ui_designer", ["ui_design", "ui", "general"]),
        (BackendEngineer, "backend_engineer", ["coding", "backend", "general"]),
        (FrontendEngineer, "frontend_engineer", ["coding", "frontend", "general"]),
        (DatabaseEngineer, "database_engineer", ["database", "schema", "coding"]),
        (MLEngineer, "ml_engineer", ["ml", "coding"]),
        (InfrastructureEngineer, "infrastructure_engineer", ["infrastructure", "iac", "coding"]),
        (DevOpsEngineer, "devops_engineer", ["devops", "cicd", "coding"]),
        (QAEngineer, "qa_engineer", ["qa", "testing"]),
        (SecurityEngineer, "security_engineer", ["security", "review"]),
        (PerformanceEngineer, "performance_engineer", ["performance", "review"]),
        (DocumentationEngineer, "documentation_engineer", ["documentation", "general"]),
        # Legacy
        (LegacySystemsResearchEngineer, "legacy_systems_research_engineer", ["legacy_research", "research"]),
        (LegacyCodeArchaeologist, "legacy_code_archaeologist", ["code_archaeology", "research"]),
        (LegacyArchitectureAnalyst, "legacy_architecture_analyst", ["architecture_reconstruction", "research"]),
        (LegacyDataEngineer, "legacy_data_engineer", ["legacy_data", "coding"]),
        (LegacyIntegrationEngineer, "legacy_integration_engineer", ["legacy_integration", "coding"]),
        (BusinessRulesAnalyst, "business_rules_analyst", ["business_rule_extraction", "research"]),
        (DependencyImpactAnalyst, "dependency_impact_analyst", ["dependency_impact_analysis", "research"]),
        (ModernizationArchitect, "modernization_architect", ["modernization_architecture", "research"]),
        (MigrationEngineer, "migration_engineer", ["migration_planning", "coding"]),
    ]

    for cls, specialized_type, tasks in workers_meta:
        WORKER_REGISTRY.register(
            worker_type=specialized_type,
            worker_class=cls,
            expertise=cls.expertise,
            compatible_tasks=tasks,
        )

# Call registration
register_all_workers()
