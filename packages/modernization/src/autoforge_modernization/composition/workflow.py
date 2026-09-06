"""Dynamic Capability Composition Workflow for AutoForge.

Enforces Section 14 of the architectural mandate:
Workflows are assembled dynamically from capabilities:
Discovery
+ Source Understanding
+ Neutral Semantic Model
+ Target Derivation
+ Gap Analysis
+ Target Planning
+ Target Generation
+ Target Verification
+ Failure Diagnosis & Repair
+ Provenance & Verified Engineering Artifact

WITHOUT requiring a dedicated COBOLToJavaEngine or any migration pair classes.
"""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import uuid
from typing import Any

from pydantic import BaseModel, Field

from autoforge_modernization.capabilities.acquisition import (
    AcquisitionStatus,
    AutonomousAcquisitionEngine,
)
from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalysisReport,
    CapabilityGapAnalyzer,
)
from autoforge_modernization.capabilities.models import CapabilityState, _utc_now
from autoforge_modernization.capabilities.providers import ProviderRegistry
from autoforge_modernization.capabilities.requirement_graph import (
    CapabilityRequirementGraph,
)
from autoforge_modernization.composition.generator import (
    GeneratedArtifact,
    GenericTargetArtifactGenerator,
)
from autoforge_modernization.composition.planner import (
    GenericTransformationPlanner,
    TransformationPlan,
)
from autoforge_modernization.composition.repair import AutonomousTargetRepairCycle
from autoforge_modernization.composition.verifier import (
    TargetToolchainVerifier,
    TargetVerificationResult,
)
from autoforge_modernization.discovery.engine import ProjectTechnologyDiscoveryEngine
from autoforge_modernization.discovery.inventory import ProjectTechnologyInventory
from autoforge_modernization.provenance import (
    ModernizationProvenanceChain,
    ProvenanceLink,
    ProvenanceStage,
)
from autoforge_modernization.repair_cycle import RepairOutcome
from autoforge_modernization.semantic.extractors import SemanticModelExtractor
from autoforge_modernization.semantic.model import (
    TechnologyNeutralSemanticModel,
)
from autoforge_modernization.target.specification import (
    TargetCapabilityDeriver,
    TargetSpecification,
)


class WorkflowStageResult(BaseModel):
    stage_name: str
    passed: bool
    details: dict[str, Any] = Field(default_factory=dict)
    duration_ms: float = 0.0


class CompositionWorkflowReport(BaseModel):
    """Execution report proving dynamic capability composition without pair hardcoding."""

    workflow_id: str = Field(default_factory=lambda: str(uuid.uuid4()))
    project_path: str
    target_specification: TargetSpecification
    source_technologies_detected: list[str] = Field(default_factory=list)
    stages: list[WorkflowStageResult] = Field(default_factory=list)
    transformation_plan: TransformationPlan | None = None
    gap_report: CapabilityGapAnalysisReport | None = None
    composed_capabilities: list[str] = Field(default_factory=list)
    unsupported_constructs_count: int = 0
    generated_artifacts: list[GeneratedArtifact] = Field(default_factory=list)
    verification_result: TargetVerificationResult | None = None
    repair_outcome: RepairOutcome | None = None
    provenance_chain: ModernizationProvenanceChain | None = None
    class_files_generated: list[str] = Field(default_factory=list)
    success: bool = True
    executed_at: datetime = Field(default_factory=_utc_now)


class DynamicCapabilityWorkflow:
    """Orchestrator that dynamically composes capabilities for any source project and target specification."""

    def __init__(
        self,
        provider_registry: ProviderRegistry | None = None,
        requirement_graph: CapabilityRequirementGraph | None = None,
    ) -> None:
        self.provider_registry = provider_registry or ProviderRegistry()
        self.requirement_graph = requirement_graph or CapabilityRequirementGraph()
        self.discovery_engine = ProjectTechnologyDiscoveryEngine(
            requirement_graph=self.requirement_graph
        )
        self.target_deriver = TargetCapabilityDeriver()
        self.gap_analyzer = CapabilityGapAnalyzer(provider_registry=self.provider_registry)
        self.semantic_extractor = SemanticModelExtractor()
        self.planner = GenericTransformationPlanner()
        self.target_generator = GenericTargetArtifactGenerator()
        self.verifier = TargetToolchainVerifier(provider_registry=self.provider_registry)
        self.repair_cycle = AutonomousTargetRepairCycle(verifier=self.verifier)
        self.acquisition_engine = AutonomousAcquisitionEngine(
            provider_registry=self.provider_registry,
            allow_external_install=False,
        )

    def execute(
        self,
        project_path: str | Path,
        target_spec: TargetSpecification,
        project_id: str = "composed-workflow",
        workload_files: list[str] | None = None,
        build_directory: Path | None = None,
        inject_defect_for_repair_proof: bool = False,
    ) -> CompositionWorkflowReport:
        report = CompositionWorkflowReport(
            project_path=str(project_path),
            target_specification=target_spec,
        )
        root_path = Path(project_path)

        # ── Stage 1: Technology Discovery ──────────────────────────────────
        t0 = datetime.now()
        inventory = self.discovery_engine.discover(project_path)
        report.source_technologies_detected = inventory.detected_technology_names()
        report.stages.append(
            WorkflowStageResult(
                stage_name="discovery",
                passed=len(inventory.technologies) > 0,
                details={
                    "technologies": report.source_technologies_detected,
                    "primary": inventory.primary_technology,
                    "files": inventory.total_files_scanned,
                    "loc": inventory.total_physical_loc,
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 2: Capability Requirements Resolution ─────────────────────
        t0 = datetime.now()
        source_reqs = inventory.all_implied_requirements
        target_reqs = self.target_deriver.derive_requirements(target_spec)
        all_reqs = source_reqs + target_reqs
        report.stages.append(
            WorkflowStageResult(
                stage_name="requirements_resolution",
                passed=len(all_reqs) > 0,
                details={
                    "source_requirements_count": len(source_reqs),
                    "target_requirements_count": len(target_reqs),
                    "total_requirements": len(all_reqs),
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 3: Capability Gap Analysis & Autonomous Preparation ────────
        t0 = datetime.now()
        initial_gap_report = self.gap_analyzer.analyze(
            all_reqs,
            project_id=project_id,
            target_technology=target_spec.language,
        )

        # Attempt safe autonomous acquisition/preparation for acquirable gaps
        acquired_any = False
        for item in initial_gap_report.items:
            if item.state == CapabilityState.ACQUIRABLE:
                rec = self.acquisition_engine.process_gap_item(item)
                if rec.status == AcquisitionStatus.SUCCESS:
                    acquired_any = True

        # Re-evaluate gaps if any capability was acquired/prepared & qualified
        gap_report = self.gap_analyzer.analyze(
            all_reqs,
            project_id=project_id,
            target_technology=target_spec.language,
        ) if acquired_any else initial_gap_report

        report.gap_report = gap_report
        report.composed_capabilities = [
            f"{c.technology}:{c.capability_name}" for c in gap_report.operational_capabilities
        ]
        report.stages.append(
            WorkflowStageResult(
                stage_name="gap_analysis",
                passed=True,
                details=gap_report.summary(),
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 4: Technology-Neutral Semantic Extraction ────────────────
        t0 = datetime.now()
        semantic_model = TechnologyNeutralSemanticModel(project_id=project_id)

        files_to_extract: list[tuple[str, Path]] = []
        if workload_files:
            for rel in workload_files:
                f_full = root_path / rel
                if f_full.exists():
                    files_to_extract.append((rel, f_full))
        else:
            # Default to sample files from discovery
            for tech_name, tech_summary in inventory.technologies.items():
                if tech_name == "COBOL":
                    for rel_file in tech_summary.sample_files[:5]:
                        fpath = root_path / rel_file
                        if fpath.exists():
                            files_to_extract.append((rel_file, fpath))
                elif tech_name == "JCL":
                    for rel_file in tech_summary.sample_files[:3]:
                        fpath = root_path / rel_file
                        if fpath.exists():
                            files_to_extract.append((rel_file, fpath))

        for rel_file, fpath in files_to_extract:
            try:
                content = fpath.read_text(encoding="utf-8", errors="replace")
                ext = fpath.suffix.lower()
                if ext in (".cbl", ".cob", ".cobol"):
                    mod = self.semantic_extractor.extract_from_cobol(content, rel_file)
                    semantic_model.add_module(mod)
                elif ext in (".jcl", ".job"):
                    mod = self.semantic_extractor.extract_from_jcl(content, rel_file)
                    semantic_model.add_module(mod)
            except Exception:
                pass

        report.unsupported_constructs_count = semantic_model.total_unsupported_constructs
        report.stages.append(
            WorkflowStageResult(
                stage_name="semantic_extraction",
                passed=semantic_model.total_modules > 0 or len(inventory.technologies) == 0,
                details={
                    "modules": semantic_model.total_modules,
                    "procedures": semantic_model.total_procedures,
                    "unsupported_constructs": semantic_model.total_unsupported_constructs,
                    "files_extracted": [f[0] for f in files_to_extract],
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 5: Generic Transformation Planning ───────────────────────
        t0 = datetime.now()
        plan = self.planner.plan(semantic_model, target_spec, gap_report)
        report.transformation_plan = plan
        report.stages.append(
            WorkflowStageResult(
                stage_name="transformation_planning",
                passed=len(plan.target_components) > 0 or len(inventory.technologies) == 0,
                details={
                    "target_components_count": len(plan.target_components),
                    "verification_checks_count": len(plan.verification_strategy),
                    "can_proceed": plan.can_proceed,
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 6: Target Generation ─────────────────────────────────────
        t0 = datetime.now()
        artifacts = self.target_generator.generate(semantic_model, plan, target_spec)

        if inject_defect_for_repair_proof and artifacts:
            # Intentionally inject compile defect for autonomous failure handling proof
            artifacts[0].code = "DEFECT_INJECTED_BAD_TOKEN;\n" + artifacts[0].code

        report.generated_artifacts = artifacts
        report.stages.append(
            WorkflowStageResult(
                stage_name="target_generation",
                passed=len(artifacts) > 0 or len(plan.target_components) == 0,
                details={
                    "artifacts_count": len(artifacts),
                    "target_language": target_spec.language,
                    "defect_injected": inject_defect_for_repair_proof,
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 7: Real Target Toolchain Verification ─────────────────────
        t0 = datetime.now()
        verify_result = self.verifier.verify(
            artifacts=artifacts,
            target_spec=target_spec,
            build_directory=build_directory,
        )
        report.verification_result = verify_result
        report.class_files_generated = verify_result.class_files_generated
        report.stages.append(
            WorkflowStageResult(
                stage_name="target_verification",
                passed=verify_result.passed,
                details={
                    "toolchain": verify_result.toolchain_used,
                    "command": verify_result.command_executed,
                    "class_files_count": len(verify_result.class_files_generated),
                    "diagnostics_count": len(verify_result.diagnostics),
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        # ── Stage 8: Autonomous Failure Handling (Diagnosis & Repair) ──────
        t0 = datetime.now()
        if not verify_result.passed:
            repaired_artifacts, repair_outcome, re_verify_result = self.repair_cycle.repair_cycle(
                artifacts=artifacts,
                initial_result=verify_result,
                target_spec=target_spec,
            )
            report.repair_outcome = repair_outcome
            report.generated_artifacts = repaired_artifacts
            report.verification_result = re_verify_result
            report.class_files_generated = re_verify_result.class_files_generated
            report.stages.append(
                WorkflowStageResult(
                    stage_name="failure_diagnosis_and_repair",
                    passed=re_verify_result.passed,
                    details={
                        "repair_status": repair_outcome.final_status.value,
                        "attempts_used": repair_outcome.total_attempts,
                        "re_verification_passed": re_verify_result.passed,
                        "class_files_count": len(re_verify_result.class_files_generated),
                    },
                    duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
                )
            )
        else:
            report.stages.append(
                WorkflowStageResult(
                    stage_name="failure_diagnosis_and_repair",
                    passed=True,
                    details={"status": "not_required_initial_verification_passed"},
                    duration_ms=0.0,
                )
            )

        # ── Stage 9: Provenance & Verified Engineering Artifact ─────────────
        t0 = datetime.now()
        prov_chain = ModernizationProvenanceChain(
            project_id=project_id,
            job_id=report.workflow_id,
        )

        # 1. Source Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.SOURCE,
                actor="ProjectTechnologyDiscoveryEngine",
                notes=f"Discovered {len(inventory.technologies)} technologies from {inventory.total_files_scanned} files.",
                output_evidence_ids=report.source_technologies_detected,
            )
        )
        # 2. Capability Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.ANALYSIS,
                actor="AutonomousAcquisitionEngine",
                notes=f"Resolved {len(report.composed_capabilities)} operational capabilities.",
                output_evidence_ids=report.composed_capabilities,
            )
        )
        # 3. Semantic Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.EVIDENCE,
                actor="SemanticModelExtractor",
                notes=f"Extracted {semantic_model.total_modules} modules, {semantic_model.total_procedures} procedures.",
                output_evidence_ids=[m.name for m in semantic_model.modules.values()],
            )
        )
        # 4. Plan Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.PLAN,
                actor="GenericTransformationPlanner",
                notes=f"Transformation plan produced for target {target_spec.language}.",
                output_artifact_ids=[c.component_id for c in plan.target_components],
            )
        )
        # 5. Transformation Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.TRANSFORMATION,
                actor="GenericTargetArtifactGenerator",
                notes=f"Generated {len(report.generated_artifacts)} target artifacts.",
                output_artifact_ids=[a.artifact_id for a in report.generated_artifacts],
            )
        )
        # 6. Verification Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.VERIFICATION,
                actor="TargetToolchainVerifier",
                tool_id=report.verification_result.toolchain_used if report.verification_result else "unknown",
                notes=f"Real toolchain verification: passed={report.verification_result.passed if report.verification_result else False}.",
                output_evidence_ids=report.class_files_generated,
            )
        )
        # 7. Artifact Link
        prov_chain.add_link(
            ProvenanceLink(
                stage=ProvenanceStage.ARTIFACT,
                actor="DynamicCapabilityWorkflow",
                notes=f"Verified engineering artifact package published with {len(report.class_files_generated)} bytecode classes.",
                output_artifact_ids=[a.artifact_id for a in report.generated_artifacts],
            )
        )

        prov_chain.is_complete = report.verification_result.passed if report.verification_result else False
        report.provenance_chain = prov_chain

        report.stages.append(
            WorkflowStageResult(
                stage_name="provenance_binding",
                passed=len(prov_chain.links) >= 7,
                details={
                    "chain_id": prov_chain.chain_id,
                    "links_count": len(prov_chain.links),
                    "stages_completed": [s.value for s in prov_chain.get_stages_completed()],
                },
                duration_ms=(datetime.now() - t0).total_seconds() * 1000.0,
            )
        )

        report.success = (
            (report.verification_result is not None and report.verification_result.passed)
            and all(s.passed for s in report.stages if s.stage_name != "target_verification" or report.repair_outcome is None)
        )
        return report
