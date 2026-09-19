"""Tests for Grounded Context Construction, Citation Attribution & Verification."""

import pytest
from autoforge_power_engines.rag.grounding import GroundedContextBuilder, GroundingVerifier


def test_grounded_context_building():
    builder = GroundedContextBuilder(max_context_chars=1000)
    raw_chunks = [
        {
            "chunk_id": "c1",
            "file_path": "docs/architecture.md",
            "line_start": 10,
            "line_end": 25,
            "score": 0.95,
            "content": "The system utilizes distributed microservices orchestrated by Kubernetes.",
        },
        {
            "chunk_id": "c2",
            "file_path": "docs/security.md",
            "line_start": 5,
            "line_end": 12,
            "score": 0.88,
            "content": "All internal RPC communications are encrypted with mutual TLS.",
        },
    ]

    ctx = builder.build_context("How is communication secured?", raw_chunks)
    assert ctx.total_chunks == 2
    assert len(ctx.citations) == 2
    assert ctx.citations[0].source_file == "docs/architecture.md"
    assert ctx.citations[1].line_range == "L5-L12"
    assert "[Source 1 | File: docs/architecture.md" in ctx.formatted_context


def test_grounding_verifier_valid_answer():
    builder = GroundedContextBuilder()
    raw_chunks = [
        {
            "chunk_id": "c1",
            "file_path": "security.md",
            "line_start": 1,
            "line_end": 10,
            "score": 0.92,
            "content": "Authentication requires RSA-256 JWT tokens.",
        }
    ]
    ctx = builder.build_context("How does authentication work?", raw_chunks)
    verifier = GroundingVerifier()

    answer = "Based on [Source 1], authentication requires RSA-256 JWT tokens."
    verified = verifier.verify_answer("How does authentication work?", answer, ctx)

    assert verified.is_grounded is True
    assert verified.grounding_score >= 0.8
    assert len(verified.citations) >= 1
    assert verified.uncertainty_signaled is False


def test_grounding_verifier_uncertainty_signaled():
    builder = GroundedContextBuilder()
    ctx = builder.build_context("What is the refund policy?", [])
    verifier = GroundingVerifier()

    verified = verifier.verify_answer(
        "What is the refund policy?",
        "I could not find information regarding refund policy in the provided documents.",
        ctx
    )

    assert verified.is_grounded is True
    assert verified.uncertainty_signaled is True
    assert "could not find" in verified.answer


def test_grounding_verifier_numeric_contradiction_rejected():
    """Permanent regression test: Source has $10,000, model says $1,000 -> REJECTED."""
    builder = GroundedContextBuilder()
    raw_chunks = [
        {
            "chunk_id": "c_compliance",
            "file_path": "compliance_manual.pdf",
            "line_start": 1,
            "line_end": 5,
            "score": 0.95,
            "content": "Transactions exceeding $10,000 USD require mandatory FinCEN Form 111 filing within 24 hours.",
        }
    ]
    ctx = builder.build_context("What is the transaction threshold for Form 111?", raw_chunks)
    verifier = GroundingVerifier()

    # Contradictory numeric claim ($1,000 instead of $10,000)
    bad_answer = (
        "Based on compliance_manual.pdf [Source 1], transactions exceeding $1,000 require "
        "mandatory FinCEN Form 111 filing within 24 hours."
    )
    result = verifier.verify_answer("What is the transaction threshold for Form 111?", bad_answer, ctx)

    assert result.is_grounded is False, "Answer with $1,000 contradictory threshold must NOT be grounded"
    assert result.grounding_score < 0.8
    assert any("1000" in claim for claim in result.unsupported_claims), "Must report 1000 as unsupported"


def test_grounding_verifier_numeric_consistency_accepted():
    """Permanent regression test: Source has $10,000, model says $10,000 -> ACCEPTED."""
    builder = GroundedContextBuilder()
    raw_chunks = [
        {
            "chunk_id": "c_compliance",
            "file_path": "compliance_manual.pdf",
            "line_start": 1,
            "line_end": 5,
            "score": 0.95,
            "content": "Transactions exceeding $10,000 USD require mandatory FinCEN Form 111 filing within 24 hours.",
        }
    ]
    ctx = builder.build_context("What is the transaction threshold for Form 111?", raw_chunks)
    verifier = GroundingVerifier()

    # Consistent numeric claim ($10,000 matches source)
    good_answer = (
        "Based on compliance_manual.pdf [Source 1], transactions exceeding $10,000 require "
        "mandatory FinCEN Form 111 filing within 24 hours."
    )
    result = verifier.verify_answer("What is the transaction threshold for Form 111?", good_answer, ctx)

    assert result.is_grounded is True, "Answer with $10,000 matching threshold must be grounded"
    assert result.grounding_score == 1.0
    assert len(result.unsupported_claims) == 0
