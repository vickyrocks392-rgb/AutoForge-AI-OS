"""Deterministic Output Verification Engine (18-COMMERCIAL-C)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from autoforge_power_engines.automation.spec import VerificationRule, VerificationRuleType
from autoforge_power_engines.automation.conditions import ConditionEvaluator, ConditionRule

logger = logging.getLogger("autoforge.power_engines.automation.verifier")


class RuleCheckOutcome(BaseModel):
    """Result of evaluating an individual verification rule."""
    rule_name: str
    rule_type: VerificationRuleType
    passed: bool
    details: str
    severity: str = "ERROR"


class VerificationResult(BaseModel):
    """Aggregate result of verifying a step or workflow output."""
    passed: bool
    rule_outcomes: List[RuleCheckOutcome] = Field(default_factory=list)
    failure_reasons: List[str] = Field(default_factory=list)

    def summary(self) -> str:
        if self.passed:
            return f"Verification PASSED ({len(self.rule_outcomes)} checks succeeded)"
        return f"Verification FAILED: {'; '.join(self.failure_reasons)}"


class WorkflowVerifier:
    """
    Evaluates deterministic verification requirements on step outputs.
    Ensures that steps produce compliant results before downstream execution.
    """

    @classmethod
    def verify_step_output(
        cls,
        step_id: str,
        output: Dict[str, Any],
        rules: List[VerificationRule],
        workspace_root: Optional[str] = None,
    ) -> VerificationResult:
        outcomes: List[RuleCheckOutcome] = []
        failure_reasons: List[str] = []

        for rule in rules:
            outcome = cls._evaluate_rule(rule, output, workspace_root)
            outcomes.append(outcome)
            if not outcome.passed:
                msg = f"[{rule.rule_name}] {outcome.details}"
                if outcome.severity == "ERROR":
                    failure_reasons.append(msg)
                else:
                    logger.warning(f"Verification warning for step '{step_id}': {msg}")

        passed = len(failure_reasons) == 0
        return VerificationResult(
            passed=passed,
            rule_outcomes=outcomes,
            failure_reasons=failure_reasons,
        )

    @classmethod
    def _evaluate_rule(
        cls,
        rule: VerificationRule,
        output: Dict[str, Any],
        workspace_root: Optional[str] = None,
    ) -> RuleCheckOutcome:
        r_type = rule.rule_type
        cfg = rule.config

        # 1. Schema Validation
        if r_type == VerificationRuleType.SCHEMA:
            required_keys = cfg.get("required_keys", [])
            missing = [k for k in required_keys if k not in output]
            if missing:
                return RuleCheckOutcome(
                    rule_name=rule.rule_name,
                    rule_type=r_type,
                    passed=False,
                    details=f"Output missing required keys: {missing}",
                    severity=rule.severity,
                )
            return RuleCheckOutcome(
                rule_name=rule.rule_name,
                rule_type=r_type,
                passed=True,
                details=f"All required schema keys present: {required_keys}",
            )

        # 2. HTTP Status Check
        elif r_type == VerificationRuleType.HTTP_STATUS:
            status_code = output.get("status_code")
            expected = cfg.get("expected_code")
            if expected is not None:
                passed = status_code == expected
                details = f"Expected status {expected}, got {status_code}"
            else:
                passed = isinstance(status_code, int) and (200 <= status_code < 300)
                details = f"HTTP status {status_code} in 2xx range"

            return RuleCheckOutcome(
                rule_name=rule.rule_name,
                rule_type=r_type,
                passed=passed,
                details=details,
                severity=rule.severity,
            )

        # 3. Numeric Invariant
        elif r_type == VerificationRuleType.NUMERIC_INVARIANT:
            # Example: total == sum(items)
            field_name = cfg.get("field")
            expected_val = cfg.get("expected_value")
            tolerance = cfg.get("tolerance", 0.001)

            actual_val = output.get(field_name) if field_name else output.get("result")
            try:
                diff = abs(float(actual_val) - float(expected_val))
                passed = diff <= tolerance
                details = f"Field '{field_name}' value {actual_val} vs expected {expected_val} (diff {diff:.4f})"
            except Exception as e:
                passed = False
                details = f"Numeric invariant check failed: {e}"

            return RuleCheckOutcome(
                rule_name=rule.rule_name,
                rule_type=r_type,
                passed=passed,
                details=details,
                severity=rule.severity,
            )

        # 4. Required Field Presence
        elif r_type == VerificationRuleType.REQUIRED_FIELD:
            field_name = cfg.get("field")
            val = output.get(field_name)
            passed = val is not None and val != ""
            details = f"Required field '{field_name}' presence: {passed}"
            return RuleCheckOutcome(
                rule_name=rule.rule_name,
                rule_type=r_type,
                passed=passed,
                details=details,
                severity=rule.severity,
            )

        # 5. File Exists
        elif r_type == VerificationRuleType.FILE_EXISTS:
            rel_path = cfg.get("path") or output.get("path")
            if not rel_path:
                return RuleCheckOutcome(
                    rule_name=rule.rule_name,
                    rule_type=r_type,
                    passed=False,
                    details="No file path provided for existence check",
                    severity=rule.severity,
                )
            root = Path(workspace_root or "./data/workspace").resolve()
            fpath = (root / rel_path).resolve()
            passed = fpath.exists()
            return RuleCheckOutcome(
                rule_name=rule.rule_name,
                rule_type=r_type,
                passed=passed,
                details=f"File '{rel_path}' exists on disk: {passed}",
                severity=rule.severity,
            )

        # 6. Business Rule
        elif r_type == VerificationRuleType.BUSINESS_RULE:
            condition_data = cfg.get("condition", {})
            try:
                rule_model = ConditionRule(**condition_data)
                context = {"output": output}
                passed = ConditionEvaluator.evaluate_rule(rule_model, context)
                details = f"Business rule evaluated to: {passed}"
            except Exception as e:
                passed = False
                details = f"Failed evaluating business rule: {e}"

            return RuleCheckOutcome(
                rule_name=rule.rule_name,
                rule_type=r_type,
                passed=passed,
                details=details,
                severity=rule.severity,
            )

        return RuleCheckOutcome(
            rule_name=rule.rule_name,
            rule_type=r_type,
            passed=True,
            details="Unknown rule type; skipped",
        )
