"""AutoForge Generalized Project Technology Discovery."""

from autoforge_modernization.discovery.engine import (
    ProjectTechnologyDiscoveryEngine,
)
from autoforge_modernization.discovery.evidence import (
    EvidenceProvider,
    FileSystemEvidenceProvider,
    SyntaxEvidenceProvider,
    TechnologyEvidenceRecord,
)
from autoforge_modernization.discovery.inventory import (
    DetectedTechnologySummary,
    ProjectTechnologyInventory,
)

__all__ = [
    "EvidenceProvider",
    "FileSystemEvidenceProvider",
    "SyntaxEvidenceProvider",
    "TechnologyEvidenceRecord",
    "DetectedTechnologySummary",
    "ProjectTechnologyInventory",
    "ProjectTechnologyDiscoveryEngine",
]
