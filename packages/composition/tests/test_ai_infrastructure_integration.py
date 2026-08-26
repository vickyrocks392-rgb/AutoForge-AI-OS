"""Integration tests: Composition Root -> AI Infrastructure Platform.

Exercises the real composition-root wiring path (not mocks) through deterministic
provider test doubles behind the real :class:`ModelExecutor` protocol.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_ai_infrastructure import RetryPolicy
from autoforge_ai_infrastructure.metadata import CapabilityIds, RoutingRequest
from autoforge_composition.ai_infrastructure_wiring import (
    AIInfrastructureServices,
    build_ai_infrastructure,
)
from autoforge_composition.checkpoint_port_adapter import RuntimeCheckpointAdapter
from tests.helpers import (
    AlwaysFailExecutor,
    FakeExecutor,
    RecordingEventSink,
    noop_sleeper,
)

pytestmark = pytest.mark.asyncio


async def test_composition_builds_ai_infrastructure():
    """Composition root constructs the platform with reference catalog."""
    services = build_ai_infrastructure()
    assert services.registry.list_providers()
    decision = services.router.route(
        RoutingRequest(required_capabilities=frozenset({CapabilityIds.CODE_GENERATION}))
    )
    assert decision.selected.model.provider_id == "reference-local"


async def test_composition_routes_local_first():
    """Local-first routing prefers local execution by default."""
    services = build_ai_infrastructure(sleeper=noop_sleeper)
    services.executor_registry.bind("reference-local", FakeExecutor())
    services.executor_registry.bind("reference-cloud", FakeExecutor())

    result = await services.continuity.execute(
        payload={"prompt": "write a function"},
        routing_request=RoutingRequest(
            required_capabilities=frozenset({CapabilityIds.CODE_GENERATION})
        ),
    )
    assert result.provider_id == "reference-local"
    assert result.model_id == "reference-local-mini-q4"
    assert result.attempts == 1
    assert result.failovers == 0


async def test_composition_failover_through_continuity():
    """Local failure triggers cloud failover via the continuity manager."""
    services = build_ai_infrastructure(
        retry_policy=RetryPolicy(max_attempts=2),
        sleeper=noop_sleeper,
    )
    services.executor_registry.bind("reference-local", AlwaysFailExecutor())
    services.executor_registry.bind("reference-cloud", FakeExecutor())

    result = await services.continuity.execute(
        payload={"prompt": "hi"},
        routing_request=RoutingRequest(
            required_capabilities=frozenset({CapabilityIds.CODE_GENERATION})
        ),
    )
    assert result.provider_id == "reference-cloud"
    assert result.failovers == 1
    assert result.attempts == 3


async def test_composition_offline_mode_never_leaves_local():
    """Offline-only routing never selects a cloud model."""
    services = build_ai_infrastructure()
    services.executor_registry.bind("reference-local", FakeExecutor())

    decision = services.router.route(
        RoutingRequest(
            required_capabilities=frozenset({CapabilityIds.CODE_GENERATION}),
            offline_only=True,
        )
    )
    assert decision.selected.model.provider_id == "reference-local"
    assert decision.selected.model.is_locally_executable


async def test_composition_checkpoint_adapter_over_runtime():
    """The checkpoint port adapter delegates to the Runtime boundary."""
    created: list[uuid.UUID] = []
    restored: list[uuid.UUID] = []

    class FakeRuntime:
        def create_checkpoint(self, project_id, checkpoint_type, *, label=None,
                              description=None, metadata=None):
            cp = type("CP", (), {"checkpoint_id": uuid.uuid4()})()
            created.append(cp.checkpoint_id)
            return cp

        def restore_checkpoint(self, checkpoint_id, restore_type):
            restored.append(checkpoint_id)
            return {"restored": True, "checkpoint_id": str(checkpoint_id)}

        def get_checkpoint_history(self, project_id):
            cp = type("CP", (), {"checkpoint_id": uuid.uuid4()})()
            return [cp]

    adapter = RuntimeCheckpointAdapter(FakeRuntime())
    project_id = uuid.uuid4()
    cp_id = adapter.create_checkpoint(project_id, "automatic")
    assert cp_id is not None
    assert created[0] == cp_id
    history = adapter.get_checkpoint_history(project_id)
    assert len(history) == 1
    result = adapter.restore_checkpoint(cp_id)
    assert result["restored"] is True
    assert restored[0] == cp_id


async def test_composition_kernel_adapter_integrates():
    """Kernel-facing adapter works with the wired platform."""
    services = build_ai_infrastructure()
    profile = await services.kernel_router.select_model(
        {"required_capabilities": ["code_generation"]}
    )
    assert profile.model_name == "reference-local-mini-q4"
    assert profile.is_active is True


async def test_composition_canonical_events_published():
    """AI Infrastructure publishes canonical events via the Event Platform."""
    from autoforge_events.base import BaseEvent
    from autoforge_events.event_types import EventType

    sink = RecordingEventSink()
    services = build_ai_infrastructure(
        event_sink=sink,
        retry_policy=RetryPolicy(max_attempts=2),
        sleeper=noop_sleeper,
    )
    services.executor_registry.bind("reference-cloud", FakeExecutor())
    services.executor_registry.bind("reference-local", AlwaysFailExecutor())

    result = await services.continuity.execute(
        payload={"prompt": "hi"},
        routing_request=RoutingRequest(
            required_capabilities=frozenset({CapabilityIds.CODE_GENERATION})
        ),
    )
    assert result.provider_id == "reference-cloud"
    canonical_types = set(EventType)
    for e in sink.events:
        assert isinstance(e, BaseEvent)
        assert e.event_type in canonical_types
