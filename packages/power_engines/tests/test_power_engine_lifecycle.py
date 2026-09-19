"""Tests for Canonical 11-Stage Power Engine Autonomous Lifecycle."""

import pytest
from pathlib import Path
from autoforge_power_engines.specification import CustomerProjectSpecification, KnowledgeSourceSpec, SourceType
from autoforge_power_engines.rag.engine import RAGKnowledgePowerEngine
from autoforge_power_engines.base import PowerEngineLifecycleStage, resolve_output_root
from autoforge_power_engines.risk import PowerEngineRiskEvaluator


@pytest.mark.asyncio
async def test_full_11_stage_lifecycle_autonomous(tmp_path):
    out_dir = tmp_path / "deliveries"
    out_dir.mkdir()

    emitted_events = []
    def sink(event):
        emitted_events.append(event)

    spec = CustomerProjectSpecification(
        project_name="AutonomousCustomerBot",
        project_description="Autonomous end-to-end knowledge assistant",
        output_root=str(out_dir),
        knowledge_sources=[
            KnowledgeSourceSpec(
                source_id="faq",
                source_type=SourceType.INLINE_TEXT,
                content="# FAQ\nQ: How to deploy?\nA: Run ./scripts/run.sh.",
            )
        ],
    )

    engine = RAGKnowledgePowerEngine(event_sink=sink)
    result = await engine.execute_lifecycle(spec)

    assert result.success is True
    assert result.project_name == "AutonomousCustomerBot"
    assert Path(result.delivery_dir).is_dir()

    # Verify all 11 stages were executed
    expected_stages = [
        "INTAKE", "UNDERSTAND_ANALYZE", "PLAN", "EXECUTE",
        "OBSERVE", "VERIFY", "DIAGNOSE", "REPAIR",
        "RE_VERIFY", "PACKAGE", "DELIVER"
    ]
    for st in expected_stages:
        assert st in result.stages_executed, f"Stage {st} was not recorded in execution"

    # Verify emitted events
    event_types = [e["event_type"] for e in emitted_events]
    assert "POWER_ENGINE_STARTED" in event_types
    assert "STAGE_INTAKE_STARTED" in event_types
    assert "STAGE_DELIVER_COMPLETED" in event_types
    assert "POWER_ENGINE_COMPLETED" in event_types


@pytest.mark.asyncio
async def test_risk_check_triggers_waiting_for_human_approval(tmp_path):
    spec = CustomerProjectSpecification(
        project_name="DangerousOperation",
        project_description="Test dangerous operation",
        output_root=str(tmp_path),
    )

    # Custom risk evaluator that detects risk on stage PLAN
    class HighRiskEvaluator(PowerEngineRiskEvaluator):
        def assess_stage_action(self, stage_name, action, target_path=None, context=None):
            if stage_name == "PLAN":
                from autoforge_power_engines.risk import RiskAssessment, RiskLevel, RiskClassification
                return RiskAssessment(
                    is_safe=False,
                    approval_required=True,
                    risk_level=RiskLevel.HIGH,
                    classification=RiskClassification.IRREVERSIBLE_ACTION,
                    reasons=["Test risk trigger requiring human sign-off."],
                )
            return super().assess_stage_action(stage_name, action, target_path, context)

    engine = RAGKnowledgePowerEngine(risk_evaluator=HighRiskEvaluator())
    # Run with auto_approve_safe_risks=False
    result = await engine.execute_lifecycle(spec, auto_approve_safe_risks=False)

    assert result.success is False
    assert "WAITING_FOR_HUMAN_APPROVAL" in result.error_message


def test_resolve_output_root(monkeypatch, tmp_path):
    # Test explicit override
    explicit = tmp_path / "explicit_dir"
    assert resolve_output_root(str(explicit)) == explicit.resolve()

    # Test environment variable AUTOFORGE_OUTPUT_ROOT
    env_dir = tmp_path / "env_dir"
    monkeypatch.setenv("AUTOFORGE_OUTPUT_ROOT", str(env_dir))
    assert resolve_output_root() == env_dir.resolve()
