# Phase 18-C: Real AI-Driven Semantic Loops

from __future__ import annotations
from pathlib import Path
import sys as _sys
import pytest

_ROOT = Path(__file__).resolve().parents[3]
for _pkg in [
    "orchestration", "workforce", "ai_infrastructure", "execution", "events",
    "observability", "composition", "models", "persistence", "workflows",
    "artifacts", "kernel", "runtime", "review", "security", "event_platform",
    "connectors", "shared", "knowledge_platform",
]:
    _src = _ROOT / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in _sys.path:
        _sys.path.insert(0, str(_src))

import os
import sys
from pathlib import Path
from typing import Any

import pytest

from autoforge_ai_infrastructure import ExecutorRegistry, InMemoryCapabilityRegistry
from autoforge_ai_infrastructure.adapters.local_runtime import (
    LocalRuntimeProviderAdapter,
)
from autoforge_ai_infrastructure.router import ModelRouterService
from autoforge_execution.context import ExecutionContext
from autoforge_orchestration.models import StageKind
from autoforge_workforce.model_allocator import register_workforce_models
from autoforge_workforce.loops import ResearchLoop, ArchitectureLoop, PlanningLoop, get_loop_class


@pytest.fixture
async def live_ollama():
    # Gate 4: the canonical local runtime is an OpenAI-compatible server
    # (llama.cpp `llama-server` / MLX), not an Ollama daemon. Override with
    # AUTOFORGE_LOCAL_RUNTIME_URL to point at a real node.
    adapter = LocalRuntimeProviderAdapter(
        provider_id="local-m1",
        base_url=os.environ.get("AUTOFORGE_LOCAL_RUNTIME_URL", "http://127.0.0.1:8080/v1"),
    )
    is_healthy = await adapter.check_health()
    if not is_healthy:
        pytest.skip("Ollama daemon not reachable")
    return adapter


@pytest.fixture
async def live_registry(live_ollama):
    registry = InMemoryCapabilityRegistry()
    register_workforce_models(registry)
    installed = await live_ollama.list_installed_models()
    if not installed:
        pytest.skip("Ollama has no installed models")
    executors = ExecutorRegistry()
    executors.bind("local-m1", live_ollama)
    return registry, executors, installed


@pytest.fixture
def model_router(live_registry):
    registry, _, _ = live_registry
    return ModelRouterService(registry)


def test_loop_class_resolution():
    assert get_loop_class("research") is ResearchLoop
    assert get_loop_class("architecture") is ArchitectureLoop
    assert get_loop_class("planning") is PlanningLoop


def test_fallback_detection():
    """H1: Validate AI output detection (18-C hardening).

    The new validator uses:
      1. Length threshold (< 50 chars → invalid)
      2. Authoritative AI provenance (ExecutionResult present → valid)
      3. Structural template matching (exact fallback template + short → invalid)
      4. Generic substring matching is NOT used (too aggressive for real LLM output)

    Key behavior change: "Implementation plan for" as a generic phrase no longer
    causes rejection. Only the exact fallback template is rejected.
    """
    rl = ResearchLoop.__new__(ResearchLoop)
    al = ArchitectureLoop.__new__(ArchitectureLoop)
    pl = PlanningLoop.__new__(PlanningLoop)

    # Test 3: Real substantive model output (50+ chars, no AI provenance, not template)
    real = ("# Research Brief\n\n## Problem\n"
            "Comprehensive research covering all aspects of this task, including user needs, "
            "technology considerations, and recommended approaches based on evidence.")
    assert len(real.strip()) >= 50, "real output must be >= MIN_OUTPUT_LENGTH"
    assert rl._is_real_ai_output(real)
    assert al._is_real_ai_output(real)
    assert pl._is_real_ai_output(real)

    # Test 4: Short / empty / None output rejected (length < 50)
    assert not rl._is_real_ai_output("short")
    assert not rl._is_real_ai_output("")
    assert not al._is_real_ai_output(None)

    # Test 5: Legitimate model output containing "Implementation plan for" ACCEPTED.
    # This was the false-positive: the old validator rejected any output containing
    # "Implementation plan for" as a substring. The new validator only rejects the
    # exact structural fallback template.
    legitimate_plan = (
        "# Implementation plan for Task: Distributed Caching Research\n\n"
        "## Overview\nThis document outlines the implementation approach for building a distributed "
        "caching system with Redis and consistent hashing.\n\n"
        "## Key Components\n1. Cache node manager\n2. Consistent hash ring\n3. Replication manager\n"
    )
    # Verify the legitimate output does contain the exact trigger phrase (case-insensitive)
    assert "implementation plan for" in legitimate_plan.lower()
    assert len(legitimate_plan.strip()) >= 50
    # No AI provider (no provenance), but also not the fallback template → ACCEPT
    assert rl._is_real_ai_output(legitimate_plan), (
        "New validator must accept legitimate output containing 'Implementation plan for' phrase. "
        "Only the exact deterministic fallback template should be rejected."
    )
    assert pl._is_real_ai_output(legitimate_plan)

    # Test 1: Known deterministic fallback template REJECTED.
    # This is the EXACT template produced by AIInfrastructureAdapter.generate_plan()
    # when routing fails. Must still be rejected.
    fallback = "Implementation plan for Task: analyze requirements, inspect files, apply edits, and verify."
    assert len(fallback.strip()) <= 200  # template is short
    assert not rl._is_real_ai_output(fallback)
    assert not al._is_real_ai_output(fallback)
    assert not pl._is_real_ai_output(fallback)

    # Test 6: AI provenance overrides template heuristic.
    # When the adapter has an ExecutionResult, output is always accepted.
    # This is the authoritative proof of real AI execution.
    class _FakeResult:
        model_id = "qwen2.5-coder-7b"
        provider_id = "local-m1"

    class _FakeAdapter:
        last_execution_result = _FakeResult()

    rl_with_provenance = ResearchLoop.__new__(ResearchLoop)
    rl_with_provenance._ai = _FakeAdapter()

    # Even the fallback template passes when AI provenance is present —
    # the template is real AI output, not the deterministic template.
    assert rl_with_provenance._is_real_ai_output(fallback), (
        "Output with AI provenance (ExecutionResult) must always be accepted "
        "regardless of content. AI provenance is authoritative."
    )


def test_context_transformation():
    rl = ResearchLoop.__new__(ResearchLoop)
    al = ArchitectureLoop.__new__(ArchitectureLoop)
    pl = PlanningLoop.__new__(PlanningLoop)
    base = ExecutionContext(
        task_id="t1", task_name="Test", task_type="general",
        task_description="Build a todo app"
    )
    rc = rl._build_research_context(base)
    assert rc.task_type == "research"
    assert "Research and analyze" in rc.task_description
    ac = al._build_architecture_context(base)
    assert ac.task_type == "architecture"
    assert "Design the system architecture" in ac.task_description
    pc = pl._build_planning_context(base)
    assert pc.task_type == "planning"
    assert "Create an execution plan" in pc.task_description
