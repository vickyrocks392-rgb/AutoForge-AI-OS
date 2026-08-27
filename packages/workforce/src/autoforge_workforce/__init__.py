"""
AutoForge Workforce Platform — Phase 13.
"""

from autoforge_workforce.capabilities import Capability, Permission, ExpertiseModel
from autoforge_workforce.registry import WorkerRegistry, WORKER_REGISTRY
from autoforge_workforce.workers import WorkforceWorker, WORKER_CLASSES
from autoforge_workforce.legacy_models import LegacySystemModel, LegacyEvidence, FactState, BusinessRule
from autoforge_workforce.legacy_analyzers import LegacyAnalyzer, get_analyzer_for_file
from autoforge_workforce.loops import get_loop_class
from autoforge_workforce.dispatch import WorkforceDispatcher
from autoforge_workforce.model_allocator import (
    register_workforce_models,
    ModelCapacityManager,
    CapacityAwareRouter,
)

__version__ = "0.1.0"

__all__ = [
    "Capability",
    "Permission",
    "ExpertiseModel",
    "WorkerRegistry",
    "WORKER_REGISTRY",
    "WorkforceWorker",
    "WORKER_CLASSES",
    "LegacySystemModel",
    "LegacyEvidence",
    "FactState",
    "BusinessRule",
    "LegacyAnalyzer",
    "get_analyzer_for_file",
    "get_loop_class",
    "WorkforceDispatcher",
    "register_workforce_models",
    "ModelCapacityManager",
    "CapacityAwareRouter",
]
