"""AutoForge Composition Root.

Wires the existing AutoForge subsystems into a real, runnable system:

- Kernel (orchestrator)
- Runtime State Manager (authoritative runtime state)
- canonical ``autoforge_events`` contracts
- Event Platform (transport / delivery / routing / DLQ)

See ADR-001 and ADR-002 in ``docs/adr/``.
"""

from autoforge_composition.composition_root import (
    AutoForgeSystem,
    build_autoforge_system,
)
from autoforge_composition.event_bus_adapter import CanonicalKernelEventBus
from autoforge_composition.runtime_facade import KernelRuntimeFacade

__all__ = [
    "AutoForgeSystem",
    "build_autoforge_system",
    "CanonicalKernelEventBus",
    "KernelRuntimeFacade",
]

__version__ = "0.1.0"