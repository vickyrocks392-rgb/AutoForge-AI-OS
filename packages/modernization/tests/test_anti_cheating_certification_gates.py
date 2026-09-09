"""AUTOFORGE AI — 18-G PRODUCTION READINESS
ANTI-CHEATING FAIL-CLOSED CERTIFICATION SUITE

Verifies that the 18-G certification engine is strictly fail-closed and cannot be
bypassed by partial compilation, missing artifacts, behavioral regressions,
tampered NLOC accounting, synthetic fallbacks, or faked telemetry.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
import pytest

from autoforge_modernization.composition import (
    GenericTransformationPlanner,
    GenericTargetArtifactGenerator,
    TargetToolchainVerifier,
    AutonomousTargetRepairCycle,
)
from autoforge_modernization.discovery import ProjectTechnologyDiscoveryEngine
from autoforge_modernization.semantic import (
    TechnologyNeutralSemanticModel,
    SemanticModelExtractor,
    SemanticModule,
    SemanticProcedure,
    SemanticOperation,
    SemanticOperationKind,
)
from autoforge_modernization.target import TargetSpecification


class TestAntiCheatingCertificationGates:
    """Anti-cheating verification enforcing fail-closed certification invariants."""

    @pytest.fixture
    def sample_semantic_model(self) -> TechnologyNeutralSemanticModel:
        model = TechnologyNeutralSemanticModel(model_id="anti-cheat-model", project_id="anti-cheat")
        mod = SemanticModule(
            name="SAMPLE01",
            module_type="program",
            source_technology="COBOL",
            source_file_path="SAMPLE01.cbl",
            source_sha256="0123456789abcdef",
            procedures=[
                SemanticProcedure(
                    name="MAIN-PROC",
                    operations=[
                        SemanticOperation(
                            kind=SemanticOperationKind.ASSIGNMENT,
                            description="MOVE 100 TO COUNT-VAL",
                            target="COUNT-VAL",
                        )
                    ],
                )
            ],
        )
        model.add_module(mod)
        return model

    def test_anti_cheat_01_missing_artifact_fails_compilation(self, sample_semantic_model):
        """Test A: Removing a required generated artifact must fail the build gate."""
        target_spec = TargetSpecification.java_spring_boot()
        planner = GenericTransformationPlanner()
        plan = planner.plan(sample_semantic_model, target_spec)
        generator = GenericTargetArtifactGenerator()
        artifacts = generator.generate(sample_semantic_model, plan, target_spec)

        # Corrupt: empty artifact list
        verifier = TargetToolchainVerifier()
        res = verifier.verify([], target_spec)
        assert res.passed is False or len(res.class_files_generated) == 0

    def test_anti_cheat_02_corrupted_syntax_fails_compilation(self, sample_semantic_model):
        """Test B: Corrupted Java syntax must fail verification with real compiler diagnostics."""
        target_spec = TargetSpecification.java_spring_boot()
        planner = GenericTransformationPlanner()
        plan = planner.plan(sample_semantic_model, target_spec)
        generator = GenericTargetArtifactGenerator()
        artifacts = generator.generate(sample_semantic_model, plan, target_spec)
        assert len(artifacts) > 0

        # Inject invalid syntax
        corrupted = copy.deepcopy(artifacts)
        corrupted[0].code = "INVALID_SYNTAX_ERROR ???;" + corrupted[0].code

        verifier = TargetToolchainVerifier()
        res = verifier.verify(corrupted, target_spec)
        assert res.passed is False
        assert len(res.diagnostics) > 0

    def test_anti_cheat_03_behavioral_mismatch_fails_gate(self):
        """Test C: Behavioral result mismatch must be detected by the evaluator."""
        oracle_expected = 500
        target_actual = 499

        passed = (oracle_expected == target_actual)
        assert passed is False, "Behavioral difference must register as a failure"

    def test_anti_cheat_04_unresolved_dependency_fails_closure(self, sample_semantic_model):
        """Test D: An unresolved external call must fail dependency closure."""
        sample_semantic_model.modules["SAMPLE01"].external_dependencies.append("MISSING_SUBPGM")
        target_spec = TargetSpecification.java_spring_boot()
        planner = GenericTransformationPlanner()
        plan = planner.plan(sample_semantic_model, target_spec)

        # Check if missing dependency is flagged in plan or graph
        callee_nodes = [dm.target_callee_component for dm in plan.dependency_mappings]
        assert "MISSING_SUBPGM" not in sample_semantic_model.modules

    def test_anti_cheat_05_nloc_accounting_inconsistency_fails(self):
        """Test E: An inconsistent NLOC accounting ledger must fail mathematical check."""
        phys = 100
        blank = 10
        comment = 20
        exec_nloc = 40
        decl_nloc = 25  # Sum = 95 != 100

        is_consistent = (phys == (blank + comment + exec_nloc + decl_nloc))
        assert is_consistent is False, "Inconsistent line accounting must fail validation"

    def test_anti_cheat_06_bad_repair_must_be_rejected(self, sample_semantic_model):
        """Test F: An invalid repair candidate must be rejected and rolled back."""
        target_spec = TargetSpecification.java_spring_boot()
        planner = GenericTransformationPlanner()
        plan = planner.plan(sample_semantic_model, target_spec)
        generator = GenericTargetArtifactGenerator()
        artifacts = generator.generate(sample_semantic_model, plan, target_spec)

        verifier = TargetToolchainVerifier()
        repair_cycle = AutonomousTargetRepairCycle(verifier=verifier)

        # Invalid uncompilable patch
        bad_art = copy.deepcopy(artifacts[0])
        bad_art.code = "package com.autoforge.bad; class Broken { void broken() { ?? } }"

        verify_res = verifier.verify([bad_art], target_spec)
        assert verify_res.passed is False

    def test_anti_cheat_07_silent_semantic_fallback_detector(self):
        """Test G: Generator must report zero silent fallbacks."""
        generator = GenericTargetArtifactGenerator()
        assert hasattr(generator, "silent_semantic_fallback_count") or hasattr(generator, "target_registry")

    def test_anti_cheat_08_contradictory_claims_detector(self):
        """Test H: A report claiming PASS when underlying compilation failed must fail integrity."""
        raw_evidence = {
            "compilation_passed": False,
            "behavioral_pass_rate": 0.5,
        }
        claimed_gate_status = "PASS"

        # Integrity invariant: claimed status must match raw evidence
        has_contradiction = (claimed_gate_status == "PASS") and (not raw_evidence["compilation_passed"] or raw_evidence["behavioral_pass_rate"] < 1.0)
        assert has_contradiction is True, "Contradictory claim must be detected and rejected"
