"""Declarative Workflow & Automation Specification Models (18-COMMERCIAL-C)."""

from __future__ import annotations

import re
from enum import Enum
from typing import Any, Dict, List, Optional, Union
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


class TriggerType(str, Enum):
    """Supported workflow trigger types."""
    MANUAL = "manual"
    WEBHOOK = "webhook"
    EVENT = "event"
    SCHEDULE = "schedule"


class StepType(str, Enum):
    """Supported workflow step types."""
    ACTION = "action"
    CONDITION = "condition"
    AI_DECISION = "ai_decision"
    HUMAN_APPROVAL = "human_approval"
    AGENT_INVOKE = "agent_invoke"


class ActionRiskLevel(str, Enum):
    """Risk tiers for workflow operations."""
    READ_ONLY = "read_only"
    SAFE_TRANSFORM = "safe_transform"
    EXTERNAL_CALL = "external_call"
    MUTATING_DATA = "mutating_data"
    HIGH_RISK = "high_risk"


class VerificationRuleType(str, Enum):
    """Deterministic verification rules."""
    SCHEMA = "schema"
    HTTP_STATUS = "http_status"
    NUMERIC_INVARIANT = "numeric_invariant"
    REQUIRED_FIELD = "required_field"
    FILE_EXISTS = "file_exists"
    BUSINESS_RULE = "business_rule"


# ── Sub-Specification Models ──────────────────────────────────────────────────

class WebhookAuthConfig(BaseModel):
    """Authentication and security configuration for webhook triggers."""
    require_auth: bool = False
    auth_header_name: str = "Authorization"
    expected_token: Optional[str] = None
    hmac_secret: Optional[str] = None
    hmac_header_name: str = "X-Webhook-Signature"
    max_payload_bytes: int = 1048576  # 1MB safe default


class TriggerSpec(BaseModel):
    """Specification for a workflow trigger."""
    name: str = Field(..., min_length=1)
    trigger_type: TriggerType = TriggerType.MANUAL
    description: Optional[str] = None
    # Webhook specific
    webhook_path: Optional[str] = None
    webhook_auth: WebhookAuthConfig = Field(default_factory=WebhookAuthConfig)
    # Event specific
    event_topic: Optional[str] = None
    event_pattern: Dict[str, Any] = Field(default_factory=dict)
    # Schedule specific (declarative cron / interval abstraction)
    cron_expression: Optional[str] = None
    interval_seconds: Optional[int] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
            raise ValueError(f"Trigger name '{v}' must be alphanumeric with underscores or hyphens.")
        return v


class RetryPolicy(BaseModel):
    """Bounded, deterministic retry policy."""
    max_attempts: int = Field(default=3, ge=1, le=10)
    initial_backoff_ms: int = Field(default=100, ge=0, le=30000)
    backoff_multiplier: float = Field(default=2.0, ge=1.0, le=5.0)
    max_backoff_ms: int = Field(default=5000, ge=0, le=60000)
    retryable_error_types: List[str] = Field(
        default_factory=lambda: ["TimeoutError", "ConnectionError", "TransientError", "HTTP_503", "HTTP_502", "HTTP_504"]
    )


class VerificationRule(BaseModel):
    """Deterministic verification requirement for step output."""
    rule_type: VerificationRuleType
    rule_name: str
    config: Dict[str, Any] = Field(default_factory=dict)
    severity: str = "ERROR"  # ERROR fails the step; WARNING flags audit trace


class ActionSpec(BaseModel):
    """Declarative specification for an executable workflow action."""
    action_type: str = Field(..., min_length=1, description="Registered action identifier, e.g. 'http_request', 'safe_calculator'")
    name: str = Field(..., min_length=1)
    description: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    timeout_seconds: float = Field(default=30.0, ge=0.1, le=300.0)
    risk_level: ActionRiskLevel = ActionRiskLevel.SAFE_TRANSFORM
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy)
    verification_rules: List[VerificationRule] = Field(default_factory=list)
    idempotency_key_template: Optional[str] = None  # e.g. "${inputs.invoice_id}-${step.name}"


class ConditionRule(BaseModel):
    """AST-safe condition evaluation rule."""
    field: Optional[str] = None  # e.g. "${steps.calc_total.output.amount}"
    operator: str = "eq"  # "eq", "neq", "gt", "gte", "lt", "lte", "contains", "in", "matches"
    value: Any = None
    # Boolean logic composites
    all_of: Optional[List[ConditionRule]] = None
    any_of: Optional[List[ConditionRule]] = None
    not_rule: Optional[ConditionRule] = None


class ConditionSpec(BaseModel):
    """Branching decision based on condition rule."""
    rule: ConditionRule
    then_step_id: str
    else_step_id: Optional[str] = None


class AIDecisionSpec(BaseModel):
    """Structured AI reasoning decision step with schema constraints."""
    prompt_template: str = Field(..., min_length=5)
    model: str = "qwen2.5-coder:7b-instruct-q3_K_M"
    expected_output_schema: Dict[str, Any] = Field(..., description="JSON Schema for required structured output")
    system_instructions: Optional[str] = "You are a precise business automation decision unit. Output strictly valid JSON matching the schema."
    temperature: float = Field(default=0.0, ge=0.0, le=1.0)
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=180.0)
    repair_malformed_json: bool = True
    max_repair_passes: int = Field(default=1, ge=1, le=2)


class HumanApprovalSpec(BaseModel):
    """Human-in-the-loop intervention requirement."""
    reason: str
    approval_prompt: str
    risk_level: ActionRiskLevel = ActionRiskLevel.HIGH_RISK
    approver_roles: List[str] = Field(default_factory=lambda: ["OPERATOR", "ADMIN"])
    timeout_seconds: float = Field(default=3600.0, ge=10.0, le=86400.0)
    on_reject_step_id: Optional[str] = None  # If rejected, jump to alternative step


class AgentInvokeSpec(BaseModel):
    """Composition step invoking an AI agent reasoning task."""
    agent_goal: str = Field(..., min_length=5)
    allowed_tools: List[str] = Field(default_factory=lambda: ["calculator", "document_lookup", "file_read"])
    max_iterations: int = Field(default=5, ge=1, le=15)
    timeout_seconds: float = Field(default=60.0, ge=1.0, le=180.0)


class StepSpec(BaseModel):
    """A single node in the workflow execution graph."""
    step_id: str = Field(..., min_length=1)
    name: str = Field(..., min_length=1)
    step_type: StepType = StepType.ACTION
    description: Optional[str] = None
    # Depending on step_type:
    action: Optional[ActionSpec] = None
    condition: Optional[ConditionSpec] = None
    ai_decision: Optional[AIDecisionSpec] = None
    human_approval: Optional[HumanApprovalSpec] = None
    agent_invoke: Optional[AgentInvokeSpec] = None
    # Flow progression
    next_step_id: Optional[str] = None
    error_step_id: Optional[str] = None

    @field_validator("step_id")
    @classmethod
    def validate_step_id(cls, v: str) -> str:
        v = v.strip()
        if not re.match(r"^[a-zA-Z0-9_\-]+$", v):
            raise ValueError(f"step_id '{v}' must be alphanumeric with underscores or hyphens.")
        return v


class WorkflowExecutionPolicy(BaseModel):
    """Safety and boundary limits for workflow execution."""
    max_total_steps: int = Field(default=50, ge=1, le=500)
    total_timeout_seconds: float = Field(default=600.0, ge=1.0, le=3600.0)
    enable_idempotency: bool = True
    record_audit_trace: bool = True
    allow_workspace_file_operations: bool = True
    workspace_directory: str = "./data/workspace"
    ssrf_protection: bool = True


# ── Top-Level Customer Automation Specification ───────────────────────────────

class CustomerAutomationSpecification(CustomerProjectSpecification):
    """
    Canonical specification contract for the AI Automation Power Engine (18-COMMERCIAL-C).
    Defines business workflows, triggers, actions, conditions, AI steps, and verification policies.
    """
    workflow_id: str = Field(default="business_process_v1", min_length=1)
    workflow_version: str = Field(default="1.0.0")
    triggers: List[TriggerSpec] = Field(default_factory=lambda: [TriggerSpec(name="default_manual", trigger_type=TriggerType.MANUAL)])
    initial_step_id: str = Field(..., min_length=1)
    steps: List[StepSpec] = Field(..., min_length=1)
    execution_policy: WorkflowExecutionPolicy = Field(default_factory=WorkflowExecutionPolicy)
    output_mapping: Dict[str, str] = Field(default_factory=dict, description="Final workflow output variables e.g. {'invoice_status': '${steps.process.output.status}'}")

    @field_validator("steps")
    @classmethod
    def validate_steps_graph(cls, steps: List[StepSpec]) -> List[StepSpec]:
        step_ids = set()
        for s in steps:
            if s.step_id in step_ids:
                raise ValueError(f"Duplicate step_id detected in workflow: '{s.step_id}'")
            step_ids.add(s.step_id)

            # Validate type-specific payloads
            if s.step_type == StepType.ACTION and not s.action:
                raise ValueError(f"Step '{s.step_id}' has step_type ACTION but no 'action' configuration.")
            elif s.step_type == StepType.CONDITION and not s.condition:
                raise ValueError(f"Step '{s.step_id}' has step_type CONDITION but no 'condition' configuration.")
            elif s.step_type == StepType.AI_DECISION and not s.ai_decision:
                raise ValueError(f"Step '{s.step_id}' has step_type AI_DECISION but no 'ai_decision' configuration.")
            elif s.step_type == StepType.HUMAN_APPROVAL and not s.human_approval:
                raise ValueError(f"Step '{s.step_id}' has step_type HUMAN_APPROVAL but no 'human_approval' configuration.")
            elif s.step_type == StepType.AGENT_INVOKE and not s.agent_invoke:
                raise ValueError(f"Step '{s.step_id}' has step_type AGENT_INVOKE but no 'agent_invoke' configuration.")

        return steps

    def get_step(self, step_id: str) -> Optional[StepSpec]:
        """Finds a step definition by its ID."""
        for s in self.steps:
            if s.step_id == step_id:
                return s
        return None

    def to_deployment_spec(self) -> CustomerDeploymentSpec:
        """Adapts this automation specification into the universal CustomerDeploymentSpec."""
        sanitized_pid = self.sanitized_project_id()
        port = 8000
        profile = self.get_deployment_profile()

        services = {
            "automation_api": ServiceDefinition(
                name="automation_api",
                build_context=".",
                dockerfile="Dockerfile",
                container_name=f"customer_automation_{sanitized_pid}",
                restart_policy=RestartPolicy.UNLESS_STOPPED,
                ports=[PortMapping(host_ip=profile.host, host_port=port, container_port=port)],
                environment={
                    "PORT": str(port),
                    "WORKFLOW_ID": self.workflow_id,
                    "WORKFLOW_VERSION": self.workflow_version,
                    "LLM_BASE_URL": profile.llm_base_url,
                    "LLM_MODEL": profile.llm_model,
                },
                volumes=[
                    VolumeDefinition(host_path="./data/workspace", container_path="/app/data/workspace"),
                    VolumeDefinition(host_path="./data/state", container_path="/app/data/state"),
                    VolumeDefinition(host_path="./data/logs", container_path="/app/data/logs"),
                    VolumeDefinition(host_path="./config", container_path="/app/config"),
                ],
                networks=["automation_network"],
                extra_hosts=["host.docker.internal:host-gateway"],
            )
        }

        networks = {
            "automation_network": NetworkDefinition(name="automation_network", driver="bridge", internal=False)
        }

        data_dirs = [
            "data/workspace",
            "data/state",
            "data/logs",
            "data/config",
            "data/traces",
        ]

        health_checks = [
            HealthCheckSpec(name="automation_health", endpoint_or_command=f"http://127.0.0.1:{port}/health"),
            HealthCheckSpec(name="workflow_status", endpoint_or_command=f"http://127.0.0.1:{port}/workflows/{self.workflow_id}"),
        ]

        return CustomerDeploymentSpec(
            project_name=self.project_name,
            sanitized_project_id=sanitized_pid,
            target=profile.target,
            primary_service="automation_api",
            services=services,
            networks=networks,
            data_directories=data_dirs,
            health_checks=health_checks,
            metadata={
                "power_engine": "18-COMMERCIAL-C",
                "workload": "ai_automation_workflow",
                "workflow_id": self.workflow_id,
                "workflow_version": self.workflow_version,
                "steps_count": len(self.steps),
            },
        )
