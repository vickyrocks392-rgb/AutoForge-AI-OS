"""Power Engine Integration Contract for Customer Delivery & Deployment."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List
from autoforge_power_engines.delivery.spec import CustomerDeploymentSpec, HealthCheckSpec
from autoforge_power_engines.delivery.packaging import CustomerDeliveryBuilder


class PowerEngineDeploymentProvider(ABC):
    """
    Contract implemented by commercial Power Engines.
    Separates what the Power Engine creates from how the shared platform delivers it.
    """

    @abstractmethod
    def build_deployment_spec(self, project_spec: Any) -> CustomerDeploymentSpec:
        """Constructs the universal CustomerDeploymentSpec for this workload."""
        pass

    @abstractmethod
    def build_workload_artifacts(
        self,
        project_spec: Any,
        delivery_builder: CustomerDeliveryBuilder,
        **kwargs: Any,
    ) -> Dict[str, Any]:
        """Generates workload-specific application code, indexes, models, and artifacts."""
        pass

    @abstractmethod
    def get_documentation_sections(self, project_spec: Any) -> Dict[str, Any]:
        """Returns workload-specific sections to inject into customer README and Delivery Report."""
        pass
