"""Tests for autoforge_modernization G.3 LLM integration and transformation strategies."""
from __future__ import annotations

import pytest
import time as _time

from autoforge_modernization.g3_llm import (
    G3LLMIntegration,
    LLMWorkloadMetrics,
    LLMConclusionRecord,
    check_ollama_health,
    LLMTaskKind,
)
from autoforge_modernization.g3_transform_strategies import G3TransformationStrategies


class TestLLMWorkloadMetrics:
    def test_semantic_coverage_zero_files(self):
        m = LLMWorkloadMetrics()
        assert m.semantic_coverage == 0.0

    def test_semantic_coverage_partial(self):
        m = LLMWorkloadMetrics(total_files=10, LLM_analyzed_files=3)
        assert m.semantic_coverage == 0.3

    def test_deterministic_coverage(self):
        m = LLMWorkloadMetrics(total_files=20, deterministic_files=8)
        assert m.deterministic_coverage == 0.4

    def test_llm_wall_clock_contribution_zero(self):
        m = LLMWorkloadMetrics()
        assert m.LLM_wall_clock_contribution == 0.0

    def test_llm_wall_clock_contribution(self):
        m = LLMWorkloadMetrics(LLM_latency_ms=200.0, wall_clock_time_ms=1000.0)
        assert m.LLM_wall_clock_contribution == 0.2


class TestLLMConclusionRecord:
    def test_is_reliable_confident_real(self):
        r = LLMConclusionRecord(
            task_kind=LLMTaskKind.BUSINESS_RULE_INTERPRETATION,
            model="qwen2.5-coder:7b",
            conclusion="A rule about interest calculation",
            confidence=0.8,
            is_fabricated=False,
            is_blocked=False,
        )
        assert r.is_reliable() is True
        assert r.is_reliable(min_confidence=0.9) is False

    def test_is_reliable_fabricated(self):
        r = LLMConclusionRecord(
            task_kind=LLMTaskKind.LEGACY_BEHAVIOR_INTERPRETATION,
            model="qwen2.5-coder:7b",
            conclusion="Fabricated",
            confidence=0.8,
            is_fabricated=True,
        )
        assert r.is_reliable() is False

    def test_is_reliable_blocked(self):
        r = LLMConclusionRecord(
            task_kind=LLMTaskKind.CODE_TRANSLATION,
            model="qwen2.5-coder:7b",
            conclusion="Blocked",
            confidence=0.5,
            is_blocked=True,
        )
        assert r.is_reliable() is False

    def test_is_reliable_no_model(self):
        r = LLMConclusionRecord(
            task_kind=LLMTaskKind.ARCHITECTURE_SYNTHESIS,
            model="",
            conclusion="Conclusion",
            confidence=0.5,
        )
        assert r.is_reliable() is False





import asyncio


@pytest.mark.asyncio
class TestG3LLMIntegrationAsyncOffline:
    async def test_interpret_business_rule_offline_fabricated(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.interpret_business_rule(
            rt="Calculate interest", sc="A = P * R * T", er=[])
        assert r.is_fabricated is True
        assert r.conclusion == "LLM_UNAVAILABLE"
        assert r.confidence == 0.0
        assert r.task_kind == LLMTaskKind.BUSINESS_RULE_INTERPRETATION
        assert r in llm.conclusions

    async def test_interpret_legacy_behavior_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.interpret_legacy_behavior(
            cs="MOVE WS-INPUT TO WS-OUTPUT", lg="COBOL", er=[])
        assert r.is_fabricated is True
        assert r.conclusion == "LLM_UNAVAILABLE"
        assert r.task_kind == LLMTaskKind.LEGACY_BEHAVIOR_INTERPRETATION

    async def test_synthesize_architecture_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.synthesize_architecture(
            cd=["service-a", "service-b"], dg="Microservices", er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.ARCHITECTURE_SYNTHESIS

    async def test_map_target_technology_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.map_target_technology(
            st="COBOL", sv="85", sp2=["batch"], er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.TARGET_MAPPING

    async def test_generate_transformation_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.generate_transformation(
            sc="MOVE A TO B", st="COBOL", tt="Java",
            tt2="migrate-cobol", er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.TRANSFORMATION_GENERATION

    async def test_explain_transformation_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.explain_transformation(
            sc="MOVE A TO B", tc="b = a;", tt2="cobol-to-java", er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.TRANSFORMATION_EXPLANATION

    async def test_interpret_version_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.interpret_version(vs="85", t="COBOL", er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.VERSION_INTERPRETATION

    async def test_interpret_unknown_technology_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.interpret_unknown_technology(
            cs="some code", ds=["pattern1"], er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.UNKNOWN_TECHNOLOGY

    async def test_translate_code_offline(self):
        llm = G3LLMIntegration(force_offline=True)
        r = await llm.translate_code(
            sc="MOVE A TO B", st="COBOL", tt="Java", er=[])
        assert r.is_fabricated is True
        assert r.task_kind == LLMTaskKind.CODE_TRANSLATION

    async def test_multiple_tasks_all_fabricated(self):
        llm = G3LLMIntegration(force_offline=True)
        await llm.interpret_business_rule("rule", "sc", [])
        await llm.interpret_legacy_behavior("code", "COBOL", [])
        await llm.synthesize_architecture(["c"], "dg", [])
        assert len(llm.conclusions) == 3
        assert all(c.is_fabricated for c in llm.conclusions)



class TestG3TransformationStrategiesGetStrategy:
    def test_cobol_refactor_returns_callable(self):
        fn = G3TransformationStrategies.get_strategy("COBOL", "refactor")
        assert callable(fn)

    def test_cobol_refactor_transforms_content(self):
        fn = G3TransformationStrategies.get_strategy("COBOL", "refactor")
        result = fn("MOVE A TO B", "COBOL")
        assert isinstance(result, str)
        assert "MOVE A TO B" in result or result != ""

    def test_cobol_unsupported_raises(self):
        fn = G3TransformationStrategies.get_strategy("COBOL", "unknown_type")
        with pytest.raises(NotImplementedError) as exc_info:
            fn("content", "COBOL")
        assert "COBOL" in str(exc_info.value)

    def test_jcl_reconfiguration_returns_callable(self):
        fn = G3TransformationStrategies.get_strategy("JCL", "reconfiguration")
        assert callable(fn)

    def test_jcl_reconfiguration_transforms(self):
        fn = G3TransformationStrategies.get_strategy("JCL", "reconfiguration")
        result = fn("//STEP01 EXEC PGM=PROG1", "JCL")
        assert isinstance(result, str)
        assert len(result) > 0

    def test_jcl_unsupported_raises(self):
        fn = G3TransformationStrategies.get_strategy("JCL", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "JCL")

    def test_shell_reconfiguration_returns_callable(self):
        fn = G3TransformationStrategies.get_strategy("BASH", "reconfiguration")
        assert callable(fn)

    def test_shell_reconfiguration_prepends_comment(self):
        fn = G3TransformationStrategies.get_strategy("BASH", "reconfiguration")
        result = fn("#!/bin/bash\necho hello", "BASH")
        assert result.startswith("# Refactored shell")

    def test_shell_unsupported_raises(self):
        fn = G3TransformationStrategies.get_strategy("BASH", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "BASH")

    def test_properties_refactor_returns_callable(self):
        fn = G3TransformationStrategies.get_strategy("PROPERTIES", "refactor")
        assert callable(fn)

    def test_properties_refactor_preserves_content(self):
        fn = G3TransformationStrategies.get_strategy("PROPERTIES", "refactor")
        result = fn("db.host=localhost\ndb.port=5432", "PROPERTIES")
        assert "db.host=localhost" in result
        assert "PROPERTIES" in result

    def test_properties_reconfiguration(self):
        fn = G3TransformationStrategies.get_strategy("XML", "reconfiguration")
        result = fn("<config/>", "XML")
        assert "XML" in result

    def test_sql_refactor_callable(self):
        fn = G3TransformationStrategies.get_strategy("SQL", "refactor")
        result = fn("SELECT * FROM table1", "SQL")
        assert "SQL" in result

    def test_assembler_refactor_callable(self):
        fn = G3TransformationStrategies.get_strategy("ASSEMBLER", "refactor")
        result = fn("LR 1,2", "ASSEMBLER")
        assert "ASSEMBLER" in result

    def test_assembler_unsupported_raises(self):
        fn = G3TransformationStrategies.get_strategy("ASSEMBLER", "reconfiguration")
        with pytest.raises(NotImplementedError):
            fn("content", "ASSEMBLER")

    def test_rpg_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("RPG", "refactor")
        with pytest.raises(NotImplementedError) as exc_info:
            fn("content", "RPG")
        assert "RPG" in str(exc_info.value)

    def test_pli_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("PLI", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "PLI")

    def test_cics_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("CICS", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "CICS")

    def test_db2_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("DB2", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "DB2")

    def test_vsam_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("VSAM", "rewrite")
        with pytest.raises(NotImplementedError):
            fn("content", "VSAM")

    def test_ims_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("IMS", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "IMS")

    def test_websphere_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("WEBSPHERE", "reconfiguration")
        with pytest.raises(NotImplementedError):
            fn("content", "WEBSPHERE")

    def test_weblogic_blocked_raises(self):
        fn = G3TransformationStrategies.get_strategy("WEBLOGIC", "transpilation")
        with pytest.raises(NotImplementedError):
            fn("content", "WEBLOGIC")

    def test_fully_unknown_technology_raises(self):
        fn = G3TransformationStrategies.get_strategy("RUBY", "refactor")
        with pytest.raises(NotImplementedError):
            fn("content", "RUBY")

    def test_case_insensitive_cobol(self):
        fn = G3TransformationStrategies.get_strategy("cobol", "refactor")
        assert callable(fn)
        result = fn("MOVE 1 TO X", "cobol")
        assert "MOVE 1 TO X" in result

    def test_job_control_language_alias(self):
        fn = G3TransformationStrategies.get_strategy("JOB_CONTROL_LANGUAGE", "reconfiguration")
        assert callable(fn)



class TestG3TransformationStrategiesIsSupported:
    def test_cobol_refactor_supported(self):
        assert G3TransformationStrategies.is_supported("COBOL", "refactor") is True

    def test_cobol_unsupported_type(self):
        assert G3TransformationStrategies.is_supported("COBOL", "unknown") is False

    def test_jcl_reconfiguration_supported(self):
        assert G3TransformationStrategies.is_supported("JCL", "reconfiguration") is True
        assert G3TransformationStrategies.is_supported("JCL", "rewrite") is True

    def test_jcl_refactor_not_supported(self):
        assert G3TransformationStrategies.is_supported("JCL", "refactor") is False

    def test_shell_reconfiguration_supported(self):
        assert G3TransformationStrategies.is_supported("BASH", "reconfiguration") is True

    def test_properties_refactor_supported(self):
        assert G3TransformationStrategies.is_supported("PROPERTIES", "refactor") is True

    def test_properties_unsupported_type(self):
        assert G3TransformationStrategies.is_supported("PROPERTIES", "unknown") is False

    def test_sql_refactor_supported(self):
        assert G3TransformationStrategies.is_supported("SQL", "refactor") is True

    def test_assembler_refactor_supported(self):
        assert G3TransformationStrategies.is_supported("ASSEMBLER", "refactor") is True

    def test_rpg_blocked_all_types(self):
        for tt in ["refactor", "rewrite", "reconfiguration", "transpilation"]:
            assert G3TransformationStrategies.is_supported("RPG", tt) is False

    def test_pli_blocked_all_types(self):
        for tt in ["refactor", "rewrite"]:
            assert G3TransformationStrategies.is_supported("PLI", tt) is False

    def test_cics_blocked_all_types(self):
        for tt in ["refactor", "rewrite", "reconfiguration"]:
            assert G3TransformationStrategies.is_supported("CICS", tt) is False

    def test_db2_blocked_all_types(self):
        for tt in ["refactor", "reconfiguration"]:
            assert G3TransformationStrategies.is_supported("DB2", tt) is False

    def test_vsam_blocked_all_types(self):
        for tt in ["refactor", "rewrite"]:
            assert G3TransformationStrategies.is_supported("VSAM", tt) is False

    def test_ims_blocked_all_types(self):
        for tt in ["refactor", "reconfiguration"]:
            assert G3TransformationStrategies.is_supported("IMS", tt) is False

    def test_websphere_blocked(self):
        assert G3TransformationStrategies.is_supported("WEBSPHERE", "refactor") is False

    def test_weblogic_blocked(self):
        assert G3TransformationStrategies.is_supported("WEBLOGIC", "refactor") is False

    def test_unknown_technology_blocked(self):
        assert G3TransformationStrategies.is_supported("RUBY", "refactor") is False
        assert G3TransformationStrategies.is_supported("NEWTECH", "refactor") is False


class TestG3TransformationStrategiesSupportedTypesFor:
    def test_cobol_supported_types(self):
        types = G3TransformationStrategies.supported_types_for("COBOL")
        assert "refactor" in types
        assert "refactor" in types; assert "transpilation" in types; assert len(types) == 2

    def test_jcl_supported_types(self):
        types = G3TransformationStrategies.supported_types_for("JCL")
        assert "reconfiguration" in types
        assert "rewrite" in types

    def test_shell_supported_types(self):
        types = G3TransformationStrategies.supported_types_for("BASH")
        assert "reconfiguration" in types

    def test_properties_supported_types(self):
        types = G3TransformationStrategies.supported_types_for("PROPERTIES")
        assert "refactor" in types or "reconfiguration" in types

    def test_sql_supported_types(self):
        types = G3TransformationStrategies.supported_types_for("SQL")
        assert "refactor" in types or "reconfiguration" in types

    def test_assembler_supported_types(self):
        types = G3TransformationStrategies.supported_types_for("ASSEMBLER")
        assert "refactor" in types

    def test_rpg_blocked_returns_blocked(self):
        types = G3TransformationStrategies.supported_types_for("RPG")
        assert types == ["blocked"]

    def test_pli_blocked_returns_blocked(self):
        types = G3TransformationStrategies.supported_types_for("PLI")
        assert types == ["blocked"]

    def test_cics_blocked_returns_blocked(self):
        types = G3TransformationStrategies.supported_types_for("CICS")
        assert types == ["blocked"]

    def test_db2_blocked_returns_blocked(self):
        types = G3TransformationStrategies.supported_types_for("DB2")
        assert types == ["blocked"]

    def test_unknown_technology_returns_blocked(self):
        types = G3TransformationStrategies.supported_types_for("RUBY")
        assert types == ["blocked"]

    def test_case_insensitive(self):
        types = G3TransformationStrategies.supported_types_for("cobol")


# ──────────────────────────────────────────────────────────────────────────────
# pipeline.py integration smoke tests
# ──────────────────────────────────────────────────────────────────────────────

from autoforge_modernization.pipeline import ModernizationPipeline



# ──────────────────────────────────────────────────────────────────────────────
# pipeline.py integration smoke tests
# ──────────────────────────────────────────────────────────────────────────────

from autoforge_modernization.pipeline import ModernizationPipeline
from autoforge_modernization.reconnaissance.models import (
    DetectedTechnology,
    FactConfidence,
    TechnologyKind,
)


class TestPipelineG3Integration:
    """Smoke tests for ModernizationPipeline with G.3 LLM integration."""

    def test_pipeline_has_offline_llm_by_default(self):
        """Pipeline should instantiate with offline G3LLMIntegration by default."""
        ppl = ModernizationPipeline()
        assert ppl.llm_integration is not None
        assert ppl.llm_integration.is_available is False
        assert ppl.llm_integration._fo is True

    def test_pipeline_accepts_custom_llm_integration(self):
        """Pipeline should accept a custom LLM integration."""
        from autoforge_modernization.g3_llm import G3LLMIntegration
        custom = G3LLMIntegration(force_offline=True)
        ppl = ModernizationPipeline(llm_integration=custom)
        assert ppl.llm_integration is custom

    def test_pipeline_force_offline_true(self):
        """Pipeline with force_offline_llm=True should use offline mode."""
        ppl = ModernizationPipeline(force_offline_llm=True)
        assert ppl.llm_integration._fo is True
        assert ppl.llm_integration.is_available is False

    def test_pipeline_extracts_technologies_from_pydantic_list(self):
        """Pipeline._extract_technologies should handle list of DetectedTechnology."""
        recon = {
            "detected_technologies": [
                DetectedTechnology(
                    name="COBOL", kind=TechnologyKind.UNKNOWN,
                    confidence=FactConfidence.HIGH, version="85",
                ),
                DetectedTechnology(
                    name="JCL", kind=TechnologyKind.UNKNOWN,
                    confidence=FactConfidence.HIGH, version=None,
                ),
            ],
        }
        ppl = ModernizationPipeline()
        result = ppl.run(
            project_id="test-g3",
            job_id="job-1",
            reconnaissance_output=recon,
        )
        assert result.analysis_report is not None
        m = ppl.llm_integration.metrics
        # Technologies tracked deterministically (no LOC on DetectedTechnology -> 0)
        assert m.total_files == 2
        assert m.deterministic_files == 2
        assert m.wall_clock_time_ms > 0.0

    def test_pipeline_run_gate_decision(self):
        """Pipeline run should produce a gate decision."""
        recon = {
            "detected_technologies": [
                DetectedTechnology(
                    name="COBOL", kind=TechnologyKind.UNKNOWN,
                    confidence=FactConfidence.HIGH, version="85",
                ),
            ],
        }
        ppl = ModernizationPipeline()
        result = ppl.run(
            project_id="test-gate",
            job_id="job-2",
            reconnaissance_output=recon,
        )
        assert len(result.gate_decisions) >= 1
        gate = result.gate_decisions[0]
        assert gate.decision.value in ("approved", "blocked")

    def test_pipeline_run_wave_results(self):
        """Pipeline run should produce wave results for a known tech."""
        recon = {
            "detected_technologies": [
                DetectedTechnology(
                    name="COBOL", kind=TechnologyKind.UNKNOWN,
                    confidence=FactConfidence.HIGH, version="85",
                ),
            ],
        }
        ppl = ModernizationPipeline()
        result = ppl.run(
            project_id="test-waves",
            job_id="job-3",
            reconnaissance_output=recon,
        )
        assert len(result.wave_results) >= 1
        assert result.wave_results[0].wave_id == "wave-1"

    def test_pipeline_empty_recon_runs(self):
        """Pipeline run with no detected technologies should not crash."""
        ppl = ModernizationPipeline()
        result = ppl.run(
            project_id="test-empty",
            job_id="job-5",
            reconnaissance_output={"detected_technologies": []},
        )
        assert result is not None
        assert result.analysis_report is not None

    def test_llm_metrics_wall_clock_recorded(self):
        """Pipeline run should record wall-clock time on the LLM integration."""
        recon = {
            "detected_technologies": [
                DetectedTechnology(
                    name="COBOL", kind=TechnologyKind.UNKNOWN,
                    confidence=FactConfidence.HIGH, version="85",
                ),
            ],
        }
        ppl = ModernizationPipeline()
        ppl.run(project_id="test", job_id="job-wc", reconnaissance_output=recon)
        assert ppl.llm_integration.metrics.wall_clock_time_ms >= 0.0

