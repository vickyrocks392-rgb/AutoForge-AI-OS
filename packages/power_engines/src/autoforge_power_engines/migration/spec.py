"""Customer Migration Specification Models (18-COMMERCIAL-D).

Strongly typed declarative specification for commercial code migration and refactoring projects.
Integrates with the shared Customer Delivery & Deployment Platform.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator

from autoforge_power_engines.specification import (
    CustomerProjectSpecification,
    CustomerDeploymentProfile,
)
from autoforge_power_engines.delivery.spec import (
    CustomerDeploymentSpec,
    DeploymentTarget,
    ServiceDefinition,
    PortMapping,
    VolumeDefinition,
    NetworkDefinition,
    RestartPolicy,
    HealthCheckSpec,
)


class MigrationType(str, Enum):
    """Supported migration and refactoring categories."""
    LANGUAGE_MIGRATION = "language_migration"
    FRAMEWORK_MIGRATION = "framework_migration"
    VERSION_UPGRADE = "version_upgrade"
    REFACTORING = "refactoring"
    API_MIGRATION = "api_migration"
    DATABASE_MIGRATION = "database_migration"
    ARCHITECTURAL_MODERNIZATION = "architectural_modernization"


class RiskTolerance(str, Enum):
    """Customer risk tolerance level."""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class ApprovalPolicy(str, Enum):
    """Human approval policy."""
    ALWAYS_APPROVE = "always_approve"
    APPROVE_HIGH_RISK = "approve_high_risk"
    STRICT_MANUAL = "strict_manual"


class VerificationPolicy(str, Enum):
    """Verification strictness policy."""
    SYNTAX_ONLY = "syntax_only"
    COMPILE_AND_TEST = "compile_and_test"
    FULL_BEHAVIOR_EQUIVALENCE = "full_behavior_equivalence"


class CustomerMigrationSpecification(CustomerProjectSpecification):
    """
    18-COMMERCIAL-D Customer Migration Specification.
    Defines the contract for migrating, modernizing, or refactoring a customer codebase.
    """
    migration_id: str = Field(..., description="Unique migration identifier, e.g. 'mig-carddemo-2026'")
    source_path: Optional[str] = Field(
        default=None,
        description="Path to local source directory or repository"
    )
    source_archive: Optional[str] = Field(
        default=None,
        description="Optional path to source zip/tar archive"
    )
    source_languages: List[str] = Field(
        default_factory=list,
        description="Primary languages in source codebase, e.g. ['cobol', 'jcl', 'sql'] or ['python']"
    )
    target_language: str = Field(
        ...,
        description="Destination programming language, e.g. 'java', 'python', 'typescript'"
    )
    target_framework: Optional[str] = Field(
        default=None,
        description="Target framework, e.g. 'spring-boot', 'fastapi'"
    )
    migration_type: MigrationType = Field(
        default=MigrationType.LANGUAGE_MIGRATION,
        description="Primary migration category"
    )
    migration_objective: str = Field(
        ...,
        description="Specific business and technical goal of the migration"
    )
    compatibility_target: str = Field(
        default="strict_behavioral_equivalence",
        description="Target compatibility mode (e.g., 'strict_behavioral_equivalence', 'backward_compatible')"
    )
    build_requirements: Dict[str, Any] = Field(
        default_factory=dict,
        description="Build constraints, e.g. {'jdk': '17', 'build_tool': 'maven'}"
    )
    test_requirements: Dict[str, Any] = Field(
        default_factory=dict,
        description="Test requirements, e.g. {'generate_unit_tests': True, 'min_coverage': 80}"
    )
    coding_standards: List[str] = Field(
        default_factory=list,
        description="Target coding standards, e.g. ['pep8', 'type_hints', 'clean_architecture']"
    )
    architecture_constraints: List[str] = Field(
        default_factory=list,
        description="Architectural rules, e.g. ['modular_services', 'rest_api_layer']"
    )
    excluded_paths: List[str] = Field(
        default_factory=lambda: [".git", "node_modules", "__pycache__", ".venv", ".DS_Store", "target", "build"],
        description="Relative paths or glob patterns to exclude from migration"
    )
    included_paths: List[str] = Field(
        default_factory=list,
        description="Optional explicit list of paths to include (if empty, processes all non-excluded files)"
    )
    risk_tolerance: RiskTolerance = Field(
        default=RiskTolerance.MEDIUM,
        description="Acceptable risk tolerance for automated transformations"
    )
    approval_policy: ApprovalPolicy = Field(
        default=ApprovalPolicy.APPROVE_HIGH_RISK,
        description="When to pause for human approval"
    )
    verification_policy: VerificationPolicy = Field(
        default=VerificationPolicy.FULL_BEHAVIOR_EQUIVALENCE,
        description="Level of verification required for certification"
    )
    deployment_requirements: Dict[str, Any] = Field(
        default_factory=dict,
        description="Deployment specifications, e.g. Docker container, port mappings"
    )
    max_repair_iterations: int = Field(
        default=3,
        ge=1,
        le=10,
        description="Maximum bounded repair attempts per failing unit"
    )
    timeout_seconds: int = Field(
        default=600,
        ge=30,
        description="Maximum execution timeout for the overall migration"
    )

    @field_validator("migration_id")
    @classmethod
    def validate_migration_id(cls, v: str) -> str:
        if not re.match(r"^[a-zA-Z0-9_-]{2,64}$", v):
            raise ValueError(f"Invalid migration_id '{v}'. Must be 2-64 alphanumeric characters, underscores, or hyphens.")
        return v

    def sanitized_migration_id(self) -> str:
        return re.sub(r"[^a-zA-Z0-9]", "_", self.migration_id).lower()

    def to_deployment_spec(self) -> CustomerDeploymentSpec:
        """Adapts this specification into a universal CustomerDeploymentSpec for delivery."""
        sanitized_id = self.sanitized_migration_id()
        primary_service = f"migrated_{sanitized_id}"
        primary_port = int(self.deployment_requirements.get("port", 8080))

        services = {
            primary_service: ServiceDefinition(
                name=primary_service,
                build_context=".",
                dockerfile="Dockerfile",
                container_name=f"customer_{sanitized_id}",
                restart_policy=RestartPolicy.UNLESS_STOPPED,
                ports=[PortMapping(host_ip="127.0.0.1", host_port=primary_port, container_port=primary_port)],
                environment={
                    "PORT": str(primary_port),
                    "ENVIRONMENT": "production",
                    "MIGRATION_ID": self.migration_id,
                    "TARGET_LANGUAGE": self.target_language,
                },
                volumes=[
                    VolumeDefinition(host_path="./data", container_path="/app/data"),
                    VolumeDefinition(host_path="./config", container_path="/app/config"),
                ],
                networks=["migration_network"],
            )
        }

        # Optional database service if migration involves database
        if self.migration_type in (MigrationType.DATABASE_MIGRATION, MigrationType.ARCHITECTURAL_MODERNIZATION) or "database" in self.deployment_requirements:
            services["database"] = ServiceDefinition(
                name="database",
                image="postgres:16-alpine",
                container_name=f"customer_{sanitized_id}_db",
                restart_policy=RestartPolicy.UNLESS_STOPPED,
                internal_ports=[5432],
                environment={
                    "POSTGRES_DB": f"{sanitized_id}_db",
                    "POSTGRES_USER": "migrated_user",
                    "POSTGRES_PASSWORD": "migrated_password",
                },
                volumes=[
                    VolumeDefinition(host_path="./data/db", container_path="/var/lib/postgresql/data")
                ],
                networks=["migration_network"],
            )

        networks = {
            "migration_network": NetworkDefinition(
                name="migration_network",
                driver="bridge",
                internal=True,
            )
        }

        data_dirs = [
            "data/storage",
            "data/db",
            "data/logs",
            "reports",
        ]

        return CustomerDeploymentSpec(
            project_name=self.project_name,
            sanitized_project_id=sanitized_id,
            target=DeploymentTarget.DOCKER_HOST,
            primary_service=primary_service,
            services=services,
            networks=networks,
            global_environment={
                "MIGRATION_ID": self.migration_id,
                "TARGET_LANGUAGE": self.target_language,
                "TARGET_FRAMEWORK": self.target_framework or "standard",
            },
            persistent_storage=True,
            private_networking=True,
            auto_open_browser=False,
            data_directories=data_dirs,
            health_checks=[
                HealthCheckSpec(
                    name=primary_service,
                    endpoint_or_command=f"http://127.0.0.1:{primary_port}/health"
                )
            ],
            metadata={
                "power_engine": "18-COMMERCIAL-D",
                "workload": "code_migration_refactoring",
                "migration_id": self.migration_id,
                "migration_type": self.migration_type.value,
                "target_language": self.target_language,
                "target_framework": self.target_framework,
            },
        )
