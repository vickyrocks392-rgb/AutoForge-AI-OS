"""Declarative Commercial Customer RAG Specification.

Extends CustomerProjectSpecification to maintain full compatibility with the
shared PowerEngine lifecycle while adding typed RAG domain configuration contracts.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import Field

from autoforge_power_engines.specification import (
    CustomerProjectSpecification,
    CustomerDeploymentProfile,
    DeploymentPreference,
    DeploymentTarget,
    EmbeddingProviderType,
    LLMProviderType,
    VectorStoreType,
)


class CustomerRAGSpecification(CustomerProjectSpecification):
    """
    Typed specification for Customer RAG Knowledge Assistant deliveries.
    Enables configuration-driven generation across diverse customer profiles.
    """
    retrieval_strategy: str = Field(
        default="semantic",
        description="Retrieval engine strategy: 'semantic', 'hybrid', or 'lexical'"
    )
    embedding_provider: EmbeddingProviderType = Field(
        default=EmbeddingProviderType.LOCAL,
        description="Embedding model provider selection"
    )
    embedding_model: str = Field(
        default="sentence-transformers/all-MiniLM-L6-v2",
        description="Pretrained embedding model identifier"
    )
    embedding_dimensions: int = Field(
        default=384,
        ge=64,
        le=4096,
        description="Vector embedding dimensionality"
    )
    vector_store_type: VectorStoreType = Field(
        default=VectorStoreType.CHROMADB,
        description="Persistent vector database backend"
    )
    vector_store_path: str = Field(
        default="./data/vector_store",
        description="Relative or external directory for persistent vector index"
    )
    top_k_default: int = Field(
        default=5,
        ge=1,
        le=50,
        description="Default number of chunks returned per query"
    )
    min_similarity_score: float = Field(
        default=0.25,
        ge=0.0,
        le=1.0,
        description="Threshold below which the assistant abstains"
    )
    hybrid_semantic_weight: float = Field(
        default=0.7,
        ge=0.0,
        le=1.0,
        description="Weight of dense vector similarity in hybrid ranking"
    )
    hybrid_lexical_weight: float = Field(
        default=0.3,
        ge=0.0,
        le=1.0,
        description="Weight of lexical TF-IDF/BM25 in hybrid ranking"
    )
    citation_granularity: str = Field(
        default="line_level",
        description="Citation precision: 'line_level', 'section_level', or 'page_level'"
    )
    conflict_detection: bool = Field(
        default=True,
        description="Whether to audit retrieved passages for policy or numeric contradictions"
    )
    prompt_injection_defense: bool = Field(
        default=True,
        description="Whether to sanitize user queries and context passages for prompt injection"
    )
    allow_extractive_fallback: bool = Field(
        default=True,
        description="Whether to allow honest extractive text synthesis if inference provider is unreachable"
    )
    ui_branding: Dict[str, Any] = Field(
        default_factory=lambda: {
            "title": "Customer Knowledge Assistant",
            "subtitle": "Autonomous Source-Grounded Knowledge Assistant",
            "primary_color": "#58a6ff",
            "accent_color": "#1f6feb",
            "theme": "dark",
        },
        description="Branding customization tokens for generated web interface"
    )
    held_out_dataset: Optional[Dict[str, Any]] = Field(
        default=None,
        description="Customer-supplied held-out evaluation dataset"
    )

    def get_deployment_profile(self) -> CustomerDeploymentProfile:
        """Derives deployment profile matching the RAG specification."""
        if self.deployment_profile:
            return self.deployment_profile

        target = DeploymentTarget.DOCKER_HOST if self.deployment_preference == DeploymentPreference.CONTAINER else DeploymentTarget.LOCAL_DESKTOP
        model = self.model_preference or "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"
        return CustomerDeploymentProfile(
            target=target,
            vector_store=self.vector_store_type,
            embedding_provider=self.embedding_provider,
            llm_provider=LLMProviderType.LOCAL_MLX,
            llm_base_url="http://127.0.0.1:19801/v1",
            llm_model=model,
            persistent_storage=True,
            private_networking=True,
        )
