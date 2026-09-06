"""AutoForge Capability Expansion Architecture."""

from autoforge_modernization.capabilities.acquisition import (
    AcquisitionAttemptRecord,
    AcquisitionStatus,
    AutonomousAcquisitionEngine,
)
from autoforge_modernization.capabilities.gap_analyzer import (
    CapabilityGapAnalysisReport,
    CapabilityGapAnalyzer,
    CapabilityGapItem,
)
from autoforge_modernization.capabilities.models import (
    CapabilityClass,
    CapabilityLevel,
    CapabilityProvenance,
    CapabilityQualificationFixture,
    CapabilityQualificationRecord,
    CapabilityRequirement,
    CapabilityState,
    QualifiedCapability,
)
from autoforge_modernization.capabilities.providers import (
    CPythonProvider,
    GnuCOBOLProvider,
    JCLUnderstandingProvider,
    NodeJSProvider,
    OpenJDKProvider,
    ProviderRegistry,
    PurePythonCOBOLProvider,
    SpecialistTechnologyProvider,
    VerifiedTechnologyProvider,
)
from autoforge_modernization.capabilities.requirement_graph import (
    CapabilityRequirementGraph,
)

__all__ = [
    "CapabilityClass",
    "CapabilityState",
    "CapabilityLevel",
    "CapabilityProvenance",
    "CapabilityQualificationFixture",
    "CapabilityQualificationRecord",
    "CapabilityRequirement",
    "QualifiedCapability",
    "VerifiedTechnologyProvider",
    "CPythonProvider",
    "OpenJDKProvider",
    "NodeJSProvider",
    "GnuCOBOLProvider",
    "PurePythonCOBOLProvider",
    "JCLUnderstandingProvider",
    "SpecialistTechnologyProvider",
    "ProviderRegistry",
    "CapabilityRequirementGraph",
    "CapabilityGapItem",
    "CapabilityGapAnalysisReport",
    "CapabilityGapAnalyzer",
    "AcquisitionStatus",
    "AcquisitionAttemptRecord",
    "AutonomousAcquisitionEngine",
]
