"""Standalone Automation Runtime & Execution Engine (18-COMMERCIAL-C)."""

from __future__ import annotations

import logging
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.automation.spec import (
    CustomerAutomationSpecification,
    StepSpec,
    StepType,
)
from autoforge_power_engines.automation.state_machine import (
    WorkflowStateMachine,
    WorkflowState,
    StepExecutionState,
)
from autoforge_power_engines.automation.actions import ActionRegistry
from autoforge_power_engines.automation.approval import ApprovalManager, ApprovalRequest, ApprovalStatus
from autoforge_power_engines.automation.idempotency import IdempotencyStore
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
from autoforge_power_engines.automation.conditions import resolve_values_recursively

logger = logging.getLogger("autoforge.power_engines.automation.runtime")


class WorkflowExecutionOutcome(BaseModel):
    """Final result of executing or pausing a workflow."""
    execution_id: str
    workflow_id: str
    status: WorkflowState
    success: bool
    outputs: Dict[str, Any] = Field(default_factory=dict)
    trace: ExecutionTrace
    pending_approval: Optional[ApprovalRequest] = None
    error_message: Optional[str] = None


class StandaloneAutomationRuntime:
    """
    Self-contained workflow execution runtime.
    Executes declarative workflows deterministically with bounded state,
    idempotency checking, AI steps, human approvals, and full audit traces.
    """

    def __init__(
        self,
        spec: CustomerAutomationSpecification,
        workspace_root: Optional[str | Path] = None,
        state_db_path: Optional[str | Path] = None,
        model_provider: Optional[ModelProvider] = None,
        on_transition: Optional[Callable[[Any], None]] = None,
        allow_private_networks: bool = False,
    ):
        self.spec = spec
        self.workspace_root = str(workspace_root or spec.execution_policy.workspace_directory)
        Path(self.workspace_root).mkdir(parents=True, exist_ok=True)

        self.action_registry = ActionRegistry(
            workspace_root=self.workspace_root,
            allow_private_networks=allow_private_networks,
        )
        self.approval_manager = ApprovalManager()
        self.idempotency_store = IdempotencyStore(db_path=state_db_path)
        self.model_provider = model_provider or OllamaModelProvider(
            base_url=spec.get_deployment_profile().llm_base_url,
            default_model=spec.get_deployment_profile().llm_model,
        )
        self.step_executor = StepExecutor(
            action_registry=self.action_registry,
            approval_manager=self.approval_manager,
            model_provider=self.model_provider,
            workspace_root=self.workspace_root,
        )
        self.on_transition = on_transition

        # In-memory store for active execution states & contexts
        self._active_executions: Dict[str, Dict[str, Any]] = {}

    def start_workflow(
        self,
        inputs: Optional[Dict[str, Any]] = None,
        trigger_name: str = "manual",
        execution_id: Optional[str] = None,
        idempotency_key: Optional[str] = None,
    ) -> WorkflowExecutionOutcome:
        """Starts a new workflow run from initial_step_id."""
        exec_id = execution_id or f"exec-{uuid.uuid4().hex[:10]}"
        raw_inputs = inputs or {}

        # 1. Idempotency Check
        if self.spec.execution_policy.enable_idempotency and idempotency_key:
            exists, cached = self.idempotency_store.check_key(idempotency_key)
            if exists and cached:
                logger.info(f"Idempotent hit for key '{idempotency_key}'. Returning cached execution outcome.")
                trace = ExecutionTrace(
                    execution_id=exec_id,
                    workflow_id=self.spec.workflow_id,
                    workflow_version=self.spec.workflow_version,
                    trigger_name=trigger_name,
                    final_status=WorkflowState.COMPLETED.value,
                    final_outputs=cached,
                )
                return WorkflowExecutionOutcome(
                    execution_id=exec_id,
                    workflow_id=self.spec.workflow_id,
                    status=WorkflowState.COMPLETED,
                    success=True,
                    outputs=cached,
                    trace=trace,
                )
            self.idempotency_store.record_start(
                key=idempotency_key,
                scope="workflow",
                workflow_id=self.spec.workflow_id,
                execution_id=exec_id,
            )

        # 2. Initialize State Machine and Execution Context
        sm = WorkflowStateMachine(on_transition=self.on_transition)
        sm.transition_workflow(WorkflowState.READY, reason="Workflow initialized")
        sm.transition_workflow(WorkflowState.RUNNING, reason=f"Triggered by '{trigger_name}'")

        context: Dict[str, Any] = {
            "inputs": raw_inputs,
            "steps": {},
            "trigger": {"name": trigger_name, "payload": raw_inputs},
            "workflow": {"id": self.spec.workflow_id, "version": self.spec.workflow_version},
        }

        trace = ExecutionTrace(
            execution_id=exec_id,
            workflow_id=self.spec.workflow_id,
            workflow_version=self.spec.workflow_version,
            trigger_name=trigger_name,
        )

        self._active_executions[exec_id] = {
            "state_machine": sm,
            "context": context,
            "trace": trace,
            "current_step_id": self.spec.initial_step_id,
            "idempotency_key": idempotency_key,
            "steps_executed_count": 0,
            "start_time": time.time(),
        }

        return self._run_execution_loop(exec_id)

    def resume_workflow(
        self,
        execution_id: str,
        approval_request_id: str,
        approved: bool,
        reviewer_id: str,
        comment: Optional[str] = None,
    ) -> WorkflowExecutionOutcome:
        """Resumes a paused workflow after human approval sign-off."""
        if execution_id not in self._active_executions:
            raise KeyError(f"Active execution '{execution_id}' not found.")

        exec_data = self._active_executions[execution_id]
        sm: WorkflowStateMachine = exec_data["state_machine"]

        if sm.current_state != WorkflowState.WAITING_FOR_APPROVAL:
            raise ValueError(f"Cannot resume execution in state {sm.current_state.value}")

        # Record decision in ApprovalManager
        self.approval_manager.record_decision(
            request_id=approval_request_id,
            approved=approved,
            reviewer_id=reviewer_id,
            comment=comment,
        )

        sm.transition_workflow(WorkflowState.RUNNING, reason=f"Human approval resolved: {approved}")
        return self._run_execution_loop(execution_id)

    def _run_execution_loop(self, execution_id: str) -> WorkflowExecutionOutcome:
        exec_data = self._active_executions[execution_id]
        sm: WorkflowStateMachine = exec_data["state_machine"]
        context: Dict[str, Any] = exec_data["context"]
        trace: ExecutionTrace = exec_data["trace"]
        current_step_id: Optional[str] = exec_data["current_step_id"]
        policy = self.spec.execution_policy

        while current_step_id:
            # 1. Check execution limits
            if exec_data["steps_executed_count"] >= policy.max_total_steps:
                err = f"Workflow exceeded maximum allowed step limit ({policy.max_total_steps})."
                sm.transition_workflow(WorkflowState.FAILED, reason=err)
                trace.finalize(WorkflowState.FAILED.value, error=err)
                return WorkflowExecutionOutcome(
                    execution_id=execution_id,
                    workflow_id=self.spec.workflow_id,
                    status=WorkflowState.FAILED,
                    success=False,
                    trace=trace,
                    error_message=err,
                )

            elapsed = time.time() - exec_data["start_time"]
            if elapsed > policy.total_timeout_seconds:
                err = f"Workflow exceeded total execution timeout ({policy.total_timeout_seconds}s)."
                sm.transition_workflow(WorkflowState.FAILED, reason=err)
                trace.finalize(WorkflowState.FAILED.value, error=err)
                return WorkflowExecutionOutcome(
                    execution_id=execution_id,
                    workflow_id=self.spec.workflow_id,
                    status=WorkflowState.FAILED,
                    success=False,
                    trace=trace,
                    error_message=err,
                )

            step_spec = self.spec.get_step(current_step_id)
            if not step_spec:
                err = f"Referenced step_id '{current_step_id}' not defined in workflow spec."
                sm.transition_workflow(WorkflowState.FAILED, reason=err)
                trace.finalize(WorkflowState.FAILED.value, error=err)
                return WorkflowExecutionOutcome(
                    execution_id=execution_id,
                    workflow_id=self.spec.workflow_id,
                    status=WorkflowState.FAILED,
                    success=False,
                    trace=trace,
                    error_message=err,
                )

            # 2. Execute step
            sm.transition_workflow(WorkflowState.EXECUTING_STEP, reason=f"Executing step '{step_spec.step_id}'", step_id=step_spec.step_id)
            sm.set_step_state(step_spec.step_id, StepExecutionState.RUNNING)
            exec_data["steps_executed_count"] += 1

            t_step_0 = time.perf_counter()
            step_trace = StepExecutionTrace(
                step_id=step_spec.step_id,
                step_type=step_spec.step_type.value,
                action_name=step_spec.action.name if step_spec.action else None,
                inputs_sanitized=mask_sensitive_data(step_spec.action.parameters if step_spec.action else {}),
            )

            res: StepExecutionResult = self.step_executor.execute_step(
                step=step_spec,
                context=context,
                workflow_id=self.spec.workflow_id,
                execution_id=execution_id,
            )

            step_trace.duration_ms = (time.perf_counter() - t_step_0) * 1000.0
            step_trace.completed_at = datetime.now(timezone.utc).isoformat()
            step_trace.retry_count = res.retry_count
            step_trace.repaired = res.repaired
            step_trace.verification_result = res.verification_result
            step_trace.outputs_sanitized = mask_sensitive_data(res.output)
            step_trace.error_message = res.error_message

            # 3. Handle Human Approval Wait State
            if res.waiting_for_approval:
                sm.transition_workflow(
                    WorkflowState.WAITING_FOR_APPROVAL,
                    reason=f"Step '{step_spec.step_id}' requires human approval",
                    step_id=step_spec.step_id,
                )
                sm.set_step_state(step_spec.step_id, StepExecutionState.WAITING_APPROVAL)
                step_trace.status = "WAITING_APPROVAL"
                trace.step_traces.append(step_trace)

                pending_list = self.approval_manager.list_pending(execution_id=execution_id)
                pending_req = pending_list[0] if pending_list else None

                return WorkflowExecutionOutcome(
                    execution_id=execution_id,
                    workflow_id=self.spec.workflow_id,
                    status=WorkflowState.WAITING_FOR_APPROVAL,
                    success=False,
                    trace=trace,
                    pending_approval=pending_req,
                    outputs={"status": "WAITING_FOR_APPROVAL", "step_id": step_spec.step_id},
                )

            # 4. Step Outcome Evaluation
            if res.success:
                sm.set_step_state(step_spec.step_id, StepExecutionState.SUCCEEDED)
                step_trace.status = "SUCCEEDED"
                trace.step_traces.append(step_trace)

                # Store output in workflow context
                context["steps"][step_spec.step_id] = {
                    "output": res.output,
                    "status": "SUCCEEDED",
                }

                current_step_id = res.next_step_id
                exec_data["current_step_id"] = current_step_id
            else:
                sm.set_step_state(step_spec.step_id, StepExecutionState.FAILED)
                step_trace.status = "FAILED"
                trace.step_traces.append(step_trace)

                # Route to error branch if defined
                if res.next_step_id:
                    logger.warning(f"Step '{step_spec.step_id}' failed, routing to error step '{res.next_step_id}'")
                    current_step_id = res.next_step_id
                    exec_data["current_step_id"] = current_step_id
                else:
                    err = res.error_message or f"Step '{step_spec.step_id}' failed without error handler."
                    sm.transition_workflow(WorkflowState.FAILED, reason=err, step_id=step_spec.step_id)
                    trace.finalize(WorkflowState.FAILED.value, error=err)
                    return WorkflowExecutionOutcome(
                        execution_id=execution_id,
                        workflow_id=self.spec.workflow_id,
                        status=WorkflowState.FAILED,
                        success=False,
                        trace=trace,
                        error_message=err,
                    )

        # 5. Workflow Complete
        sm.transition_workflow(WorkflowState.COMPLETED, reason="All workflow steps finished successfully")
        final_outputs = self._resolve_output_mapping(context)
        trace.finalize(WorkflowState.COMPLETED.value, outputs=final_outputs)

        # Record idempotency completion if enabled
        idempotency_key = exec_data.get("idempotency_key")
        if idempotency_key and policy.enable_idempotency:
            self.idempotency_store.record_complete(idempotency_key, final_outputs)

        return WorkflowExecutionOutcome(
            execution_id=execution_id,
            workflow_id=self.spec.workflow_id,
            status=WorkflowState.COMPLETED,
            success=True,
            outputs=final_outputs,
            trace=trace,
        )

    def _resolve_output_mapping(self, context: Dict[str, Any]) -> Dict[str, Any]:
        """Maps final output variables per spec.output_mapping."""
        if not self.spec.output_mapping:
            # Default to all step outputs
            return {k: v.get("output", {}) for k, v in context.get("steps", {}).items()}

        return {k: resolve_values_recursively(v, context) for k, v in self.spec.output_mapping.items()}
