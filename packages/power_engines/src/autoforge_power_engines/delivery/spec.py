"""Shared Customer Deployment & Service Specification Models for AutoForge Power Engines."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator


class DeploymentTarget(str, Enum):
    """Customer deployment targets."""
    LOCAL_DESKTOP = "local_desktop"
    DOCKER_HOST = "docker_host"
    VPS = "vps"
    PRIVATE_SERVER = "private_server"
    CUSTOM = "custom"
    # Planned / unsupported cloud hosting options
    AWS = "aws"
    AZURE = "azure"
    GCP = "gcp"


class TargetCapabilityStatus(str, Enum):
    """Implementation capability status for deployment targets."""
    SUPPORTED = "supported"
    PLANNED = "planned"
    UNSUPPORTED = "unsupported"


TARGET_CAPABILITIES: Dict[DeploymentTarget, TargetCapabilityStatus] = {
    DeploymentTarget.LOCAL_DESKTOP: TargetCapabilityStatus.SUPPORTED,
    DeploymentTarget.DOCKER_HOST: TargetCapabilityStatus.SUPPORTED,
    DeploymentTarget.VPS: TargetCapabilityStatus.PLANNED,
    DeploymentTarget.PRIVATE_SERVER: TargetCapabilityStatus.PLANNED,
    DeploymentTarget.CUSTOM: TargetCapabilityStatus.PLANNED,
    DeploymentTarget.AWS: TargetCapabilityStatus.UNSUPPORTED,
    DeploymentTarget.AZURE: TargetCapabilityStatus.UNSUPPORTED,
    DeploymentTarget.GCP: TargetCapabilityStatus.UNSUPPORTED,
}


class UnsupportedDeploymentTargetError(ValueError):
    """Raised when an unsupported deployment target is requested without a dedicated adapter."""


def get_target_capability(target: DeploymentTarget) -> TargetCapabilityStatus:
    """Return the capability status of a deployment target."""
    return TARGET_CAPABILITIES.get(target, TargetCapabilityStatus.UNSUPPORTED)


def assert_target_supported(target: DeploymentTarget) -> None:
    """Assert that a target is supported; raises UnsupportedDeploymentTargetError otherwise."""
    status = get_target_capability(target)
    if status == TargetCapabilityStatus.UNSUPPORTED:
        raise UnsupportedDeploymentTargetError(
            f"Deployment target '{target.value}' is UNSUPPORTED. Only local/Docker deployment targets are fully implemented."
        )


class RestartPolicy(str, Enum):
    """Container restart policies."""
    NO = "no"
    ALWAYS = "always"
    ON_FAILURE = "on-failure"
    UNLESS_STOPPED = "unless-stopped"


class PersistenceMode(str, Enum):
    """Volume persistence modes."""
    PERSISTENT = "persistent"
    EPHEMERAL = "ephemeral"
    CONFIG = "config"
    LOGS = "logs"


class PortMapping(BaseModel):
    """Port binding configuration for public or internal exposure."""
    host_port: int
    container_port: int
    host_ip: str = "127.0.0.1"
    protocol: str = "tcp"

    @field_validator("host_port", "container_port")
    @classmethod
    def validate_port_range(cls, v: int) -> int:
        if not (1 <= v <= 65535):
            raise ValueError(f"Port {v} out of valid range (1-65535)")
        return v

    def compose_format(self) -> str:
        """Formats for docker-compose ports directive."""
        if self.host_ip:
            return f"{self.host_ip}:{self.host_port}:{self.container_port}"
        return f"{self.host_port}:{self.container_port}"


class VolumeDefinition(BaseModel):
    """Persistent storage volume binding definition."""
    host_path: str
    container_path: str
    mode: str = "rw"
    persistence_mode: PersistenceMode = PersistenceMode.PERSISTENT

    def compose_format(self) -> str:
        """Formats for docker-compose volumes directive."""
        return f"{self.host_path}:{self.container_path}"


class NetworkDefinition(BaseModel):
    """Container network configuration."""
    name: str
    driver: str = "bridge"
    internal: bool = True


class HealthCheckSpec(BaseModel):
    """Service or component health check declaration."""
    name: str
    endpoint_or_command: str
    interval_seconds: int = 10
    timeout_seconds: int = 5
    retries: int = 3
    required: bool = True
    component_type: str = "service"
    description: Optional[str] = None


class ServiceDefinition(BaseModel):
    """
    Generic declaration of a customer-deployable service/container.
    Decoupled from specific workloads (RAG, Agent, Automation, Migration).
    """
    name: str = Field(..., description="Unique service identifier (e.g. api, worker, db)")
    image: Optional[str] = Field(default=None, description="Container image name if using pre-built image")
    build_context: Optional[str] = Field(default=None, description="Directory for docker build context")
    dockerfile: Optional[str] = Field(default=None, description="Dockerfile name within build context")
    container_name: Optional[str] = Field(default=None, description="Explicit container name")
    command: Optional[str] = Field(default=None, description="Startup command or entrypoint override")
    environment: Dict[str, str] = Field(default_factory=dict, description="Environment variables for the service")
    ports: List[PortMapping] = Field(default_factory=list, description="Public host port bindings")
    internal_ports: List[int] = Field(default_factory=list, description="Internal ports exposed only to private network")
    volumes: List[VolumeDefinition] = Field(default_factory=list, description="Volume mounts")
    networks: List[str] = Field(default_factory=list, description="Networks this service attaches to")
    depends_on: List[str] = Field(default_factory=list, description="Services this service depends upon")
    restart_policy: RestartPolicy = Field(default=RestartPolicy.UNLESS_STOPPED, description="Restart policy")
    extra_hosts: List[str] = Field(default_factory=list, description="Extra host-to-IP mappings")
    security_opt: List[str] = Field(default_factory=lambda: ["no-new-privileges:true"], description="Security options")
    read_only_root: bool = Field(default=False, description="Whether root filesystem is read-only")
    health_check: Optional[HealthCheckSpec] = Field(default=None, description="Service-level health check")


class CustomerDeploymentSpec(BaseModel):
    """
    Universal Customer Deployment Specification.
    Describes what the customer workload needs to run without assuming the workload domain.
    """
    project_name: str = Field(..., description="Customer project name")
    sanitized_project_id: str = Field(..., description="Filesystem & identifier-safe project name")
    deployment_version: str = Field(default="1.0", description="Deployment specification schema version")
    target: DeploymentTarget = Field(default=DeploymentTarget.DOCKER_HOST, description="Deployment target")
    primary_service: str = Field(..., description="Name of the primary user-facing service")
    services: Dict[str, ServiceDefinition] = Field(default_factory=dict, description="Services in this deployment")
    networks: Dict[str, NetworkDefinition] = Field(default_factory=dict, description="Container networks")
    global_environment: Dict[str, str] = Field(default_factory=dict, description="Global environment variables")
    persistent_storage: bool = Field(default=True, description="Whether persistent host volumes are used")
    private_networking: bool = Field(default=True, description="Whether internal services remain unexposed publicly")
    auto_open_browser: bool = Field(default=True, description="Whether launchers attempt to open browser")
    data_directories: List[str] = Field(default_factory=list, description="Host data directories to create")
    health_checks: List[HealthCheckSpec] = Field(default_factory=list, description="Deployment-level health checks")
    metadata: Dict[str, Any] = Field(default_factory=dict, description="Custom workload metadata")

    @model_validator(mode="after")
    def validate_deployment_integrity(self) -> "CustomerDeploymentSpec":
        """Validates internal consistency and integrity of deployment declaration."""
        if self.services and self.primary_service not in self.services:
            raise ValueError(
                f"Declared primary_service '{self.primary_service}' is not defined in services: "
                f"{list(self.services.keys())}"
            )

        # Validate depends_on targets exist
        all_service_names = set(self.services.keys())
        for s_name, svc in self.services.items():
            for dep in svc.depends_on:
                if dep not in all_service_names:
                    raise ValueError(
                        f"Service '{s_name}' depends on unknown service '{dep}'. "
                        f"Available services: {list(all_service_names)}"
                    )

        # Validate no host port collisions across services
        bound_ports: Dict[str, str] = {}
        for s_name, svc in self.services.items():
            for p in svc.ports:
                key = f"{p.host_ip}:{p.host_port}"
                if key in bound_ports:
                    raise ValueError(
                        f"Host port collision on '{key}': claimed by both '{bound_ports[key]}' and '{s_name}'"
                    )
                bound_ports[key] = s_name

        return self

    def get_primary_service(self) -> Optional[ServiceDefinition]:
        """Returns the declared primary service."""
        return self.services.get(self.primary_service)

    def get_primary_port(self) -> int:
        """Returns the public host port of the primary service, defaulting to 8000."""
        svc = self.get_primary_service()
        if svc and svc.ports:
            return svc.ports[0].host_port
        return 8000

    def get_primary_host(self) -> str:
        """Returns the public host binding of the primary service, defaulting to 127.0.0.1."""
        svc = self.get_primary_service()
        if svc and svc.ports:
            return svc.ports[0].host_ip
        return "127.0.0.1"

    def target_capability_status(self) -> TargetCapabilityStatus:
        """Return the capability status of this deployment target."""
        return get_target_capability(self.target)
