"""Step Execution Handlers & AI Decision Evaluation (18-COMMERCIAL-C)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, Optional, Tuple
import requests

from autoforge_power_engines.automation.spec import (
    StepSpec,
    StepType,
    ActionRiskLevel,
)
from autoforge_power_engines.automation.actions import ActionRegistry
from autoforge_power_engines.automation.conditions import ConditionEvaluator, resolve_values_recursively
from autoforge_power_engines.automation.verifier import WorkflowVerifier, VerificationResult
from autoforge_power_engines.automation.repair import RepairHandler
from autoforge_power_engines.automation.approval import ApprovalManager, ApprovalStatus
from autoforge_power_engines.automation.trace import mask_sensitive_data

logger = logging.getLogger("autoforge.power_engines.automation.execution")


class ModelProvider:
    """Interface for invoking local or HTTP LLM backends."""

    def invoke(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.0) -> str:
        raise NotImplementedError


class OllamaModelProvider(ModelProvider):
    """Local Ollama inference provider with zero paid dependencies."""

    def __init__(self, base_url: str = "http://127.0.0.1:11434", default_model: str = "qwen2.5-coder:7b-instruct-q3_K_M"):
        self.base_url = base_url.rstrip("/")
        self.default_model = default_model

    def invoke(self, prompt: str, system: Optional[str] = None, model: Optional[str] = None, temperature: float = 0.0) -> str:
        url = f"{self.base_url}/api/generate"
        payload = {
            "model": model or self.default_model,
            "prompt": prompt,
            "system": system or "You are a precise business automation decision unit. Output strictly valid JSON.",
            "stream": False,
            "options": {"temperature": temperature},
        }

        resp = requests.post(url, json=payload, timeout=90.0)
        if resp.status_code != 200:
            raise RuntimeError(f"Ollama call failed ({resp.status_code}): {resp.text}")

        data = resp.json()
        return data.get("response", "").strip()


class StepExecutionResult:
    """Outcome of executing a single workflow step."""

    def __init__(
        self,
        step_id: str,
        success: bool,
        output: Dict[str, Any],
        next_step_id: Optional[str] = None,
        verification_result: Optional[VerificationResult] = None,
        repaired: bool = False,
        retry_count: int = 0,
        waiting_for_approval: bool = False,
        error_message: Optional[str] = None,
    ):
        self.step_id = step_id
        self.success = success
        self.output = output
        self.next_step_id = next_step_id
        self.verification_result = verification_result
        self.repaired = repaired
        self.retry_count = retry_count
        self.waiting_for_approval = waiting_for_approval
        self.error_message = error_message


class StepExecutor:
    """Executes different step types against runtime context."""

    def __init__(
        self,
        action_registry: ActionRegistry,
        approval_manager: ApprovalManager,
        model_provider: Optional[ModelProvider] = None,
        workspace_root: str = "./data/workspace",
    ):
        self.action_registry = action_registry
        self.approval_manager = approval_manager
        self.model_provider = model_provider or OllamaModelProvider()
        self.workspace_root = workspace_root

    def execute_step(
        self,
        step: StepSpec,
        context: Dict[str, Any],
        workflow_id: str,
        execution_id: str,
    ) -> StepExecutionResult:
        """Dispatches step execution to the specialized handler."""
        if step.step_type == StepType.ACTION:
            return self._execute_action_step(step, context)
        elif step.step_type == StepType.CONDITION:
            return self._execute_condition_step(step, context)
        elif step.step_type == StepType.AI_DECISION:
            return self._execute_ai_decision_step(step, context)
        elif step.step_type == StepType.HUMAN_APPROVAL:
            return self._execute_human_approval_step(step, context, workflow_id, execution_id)
        elif step.step_type == StepType.AGENT_INVOKE:
            return self._execute_agent_invoke_step(step, context)
        else:
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                output={},
                error_message=f"Unsupported step type: {step.step_type}",
            )

    def _execute_action_step(self, step: StepSpec, context: Dict[str, Any]) -> StepExecutionResult:
        act_spec = step.action
        if not act_spec:
            return StepExecutionResult(step.step_id, False, {}, error_message="Missing action spec")

        action = self.action_registry.get(act_spec.action_type)
        if not action:
            return StepExecutionResult(
                step.step_id,
                False,
                {},
                error_message=f"Unauthorized or unregistered action: '{act_spec.action_type}'",
            )

        # Resolve parameters from context
        resolved_params = resolve_values_recursively(act_spec.parameters, context)

        # Execute with retry policy
        def run_action() -> Dict[str, Any]:
            return action.execute(resolved_params, context)

        ok, result, attempts, last_err = RepairHandler.execute_with_retry(
            action_fn=run_action,
            retry_policy=act_spec.retry_policy,
            step_id=step.step_id,
        )

        if not ok:
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                output={},
                next_step_id=step.error_step_id,
                retry_count=attempts,
                error_message=f"Action '{act_spec.name}' failed: {last_err}",
            )

        # Run Verification Rules
        v_res = WorkflowVerifier.verify_step_output(
            step_id=step.step_id,
            output=result,
            rules=act_spec.verification_rules,
            workspace_root=self.workspace_root,
        )

        if not v_res.passed:
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                output=result,
                next_step_id=step.error_step_id,
                verification_result=v_res,
                retry_count=attempts,
                error_message=f"Verification failed: {'; '.join(v_res.failure_reasons)}",
            )

        return StepExecutionResult(
            step_id=step.step_id,
            success=True,
            output=result,
            next_step_id=step.next_step_id,
            verification_result=v_res,
            retry_count=attempts,
        )

    def _execute_condition_step(self, step: StepSpec, context: Dict[str, Any]) -> StepExecutionResult:
        cond_spec = step.condition
        if not cond_spec:
            return StepExecutionResult(step.step_id, False, {}, error_message="Missing condition spec")

        branch_target = ConditionEvaluator.resolve_branch(cond_spec, context)
        return StepExecutionResult(
            step_id=step.step_id,
            success=True,
            output={"resolved_branch": branch_target},
            next_step_id=branch_target,
        )

    def _execute_ai_decision_step(self, step: StepSpec, context: Dict[str, Any]) -> StepExecutionResult:
        ai_spec = step.ai_decision
        if not ai_spec:
            return StepExecutionResult(step.step_id, False, {}, error_message="Missing ai_decision spec")

        # Interpolate prompt template with workflow variables
        resolved_prompt = resolve_values_recursively(ai_spec.prompt_template, context)

        def call_model(prompt: str) -> str:
            return self.model_provider.invoke(
                prompt=prompt,
                system=ai_spec.system_instructions,
                model=ai_spec.model,
                temperature=ai_spec.temperature,
            )

        t0 = time.perf_counter()
        try:
            raw_response = call_model(resolved_prompt)
        except Exception as ex:
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                output={},
                next_step_id=step.error_step_id,
                error_message=f"Model inference failed: {ex}",
            )

        # Parse and repair JSON with schema validation
        ok, parsed, repaired, parse_err = RepairHandler.parse_and_repair_json(
            raw_text=raw_response,
            expected_schema=ai_spec.expected_output_schema,
            repair_fn=call_model if ai_spec.repair_malformed_json else None,
            max_repair_passes=ai_spec.max_repair_passes if ai_spec.repair_malformed_json else 0,
        )

        latency_ms = (time.perf_counter() - t0) * 1000.0

        if not ok:
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                output={"raw_response": raw_response},
                next_step_id=step.error_step_id,
                repaired=repaired,
                error_message=f"AI Decision output schema violation: {parse_err}",
            )

        output_payload = {
            "decision": parsed,
            "model": ai_spec.model,
            "latency_ms": latency_ms,
            "repaired": repaired,
        }

        return StepExecutionResult(
            step_id=step.step_id,
            success=True,
            output=output_payload,
            next_step_id=step.next_step_id,
            repaired=repaired,
        )

    def _execute_human_approval_step(
        self,
        step: StepSpec,
        context: Dict[str, Any],
        workflow_id: str,
        execution_id: str,
    ) -> StepExecutionResult:
        app_spec = step.human_approval
        if not app_spec:
            return StepExecutionResult(step.step_id, False, {}, error_message="Missing human_approval spec")

        # Check if an approval request already exists and was decided
        pending_requests = self.approval_manager.list_pending(execution_id=execution_id)
        existing = [r for r in pending_requests if r.step_id == step.step_id]

        if not existing:
            # Check if there is an already decided request for this step
            all_for_exec = [
                r for r in self.approval_manager._requests.values()
                if r.execution_id == execution_id and r.step_id == step.step_id
            ]
            if all_for_exec:
                req = all_for_exec[-1]
                if req.status == ApprovalStatus.APPROVED:
                    return StepExecutionResult(
                        step_id=step.step_id,
                        success=True,
                        output={"approval_id": req.request_id, "status": "APPROVED", "reviewer": req.decision.reviewer_id if req.decision else None},
                        next_step_id=step.next_step_id,
                    )
                elif req.status == ApprovalStatus.REJECTED:
                    return StepExecutionResult(
                        step_id=step.step_id,
                        success=False,
                        output={"approval_id": req.request_id, "status": "REJECTED"},
                        next_step_id=app_spec.on_reject_step_id or step.error_step_id,
                        error_message=f"Human approval rejected: {req.decision.comment if req.decision else 'Denied'}",
                    )

            # Create new approval request and enter wait state
            req = self.approval_manager.create_request(
                workflow_id=workflow_id,
                execution_id=execution_id,
                step_id=step.step_id,
                spec=app_spec,
                context_summary=mask_sensitive_data(context.get("inputs", {})),
            )
            return StepExecutionResult(
                step_id=step.step_id,
                success=True,
                output={"approval_id": req.request_id, "status": "PENDING"},
                waiting_for_approval=True,
            )

        # If already pending, remain waiting
        return StepExecutionResult(
            step_id=step.step_id,
            success=True,
            output={"approval_id": existing[0].request_id, "status": "PENDING"},
            waiting_for_approval=True,
        )

    def _execute_agent_invoke_step(self, step: StepSpec, context: Dict[str, Any]) -> StepExecutionResult:
        agent_spec = step.agent_invoke
        if not agent_spec:
            return StepExecutionResult(step.step_id, False, {}, error_message="Missing agent_invoke spec")

        # Autonomous bounded agent invocation
        resolved_goal = resolve_values_recursively(agent_spec.agent_goal, context)
        prompt = (
            f"You are an AI Agent performing a specific business task.\n"
            f"Goal: {resolved_goal}\n"
            f"Available tools: {', '.join(agent_spec.allowed_tools)}\n"
            f"Analyze the inputs and provide the final structured findings in JSON format:\n"
            f'{{"status": "completed", "summary": "...", "data": {{}}}}\n'
        )

        try:
            raw = self.model_provider.invoke(prompt=prompt)
            parsed, _ = RepairHandler._try_parse_json(raw, {})
            result_data = parsed or {"raw_output": raw, "status": "completed"}
            return StepExecutionResult(
                step_id=step.step_id,
                success=True,
                output={"agent_result": result_data, "goal": resolved_goal},
                next_step_id=step.next_step_id,
            )
        except Exception as e:
            return StepExecutionResult(
                step_id=step.step_id,
                success=False,
                output={},
                next_step_id=step.error_step_id,
                error_message=f"Agent invocation failed: {e}",
            )
