"""Kernel <-> Runtime boundary verification tests.

Verifies through interfaces, imports, dependency direction and behaviour:

- Kernel decides/orchestrates; Runtime owns authoritative state.
- Kernel must REQUEST changes; Runtime validates/executes transitions.
- Runtime never decides workflow strategy.
- Neither subsystem imports the other's implementation or the transport.
"""

from __future__ import annotations

import subprocess
import sys

import pytest

from autoforge_composition import build_autoforge_system
from autoforge_kernel.interfaces import Request
from autoforge_models.project import Project
from autoforge_runtime.exceptions import InvalidTransitionError

_BOUNDARY_CHECK = """
import sys
import autoforge_kernel.kernel as kernel_mod
banned_transport = "autoforge_event_platform" in sys.modules
banned_runtime_impl = "autoforge_runtime" in sys.modules
sys.exit(3 if (banned_transport or banned_runtime_impl) else 0)
"""

_RUNTIME_INDEPENDENCE_CHECK = """
import sys
import autoforge_runtime
banned = {"autoforge_kernel", "autoforge_event_platform", "autoforge_events"}
violations = [m for m in banned if m in sys.modules]
sys.exit(4 if violations else 0)
"""


def test_kernel_does_not_import_runtime_or_transport() -> None:
    """Importing the Kernel pulls in neither runtime impl nor transport."""
    proc = subprocess.run(
        [sys.executable, "-c", _BOUNDARY_CHECK], capture_output=True, text=True
    )
    assert proc.returncode == 0, (
        f"Kernel boundary violated (rc={proc.returncode}): {proc.stderr}"
    )


def test_runtime_is_independent_of_kernel_events_and_transport() -> None:
    """Runtime imports none of kernel/events/event-platform."""
    proc = subprocess.run(
        [sys.executable, "-c", _RUNTIME_INDEPENDENCE_CHECK],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, (
        f"Runtime independence violated (rc={proc.returncode}): {proc.stderr}"
    )


async def test_runtime_rejects_invalid_kernel_requested_transition() -> None:
    """Transition requests are validated by the RUNTIME, not the facade."""
    system = build_autoforge_system()
    await system.initialize()
    try:
        pid = await system.runtime_facade.create_project(Project(name="Boundary"))
        # Kernel ABC call -> facade -> runtime validation -> rejection.
        with pytest.raises(InvalidTransitionError):
            await system.runtime_facade.transition_state(pid, "finished")
        # State untouched by the rejected request.
        assert system.runtime.get_project_state(pid).status.value == "created"
    finally:
        await system.shutdown("boundary-test")


async def test_health_check_flows_through_real_boundary() -> None:
    """kernel.initialize() succeeds against the REAL runtime health check."""
    system = build_autoforge_system()
    # initialize() calls facade.health_check() -> real runtime internally.
    await system.initialize()
    assert system.kernel.get_runtime_status() == "ready"
    await system.shutdown("health-check-test")


async def test_submit_request_creates_matching_runtime_identity() -> None:
    """Kernel-generated project ID is the Runtime's project identity."""
    system = build_autoforge_system()
    await system.initialize()
    try:
        result = await system.kernel.submit_request(
            Request(request_text="Identity check")
        )
        pid = result["project_id"]
        # Same aggregate visible through both subsystems.
        domain_view = await system.kernel.runtime_state_manager.get_project(
            __import__("uuid").UUID(str(pid))
        )
        assert domain_view is not None
        assert str(domain_view.id) == str(pid)
    finally:
        await system.shutdown("identity-test")