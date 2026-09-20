"""AutoForge Power Engines — Phase 18-COMMERCIAL Canonical Autonomous Customer-Delivery Engines."""

from autoforge_power_engines.base import (
    PowerEngine,
    PowerEngineLifecycleStage,
    PowerEngineContext,
    PowerEngineResult,
    resolve_output_root,
)
from autoforge_power_engines.specification import (
    CustomerProjectSpecification,
    KnowledgeSourceSpec,
    DeploymentPreference,
    DeploymentTarget,
    CustomerDeploymentProfile,
)
from autoforge_power_engines.delivery import (
    CustomerDeploymentSpec,
    ServiceDefinition,
    VolumeDefinition,
    PortMapping,
    DeploymentBuilder,
    CustomerDeliveryBuilder,
    CustomerDocumentationBuilder,
    ProprietaryBoundarySanitizer,
    ProprietaryCodeViolationError,
    PowerEngineDeploymentProvider,
)
from autoforge_power_engines.agent import (
    CustomAIAgentPowerEngine,
    CustomerAgentSpecification,
    StandaloneCustomerAgentGenerator,
)
from autoforge_power_engines.automation import (
    AIAutomationPowerEngine,
    CustomerAutomationSpecification,
    StandaloneCustomerAutomationGenerator,
)
from autoforge_power_engines.migration import (
    CodeMigrationPowerEngine,
    CustomerMigrationSpecification,
    StandaloneCustomerMigrationGenerator,
    MigrationType,
    ApprovalPolicy,
    VerificationPolicy,
)

__all__ = [
    "PowerEngine",
    "PowerEngineLifecycleStage",
    "PowerEngineContext",
    "PowerEngineResult",
    "resolve_output_root",
    "CustomerProjectSpecification",
    "KnowledgeSourceSpec",
    "DeploymentPreference",
    "DeploymentTarget",
    "CustomerDeploymentProfile",
    "CustomerDeploymentSpec",
    "ServiceDefinition",
    "VolumeDefinition",
    "PortMapping",
    "DeploymentBuilder",
    "CustomerDeliveryBuilder",
    "CustomerDocumentationBuilder",
    "ProprietaryBoundarySanitizer",
    "ProprietaryCodeViolationError",
    "PowerEngineDeploymentProvider",
    "CustomAIAgentPowerEngine",
    "CustomerAgentSpecification",
    "StandaloneCustomerAgentGenerator",
    "AIAutomationPowerEngine",
    "CustomerAutomationSpecification",
    "StandaloneCustomerAutomationGenerator",
    "CodeMigrationPowerEngine",
    "CustomerMigrationSpecification",
    "StandaloneCustomerMigrationGenerator",
    "MigrationType",
    "ApprovalPolicy",
    "VerificationPolicy",
]
