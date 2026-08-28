"""AutoForge Composition Root.

Wires the existing AutoForge subsystems into a real, runnable system:

- Kernel (orchestrator)
- Runtime State Manager (authoritative runtime state)
- canonical ``autoforge_events`` contracts
- Event Platform (transport / delivery / routing / DLQ)

See ADR-001 and ADR-002 in ``docs/adr/``.
"""

from autoforge_composition.ai_infrastructure_wiring import (
    AIInfrastructureServices,
    build_ai_infrastructure,
)
from autoforge_composition.checkpoint_port_adapter import RuntimeCheckpointAdapter
from autoforge_composition.composition_root import (
    AutoForgeSystem,
    build_autoforge_system,
)
from autoforge_composition.event_bus_adapter import CanonicalKernelEventBus
from autoforge_composition.runtime_facade import KernelRuntimeFacade
from autoforge_composition.security_wiring import build_security_platform_from_bus

__all__ = [
    "AIInfrastructureServices",
    "AutoForgeSystem",
    "build_ai_infrastructure",
    "build_autoforge_system",
    "build_security_platform_from_bus",
    "CanonicalKernelEventBus",
    "KernelRuntimeFacade",
    "RuntimeCheckpointAdapter",
]

__version__ = "0.1.0"