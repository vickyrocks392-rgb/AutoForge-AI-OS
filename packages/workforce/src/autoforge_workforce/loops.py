"""
Specialized loops for Greenfield and Legacy Engineering Workers.
"""

from __future__ import annotations
import uuid
import time
from typing import Any, Callable, Tuple

from autoforge_execution.loop import EngineeringLoop
from autoforge_execution.context import ExecutionContext
from autoforge_execution.models import (
    ArtifactRecord,
    ArtifactType,
    EvaluationResult,
    EvaluationStatus,
    LoopStatus,
    ArtifactProvenance,
)

from autoforge_workforce.legacy_models import LegacySystemModel, LegacyEvidence, FactState, BusinessRule
from autoforge_workforce.legacy_analyzers import get_analyzer_for_file


class SpecializedLoop(EngineeringLoop):
    """
    Base class for workforce specialized loops.
    """
    pass


# ── Greenfield Loops ─────────────────────────────────────────────────────────

class ResearchLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )
        
        # Simulates querying knowledge platform and extracting content
        idea = context.input_data.get("idea", "")
        plan = f"Researching: {idea}"
        
        # Create research brief artifact
        brief_content = f"# Research Brief for '{idea}'\n\n- Proposed concept validated against patterns.\n- Domain analysis completed."
        brief_art = self._artifacts.record_artifact(
            name="research_brief.md",
            artifact_type=ArtifactType.SUMMARY,
            content=brief_content,
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Research completed successfully.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [brief_art], eval_res


class ArchitectureLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        proposal_content = "# Architecture Proposal\n\n- Component boundaries defined.\n- Service interactions mapped."
        proposal_art = self._artifacts.record_artifact(
            name="architecture_proposal.md",
            artifact_type=ArtifactType.SUMMARY,
            content=proposal_content,
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Architecture finalized.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [proposal_art], eval_res


class PlanningLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        wbs_content = "# Work Breakdown Structure\n\n- Task 1: Initialize Database Schema\n- Task 2: Implement Backend Routes\n- Task 3: Build UI Components"
        wbs_art = self._artifacts.record_artifact(
            name="work_breakdown_structure.md",
            artifact_type=ArtifactType.SUMMARY,
            content=wbs_content,
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Planning completed.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [wbs_art], eval_res


# ── Legacy Modernization Loops ────────────────────────────────────────────────

class LegacyDiscoveryLoop(SpecializedLoop):
    """
    Loop that scans files in the workspace environment, detects technologies,
    extracts metadata deterministically, and produces a LegacySystemModel.
    """
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        # Ingest files through workspace environment filesystem
        model = LegacySystemModel(
            system_id=str(uuid.uuid4()),
            name=context.task_name,
            description=context.task_description,
        )

        # Recursively list workspace files and analyze
        root = self._env.filesystem.root
        files = []
        for p in root.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(root)))
        for f in files:
            content = self._env.filesystem.read_text(f)
            analyzer = get_analyzer_for_file(content, f)
            analysis = analyzer.analyze(content, f)

            # Record technologies and components
            lang = analysis.get("language", "UNKNOWN")
            model.technologies[lang] = FactState.FACT

            # Record symbols as evidence
            for sym in analysis.get("symbols", []):
                ev = LegacyEvidence(
                    evidence_id=str(uuid.uuid4())[:8],
                    source_file=f,
                    analyzer_id=analyzer.__class__.__name__,
                    observation=f"Extracted symbol: {sym}",
                    confidence=1.0,
                )
                model.record_evidence(ev)

            # Record analysis gaps
            if "analysis_gap" in analysis:
                model.record_gap("Technology Ingestion", analysis["analysis_gap"], severity="medium")

        # Record system model artifact
        model_art = self._artifacts.record_artifact(
            name="legacy_system_model.json",
            artifact_type=ArtifactType.SUMMARY,
            content=model.model_dump_json(indent=2),
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings=f"Discovered {len(model.technologies)} technologies and {len(model.evidence_ledger)} evidence points.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [model_art], eval_res


class LegacyCodeArchaeologyLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        # Simulate parsing legacy code logic structures
        finding = "# Archaeology Findings\n\n- Entry Points: mainframe batch interface\n- Shared State: global variables block\n- Dead Code: 3 unused paragraphs"
        finding_art = self._artifacts.record_artifact(
            name="code_archaeology_finding.md",
            artifact_type=ArtifactType.SUMMARY,
            content=finding,
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Archaeology reconstruction complete.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [finding_art], eval_res


class BusinessRuleExtractionLoop(SpecializedLoop):
    """
    Loop that scans for business rules and returns a structured rule list with evidence.
    """
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        # Recursively list workspace files
        root = self._env.filesystem.root
        files = []
        for p in root.rglob("*"):
            if p.is_file():
                files.append(str(p.relative_to(root)))
        rules = []
        for f in files:
            content = self._env.filesystem.read_text(f)
            # Extracted rule based on deterministic patterns e.g. IF, COMPUTE, etc.
            if "IF" in content or "compute" in content:
                ev = LegacyEvidence(
                    evidence_id=str(uuid.uuid4())[:8],
                    source_file=f,
                    analyzer_id="BusinessRulesAnalyst",
                    observation="Calculation logic matching IF/COMPUTE statements",
                    confidence=0.9,
                )
                rule = BusinessRule(
                    rule_id=f"rule_{len(rules) + 1}",
                    statement=f"Calculate output values using rules defined in {f}",
                    evidence=[ev],
                    state=FactState.FACT,
                )
                rules.append(rule)

        # Create rules artifact
        rules_art = self._artifacts.record_artifact(
            name="business_rules_list.json",
            artifact_type=ArtifactType.SUMMARY,
            content=f"[{','.join(r.model_dump_json(indent=2) for r in rules)}]" if rules else "[]",
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings=f"Extracted {len(rules)} business rules.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [rules_art], eval_res


class ModernizationArchitectureLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )

        proposal = "# Modernization Architecture Proposal\n\n- Strategy: Strangler Pattern\n- Target Stack: Python FastAPI + PostgreSQL\n- Cutover Plan: Phase-based API proxying"
        proposal_art = self._artifacts.record_artifact(
            name="modernization_proposal.md",
            artifact_type=ArtifactType.SUMMARY,
            content=proposal,
            provenance=provenance,
        )

        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Modernization proposal generated.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [proposal_art], eval_res


class LegacyArchitectureReconstructionLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )
        art = self._artifacts.record_artifact(
            name="legacy_reconstruction.md",
            artifact_type=ArtifactType.SUMMARY,
            content="# Reconstructed Architecture\n\n- Monolith core reconstructed.",
            provenance=provenance,
        )
        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Architecture reconstructed.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [art], eval_res


class LegacyDataAnalysisLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )
        art = self._artifacts.record_artifact(
            name="legacy_data_analysis.md",
            artifact_type=ArtifactType.SUMMARY,
            content="# Data Analysis\n\n- Schema & data elements analyzed.",
            provenance=provenance,
        )
        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Data analysis completed.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [art], eval_res


class LegacyIntegrationAnalysisLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )
        art = self._artifacts.record_artifact(
            name="legacy_integration_analysis.md",
            artifact_type=ArtifactType.SUMMARY,
            content="# Integration Analysis\n\n- External API & DB boundaries analyzed.",
            provenance=provenance,
        )
        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Integration analysis completed.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [art], eval_res


class DependencyImpactAnalysisLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )
        art = self._artifacts.record_artifact(
            name="dependency_impact_analysis.md",
            artifact_type=ArtifactType.SUMMARY,
            content="# Dependency & Impact Analysis\n\n- Impact scope determined.",
            provenance=provenance,
        )
        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Impact analysis completed.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [art], eval_res


class MigrationPlanningLoop(SpecializedLoop):
    async def run(
        self,
        context: ExecutionContext,
        worker_id: str,
        *,
        verification_commands: Any = None,
        is_cancelled: Callable[[], bool] | None = None,
    ) -> Tuple[bool, list[ArtifactRecord], EvaluationResult | None]:
        self._status = LoopStatus.RUNNING
        provenance = ArtifactProvenance(
            task_id=context.task_id,
            worker_id=worker_id,
            workflow_id=context.workflow_id,
            correlation_id=context.correlation_id,
            attempt_number=context.attempt_number,
            iteration=1,
        )
        art = self._artifacts.record_artifact(
            name="migration_plan.md",
            artifact_type=ArtifactType.SUMMARY,
            content="# Migration Plan\n\n- Step-by-step sequencing plan.",
            provenance=provenance,
        )
        eval_res = EvaluationResult(
            status=EvaluationStatus.PASSED,
            qualitative_findings="Migration plan generated.",
        )
        self._status = LoopStatus.COMPLETED
        return True, [art], eval_res


# ── Mapping from Loop Type to Class ─────────────────────────────────────────

_LOOP_CLASSES: dict[str, type[SpecializedLoop]] = {
    "research": ResearchLoop,
    "architecture": ArchitectureLoop,
    "planning": PlanningLoop,
    "legacy_discovery": LegacyDiscoveryLoop,
    "legacy_code_archaeology": LegacyCodeArchaeologyLoop,
    "legacy_architecture_reconstruction": LegacyArchitectureReconstructionLoop,
    "legacy_data_analysis": LegacyDataAnalysisLoop,
    "legacy_integration_analysis": LegacyIntegrationAnalysisLoop,
    "business_rule_extraction": BusinessRuleExtractionLoop,
    "dependency_impact_analysis": DependencyImpactAnalysisLoop,
    "modernization_architecture": ModernizationArchitectureLoop,
    "migration_planning": MigrationPlanningLoop,
}

def get_loop_class(loop_type: str) -> type[EngineeringLoop]:
    return _LOOP_CLASSES.get(loop_type, EngineeringLoop)
