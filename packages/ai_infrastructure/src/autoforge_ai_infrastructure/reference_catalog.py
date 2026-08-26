"""Reference AI infrastructure catalog.

NON-NORMATIVE seed data demonstrating the Capability Registry's public
registration API end-to-end. The architecture does NOT know these entries —
they are ordinary registered metadata, exactly what an operator or a future
provider-integration package would register at runtime.

Two deliberately generic providers/models are included:

- ``reference-local``  — a local runtime provider with a small quantized
  model sized for an 8 GB RAM laptop (unpriced ⇒ cost-free, low latency).
- ``reference-cloud``  — a cloud provider with a larger, priced,
  higher-quality model (optional; excluded automatically in offline mode).

No real vendor appears anywhere. Tests and the composition-root demo wire
this catalog to exercise routing deterministically.
"""

from __future__ import annotations

from autoforge_ai_infrastructure.interfaces import CapabilityRegistryPort
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    CapabilityMetadata,
    CostSpec,
    DeploymentMetadata,
    DeploymentMode,
    LatencyProfile,
    ModelMetadata,
    ModelStatus,
    Modality,
    ProviderMetadata,
    ProviderType,
    ResourceConstraints,
)

_CAPABILITIES = (
    ("text_generation", "Text Generation", "Produces natural-language output."),
    ("code_generation", "Code Generation", "Produces source code."),
    ("reasoning", "Reasoning", "Multi-step analytical reasoning."),
    ("structured_output", "Structured Output", "Emits schema-conforming JSON."),
    ("tool_use", "Tool Use", "Invokes tools/functions."),
    ("long_context_processing", "Long Context Processing", "Large context windows."),
)


def register_reference_capabilities(registry: CapabilityRegistryPort) -> None:
    """Register the illustrative capability set."""
    for capability_id, display_name, description in _CAPABILITIES:
        registry.register_capability(
            CapabilityMetadata(
                capability_id=capability_id,
                display_name=display_name,
                description=description,
            )
        )


def register_reference_providers(registry: CapabilityRegistryPort) -> None:
    """Register the two reference providers."""
    registry.register_provider(
        ProviderMetadata(
            provider_id="reference-local",
            display_name="Reference Local Runtime",
            provider_type=ProviderType.LOCAL_RUNTIME,
            endpoint=None,
            supported_capabilities=frozenset(c[0] for c in _CAPABILITIES),
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )
    registry.register_provider(
        ProviderMetadata(
            provider_id="reference-cloud",
            display_name="Reference Cloud Provider",
            provider_type=ProviderType.CLOUD,
            endpoint="https://reference.invalid/v1",
            supported_capabilities=frozenset(c[0] for c in _CAPABILITIES),
            deployment_modes=frozenset({DeploymentMode.CLOUD}),
        )
    )


def register_reference_models(registry: CapabilityRegistryPort) -> None:
    """Register one small local model and one large cloud model."""
    registry.register_model(
        ModelMetadata(
            model_id="reference-local-mini-q4",
            display_name="Reference Mini (Q4 quantized)",
            provider_id="reference-local",
            family="reference-mini",
            version="1.0",
            status=ModelStatus.ACTIVE,
            context_window_tokens=8192,
            max_output_tokens=2048,
            capabilities=frozenset(
                {
                    CapabilityIds.TEXT_GENERATION,
                    CapabilityIds.CODE_GENERATION,
                    CapabilityIds.STRUCTURED_OUTPUT,
                    CapabilityIds.TOOL_USE,
                }
            ),
            input_modalities=frozenset({Modality.TEXT}),
            output_modalities=frozenset({Modality.TEXT}),
            cost=CostSpec(),  # unpriced: free local inference
            latency=LatencyProfile(typical_latency_ms=250),
            quality_tier=2,
            reliability=0.97,
            deployment_modes=frozenset({DeploymentMode.LOCAL}),
        )
    )
    registry.register_model(
        ModelMetadata(
            model_id="reference-cloud-large-v2",
            display_name="Reference Large v2",
            provider_id="reference-cloud",
            family="reference-large",
            version="2.0",
            status=ModelStatus.ACTIVE,
            context_window_tokens=128_000,
            max_output_tokens=16_384,
            capabilities=frozenset(c[0] for c in _CAPABILITIES),
            input_modalities=frozenset({Modality.TEXT, Modality.IMAGE}),
            output_modalities=frozenset({Modality.TEXT}),
            cost=CostSpec(
                cost_per_million_input_tokens=1.50,
                cost_per_million_output_tokens=6.00,
            ),
            latency=LatencyProfile(typical_latency_ms=1800),
            quality_tier=4,
            reliability=0.995,
            deployment_modes=frozenset({DeploymentMode.CLOUD}),
        )
    )


def register_reference_deployments(registry: CapabilityRegistryPort) -> None:
    """Register deployment metadata including the 8 GB constraint profile."""
    registry.register_deployment(
        DeploymentMetadata(
            model_id="reference-local-mini-q4",
            mode=DeploymentMode.LOCAL,
            environment="8gb_ram_laptop",
            resource_constraints=ResourceConstraints(
                min_memory_mb=2048,
                recommended_memory_mb=4096,
                requires_gpu=False,
            ),
            runtime_hints={"quantization": "q4_k_m"},
        )
    )
    registry.register_deployment(
        DeploymentMetadata(
            model_id="reference-cloud-large-v2",
            mode=DeploymentMode.CLOUD,
            environment="cloud",
            resource_constraints=ResourceConstraints(),
            runtime_hints={},
        )
    )


def install_reference_catalog(registry: CapabilityRegistryPort) -> None:
    """Convenience: register capabilities, providers, models, deployments."""
    register_reference_capabilities(registry)
    register_reference_providers(registry)
    register_reference_models(registry)
    register_reference_deployments(registry)
