"""Test AI Infrastructure integration for the Review Platform (Section 22).

Verifies that:
- AI-assisted review routes exclusively through Phase 7 AI Infrastructure
- ModelRouterService and RoutedModelExecutor are utilized
- Structured outputs are correctly deserialized into proposed findings
- AI failure degrades gracefully without crashing the Review Engine
- AISourceMetadata accurately captures routing provenance
- AI proposals are clamped by ReviewPolicy and never override deterministic blocks
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from autoforge_ai_infrastructure.execution import (
    ExecutionRequest,
    ExecutionResult,
    RoutedModelExecutor,
)
from autoforge_ai_infrastructure.metadata import CapabilityIds, RoutingRequest
from autoforge_ai_infrastructure.router import ModelRouterService

from autoforge_review.ai_reviewer import (
    AIInfrastructureReviewAdapter,
    AIReviewTask,
    ProposedFinding,
)
from autoforge_review.engine import ReviewEngine
from autoforge_review.models import (
    FindingClassification,
    FindingKind,
    ReviewCategory,
    ReviewEvidence,
    ReviewRequest,
    Severity,
)
from autoforge_review.policies import ReviewPolicy


@pytest.mark.asyncio
async def test_ai_adapter_executes_structured_review_task() -> None:
    """AIInfrastructureReviewAdapter invokes executor and parses findings."""
    mock_router = MagicMock(spec=ModelRouterService)
    mock_router.default_policy_name = "local_first"
    mock_executor = MagicMock(spec=RoutedModelExecutor)

    mock_executor.execute = AsyncMock(
        return_value=ExecutionResult(
            execution_id=uuid.uuid4(),
            provider_id="mock-provider",
            model_id="mock-model-v1",
            output={
                "findings": [
                    {
                        "title": "Potential Memory Inefficiency",
                        "description": "Large list comprehension in memory loop.",
                        "evidence": ["lines 10-15"],
                        "severity": "medium",
                        "kind": "quality_issue",
                        "confidence": 0.85,
                        "file": "app.py",
                        "remediation": "Use generator expression instead.",
                    }
                ]
            },
            attempts=1,
            failovers=0,
            latency_ms=45.0,
        )
    )

    adapter = AIInfrastructureReviewAdapter(
        router=mock_router,
        model_executor=mock_executor,
    )

    task = AIReviewTask(
        category=ReviewCategory.CODE,
        scope={"app.py": "def process():\n    return [i for i in range(1000000)]\n"},
        policy_context="Code quality review",
    )

    result = await adapter.review(task)

    assert len(result.findings) == 1
    finding = result.findings[0]
    assert finding.title == "Potential Memory Inefficiency"
    assert finding.severity == Severity.MEDIUM
    assert finding.kind == FindingKind.QUALITY
    assert finding.confidence == 0.85
    assert finding.file == "app.py"
    assert finding.remediation == "Use generator expression instead."

    assert result.ai_source.executed is True
    assert result.ai_source.provider_id == "mock-provider"
    assert result.ai_source.model_id == "mock-model-v1"
    assert result.ai_source.capability_id == CapabilityIds.STRUCTURED_OUTPUT
    assert result.ai_source.prompt_version == "review.v1"


@pytest.mark.asyncio
async def test_ai_adapter_degrades_gracefully_on_executor_exception() -> None:
    """When Phase 7 executor raises an exception, adapter returns empty findings with error metadata."""
    mock_router = MagicMock(spec=ModelRouterService)
    mock_executor = MagicMock(spec=RoutedModelExecutor)
    mock_executor.execute = AsyncMock(side_effect=RuntimeError("AI Provider Timeout"))

    adapter = AIInfrastructureReviewAdapter(
        router=mock_router,
        model_executor=mock_executor,
    )

    task = AIReviewTask(
        category=ReviewCategory.SECURITY,
        scope={"auth.py": "def login(): pass"},
    )

    result = await adapter.review(task)

    assert result.findings == []
    assert result.ai_source.executed is False
    assert "AI Provider Timeout" in (result.ai_source.error_message or "")


@pytest.mark.asyncio
async def test_ai_adapter_handles_unconfigured_infrastructure() -> None:
    """When router or executor is None, adapter safely returns unexecuted metadata."""
    adapter = AIInfrastructureReviewAdapter(router=None, model_executor=None)
    task = AIReviewTask(category=ReviewCategory.CODE, scope={"a.py": "x=1"})

    result = await adapter.review(task)

    assert result.findings == []
    assert result.ai_source.executed is False


@pytest.mark.asyncio
async def test_engine_with_ai_infrastructure_adapter_end_to_end() -> None:
    """Full ReviewEngine review incorporating AI reasoning alongside deterministic rules."""
    mock_router = MagicMock(spec=ModelRouterService)
    mock_router.default_policy_name = "default"
    mock_executor = MagicMock(spec=RoutedModelExecutor)

    mock_executor.execute = AsyncMock(
        return_value=ExecutionResult(
            execution_id=uuid.uuid4(),
            provider_id="phase7-provider",
            model_id="phase7-model",
            output={
                "findings": [
                    {
                        "title": "Suboptimal Loop Construct",
                        "description": "Consider refactoring nested loops.",
                        "evidence": ["nested for"],
                        "severity": "low",
                        "kind": "quality_issue",
                        "confidence": 0.9,
                        "file": "calc.py",
                    }
                ]
            },
            attempts=1,
            failovers=0,
            latency_ms=50.0,
        )
    )

    ai_adapter = AIInfrastructureReviewAdapter(
        router=mock_router,
        model_executor=mock_executor,
    )

    policy = ReviewPolicy(
        ai_enabled=True,
        max_ai_severity=Severity.LOW,
    )

    engine = ReviewEngine(policy=policy, ai_provider=ai_adapter)

    req = ReviewRequest(
        review_id="ai-e2e-1",
        categories=frozenset({ReviewCategory.CODE}),
        evidence=ReviewEvidence(
            source_files={
                "calc.py": "def calc(matrix):\n    for row in matrix:\n        for cell in row:\n            pass\n",
                "README.md": "# Matrix Calc\n\n## Usage\n",
            }
        ),
    )

    result = await engine.review(req)

    assert result.approved
    assert result.ai_findings == 1
    ai_f = [f for f in result.findings if f.classification == FindingClassification.AI_ASSISTED][0]
    assert ai_f.title == "Suboptimal Loop Construct"
    assert ai_f.severity == Severity.LOW
    assert ai_f.provenance is not None
    assert ai_f.provenance.ai_source is not None
    assert ai_f.provenance.ai_source.provider_id == "phase7-provider"
    assert ai_f.provenance.ai_source.model_id == "phase7-model"
