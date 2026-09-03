"""D3 regression tests: MigrationUnitSpec.source_technology propagation.

These tests cover the D3 fix: MigrationUnitSpec now has source_technology and
source_language fields, _derive_default_plan() populates source_technology from
detected_name, and _run_wave() fails fast with a clear error when source_technology
is missing (instead of silently falling back to target_language="java").
"""
from __future__ import annotations

import pytest

from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies
from autoforge_modernization.strategy import MigrationUnitSpec, MigrationStrategy
from autoforge_modernization.pipeline import ModernizationPipeline
from autoforge_modernization.analysis import (
    LegacyAnalysisEngine,
    TechnologyAnalysisStage1,
    AnalysisReport,
)
from autoforge_modernization.knowledge import (
    TechnologyKnowledge,
    TechnologyFamily,
    ModernizationPath,
)


class TestSourceTechnologyPropagation:

    def test_cobol_source_gets_cobol_refactor_strategy(self):
        strat = G3TransformationStrategies.get_strategy("COBOL", "refactor")
        assert strat is not None
        assert strat.__name__ == "_cobol_refactor"

    def test_jcl_source_gets_jcl_workflow_config_strategy(self):
        strat = G3TransformationStrategies.get_strategy("JCL", "reconfiguration")
        assert strat is not None
        assert strat.__name__ == "_jcl_to_workflow_config"

    def test_rpg_source_gets_unsupported_transform(self):
        strat = G3TransformationStrategies.get_strategy("RPG", "refactor")
        assert strat is not None
        assert strat.__name__ == "_unsupported_transform"

    def test_is_supported_cobol_refactor(self):
        assert G3TransformationStrategies.is_supported("COBOL", "refactor") is True

    def test_is_supported_jcl_reconfiguration(self):
        assert G3TransformationStrategies.is_supported("JCL", "reconfiguration") is True

    def test_is_supported_rpg_refactor(self):
        assert G3TransformationStrategies.is_supported("RPG", "refactor") is False


    def test_derive_default_plan_preserves_source_technology(self):
        engine = LegacyAnalysisEngine()
        ta = TechnologyAnalysisStage1(
            detected_name="COBOL",
            is_mainframe=True,
            is_supported=True,
            modernization_paths=[
                ModernizationPath(
                    target_technology="java",
                    strategy="refactor",
                    target_family=TechnologyFamily.ENTERPRISE_LANGUAGE,
                    compatibility="partial",
                    description="test",
                    required_tools=[],
                    required_adapters=[],
                ),
            ],
            confidence=0.9,
            evidence_refs=["file:cobol.cbl"],
        )
        ta.knowledge_entry = TechnologyKnowledge(
            technology_name="cobol",
            family=TechnologyFamily.MAINFRAME_LANGUAGE,
            description="COBOL",
            claims=[],
        )
        arch = engine.analyze_architecture([ta], None)
        data = engine.analyze_data([ta])
        beh = engine.analyze_business_behavior([ta])
        chain = engine._record_provenance("p1", "j1", [ta])
        report = AnalysisReport(
            project_id="p1",
            job_id="j1",
            technologies=[ta],
            architecture=arch,
            data=data,
            business_behavior=beh,
            provenance_chain=chain,
            primary_language="cobol",
        )
        pipeline = ModernizationPipeline()
        plan = pipeline._derive_default_plan("p1", report)
        assert len(plan.units) == 1
        unit = plan.units[0]
        assert unit.source_technology == "COBOL"
        assert unit.target_language == "java"

    def test_derive_default_plan_multiple_technologies(self):
        engine = LegacyAnalysisEngine()

        def make_ta(name):
            t = TechnologyAnalysisStage1(
                detected_name=name,
                is_mainframe=True,
                is_supported=True,
            )
            t.knowledge_entry = TechnologyKnowledge(
                technology_name=name.lower(),
                family=TechnologyFamily.MAINFRAME_LANGUAGE,
                description=name,
                claims=[],
            )
            return t

        report = AnalysisReport(
            project_id="p1",
            job_id="j1",
            technologies=[make_ta("COBOL"), make_ta("JCL"), make_ta("RPG")],
            architecture=engine.analyze_architecture([make_ta("COBOL")], None),
            data=engine.analyze_data([make_ta("COBOL")]),
            business_behavior=engine.analyze_business_behavior([make_ta("COBOL")]),
            provenance_chain=engine._record_provenance("p1", "j1", [make_ta("COBOL")]),
        )
        pipeline = ModernizationPipeline()
        plan = pipeline._derive_default_plan("p1", report)
        assert len(plan.units) == 3
        names = {u.source_technology for u in plan.units}
        assert names == {"COBOL", "JCL", "RPG"}

    def test_run_wave_missing_source_technology_fails_with_clear_error(self):
        class FakeTE:
            def apply(self, **kw):
                raise RuntimeError("should not be called")

        u = MigrationUnitSpec(
            wave_id="wave-1",
            component_id="no-source",
            strategy=MigrationStrategy.REFACTOR,
            description="unit without source",
            target_language="java",
        )
        pipeline = ModernizationPipeline()
        plan = pipeline._derive_default_plan("p1", None)
        plan.units = [u]
        wr = pipeline._run_wave("p1", "j1", plan, "wave-1", 0, FakeTE())
        assert wr.units_failed == 1
        err = (wr.error_message or "").lower()
        assert "no source_technology" in err
        assert "java" not in err

    def test_run_wave_unsupported_source_fails_with_not_implemented_error(self):
        """RPG strategy raises NotImplementedError, caught by _run_wave as failed."""
        from autoforge_modernization.transformation import TransformationStatus

        class FakeRecord:
            status = TransformationStatus.FAILED
            record_id = "r1"
            error_message = "Not implemented: RPG"

        class FakeTE:
            def apply(self, **kw):
                # The transformation_fn inside _run_wave calls _unsupported_transform
                # which raises NotImplementedError -> caught as TransformationError.
                # FakeTE simulates the real engine returning a FAILED record.
                return FakeRecord()

        u = MigrationUnitSpec(
            wave_id="wave-1",
            component_id="rpg-app",
            strategy=MigrationStrategy.REFACTOR,
            description="rpg unit",
            source_technology="RPG",
            target_language="java",
        )
        pipeline = ModernizationPipeline()
        plan = pipeline._derive_default_plan("p1", None)
        plan.units = [u]
        wr = pipeline._run_wave("p1", "j1", plan, "wave-1", 0, FakeTE())
        assert wr.units_failed == 1
        assert wr.units_transformed == 0

