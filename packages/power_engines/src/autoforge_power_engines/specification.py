"""Customer Project Specification Models for AutoForge Power Engines."""

from __future__ import annotations

import os
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class DeploymentPreference(str, Enum):
    """Customer target deployment preferences."""
    STANDALONE_FASTAPI = "standalone_fastapi"
    STANDALONE_CLI = "standalone_cli"
    CONTAINER = "container"
    PYTHON_PACKAGE = "python_package"


from autoforge_power_engines.delivery.spec import (
    DeploymentTarget,
    CustomerDeploymentSpec,
    ServiceDefinition,
    PortMapping,
    VolumeDefinition,
    NetworkDefinition,
    RestartPolicy,
)


class VectorStoreType(str, Enum):
    """Vector database implementation choices."""
    LOCAL_IN_MEMORY = "local_in_memory"
    QDRANT = "qdrant"
    PGVECTOR = "pgvector"
    ENTERPRISE_SEARCH = "enterprise_search"


class EmbeddingProviderType(str, Enum):
    """Embedding generation provider choices."""
    LOCAL = "local"
    EXTERNAL_HTTP = "external_http"
    CUSTOM = "custom"


class LLMProviderType(str, Enum):
    """LLM inference provider choices."""
    OLLAMA = "ollama"
    EXTERNAL_HTTP = "external_http"
    CUSTOM = "custom"


class CustomerDeploymentProfile(BaseModel):
    """
    Customer-facing Architecture & Deployment Profile.
    Decouples engine generation from hardcoded technology assumptions.
    """
    target: DeploymentTarget = Field(
        default=DeploymentTarget.DOCKER_HOST,
        description="Target deployment environment"
    )
    vector_store: VectorStoreType = Field(
        default=VectorStoreType.LOCAL_IN_MEMORY,
        description="Vector store backend selection"
    )
    embedding_provider: EmbeddingProviderType = Field(
        default=EmbeddingProviderType.LOCAL,
        description="Embedding model provider"
    )
    llm_provider: LLMProviderType = Field(
        default=LLMProviderType.OLLAMA,
        description="Inference provider"
    )
    llm_base_url: str = Field(
        default="http://127.0.0.1:11434",
        description="Base URL for LLM provider"
    )
    llm_model: str = Field(
        default="qwen2.5-coder:7b-instruct-q3_K_M",
        description="Target LLM model identifier"
    )
    vector_store_url: Optional[str] = Field(
        default=None,
        description="Optional remote vector store URL if external"
    )
    private_networking: bool = Field(
        default=True,
        description="Whether internal services (like Qdrant) must remain unexposed to public networks"
    )
    persistent_storage: bool = Field(
        default=True,
        description="Whether persistent host volumes are configured for customer data and index"
    )
    auto_open_browser: bool = Field(
        default=True,
        description="Whether the launcher should open default browser upon successful launch"
    )
    host: str = Field(
        default="127.0.0.1",
        description="Host interface to bind public API (localhost by default for security)"
    )
    port: int = Field(
        default=8000,
        description="Public port for customer application API"
    )

    def to_deployment_spec(
        self,
        project_name: str,
        sanitized_project_id: str,
        require_auth: bool = False,
    ) -> CustomerDeploymentSpec:
        """Adapts this deployment profile into a universal CustomerDeploymentSpec."""
        services = {}
        
        # Primary RAG API service
        services["rag_api"] = ServiceDefinition(
            name="rag_api",
            build_context=".",
            dockerfile="Dockerfile",
            container_name=f"customer_rag_api_{sanitized_project_id}",
            restart_policy=RestartPolicy.UNLESS_STOPPED,
            ports=[
                PortMapping(host_ip=self.host, host_port=self.port, container_port=self.port)
            ],
            environment={
                "HOST": "0.0.0.0",
                "PORT": str(self.port),
                "VECTOR_STORE": self.vector_store.value,
                "QDRANT_URL": "http://qdrant_internal:6333",
                "LLM_PROVIDER": self.llm_provider.value,
                "LLM_BASE_URL": "http://host.docker.internal:11434",
                "LLM_MODEL": self.llm_model,
            },
            volumes=[
                VolumeDefinition(host_path="./data", container_path="/app/data"),
                VolumeDefinition(host_path="./config", container_path="/app/config"),
                VolumeDefinition(host_path="./artifacts", container_path="/app/artifacts"),
            ],
            networks=["rag_internal_network"],
            extra_hosts=["host.docker.internal:host-gateway"],
        )

        # Private Qdrant instance - isolated from public network
        services["qdrant_internal"] = ServiceDefinition(
            name="qdrant_internal",
            image="qdrant/qdrant:v1.7.4",
            container_name=f"customer_rag_qdrant_{sanitized_project_id}",
            restart_policy=RestartPolicy.UNLESS_STOPPED,
            internal_ports=[6333],
            volumes=[
                VolumeDefinition(host_path="./data/qdrant", container_path="/qdrant/storage")
            ],
            networks=["rag_internal_network"],
        )

        networks = {
            "rag_internal_network": NetworkDefinition(
                name="rag_internal_network",
                driver="bridge",
                internal=False,
            )
        }

        global_env = {
            "VECTOR_STORE": self.vector_store.value,
            "QDRANT_URL": "http://127.0.0.1:6333",
            "LLM_PROVIDER": self.llm_provider.value,
            "LLM_BASE_URL": self.llm_base_url,
            "LLM_MODEL": self.llm_model,
            "REQUIRE_AUTH": str(require_auth).lower(),
            "AUTH_TOKEN": "",
        }

        data_dirs = [
            "data/index",
            "data/uploads",
            "data/logs",
            "data/config",
            "data/qdrant",
        ]

        metadata = {
            "vector_store": self.vector_store.value,
            "embedding_provider": self.embedding_provider.value,
            "llm_provider": self.llm_provider.value,
            "llm_model": self.llm_model,
        }

        return CustomerDeploymentSpec(
            project_name=project_name,
            sanitized_project_id=sanitized_project_id,
            target=self.target,
            primary_service="rag_api",
            services=services,
            networks=networks,
            global_environment=global_env,
            persistent_storage=self.persistent_storage,
            private_networking=self.private_networking,
            auto_open_browser=self.auto_open_browser,
            data_directories=data_dirs,
            metadata=metadata,
        )


class SourceType(str, Enum):
    """Supported knowledge source types."""
    DOCUMENT = "document"       # PDF, Markdown, TXT, DOCX
    SOURCE_CODE = "source_code" # Python, JS, TS, Java, etc.
    STRUCTURED = "structured"   # JSON, YAML
    DIRECTORY = "directory"     # Directory containing mixed supported files
    INLINE_TEXT = "inline_text" # Raw text provided directly in spec


class KnowledgeSourceSpec(BaseModel):
    """A single customer-provided knowledge source."""
    source_id: str
    source_type: SourceType = SourceType.DOCUMENT
    path: Optional[str] = None
    content: Optional[str] = None
    description: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CustomerProjectSpecification(BaseModel):
    """
    Structured customer request specification.
    Translates customer business intent into an actionable internal engineering contract.
    """
    project_name: str = Field(..., min_length=1, description="Unique human-readable project identifier")
    project_description: str = Field(..., description="High-level description of the customer project")
    knowledge_sources: List[KnowledgeSourceSpec] = Field(default_factory=list, description="Knowledge files or directories")
    desired_assistant_behavior: str = Field(
        default="Accurate, source-grounded answers with precise citations. Surfaces uncertainty if facts are absent.",
        description="Behavioral guidelines and tone for the assistant"
    )
    output_root: Optional[str] = Field(
        default=None,
        description="Optional custom destination root. If omitted, uses AUTOFORGE_OUTPUT_ROOT environment variable."
    )
    deployment_preference: DeploymentPreference = Field(
        default=DeploymentPreference.STANDALONE_FASTAPI,
        description="Target runnable deliverable architecture"
    )
    deployment_profile: Optional[CustomerDeploymentProfile] = Field(
        default=None,
        description="Detailed customer deployment and architecture profile"
    )
    model_preference: Optional[str] = Field(
        default=None,
        description="Preferred model or runtime (e.g. qwen2.5-coder:7b, ollama local, openai-compatible)"
    )
    require_ui: bool = Field(default=False, description="Whether to include a lightweight web UI in the customer delivery")
    require_api: bool = Field(default=True, description="Whether to expose a standalone REST API")
    require_auth: bool = Field(default=False, description="Whether to include token or key-based authentication")
    custom_parameters: Dict[str, Any] = Field(default_factory=dict, description="Domain or project-specific options")

    def get_deployment_profile(self) -> CustomerDeploymentProfile:
        """Returns the configured deployment profile or derives a secure default."""
        if self.deployment_profile:
            return self.deployment_profile
        # Derive defaults based on deployment_preference
        target = DeploymentTarget.DOCKER_HOST if self.deployment_preference == DeploymentPreference.CONTAINER else DeploymentTarget.LOCAL_DESKTOP
        model = self.model_preference or "qwen2.5-coder:7b-instruct-q3_K_M"
        return CustomerDeploymentProfile(
            target=target,
            vector_store=VectorStoreType.LOCAL_IN_MEMORY,
            embedding_provider=EmbeddingProviderType.LOCAL,
            llm_provider=LLMProviderType.OLLAMA,
            llm_model=model,
            persistent_storage=True,
            private_networking=True,
        )

    def sanitized_project_id(self) -> str:
        """Derives a filesystem and identifier-safe project name."""
        return "".join(c if c.isalnum() or c in ("-", "_") else "_" for c in self.project_name.lower().strip())

