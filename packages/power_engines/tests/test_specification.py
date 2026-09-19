"""Tests for Customer Project Specification Models & Intake Validation."""

import pytest
from autoforge_power_engines.specification import (
    CustomerProjectSpecification,
    KnowledgeSourceSpec,
    SourceType,
    DeploymentPreference,
)


def test_specification_defaults():
    spec = CustomerProjectSpecification(
        project_name="Acme Knowledge Assistant",
        project_description="RAG assistant for Acme developer documentation.",
    )
    assert spec.project_name == "Acme Knowledge Assistant"
    assert spec.sanitized_project_id() == "acme_knowledge_assistant"
    assert spec.deployment_preference == DeploymentPreference.STANDALONE_FASTAPI
    assert spec.require_api is True
    assert spec.require_ui is False
    assert spec.require_auth is False
    assert "Accurate" in spec.desired_assistant_behavior


def test_specification_sources():
    sources = [
        KnowledgeSourceSpec(
            source_id="src-1",
            source_type=SourceType.DOCUMENT,
            path="/tmp/docs/manual.md",
        ),
        KnowledgeSourceSpec(
            source_id="src-2",
            source_type=SourceType.INLINE_TEXT,
            content="# FAQ\nQ: How to reset password?\nA: Click reset link.",
        ),
    ]
    spec = CustomerProjectSpecification(
        project_name="IT Support Bot",
        project_description="Internal IT Support Q&A",
        knowledge_sources=sources,
        require_auth=True,
    )
    assert len(spec.knowledge_sources) == 2
    assert spec.require_auth is True
    assert spec.knowledge_sources[1].content.startswith("# FAQ")
