"""Deterministic Verification and Bounded Repair Coordinator (Phase 18-COMMERCIAL-B).

Enforces strict runtime correctness checks and bounded recovery policies
for tool calls, schemas, execution limits, and terminal state.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.agent.spec import RetryPolicy, VerificationPolicy
from autoforge_power_engines.agent.parser import ParsedToolCall
from autoforge_power_engines.agent.tools import ToolRegistry

logger = logging.getLogger("autoforge.power_engines.agent.verifier")


class VerificationResult(BaseModel):
    passed: bool
    requires_repair: bool = False
    repair_prompt: Optional[str] = None
    violation_code: Optional[str] = None
    details: Dict[str, Any] = Field(default_factory=dict)


class AgentVerifier:
    """Verifies tool calls, schemas, and execution state against commercial policies."""

    def __init__(
        self,
        tool_registry: ToolRegistry,
        verification_policy: VerificationPolicy,
        retry_policy: RetryPolicy,
    ):
        self.tool_registry = tool_registry
        self.verification_policy = verification_policy
        self.retry_policy = retry_policy

    def verify_tool_call(self, call: ParsedToolCall, repair_attempts: int = 0) -> VerificationResult:
        """Verifies an incoming tool call before execution."""
        # Check for parsing errors
        if call.parse_error:
            if self.retry_policy.repair_malformed_args and repair_attempts < 1:
                return VerificationResult(
                    passed=False,
                    requires_repair=True,
                    repair_prompt=f"The previous tool call was malformed: {call.parse_error}. Please provide valid JSON.",
                    violation_code="MALFORMED_TOOL_SYNTAX",
                    details={"raw_input": call.raw_input},
                )
            return VerificationResult(
                passed=False,
                requires_repair=False,
                violation_code="UNREPAIRABLE_MALFORMED_SYNTAX",
                details={"error": call.parse_error},
            )

        # Check tool registration
        if not self.tool_registry.has_tool(call.tool_name):
            return VerificationResult(
                passed=False,
                requires_repair=False,
                violation_code="UNKNOWN_TOOL",
                details={"tool_name": call.tool_name},
            )

        # Check arguments against schema if required
        if self.verification_policy.verify_tool_inputs:
            config = self.tool_registry.get_tool_config(call.tool_name)
            if config and config.parameters:
                required = config.parameters.get("required", [])
                missing = [r for r in required if r not in call.arguments]
                if missing:
                    if self.retry_policy.repair_malformed_args and repair_attempts < 1:
                        return VerificationResult(
                            passed=False,
                            requires_repair=True,
                            repair_prompt=f"Tool '{call.tool_name}' requires parameters: {missing}. You provided: {list(call.arguments.keys())}. Please retry with required arguments.",
                            violation_code="MISSING_REQUIRED_PARAMS",
                            details={"missing": missing, "provided": list(call.arguments.keys())},
                        )
                    return VerificationResult(
                        passed=False,
                        requires_repair=False,
                        violation_code="MISSING_REQUIRED_PARAMS_EXHAUSTED",
                        details={"missing": missing},
                    )

        return VerificationResult(passed=True)

    def verify_tool_output(self, tool_name: str, result: Dict[str, Any]) -> VerificationResult:
        """Verifies tool output validity and detects execution errors."""
        if not self.verification_policy.verify_tool_outputs:
            return VerificationResult(passed=True)

        if result.get("status") == "error":
            return VerificationResult(
                passed=False,
                requires_repair=False,
                violation_code="TOOL_EXECUTION_ERROR",
                details={"tool": tool_name, "error": result.get("error", "Unknown tool failure")},
            )

        return VerificationResult(passed=True)

    def verify_final_response(self, response_text: str) -> VerificationResult:
        """Verifies that terminal answer is well-formed and non-empty."""
        if not self.verification_policy.verify_final_state:
            return VerificationResult(passed=True)

        if not response_text or not response_text.strip():
            return VerificationResult(
                passed=False,
                violation_code="EMPTY_FINAL_RESPONSE",
                details={"message": "Agent produced an empty response without tool calls or text."},
            )

        return VerificationResult(passed=True)
