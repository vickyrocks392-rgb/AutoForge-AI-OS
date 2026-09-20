"""Bounded Retries & 1-Pass Closed-Loop Repair Handler (18-COMMERCIAL-C)."""

from __future__ import annotations

import json
import logging
import time
from typing import Any, Callable, Dict, List, Optional, Tuple

from autoforge_power_engines.automation.spec import RetryPolicy

logger = logging.getLogger("autoforge.power_engines.automation.repair")


class RepairHandler:
    """
    Coordinates bounded retry loops and 1-pass closed-loop repair for workflow actions and AI steps.
    """

    @classmethod
    def execute_with_retry(
        cls,
        action_fn: Callable[[], Dict[str, Any]],
        retry_policy: RetryPolicy,
        step_id: str,
    ) -> Tuple[bool, Dict[str, Any], int, Optional[str]]:
        """
        Executes action_fn under the configured retry policy.
        Returns: (success, result, attempts_used, last_error)
        """
        attempts = 0
        current_backoff = retry_policy.initial_backoff_ms / 1000.0
        last_error = None

        while attempts < retry_policy.max_attempts:
            attempts += 1
            try:
                result = action_fn()
                return True, result, attempts, None
            except Exception as ex:
                last_error = str(ex)
                ex_type = type(ex).__name__

                # Check if retryable
                is_retryable = any(
                    target.lower() in ex_type.lower() or target.lower() in str(ex).lower()
                    for target in retry_policy.retryable_error_types
                )

                if not is_retryable or attempts >= retry_policy.max_attempts:
                    logger.warning(
                        f"Step '{step_id}' failed on attempt {attempts}/{retry_policy.max_attempts} "
                        f"(non-retryable or max attempts exhausted): {ex}"
                    )
                    break

                logger.info(
                    f"Step '{step_id}' failed on attempt {attempts}/{retry_policy.max_attempts}: {ex}. "
                    f"Retrying in {current_backoff:.3f}s..."
                )
                time.sleep(current_backoff)
                current_backoff = min(
                    current_backoff * retry_policy.backoff_multiplier,
                    retry_policy.max_backoff_ms / 1000.0,
                )

        return False, {}, attempts, last_error

    @classmethod
    def build_repair_prompt(
        cls,
        original_prompt: str,
        malformed_output: str,
        expected_schema: Dict[str, Any],
        error_details: str,
    ) -> str:
        """
        Synthesizes a precise, bounded 1-pass repair prompt for an AI decision step.
        """
        schema_str = json.dumps(expected_schema, indent=2)
        return (
            f"Your previous response violated the required JSON format or schema.\n"
            f"Error details: {error_details}\n\n"
            f"Required Output JSON Schema:\n```json\n{schema_str}\n```\n\n"
            f"Your previous raw response was:\n{malformed_output}\n\n"
            f"Correct the syntax and ensure all required fields are populated.\n"
            f"Output ONLY the valid JSON object inside ```json ... ``` code fences."
        )

    @classmethod
    def parse_and_repair_json(
        cls,
        raw_text: str,
        expected_schema: Dict[str, Any],
        repair_fn: Optional[Callable[[str], str]] = None,
        max_repair_passes: int = 1,
    ) -> Tuple[bool, Dict[str, Any], bool, Optional[str]]:
        """
        Parses JSON from raw model text.
        If malformed or missing schema keys, attempts up to max_repair_passes using repair_fn.
        Returns: (success, parsed_dict, was_repaired, error_message)
        """
        # Initial parse attempt
        parsed, err = cls._try_parse_json(raw_text, expected_schema)
        if parsed is not None:
            return True, parsed, False, None

        if not repair_fn or max_repair_passes <= 0:
            return False, {}, False, err

        # 1-pass repair attempt
        logger.info(f"Triggering 1-pass repair for malformed AI output. Error: {err}")
        repair_prompt = cls.build_repair_prompt(
            original_prompt="",
            malformed_output=raw_text,
            expected_schema=expected_schema,
            error_details=err or "Invalid JSON structure",
        )

        try:
            repaired_text = repair_fn(repair_prompt)
            repaired_parsed, repair_err = cls._try_parse_json(repaired_text, expected_schema)
            if repaired_parsed is not None:
                logger.info("1-pass repair succeeded; valid JSON recovered.")
                return True, repaired_parsed, True, None
            return False, {}, True, f"Repair pass failed: {repair_err}"
        except Exception as e:
            return False, {}, True, f"Exception during repair pass: {e}"

    @classmethod
    def _try_parse_json(
        cls,
        text: str,
        expected_schema: Dict[str, Any],
    ) -> Tuple[Optional[Dict[str, Any]], Optional[str]]:
        """Extracts and validates JSON from markdown fences or text."""
        cleaned = text.strip()
        if "```json" in cleaned:
            parts = cleaned.split("```json")
            if len(parts) > 1:
                cleaned = parts[1].split("```")[0].strip()
        elif "```" in cleaned:
            parts = cleaned.split("```")
            if len(parts) > 1:
                cleaned = parts[1].strip()

        try:
            data = json.loads(cleaned)
            if not isinstance(data, dict):
                return None, f"Expected JSON object, got {type(data).__name__}"

            # Validate required schema keys if specified
            req_keys = expected_schema.get("required", [])
            missing = [k for k in req_keys if k not in data]
            if missing:
                return None, f"Missing required schema fields: {missing}"

            return data, None
        except Exception as ex:
            return None, str(ex)
