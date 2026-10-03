"""Phase 19B-3 — Gates 2-4: experience capture, signal extraction, hypotheses."""

from __future__ import annotations

import uuid

import pytest

from autoforge_learning import (
    ExperienceCollector,
    ExperienceSource,
    HypothesisGenerator,
    LearningScope,
    LearningScopeKind,
    LearningSignal,
    SignalClass,
    SignalExtractor,
    SignalPolarity,
)
from autoforge_learning.experience import SOURCE_BY_EVENT
from autoforge_learning.hypothesis import proposal_kind_for
from autoforge_learning.models import EvidenceRef, EvidenceSource
from autoforge_security.ai_guardrails import LEARNABLE_PROPOSAL_KINDS


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


@pytest.fixture()
def scope(project_id: uuid.UUID) -> LearningScope:
    return LearningScope(kind=LearningScopeKind.PROJECT, project_id=project_id)


@pytest.fixture()
def collector() -> ExperienceCollector:
    return ExperienceCollector()


@pytest.fixture()
def extractor() -> SignalExtractor:
    return SignalExtractor()


# ── Gate 2: real experience capture ───────────────────────────────────────────


def test_only_real_sources_produce_observations(collector, project_id):
    observations = collector.capture_from_execution(
        project_id=project_id,
        execution_events={
            "validation": {"passed": True},
            "tool_outcome": None,           # absent -> no observation
            "not_a_real_source": {"a": 1},  # unknown -> no observation
        },
    )
    assert [o.source for o in observations] == [ExperienceSource.VALIDATION]


def test_every_observation_carries_a_content_hash(collector, project_id):
    observations = collector.capture_from_execution(
        project_id=project_id,
        execution_events={"task_execution": {"task_id": "t1", "status": "succeeded"}},
    )
    assert observations
    for observation in observations:
        assert len(observation.content_hash) == 64


def test_missing_measurement_is_none_not_zero(collector, project_id):
    """19A's fabrication fix: absent is absent, never zero."""
    observations = collector.capture_from_execution(
        project_id=project_id, execution_events={"validation": {"passed": True}}
    )
    assert observations[0].duration_ms is None
    assert observations[0].resource_units is None


def test_model_annotation_is_never_authoritative(collector, project_id):
    observations = collector.capture_from_execution(
        project_id=project_id,
        execution_events={"validation": {"passed": True}},
        model_annotation="this definitely worked because I say so",
    )
    assert observations[0].model_annotation_authoritative is False


def test_empty_execution_produces_no_observations(collector, project_id):
    assert (
        collector.capture_from_execution(
            project_id=project_id, execution_events=None
        )
        == ()
    )


def test_all_gate2_sources_are_capturable(collector, project_id):
    """Every source Gate 2 names has a real capture path."""
    assert len(SOURCE_BY_EVENT) >= 15
    events = {name: {"status": "ok"} for name in SOURCE_BY_EVENT}
    observations = collector.capture_from_execution(
        project_id=project_id, execution_events=events
    )
    assert len(observations) == len(SOURCE_BY_EVENT)