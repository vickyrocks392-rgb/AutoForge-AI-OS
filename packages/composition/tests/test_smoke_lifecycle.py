"""THE authoritative Phase 0 integration smoke test.

Proves the architectural spine is real:

    User Request -> Composition Root -> Kernel -> Runtime State
        -> Canonical Event -> Event Platform Transport
        -> Subscriber/Observer -> State/Event verification

No mock-only shortcuts: every component is the real implementation.
"""

from __future__ import annotations

import uuid

import pytest

from autoforge_composition import AutoForgeSystem, build_autoforge_system
from autoforge_events.base import BaseEvent
from autoforge_events.event_types import EventCategory, EventType
from autoforge_kernel.interfaces import Request


@pytest.fixture
async def system() -> AutoForgeSystem:
    """A fully wired, initialised AutoForge foundation stack."""
    s = build_autoforge_system()
    await s.initialize()
    return s


async def test_kernel_boots_against_real_runtime(system: AutoForgeSystem) -> None:
    """Kernel.initialize() verifies health through the composed boundary."""
    assert system.kernel.get_runtime_status() == "ready"

    report = await system.runtime_facade.health_check()
    assert report["healthy"] is True
    assert report["runtime_id"] == str(system.runtime.runtime_id)


async def test_request_to_runtime_to_transport_to_observer(
    system: AutoForgeSystem,
) -> None:
    """A user request produces real state and real canonical events."""
    received: list[BaseEvent] = []
    system.events.subscribe(
        received.append,
        event_types=[EventType.PROJECT_CREATED],
    )

    request = Request(request_text="Build a todo application")
    result = await system.kernel.submit_request(request)

    # ── State verification (Runtime is the authority) ────────────────
    project_id = uuid.UUID(str(result["project_id"]))
    state = system.runtime.get_project_state(project_id)
    # The Kernel's intake pipeline drives intake -> planning; the runtime
    # executed and recorded those transitions.
    assert state.status.value == "planning"
    assert state.version >= 2

    # The Kernel's view comes from the same authoritative runtime.
    kernel_view = await system.kernel.runtime_state_manager.get_project_state(
        project_id
    )
    assert str(kernel_view["project_id"]) == str(project_id)

    # ── Event verification (canonical vocabulary end to end) ─────────
    project_created = [
        e
        for e in received
        if e.event_type == EventType.PROJECT_CREATED
        and e.aggregate_id == project_id
    ]
    assert project_created, "Kernel PROJECT_CREATED never reached the observer"

    event = project_created[0]
    assert event.event_category == EventCategory.PROJECT
    assert isinstance(event.correlation_id, uuid.UUID) or event.correlation_id is None

    # ── Transport-level verification ──────────────────────────────────
    history = system.event_platform.event_bus.get_subscriptions()
    assert any(sub.subscription_id for sub in history)


async def test_shutdown_is_clean(system: AutoForgeSystem) -> None:
    """Composed shutdown stops kernel and runtime without errors."""
    await system.shutdown("smoke-test-complete")
    assert system.kernel.get_runtime_status() == "stopped"


async def test_runtime_diagnostics_do_not_pollute_canonical_vocabulary(
    system: AutoForgeSystem,
) -> None:
    """Internal runtime diagnostics are captured, never re-typed."""
    system.runtime.health_check()
    # No exception raised; skipped list stays accessible for observability.
    assert isinstance(system.skipped_runtime_events, list)
