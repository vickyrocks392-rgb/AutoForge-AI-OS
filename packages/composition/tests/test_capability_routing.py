"""
DEF-18LE-A: canonical capability routing regression tests.

18-LD proved the canonical O-2 path could not reach ANY of the five Commercial
Power Engines. These tests lock the repair at two levels:

  * unit level -- the identifier vocabulary, resolution precedence and the
                  fail-closed behaviour of the router;
  * seam level -- ``KernelExecutionEngineAdapter.execute_loop`` routes when a
                  capability is declared and is UNCHANGED when none is.

No engine internals are mocked away: the seam tests drive a real router and a
real engine.
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
for _pkg in [
    "events", "event_platform", "runtime", "models", "ai_infrastructure",
    "workflows", "execution", "artifacts", "review", "security",
    "connectors", "orchestration", "kernel", "composition", "workforce",
    "power_engines",
]:
    _src = _REPO / "packages" / _pkg / "src"
    if _src.exists() and str(_src) not in sys.path:
        sys.path.insert(0, str(_src))

from autoforge_composition.capability_router import (  # noqa: E402
    CANONICAL_CAPABILITIES,
    CAPABILITY_AGENT,
    CAPABILITY_AUTOMATION,
    CAPABILITY_MIGRATION,
    CAPABILITY_MODERNIZATION,
    CAPABILITY_RAG,
    CommercialCapabilityRouter,
    UnknownCapabilityError,
    build_default_router,
    normalize_capability,
    read_capability,
)


# ── the five capabilities are exactly the five engines ──────────────────────

def test_canonical_capabilities_are_the_five_offerings():
    assert set(CANONICAL_CAPABILITIES) == {
        "rag_knowledge",
        "custom_ai_agent",
        "ai_automation",
        "code_migration",
        "legacy_modernization",
    }


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("rag_knowledge", CAPABILITY_RAG), ("RAG", CAPABILITY_RAG),
        ("rag", CAPABILITY_RAG), ("rag-pipeline", CAPABILITY_RAG),
        ("custom_ai_agent", CAPABILITY_AGENT), ("AGENT", CAPABILITY_AGENT),
        ("ai_automation", CAPABILITY_AUTOMATION), ("AUTOMATION", CAPABILITY_AUTOMATION),
        ("code_migration", CAPABILITY_MIGRATION), ("MIGRATION", CAPABILITY_MIGRATION),
        ("legacy_modernization", CAPABILITY_MODERNIZATION),
        ("MODERNIZATION", CAPABILITY_MODERNIZATION),
    ],
)
def test_identifier_is_deterministic(raw, expected):
    assert normalize_capability(raw) == expected
    assert normalize_capability(raw) == normalize_capability(raw)


def test_unknown_capability_is_not_guessed():
    # Fail-closed: an unrecognised value must NOT silently resolve, which would
    # recreate BLOCKER A invisibly.
    assert normalize_capability("quantum_telepathy") is None
    assert normalize_capability("") is None
    assert normalize_capability(None) is None


# ── resolution precedence ───────────────────────────────────────────────────

def test_capability_resolves_from_loop_input():
    cap, source = read_capability(
        {"loop": {"input_data": {"capability": "rag_knowledge"}}}, None
    )
    assert (cap, source) == (CAPABILITY_RAG, "loop_input")


def test_capability_resolves_from_durable_project_configuration():
    cap, source = read_capability(
        None, {"configuration": {"capability": "custom_ai_agent"}}
    )
    assert (cap, source) == (CAPABILITY_AGENT, "project_configuration")


def test_loop_input_takeves_precedence():
    cap, source = read_capability(
        {"loop": {"input_data": {"capability": "rag_knowledge"}}},
        {"configuration": {"capability": "ai_automation"}},
    )
    assert (cap, source) == (CAPABILITY_RAG, "loop_input")


def test_no_capability_resolves_to_none():
    assert read_capability(None, None) == (None, None)
    assert read_capability({"loop": {"input_data": {}}}, {"configuration": {}}) == (
        None, None
    )


# ── the router binds all five real engines ──────────────────────────────────

def test_default_router_binds_all_five():
    router = build_default_router()
    assert set(router.capabilities) == {
        "rag_knowledge", "custom_ai_agent", "ai_automation", "code_migration",
    }
    # Modernization is registered through its own (different) adapter contract.
    assert router.supports(CAPABILITY_MODERNIZATION) is True
    for capability in CANONICAL_CAPABILITIES:
        assert router.supports(capability) is True


def test_router_rejects_unknown_capability_registration():
    router = CommercialCapabilityRouter()
    with pytest.raises(UnknownCapabilityError):
        router.register("not_a_capability", lambda: None)


async def test_unknown_capability_raises_rather_than_falling_back():
    router = build_default_router()
    with pytest.raises(UnknownCapabilityError):
        await router.invoke("not_a_capability", project_id="p", request_text="x")


# ── seam behaviour: generic requests are untouched ──────────────────────────

class _RecordingEngine:
    """Stands in for the generic ``ExecutionEngine`` (not a commercial engine)."""

    def __init__(self) -> None:
        self.calls: list = []

    async def execute_task_definition(self, task_def, workflow_id=None,
                                      correlation_id=None, attempt_number=1,
                                      worker_type=None):
        self.calls.append(task_def)
        return True, [], None


class _ConfigReader:
    def __init__(self, configuration: dict) -> None:
        self._configuration = configuration

    async def get_project_state(self, project_id):  # noqa: ANN001
        return {"configuration": self._configuration}


def _adapter(router, configuration):
    from autoforge_composition.kernel_adapters import KernelExecutionEngineAdapter
    engine = _RecordingEngine()
    adapter = KernelExecutionEngineAdapter(
        concrete_engine=engine,
        capability_router=router,
        project_configuration_reader=_ConfigReader(configuration),
    )
    return adapter, engine


def _loop(**input_data):
    return {
        "project_id": "p1",
        "workflow_id": str(uuid.uuid4()),
        "request_text": "Build something",
        "loop": {"type": "coding", "name": "Core Implementation",
                 "task_id": "t1", "input_data": input_data},
    }


async def test_no_capability_uses_the_generic_engine_unchanged():
    adapter, engine = _adapter(build_default_router(), {"language": "python"})
    result = await adapter.execute_loop("coding", _loop(), _loop())
    assert engine.calls, "the generic engine must still execute"
    assert "routed" not in result
    assert result["status"] == "complete"


async def test_capability_routes_and_reports_the_real_engine():
    adapter, engine = _adapter(build_default_router(), {"capability": "rag_knowledge"})
    result = await adapter.execute_loop("coding", _loop(), _loop())
    assert result["routed"] is True
    assert result["capability"] == CAPABILITY_RAG
    assert result["engine_class"] == "RAGKnowledgePowerEngine"
    assert result["capability_source"] == "project_configuration"
    assert not engine.calls, "the generic engine must NOT run for a commercial request"


async def test_routed_result_carries_engine_verification_scorecard():
    """DECISION B layer 2: the engine's OWN deterministic evidence is transported.

    The Custom AI Agent engine produces a ``verification_scorecard`` from its own
    INTAKE/VERIFY stages (syntax, proprietary-boundary isolation, test-file
    presence) and needs no customer corpus, so it is the cleanest proof that the
    engine's own verification reaches the canonical result.
    """
    adapter, _ = _adapter(build_default_router(), {"capability": "custom_ai_agent"})
    result = await adapter.execute_loop("coding", _loop(), _loop())
    scorecard = result.get("verification_scorecard") or {}
    assert result["engine_class"] == "CustomAIAgentPowerEngine"
    assert scorecard, "engine verification scorecard must be transported"
    # The engine's own deterministic keys survive the boundary unchanged.
    assert "passed" in scorecard
    assert "defects_count" in scorecard


async def test_declared_verification_reaches_task_definition():
    """DECISION B layer 1 transport lands on the real worker contract key."""
    adapter, engine = _adapter(
        build_default_router(),
        {"language": "python", "verification_command": "pytest -q"},
    )
    await adapter.execute_loop("coding", _loop(), _loop())
    assert engine.calls
    input_data = engine.calls[0].input_data
    assert input_data["verification_commands"] == [["pytest", "-q"]]


async def test_no_declared_verification_leaves_input_untouched():
    adapter, engine = _adapter(build_default_router(), {"language": "python"})
    await adapter.execute_loop("coding", _loop(), _loop())
    assert "verification_commands" not in engine.calls[0].input_data
