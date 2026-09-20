"""AutoForge AI Automation Power Engine (Phase 18-COMMERCIAL-C)."""

from autoforge_power_engines.automation.spec import (
    CustomerAutomationSpecification,
    TriggerSpec,
    TriggerType,
    StepSpec,
    StepType,
    ActionSpec,
    ActionRiskLevel,
    ConditionSpec,
    ConditionRule,
    AIDecisionSpec,
    HumanApprovalSpec,
    AgentInvokeSpec,
    WorkflowExecutionPolicy,
    RetryPolicy,
    VerificationRule,
    VerificationRuleType,
    WebhookAuthConfig,
)
from autoforge_power_engines.automation.triggers import (
    Trigger,
    ManualTrigger,
    WebhookTrigger,
    EventTrigger,
    ScheduledTrigger,
    TriggerRegistry,
    TriggerPayload,
    TriggerSecurityError,
)
from autoforge_power_engines.automation.actions import (
    Action,
    ActionRegistry,
    HTTPRequestAction,
    TransformDataAction,
    SafeCalculatorAction,
    FileOperationAction,
    DocumentLookupAction,
    SendOutputAction,
    ActionSecurityError,
    WorkspaceSecurityError,
    SSRFSecurityError,
    validate_workspace_path,
    validate_outbound_url,
    safe_eval_expression,
)
from autoforge_power_engines.automation.conditions import (
    ConditionEvaluator,
    resolve_variable,
    resolve_values_recursively,
)
from autoforge_power_engines.automation.state_machine import (
    WorkflowStateMachine,
    WorkflowState,
    StepExecutionState,
    StateTransitionRecord,
)
from autoforge_power_engines.automation.approval import (
    ApprovalManager,
    ApprovalRequest,
    ApprovalDecision,
    ApprovalStatus,
)
from autoforge_power_engines.automation.verifier import (
    WorkflowVerifier,
    VerificationResult,
    RuleCheckOutcome,
)
from autoforge_power_engines.automation.repair import (
    RepairHandler,
)
from autoforge_power_engines.automation.idempotency import (
    IdempotencyStore,
)
from autoforge_power_engines.automation.trace import (
    ExecutionTrace,
    StepExecutionTrace,
    mask_sensitive_data,
)
from autoforge_power_engines.automation.execution import (
    StepExecutor,
    StepExecutionResult,
    ModelProvider,
    OllamaModelProvider,
)
from autoforge_power_engines.automation.runtime import (
    StandaloneAutomationRuntime,
    WorkflowExecutionOutcome,
)
from autoforge_power_engines.automation.generator import (
    StandaloneCustomerAutomationGenerator,
)
from autoforge_power_engines.automation.engine import (
    AIAutomationPowerEngine,
)

__all__ = [
    "CustomerAutomationSpecification",
    "TriggerSpec",
    "TriggerType",
    "StepSpec",
    "StepType",
    "ActionSpec",
    "ActionRiskLevel",
    "ConditionSpec",
    "ConditionRule",
    "AIDecisionSpec",
    "HumanApprovalSpec",
    "AgentInvokeSpec",
    "WorkflowExecutionPolicy",
    "RetryPolicy",
    "VerificationRule",
    "VerificationRuleType",
    "WebhookAuthConfig",
    "Trigger",
    "ManualTrigger",
    "WebhookTrigger",
    "EventTrigger",
    "ScheduledTrigger",
    "TriggerRegistry",
    "TriggerPayload",
    "TriggerSecurityError",
    "Action",
    "ActionRegistry",
    "HTTPRequestAction",
    "TransformDataAction",
    "SafeCalculatorAction",
    "FileOperationAction",
    "DocumentLookupAction",
    "SendOutputAction",
    "ActionSecurityError",
    "WorkspaceSecurityError",
    "SSRFSecurityError",
    "validate_workspace_path",
    "validate_outbound_url",
    "safe_eval_expression",
    "ConditionEvaluator",
    "resolve_variable",
    "resolve_values_recursively",
    "WorkflowStateMachine",
    "WorkflowState",
    "StepExecutionState",
    "StateTransitionRecord",
    "ApprovalManager",
    "ApprovalRequest",
    "ApprovalDecision",
    "ApprovalStatus",
    "WorkflowVerifier",
    "VerificationResult",
    "RuleCheckOutcome",
    "RepairHandler",
    "IdempotencyStore",
    "ExecutionTrace",
    "StepExecutionTrace",
    "mask_sensitive_data",
    "StepExecutor",
    "StepExecutionResult",
    "ModelProvider",
    "OllamaModelProvider",
    "StandaloneAutomationRuntime",
    "WorkflowExecutionOutcome",
    "StandaloneCustomerAutomationGenerator",
    "AIAutomationPowerEngine",
]
