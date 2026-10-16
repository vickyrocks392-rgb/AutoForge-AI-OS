"""Customer AI Agent Specification Models and Validation (Phase 18-COMMERCIAL-B)."""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field, field_validator, model_validator

from autoforge_power_engines.specification import (
    CustomerProjectSpecification,
    CustomerDeploymentProfile,
    DeploymentPreference,
    DeploymentTarget,
    LLMProviderType,
)
from autoforge_power_engines.delivery.spec import (
    CustomerDeploymentSpec,
    ServiceDefinition,
    PortMapping,
    VolumeDefinition,
    NetworkDefinition,
    RestartPolicy,
    HealthCheckSpec,
)


class ToolRiskLevel(str, Enum):
    """Risk classification for agent tools."""
    SAFE_READ = "safe_read"
    COMPUTATION = "computation"
    NETWORK_IO = "network_io"
    WORKSPACE_WRITE = "workspace_write"
    ELEVATED = "elevated"


class AgentToolConfig(BaseModel):
    """Declarative specification for an agent tool."""
    name: str = Field(..., min_length=1, description="Unique tool identifier")
    description: str = Field(..., min_length=1, description="Functional summary presented to the model")
    parameters: Dict[str, Any] = Field(
        default_factory=lambda: {"type": "object", "properties": {}},
        description="JSON Schema for tool arguments"
    )
    risk_level: ToolRiskLevel = Field(default=ToolRiskLevel.SAFE_READ, description="Tool risk classification")
    timeout_seconds: float = Field(default=10.0, gt=0, le=120, description="Execution timeout for this tool")
    requires_approval: bool = Field(default=False, description="Whether invocation requires human approval")

    @field_validator("name")
    @classmethod
    def validate_tool_name(cls, v: str) -> str:
        name = v.strip()
        if not name.replace("_", "").isalnum():
            raise ValueError(f"Tool name '{v}' must be alphanumeric with underscores only.")
        return name


class AgentModelConfig(BaseModel):
    """Inference configuration for customer agent."""
    provider: str = Field(default="generic_http", description="Inference provider (generic_http, ollama, external_http)")
    model_name: str = Field(default="mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2", description="Model identifier")
    base_url: str = Field(default="http://127.0.0.1:19801/v1", description="Provider API base endpoint")
    temperature: float = Field(default=0.2, ge=0.0, le=2.0, description="Sampling temperature")
    max_tokens: int = Field(default=2048, ge=64, le=32768, description="Max generation tokens")
    timeout_seconds: float = Field(default=60.0, gt=0, description="HTTP request timeout")


class MemoryPolicy(BaseModel):
    """Agent memory and persistence configuration."""
    enabled: bool = Field(default=True, description="Enable conversation and state persistence")
    max_history_turns: int = Field(default=20, ge=1, le=200, description="Sliding conversation turn window")
    persistence_type: str = Field(default="sqlite", description="Persistence mechanism (sqlite, in_memory)")
    database_path: str = Field(default="data/state/agent_state.db", description="Relative path to state database")


class ExecutionLimits(BaseModel):
    """Deterministic bounding limits for the agent loop."""
    max_iterations: int = Field(default=10, ge=1, le=50, description="Maximum thought/tool loop iterations per turn")
    max_tool_calls_per_turn: int = Field(default=5, ge=1, le=30, description="Max tool executions per turn")
    total_timeout_seconds: float = Field(default=120.0, gt=0, le=600, description="Max turn duration before TIMEOUT")


class RetryPolicy(BaseModel):
    """Bounded recovery policy for tool and model failures."""
    max_retries: int = Field(default=2, ge=0, le=5, description="Maximum retry attempts on transient tool errors")
    repair_malformed_args: bool = Field(default=True, description="Attempt 1-pass repair for malformed tool arguments")
    backoff_seconds: float = Field(default=0.5, ge=0.0, description="Delay between retries")


class VerificationPolicy(BaseModel):
    """Deterministic verification rules."""
    verify_tool_inputs: bool = Field(default=True, description="Validate tool arguments against JSON Schema")
    verify_tool_outputs: bool = Field(default=True, description="Validate tool responses are non-empty and well-formed")
    verify_final_state: bool = Field(default=True, description="Verify agent concluded in valid terminal state")


class SafetyConstraintsConfig(BaseModel):
    """Security restrictions enforced on the agent and its tools."""
    deny_shell: bool = Field(default=True, description="Strictly prohibit arbitrary shell execution")
    deny_arbitrary_python: bool = Field(default=True, description="Strictly prohibit arbitrary Python eval/exec")
    path_confinement: bool = Field(default=True, description="Confine all file tools to customer workspace")
    allowed_workspace_dirs: List[str] = Field(
        default_factory=lambda: ["./data/workspace", "./workspace"],
        description="Jailed directories accessible to file tools"
    )
    url_validation: bool = Field(default=True, description="Validate outbound URLs for HTTP tools")
    deny_private_networks: bool = Field(default=True, description="Block SSRF to localhost/link-local/RFC1918")
    allowed_domains: List[str] = Field(default_factory=list, description="Optional whitelist of outbound domains")


class CustomerAgentSpecification(CustomerProjectSpecification):
    """
    Declarative Commercial Customer Agent Specification (Phase 18-COMMERCIAL-B).
    Extends CustomerProjectSpecification to maintain full compatibility with the
    shared PowerEngine lifecycle while adding rich agent domain contracts.
    """
    agent_purpose: str = Field(..., min_length=5, description="High-level commercial objective and role of the agent")
    system_instructions: str = Field(..., min_length=10, description="Detailed behavioral rules and persona prompt")
    model_config_spec: AgentModelConfig = Field(default_factory=AgentModelConfig, description="Model inference setup")
    allowed_tools: List[str] = Field(
        default_factory=lambda: ["calculator", "structured_http", "document_lookup", "current_time", "file_read"],
        description="List of tool names permitted for this agent"
    )
    tool_definitions: List[AgentToolConfig] = Field(
        default_factory=list,
        description="Explicit tool configurations (derived or customer-supplied)"
    )
    memory_policy: MemoryPolicy = Field(default_factory=MemoryPolicy, description="State and memory persistence rules")
    execution_limits: ExecutionLimits = Field(default_factory=ExecutionLimits, description="Execution bounding constraints")
    retry_policy: RetryPolicy = Field(default_factory=RetryPolicy, description="Recovery policy")
    verification_policy: VerificationPolicy = Field(default_factory=VerificationPolicy, description="Verification policies")
    safety_constraints: SafetyConstraintsConfig = Field(default_factory=SafetyConstraintsConfig, description="Security sandbox")
    require_ui: bool = Field(default=True, description="Include customer web UI")
    require_api: bool = Field(default=True, description="Include customer REST API")
    host: str = Field(default="127.0.0.1", description="Localhost binding")
    port: int = Field(default=8000, description="Customer API port")

    @model_validator(mode="before")
    @classmethod
    def populate_base_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if "project_description" not in data or not data["project_description"]:
                purpose = data.get("agent_purpose", "")
                data["project_description"] = f"Customer AI Agent: {purpose}"
            if "desired_assistant_behavior" not in data or not data["desired_assistant_behavior"]:
                data["desired_assistant_behavior"] = data.get("system_instructions", "Helpful assistant")
        return data

    @model_validator(mode="after")
    def validate_agent_integrity(self) -> "CustomerAgentSpecification":
        # 1. Ensure safety invariant: shell & arbitrary python execution must never be permitted
        if not self.safety_constraints.deny_shell:
            raise ValueError("Security violation: deny_shell must be True. Arbitrary shell execution is forbidden.")
        if not self.safety_constraints.deny_arbitrary_python:
            raise ValueError("Security violation: deny_arbitrary_python must be True. Arbitrary code eval is forbidden.")

        # 2. Check that allowed_tools does not contain forbidden dangerous tools
        forbidden_tools = {"bash", "sh", "shell", "exec", "system", "terminal", "eval"}
        for t in self.allowed_tools:
            if t.lower() in forbidden_tools:
                raise ValueError(f"Security violation: tool '{t}' is forbidden in commercial customer agents.")

        # 3. Synchronize tool definitions if not explicitly provided
        if not self.tool_definitions and self.allowed_tools:
            built_in_defs = {
                "calculator": AgentToolConfig(
                    name="calculator",
                    description="Evaluate a mathematical expression safely (supports +, -, *, /, **, %, parentheses).",
                    parameters={
                        "type": "object",
                        "properties": {
                            "expression": {"type": "string", "description": "The mathematical expression to evaluate"}
                        },
                        "required": ["expression"]
                    },
                    risk_level=ToolRiskLevel.COMPUTATION,
                ),
                "structured_http": AgentToolConfig(
                    name="structured_http",
                    description="Execute a safe outbound HTTP GET or POST request to a public API endpoint.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "url": {"type": "string", "description": "The destination HTTP URL"},
                            "method": {"type": "string", "enum": ["GET", "POST"], "default": "GET"},
                            "headers": {"type": "object", "description": "Optional HTTP headers"},
                            "params": {"type": "object", "description": "Query parameters"},
                            "json_body": {"type": "object", "description": "JSON payload for POST"}
                        },
                        "required": ["url"]
                    },
                    risk_level=ToolRiskLevel.NETWORK_IO,
                ),
                "document_lookup": AgentToolConfig(
                    name="document_lookup",
                    description="Search for keywords or phrases across text documents in the customer workspace.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "query": {"type": "string", "description": "Search query keywords"}
                        },
                        "required": ["query"]
                    },
                    risk_level=ToolRiskLevel.SAFE_READ,
                ),
                "current_time": AgentToolConfig(
                    name="current_time",
                    description="Retrieve the current date and time in UTC or local timezone.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "timezone": {"type": "string", "default": "UTC", "description": "Timezone name (e.g. UTC, US/Eastern)"}
                        }
                    },
                    risk_level=ToolRiskLevel.COMPUTATION,
                ),
                "file_read": AgentToolConfig(
                    name="file_read",
                    description="Read the contents of a confined text file within the customer workspace.",
                    parameters={
                        "type": "object",
                        "properties": {
                            "file_path": {"type": "string", "description": "Relative path to file inside workspace"}
                        },
                        "required": ["file_path"]
                    },
                    risk_level=ToolRiskLevel.SAFE_READ,
                ),
            }
            resolved: List[AgentToolConfig] = []
            for tool_name in self.allowed_tools:
                if tool_name in built_in_defs:
                    resolved.append(built_in_defs[tool_name])
                else:
                    raise ValueError(
                        f"Unknown tool '{tool_name}' in allowed_tools. "
                        f"Provide an explicit AgentToolConfig in tool_definitions for custom tools."
                    )
            self.tool_definitions = resolved
        elif self.tool_definitions:
            declared_names = {t.name for t in self.tool_definitions}
            for t_name in self.allowed_tools:
                if t_name not in declared_names:
                    raise ValueError(f"Allowed tool '{t_name}' has no matching declaration in tool_definitions.")

        return self

    def to_deployment_spec(self) -> CustomerDeploymentSpec:
        """Constructs universal CustomerDeploymentSpec for Commercial B Agent workload."""
        sanitized_pid = self.sanitized_project_id()
        primary_service_name = "agent_api"

        services: Dict[str, ServiceDefinition] = {
            primary_service_name: ServiceDefinition(
                name=primary_service_name,
                build_context=".",
                dockerfile="Dockerfile",
                container_name=f"customer_agent_{sanitized_pid}",
                restart_policy=RestartPolicy.UNLESS_STOPPED,
                ports=[
                    PortMapping(host_ip=self.host, host_port=self.port, container_port=self.port)
                ],
                environment={
                    "PORT": str(self.port),
                    "HOST": "0.0.0.0",
                    "MODEL_PROVIDER": self.model_config_spec.provider,
                    "MODEL_NAME": self.model_config_spec.model_name,
                    "LLM_BASE_URL": self.model_config_spec.base_url.replace("127.0.0.1", "host.docker.internal").replace("localhost", "host.docker.internal") if ("127.0.0.1" in self.model_config_spec.base_url or "localhost" in self.model_config_spec.base_url) else self.model_config_spec.base_url,
                    "MAX_ITERATIONS": str(self.execution_limits.max_iterations),
                    "MAX_TOOL_CALLS": str(self.execution_limits.max_tool_calls_per_turn),
                    "REQUEST_TIMEOUT": str(int(self.execution_limits.total_timeout_seconds)),
                    "MEMORY_ENABLED": str(self.memory_policy.enabled).lower(),
                },
                volumes=[
                    VolumeDefinition(host_path="./data/state", container_path="/app/data/state"),
                    VolumeDefinition(host_path="./data/workspace", container_path="/app/data/workspace"),
                    VolumeDefinition(host_path="./data/logs", container_path="/app/data/logs"),
                    VolumeDefinition(host_path="./config", container_path="/app/config"),
                ],
                networks=["agent_network"],
                extra_hosts=["host.docker.internal:host-gateway"],
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                cpu_limit="2.0",
                memory_limit="2048M",
            )
        }

        networks = {
            "agent_network": NetworkDefinition(name="agent_network", driver="bridge", internal=False)
        }

        data_directories = [
            "data/state",
            "data/workspace",
            "data/logs",
            "data/config",
        ]

        health_checks = [
            HealthCheckSpec(
                name="agent_api",
                endpoint_or_command=f"http://127.0.0.1:{self.port}/health",
                interval_seconds=10,
                timeout_seconds=5,
                retries=3,
                description="Verifies customer AI agent REST API is operational"
            )
        ]

        global_env = {
            "MODEL_PROVIDER": self.model_config_spec.provider,
            "MODEL_NAME": self.model_config_spec.model_name,
            "LLM_BASE_URL": self.model_config_spec.base_url,
            "MAX_ITERATIONS": str(self.execution_limits.max_iterations),
            "MAX_TOOL_CALLS": str(self.execution_limits.max_tool_calls_per_turn),
            "REQUEST_TIMEOUT": str(int(self.execution_limits.total_timeout_seconds)),
            "MEMORY_ENABLED": str(self.memory_policy.enabled).lower(),
        }

        return CustomerDeploymentSpec(
            project_name=self.project_name,
            sanitized_project_id=sanitized_pid,
            target=DeploymentTarget.DOCKER_HOST,
            primary_service=primary_service_name,
            services=services,
            networks=networks,
            global_environment=global_env,
            persistent_storage=True,
            private_networking=True,
            auto_open_browser=True,
            data_directories=data_directories,
            health_checks=health_checks,
            metadata={
                "power_engine": "18-COMMERCIAL-B",
                "workload": "custom_ai_agent",
                "agent_purpose": self.agent_purpose,
                "model_name": self.model_config_spec.model_name,
                "allowed_tools": self.allowed_tools,
            }
        )
