"""Deterministic Condition Evaluation & Branching Engine (18-COMMERCIAL-C)."""

from __future__ import annotations

import re
import logging
from typing import Any, Dict, Optional
from autoforge_power_engines.automation.spec import ConditionRule, ConditionSpec

logger = logging.getLogger("autoforge.power_engines.automation.conditions")


def resolve_variable(ref: str, context: Dict[str, Any]) -> Any:
    """
    Resolves variable references formatted like:
    ${inputs.var_name}
    ${steps.step_id.output.nested.key}
    ${trigger.payload.key}
    """
    if not isinstance(ref, str) or not (ref.startswith("${") and ref.endswith("}")):
        return ref

    path = ref[2:-1].strip().split(".")
    curr: Any = context
    for segment in path:
        if isinstance(curr, dict) and segment in curr:
            curr = curr[segment]
        elif hasattr(curr, segment):
            curr = getattr(curr, segment)
        else:
            return None
    return curr


def resolve_values_recursively(obj: Any, context: Dict[str, Any]) -> Any:
    """Recursively replaces ${...} strings in nested dictionaries, lists, or strings."""
    if isinstance(obj, str):
        # Full string match
        if obj.startswith("${") and obj.endswith("}") and obj.count("${") == 1:
            return resolve_variable(obj, context)
        # Embedded string match
        pattern = re.compile(r"\$\{([^}]+)\}")
        def repl(match: re.Match) -> str:
            resolved = resolve_variable(f"${{{match.group(1)}}}", context)
            return str(resolved) if resolved is not None else ""
        return pattern.sub(repl, obj)
    elif isinstance(obj, dict):
        return {k: resolve_values_recursively(v, context) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [resolve_values_recursively(item, context) for item in obj]
    return obj


class ConditionEvaluator:
    """
    AST-Safe, deterministic condition evaluation engine.
    Compares variables, literals, and boolean expressions without executing arbitrary code.
    """

    @classmethod
    def evaluate_rule(cls, rule: ConditionRule, context: Dict[str, Any]) -> bool:
        """Evaluates a ConditionRule against the current workflow context."""
        # Composite: all_of
        if rule.all_of:
            return all(cls.evaluate_rule(sub_rule, context) for sub_rule in rule.all_of)

        # Composite: any_of
        if rule.any_of:
            return any(cls.evaluate_rule(sub_rule, context) for sub_rule in rule.any_of)

        # Composite: not_rule
        if rule.not_rule:
            return not cls.evaluate_rule(rule.not_rule, context)

        # Atomic comparison
        field_val = resolve_variable(rule.field, context) if rule.field else None
        target_val = resolve_values_recursively(rule.value, context)
        op = rule.operator.lower().strip()

        return cls._compare(field_val, op, target_val)

    @classmethod
    def _compare(cls, left: Any, op: str, right: Any) -> bool:
        try:
            if op in ("eq", "=="):
                return left == right
            elif op in ("neq", "!="):
                return left != right
            elif op in ("gt", ">"):
                return float(left) > float(right)
            elif op in ("gte", ">="):
                return float(left) >= float(right)
            elif op in ("lt", "<"):
                return float(left) < float(right)
            elif op in ("lte", "<="):
                return float(left) <= float(right)
            elif op == "contains":
                if left is None:
                    return False
                return right in left
            elif op in ("in", "is_in"):
                if right is None:
                    return False
                return left in right
            elif op == "matches":
                if left is None:
                    return False
                return bool(re.search(str(right), str(left)))
            elif op == "is_null":
                return left is None
            elif op == "not_null":
                return left is not None
            else:
                logger.warning(f"Unknown condition operator '{op}', defaulting to False.")
                return False
        except Exception as ex:
            logger.warning(f"Error comparing {left} {op} {right}: {ex}")
            return False

    @classmethod
    def resolve_branch(cls, spec: ConditionSpec, context: Dict[str, Any]) -> Optional[str]:
        """
        Evaluates the condition and returns either then_step_id or else_step_id.
        """
        passed = cls.evaluate_rule(spec.rule, context)
        logger.info(f"Condition evaluated to {passed}. Routing to: {spec.then_step_id if passed else spec.else_step_id}")
        return spec.then_step_id if passed else spec.else_step_id
