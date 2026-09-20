"""Durable execution recorder — the bridge between the Execution Engine and
the runtime's durable execution store (Phase 18-J.2).

The Execution Engine must not maintain a second authoritative execution
state. When a durable recorder is attached, execution identity becomes
durable and canonical:

* one logical execution per ``workflow_id + task_id`` work unit — the
  ``execution_id`` is derived deterministically from that key, so retries
  (attempt 2, 3, ...) extend the *same* logical execution instead of minting
  a new one;
* the durable record is written *before* a task is dispatched and *after*
  its outcome is known, so a crash can never make in-flight work look
  committed;
* a durable boundary (``dispatch-completed``) separates "the work unit ran"
  from "the outcome was committed" — a process that dies between the two
  leaves durable evidence of exactly what was and was not committed.

The recorder is a :class:`Protocol`: the execution package depends only on
this structural contract, while composition wires the concrete
:class:`~autoforge_runtime.execution_store.DurableExecutionStore`, which is
backed by the *same* runtime ``PersistenceLayer`` as every other runtime
entity — one database, one source of truth, no competing store.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

__all__ = ["DurableExecutionRecorder"]


@runtime_checkable
class DurableExecutionRecorder(Protocol):
    """Structural contract the Execution Engine uses for durable writes.

    Implementations must be backed by the runtime ``PersistenceLayer`` (the
    single durable foundation). Implementations MUST raise on any protocol
    violation (unknown execution, terminal execution, stale optimistic
    version) rather than swallowing the error: durable truth must never be
    silently skipped.
    """

    def begin_execution(
        self,
        execution_id: Any | None = None,
        *,
        execution_key: str | None = None,
        workflow_id: Any | None = None,
        task_id: str | None = None,
        correlation_id: Any | None = None,
        attempt_number: int = 1,
        worker_id: str | None = None,
        worker_type: str | None = None,
        max_attempts: int | None = None,
        owner_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        expected_version: int | None = None,
        transition_id: Any | None = None,
    ) -> Any:
        """Durably record that a logical execution (and its attempt) started.

        Returns the durable execution record; its ``status`` tells the caller
        whether this dispatch is the first start (``created``/``running``) or
        a replay of an already-recorded attempt. A terminal status means the
        outcome was already committed and MUST NOT be produced again.
        """
        ...

    def record_checkpoint(
        self,
        execution_id: Any,
        *,
        label: str,
        boundary_state: dict[str, Any] | None = None,
        attempt_id: Any | None = None,
        created_by: str = "system",
        metadata: dict[str, Any] | None = None,
        transition_id: Any | None = None,
    ) -> Any:
        """Commit a durable boundary for the current attempt."""
        ...

    def complete_attempt(
        self,
        execution_id: Any,
        *,
        attempt_id: Any | None = None,
        result: dict[str, Any] | None = None,
        worker_id: str | None = None,
        transition_id: Any | None = None,
    ) -> Any:
        """Commit success of the current attempt *and* the execution atomically."""
        ...

    def fail_attempt(
        self,
        execution_id: Any,
        *,
        attempt_id: Any | None = None,
        error_code: str | None = None,
        error_message: str = "",
        retryable: bool = True,
        source: Any | None = None,
        result: dict[str, Any] | None = None,
        worker_id: str | None = None,
        transition_id: Any | None = None,
    ) -> Any:
        """Commit failure of the current attempt.

        ``retryable=True`` keeps the logical execution ``running`` so the
        workflow engine's next retry continues the *same* execution; the
        workflow-level terminal-failure reconciliation is a later phase
        (18-J.3) responsibility.
        """
        ...

    def resume_execution(
        self,
        execution_id: Any,
        *,
        worker_id: str | None = None,
        worker_type: str | None = None,
        owner_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        transition_id: Any | None = None,
    ) -> Any:
        """Resume an interrupted execution by transitioning to RUNNING and recording attempt N+1."""
        ...
