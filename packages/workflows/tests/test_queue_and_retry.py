"""
Phase 9 — Queue and Retry policy tests.

Covers:
- Task enqueue/dequeue in priority order.
- FIFO within same priority band.
- No duplicate enqueue.
- Readiness-gated dequeue.
- Batch dequeue.
- Queue cancellation.
- Queue snapshot/restore.
- should_retry() deterministic logic.
- compute_backoff() for all strategies.
- assert_retryable().
"""

from __future__ import annotations

import math
import pytest

from autoforge_workflows.errors import QueueError, RetryLimitExceeded
from autoforge_workflows.models import BackoffStrategy, RetryPolicy, WorkflowTaskStatus
from autoforge_workflows.queue import QueueEntry, TaskQueue
from autoforge_workflows.retry import (
    RetryContext,
    assert_retryable,
    compute_backoff,
    should_retry,
)


class TestTaskQueue:
    """Tests for TaskQueue."""

    def test_enqueue_returns_entry(self) -> None:
        q = TaskQueue()
        entry = q.enqueue("t1", "wf-1", "medium")
        assert entry.task_id == "t1"
        assert entry.workflow_id == "wf-1"
        assert entry.priority == "medium"

    def test_len_and_bool(self) -> None:
        q = TaskQueue()
        assert len(q) == 0
        assert not q
        q.enqueue("t1", "wf-1")
        assert len(q) == 1
        assert q

    def test_duplicate_enqueue_raises(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1")
        with pytest.raises(QueueError):
            q.enqueue("t1", "wf-1")

    def test_priority_ordering(self) -> None:
        q = TaskQueue()
        q.enqueue("low-task", "wf-1", "low")
        q.enqueue("critical-task", "wf-1", "critical")
        q.enqueue("medium-task", "wf-1", "medium")
        q.enqueue("high-task", "wf-1", "high")

        statuses = {
            "low-task": WorkflowTaskStatus.READY,
            "critical-task": WorkflowTaskStatus.READY,
            "medium-task": WorkflowTaskStatus.READY,
            "high-task": WorkflowTaskStatus.READY,
        }

        first = q.dequeue(statuses)
        assert first is not None
        assert first.task_id == "critical-task"

        second = q.dequeue(statuses)
        assert second is not None
        assert second.task_id == "high-task"

        third = q.dequeue(statuses)
        assert third is not None
        assert third.task_id == "medium-task"

    def test_fifo_within_same_priority(self) -> None:
        q = TaskQueue()
        q.enqueue("first", "wf-1", "medium")
        q.enqueue("second", "wf-1", "medium")
        q.enqueue("third", "wf-1", "medium")

        statuses = {
            "first": WorkflowTaskStatus.READY,
            "second": WorkflowTaskStatus.READY,
            "third": WorkflowTaskStatus.READY,
        }

        order = []
        while q:
            entry = q.dequeue(statuses)
            if entry:
                order.append(entry.task_id)
        assert order == ["first", "second", "third"]

    def test_dequeue_skips_non_ready_tasks(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1", "high")
        q.enqueue("t2", "wf-1", "medium")

        statuses = {
            "t1": WorkflowTaskStatus.PENDING,  # not READY
            "t2": WorkflowTaskStatus.READY,
        }

        entry = q.dequeue(statuses)
        assert entry is not None
        assert entry.task_id == "t2"

    def test_dequeue_returns_none_when_empty(self) -> None:
        q = TaskQueue()
        result = q.dequeue({})
        assert result is None

    def test_dequeue_returns_none_when_no_ready(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1")
        statuses = {"t1": WorkflowTaskStatus.PENDING}
        result = q.dequeue(statuses)
        assert result is None

    def test_batch_dequeue(self) -> None:
        q = TaskQueue()
        for i in range(5):
            q.enqueue(f"t{i}", "wf-1", "medium")

        statuses = {f"t{i}": WorkflowTaskStatus.READY for i in range(5)}
        batch = q.dequeue_batch(statuses, max_count=3)
        assert len(batch) == 3
        assert len(q) == 2

    def test_cancel(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1")
        q.enqueue("t2", "wf-1")

        removed = q.cancel("t1")
        assert removed is True
        assert len(q) == 1
        assert not q.contains("t1")
        assert q.contains("t2")

    def test_cancel_nonexistent_returns_false(self) -> None:
        q = TaskQueue()
        result = q.cancel("nonexistent")
        assert result is False

    def test_contains(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1")
        assert q.contains("t1") is True
        assert q.contains("t2") is False

    def test_snapshot_and_restore(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1", "high")
        q.enqueue("t2", "wf-1", "medium")

        snap = q.snapshot()
        q2 = TaskQueue.from_snapshot(snap)

        assert len(q2) == 2
        assert q2.contains("t1")
        assert q2.contains("t2")

        statuses = {
            "t1": WorkflowTaskStatus.READY,
            "t2": WorkflowTaskStatus.READY,
        }
        first = q2.dequeue(statuses)
        assert first is not None
        assert first.task_id == "t1"  # high priority

    def test_ready_count(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1")
        q.enqueue("t2", "wf-1")

        statuses = {
            "t1": WorkflowTaskStatus.READY,
            "t2": WorkflowTaskStatus.PENDING,
        }
        assert q.ready_count(statuses) == 1

    def test_peek_does_not_dequeue(self) -> None:
        q = TaskQueue()
        q.enqueue("t1", "wf-1")
        peek = q.peek()
        assert peek is not None
        assert peek.task_id == "t1"
        assert len(q) == 1  # still in queue


class TestShouldRetry:
    """Tests for should_retry() deterministic logic."""

    def test_retry_allowed_within_limit(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        ctx = RetryContext(task_id="t1", attempt_number=1)
        assert should_retry(ctx, policy) is True

    def test_no_retry_when_limit_reached(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        ctx = RetryContext(task_id="t1", attempt_number=3)
        assert should_retry(ctx, policy) is False

    def test_no_retry_when_limit_exceeded(self) -> None:
        policy = RetryPolicy(max_attempts=1)
        ctx = RetryContext(task_id="t1", attempt_number=1)
        assert should_retry(ctx, policy) is False

    def test_non_retryable_error_code(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            non_retryable_error_codes=frozenset({"AUTH_FAILURE"}),
        )
        ctx = RetryContext(task_id="t1", attempt_number=1, error_code="AUTH_FAILURE")
        assert should_retry(ctx, policy) is False

    def test_retryable_allowlist_empty_allows_all(self) -> None:
        policy = RetryPolicy(max_attempts=5, retryable_error_codes=frozenset())
        ctx = RetryContext(task_id="t1", attempt_number=1, error_code="ANY_ERROR")
        assert should_retry(ctx, policy) is True

    def test_retryable_allowlist_non_empty_restricts(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            retryable_error_codes=frozenset({"TRANSIENT_ERROR"}),
        )
        ctx_ok = RetryContext(task_id="t1", attempt_number=1, error_code="TRANSIENT_ERROR")
        ctx_bad = RetryContext(task_id="t1", attempt_number=1, error_code="PERMANENT_ERROR")
        assert should_retry(ctx_ok, policy) is True
        assert should_retry(ctx_bad, policy) is False

    def test_non_retryable_takes_precedence_over_allowlist(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            retryable_error_codes=frozenset({"ERR"}),
            non_retryable_error_codes=frozenset({"ERR"}),
        )
        ctx = RetryContext(task_id="t1", attempt_number=1, error_code="ERR")
        # non_retryable_error_codes checked first → no retry
        assert should_retry(ctx, policy) is False


class TestComputeBackoff:
    """Tests for compute_backoff() pure function."""

    def test_fixed_backoff(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            backoff_strategy=BackoffStrategy.FIXED,
            base_delay_seconds=2.0,
        )
        assert compute_backoff(1, policy) == 2.0
        assert compute_backoff(3, policy) == 2.0
        assert compute_backoff(10, policy) == 2.0

    def test_linear_backoff(self) -> None:
        policy = RetryPolicy(
            max_attempts=5,
            backoff_strategy=BackoffStrategy.LINEAR,
            base_delay_seconds=5.0,
        )
        assert compute_backoff(1, policy) == 5.0
        assert compute_backoff(2, policy) == 10.0
        assert compute_backoff(3, policy) == 15.0

    def test_exponential_backoff(self) -> None:
        policy = RetryPolicy(
            max_attempts=10,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            base_delay_seconds=1.0,
            max_delay_seconds=1000.0,
        )
        assert compute_backoff(1, policy) == 1.0
        assert compute_backoff(2, policy) == 2.0
        assert compute_backoff(3, policy) == 4.0
        assert compute_backoff(4, policy) == 8.0

    def test_max_delay_cap(self) -> None:
        policy = RetryPolicy(
            max_attempts=10,
            backoff_strategy=BackoffStrategy.EXPONENTIAL,
            base_delay_seconds=1.0,
            max_delay_seconds=10.0,
        )
        # 2^20 would be huge — capped at 10.0
        result = compute_backoff(20, policy)
        assert result == 10.0

    def test_zero_base_delay(self) -> None:
        policy = RetryPolicy(
            max_attempts=3,
            base_delay_seconds=0.0,
            backoff_strategy=BackoffStrategy.FIXED,
        )
        assert compute_backoff(1, policy) == 0.0


class TestAssertRetryable:
    """Tests for assert_retryable()."""

    def test_raises_when_limit_reached(self) -> None:
        policy = RetryPolicy(max_attempts=2)
        ctx = RetryContext(task_id="t1", attempt_number=2)
        with pytest.raises(RetryLimitExceeded) as exc_info:
            assert_retryable(ctx, policy)
        assert "t1" in str(exc_info.value)

    def test_does_not_raise_when_retryable(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        ctx = RetryContext(task_id="t1", attempt_number=1)
        # Should not raise.
        assert_retryable(ctx, policy)
