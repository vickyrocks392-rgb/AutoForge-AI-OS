"""
Retry policies — Phase 9.

All retry decisions are DETERMINISTIC — they are made by comparing task
attempt counts, error codes, and policy configuration.  No model inference
is used to decide whether to retry.

Public API
----------
- ``should_retry(context, policy)`` → bool
- ``compute_backoff(attempt, policy)`` → float (seconds)
- ``RetryContext`` — immutable snapshot of retry-relevant facts
- ``BackoffStrategy`` (re-exported from models for convenience)
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from autoforge_workflows.errors import RetryLimitExceeded
from autoforge_workflows.models import BackoffStrategy, RetryPolicy


@dataclass(frozen=True)
class RetryContext:
    """
    Immutable snapshot of the retry-relevant facts for a single task attempt.
    """

    task_id: str
    attempt_number: int
    """Number of attempts so far (1 = first attempt just finished)."""
    error_code: str | None = None
    """Machine-readable error code from the most recent failure."""
    error_message: str | None = None
    is_timeout: bool = False
    """True if the failure was caused by a timeout."""


def should_retry(context: RetryContext, policy: RetryPolicy) -> bool:
    """
    Determine whether a failed task should be retried.

    Decision logic (deterministic — no AI):

    1. If attempt_number >= max_attempts → False (limit exceeded).
    2. If error_code is in non_retryable_error_codes → False.
    3. If retryable_error_codes is non-empty AND error_code is NOT in it → False.
    4. Otherwise → True.

    Args:
        context: Facts about the most recent failure.
        policy: The retry policy to apply.

    Returns:
        True if the task should be retried.
    """
    # 1. Attempt limit.
    if context.attempt_number >= policy.max_attempts:
        return False

    # 2. Explicit non-retryable codes.
    if context.error_code and context.error_code in policy.non_retryable_error_codes:
        return False

    # 3. Allowlist: if defined, only listed codes are retryable.
    if policy.retryable_error_codes:
        if context.error_code not in policy.retryable_error_codes:
            return False

    return True


def compute_backoff(attempt_number: int, policy: RetryPolicy) -> float:
    """
    Compute the delay (in seconds) before the next retry attempt.

    This is a pure function — identical inputs always produce identical outputs.

    Args:
        attempt_number: The attempt that just FAILED (1-indexed).
        policy: The retry policy.

    Returns:
        Delay in seconds, capped at policy.max_delay_seconds.
    """
    base = policy.base_delay_seconds
    strategy = policy.backoff_strategy

    if strategy == BackoffStrategy.FIXED:
        delay = base

    elif strategy == BackoffStrategy.LINEAR:
        # Delay grows linearly: base × attempt_number
        delay = base * attempt_number

    elif strategy == BackoffStrategy.EXPONENTIAL:
        # Delay doubles each retry: base × 2^(attempt_number - 1)
        delay = base * math.pow(2, attempt_number - 1)

    else:
        delay = base

    return min(delay, policy.max_delay_seconds)


def assert_retryable(context: RetryContext, policy: RetryPolicy) -> None:
    """
    Assert that a task is eligible for retry, raising RetryLimitExceeded
    if it is not.

    Args:
        context: Retry context.
        policy: Retry policy.

    Raises:
        RetryLimitExceeded: If the task may not be retried.
    """
    if not should_retry(context, policy):
        raise RetryLimitExceeded(
            f"Task {context.task_id!r} has exhausted retry policy "
            f"(attempt {context.attempt_number}/{policy.max_attempts}, "
            f"error_code={context.error_code!r}).",
            details={
                "task_id": context.task_id,
                "attempt_number": context.attempt_number,
                "max_attempts": policy.max_attempts,
                "error_code": context.error_code,
            },
        )
