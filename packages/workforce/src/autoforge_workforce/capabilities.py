"""
Capability, Expertise, Permission, and Model Policy Models for AutoForge Workforce.
"""

from __future__ import annotations
from typing import Any, Optional, Union
from pydantic import BaseModel, Field
from autoforge_ai_infrastructure.metadata import CapabilityIds


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
    allowed_operations: list[str] = Field(default_factory=list)  # e.g. ["read", "write", "execute"]


class WorkerModelProfile(BaseModel):
    """
    Deterministic specification of what a worker needs from an LLM.
    Workers declare requirements and preferences, never fixed model identities.
    """
    worker_type: str = "general"
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    min_context_window_tokens: int = 1024
    reasoning_required: bool = False
    coding_required: bool = False
    structured_output_required: bool = False
    tool_use_required: bool = False
    multimodal_required: bool = False
    privacy_policy: str = "local_only"  # "local_only", "local_preferred", "any"
    quality_priority: int = 1  # Tier 1-5
    latency_priority: str = "medium"  # "low", "medium", "high"
    cost_priority: str = "medium"  # "low", "medium", "high"
    reliability_minimum: float = 0.0
    fallback_policy: str = "queue"  # "queue", "alternative", "fail"


class TaskModelRequirements(BaseModel):
    """
    Task-level refinement or override of model requirements.
    Can strengthen worker constraints, but cannot silently weaken mandatory worker policies.
    """
    task_id: Optional[str] = None
    required_capabilities: list[str] = Field(default_factory=list)
    preferred_capabilities: list[str] = Field(default_factory=list)
    min_context_window_tokens: Optional[int] = None
    reasoning_required: Optional[bool] = None
    coding_required: Optional[bool] = None
    structured_output_required: Optional[bool] = None
    tool_use_required: Optional[bool] = None
    multimodal_required: Optional[bool] = None
    privacy_policy: Optional[str] = None
    quality_priority: Optional[int] = None
    latency_priority: Optional[str] = None
    cost_priority: Optional[str] = None
    reliability_minimum: Optional[float] = None
    fallback_policy: Optional[str] = None


class EffectiveModelRequirements(BaseModel):
    """
    Resolved, deterministic model requirements passed to ModelAllocator / ModelRouterService.
    """
    required_capabilities: frozenset[str]
    preferred_capabilities: frozenset[str]
    min_context_window_tokens: int
    reasoning_required: bool
    coding_required: bool
    structured_output_required: bool
    tool_use_required: bool
    multimodal_required: bool
    privacy_policy: str
    quality_priority: int
    latency_priority: str
    cost_priority: str
    reliability_minimum: float
    fallback_policy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "required_capabilities": list(self.required_capabilities),
            "preferred_capabilities": list(self.preferred_capabilities),
            "capabilities": list(self.required_capabilities),
            "min_context": self.min_context_window_tokens,
            "min_context_window_tokens": self.min_context_window_tokens,
            "reasoning": self.reasoning_required,
            "coding": self.coding_required,
            "structured_output": self.structured_output_required,
            "tool_use": self.tool_use_required,
            "multimodal": self.multimodal_required,
            "privacy_policy": self.privacy_policy,
            "quality_priority": self.quality_priority,
            "latency_priority": self.latency_priority,
            "cost_priority": self.cost_priority,
            "reliability_minimum": self.reliability_minimum,
            "fallback_policy": self.fallback_policy,
        }


def resolve_effective_requirements(
    worker_profile: WorkerModelProfile,
    task_requirements: Union[TaskModelRequirements, dict[str, Any], None] = None,
) -> EffectiveModelRequirements:
    """
    Deterministically merge worker model profile defaults and task-level refinements.
    
    Precedence rules:
    - Mandatory constraints (required capabilities, min context, privacy) are strengthened.
    - Tasks cannot weaken worker's local-only privacy constraint.
    - Boolean requirement flags are combined with logical OR.
    - Quality tier and context requirements take the higher value.
    """
    # Normalize task_requirements if dict
    if isinstance(task_requirements, dict):
        # Check if dict contains "model_requirements" key
        if "model_requirements" in task_requirements and isinstance(task_requirements["model_requirements"], dict):
            task_dict = task_requirements["model_requirements"]
        else:
            task_dict = task_requirements
        task_req = TaskModelRequirements(**{
            k: v for k, v in task_dict.items()
            if k in TaskModelRequirements.model_fields
        })
    elif isinstance(task_requirements, TaskModelRequirements):
        task_req = task_requirements
    else:
        task_req = TaskModelRequirements()

    # 1. Capability resolution
    req_caps = set(worker_profile.required_capabilities)
    req_caps.update(task_req.required_capabilities)

    reasoning = worker_profile.reasoning_required or bool(task_req.reasoning_required)
    coding = worker_profile.coding_required or bool(task_req.coding_required)
    structured_out = worker_profile.structured_output_required or bool(task_req.structured_output_required)
    tool_use = worker_profile.tool_use_required or bool(task_req.tool_use_required)
    multimodal = worker_profile.multimodal_required or bool(task_req.multimodal_required)

    if reasoning:
        req_caps.add(CapabilityIds.REASONING)
    if coding:
        req_caps.add(CapabilityIds.CODE_GENERATION)
    if structured_out:
        req_caps.add(CapabilityIds.STRUCTURED_OUTPUT)
    if tool_use:
        req_caps.add(CapabilityIds.TOOL_USE)
    if multimodal:
        req_caps.add(CapabilityIds.MULTIMODAL_INPUT)

    # If no specific capability is indicated, default to TEXT_GENERATION
    if not req_caps:
        req_caps.add(CapabilityIds.TEXT_GENERATION)

    pref_caps = set(worker_profile.preferred_capabilities)
    pref_caps.update(task_req.preferred_capabilities)

    # 2. Context window: task can increase (strengthen), but never decrease below worker minimum
    task_context = task_req.min_context_window_tokens or 0
    min_context = max(worker_profile.min_context_window_tokens, task_context)

    # 3. Privacy policy: worker's local_only constraint cannot be relaxed by a task
    if worker_profile.privacy_policy == "local_only":
        if task_req.privacy_policy and task_req.privacy_policy != "local_only":
            # Task attempted to weaken privacy constraint; enforce worker constraint deterministically
            privacy = "local_only"
        else:
            privacy = "local_only"
    elif task_req.privacy_policy:
        privacy = task_req.privacy_policy
    else:
        privacy = worker_profile.privacy_policy

    # 4. Quality priority: take the higher tier
    quality = max(worker_profile.quality_priority, task_req.quality_priority or 1)

    # 5. Priorities and fallback
    latency = task_req.latency_priority or worker_profile.latency_priority
    cost = task_req.cost_priority or worker_profile.cost_priority
    reliability = max(worker_profile.reliability_minimum, task_req.reliability_minimum or 0.0)
    fallback = task_req.fallback_policy or worker_profile.fallback_policy

    return EffectiveModelRequirements(
        required_capabilities=frozenset(req_caps),
        preferred_capabilities=frozenset(pref_caps),
        min_context_window_tokens=min_context,
        reasoning_required=reasoning,
        coding_required=coding,
        structured_output_required=structured_out,
        tool_use_required=tool_use,
        multimodal_required=multimodal,
        privacy_policy=privacy,
        quality_priority=quality,
        latency_priority=latency,
        cost_priority=cost,
        reliability_minimum=reliability,
        fallback_policy=fallback,
    )


class ExpertiseModel(BaseModel):
    """
    Structural representation of a worker's expertise, constraints, permissions, and model profile.
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
    model_profile: WorkerModelProfile = Field(default_factory=WorkerModelProfile)
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
