"""
Capability, Expertise, and Permission Models for AutoForge Workforce.
"""

from __future__ import annotations
from typing import Any
from pydantic import BaseModel, Field

class Capability(BaseModel):
    """
    Represents a specific expertise capability of a worker.
    """
    capability_id: str
    display_name: str
    description: str = ""
    constraints: dict[str, Any] = Field(default_factory=dict)

class Permission(BaseModel):
    """
    Represents an allowed operation or security permission for a worker.
    """
    permission_id: str
    resource: str
    allowed_operations: list[str] = Field(default_factory=list) # e.g. ["read", "write", "execute"]

class ExpertiseModel(BaseModel):
    """
    Structural representation of a worker's expertise, constraints, and permissions.
    """
    worker_type: str
    capabilities: list[str] = Field(default_factory=list)
    permissions: list[Permission] = Field(default_factory=list)
    required_evidence: list[str] = Field(default_factory=list)
    tool_access: list[str] = Field(default_factory=list)
    connector_capabilities: list[str] = Field(default_factory=list)
    allowed_operations: list[str] = Field(default_factory=list)
    context_requirements: list[str] = Field(default_factory=list)
    expected_artifacts: list[str] = Field(default_factory=list)
    review_criteria: list[str] = Field(default_factory=list)
    default_loop_type: str = "general"
    model_requirements: dict[str, Any] = Field(default_factory=dict)
    deterministic_validation_rules: list[str] = Field(default_factory=list)
    failure_handling_policy: dict[str, Any] = Field(default_factory=dict)

    def has_capability(self, capability_id: str) -> bool:
        return capability_id in self.capabilities

    def validates_permissions(self, operation: str, resource: str) -> bool:
        """
        Deterministically validate if the worker is allowed to perform an operation on a resource.
        """
        # Check explicit resource permissions
        for perm in self.permissions:
            if perm.resource == "*" or perm.resource == resource:
                if not perm.allowed_operations or operation in perm.allowed_operations or "*" in perm.allowed_operations:
                    return True
        # If not matched by resource permissions, check allowed_operations on model
        if operation in self.allowed_operations:
            return True
        # If no permissions list at all, default to allowed operations
        if not self.permissions and not self.allowed_operations:
            return True
        return False
