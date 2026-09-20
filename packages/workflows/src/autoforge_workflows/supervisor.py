"""Workflow Supervisor — Phase 18-J.3.

Provides supervisor-level startup reconciliation and discovery across the
durable runtime state foundation.

Core rule:
Startup reconciliation is purely reconciliatory. It does NOT automatically
execute or dispatch any workflows or tasks. It transitions abandoned
executions and workflows to INTERRUPTED (recoverable) so that deliberate,
controlled resume operations can be issued.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from autoforge_runtime.execution_store import DurableExecutionStore
from autoforge_runtime.idempotency import DurableIdempotencyStore
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_runtime.approval_store import DurableApprovalStore

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class StartupReconciliationReport:
    """Summary of actions taken during supervisor startup reconciliation."""

    reconciled_executions: list[uuid.UUID] = field(default_factory=list)
    reconciled_workflows: list[uuid.UUID] = field(default_factory=list)
    reconciled_operations: list[uuid.UUID] = field(default_factory=list)
    reconciled_approvals: list[uuid.UUID] = field(default_factory=list)
    recoverable_workflows: list[uuid.UUID] = field(default_factory=list)

    @property
    def total_reconciled(self) -> int:
        return (
            len(self.reconciled_executions)
            + len(self.reconciled_workflows)
            + len(self.reconciled_operations)
            + len(self.reconciled_approvals)
        )


class WorkflowSupervisor:
    """Supervisor responsible for runtime startup reconciliation.

    At startup, discovers active/abandoned executions, workflows, and
    idempotent operations, reconciles them against owner liveness, and leaves
    them in a controlled INTERRUPTED state ready for explicit resume.
    """

    def __init__(
        self,
        *,
        workflow_store: DurableWorkflowStore,
        execution_store: DurableExecutionStore,
        idempotency_store: DurableIdempotencyStore | None = None,
        approval_store: DurableApprovalStore | None = None,
    ) -> None:
        self._workflow_store = workflow_store
        self._execution_store = execution_store
        self._idempotency_store = idempotency_store
        self._approval_store = approval_store

    def reconcile_startup(self) -> StartupReconciliationReport:
        """Perform non-dispatching startup reconciliation.

        1. Reconcile abandoned executions in the durable execution store.
        2. Reconcile abandoned workflows in the durable workflow store.
        3. Reconcile abandoned idempotent operations in the durable idempotency store (Phase 18-J.4).
        4. Discover all recoverable interrupted workflows.

        Guarantees:
        - NEVER dispatches or executes any workflow or task.
        - Idempotent: safe to run multiple times.
        - Preserves all durable facts and increments state version where modified.
        """
        # 1. Reconcile abandoned executions
        reconciled_execs = self._execution_store.reconcile_interrupted_executions()

        # 2. Reconcile abandoned workflows
        reconciled_wfs = self._workflow_store.reconcile_abandoned_workflows()

        # 3. Reconcile abandoned idempotent operations
        reconciled_ops = []
        if self._idempotency_store is not None:
            reconciled_ops = self._idempotency_store.reconcile_interrupted_operations()

        # 4. Reconcile overdue expired approvals (Phase 18-J.5)
        reconciled_apps = []
        if self._approval_store is not None:
            reconciled_apps = self._approval_store.reconcile_expired_approvals()

        # 5. Discover recoverable workflows
        interrupted_wfs = self._workflow_store.list_interrupted_workflows()
        recoverable_ids = [w.workflow_id for w in interrupted_wfs if w.recoverable]

        report = StartupReconciliationReport(
            reconciled_executions=[e.execution_id for e in reconciled_execs],
            reconciled_workflows=[w.workflow_id for w in reconciled_wfs],
            reconciled_operations=[op.operation_id for op in reconciled_ops],
            reconciled_approvals=[app.approval_id for app in reconciled_apps],
            recoverable_workflows=recoverable_ids,
        )

        logger.info(
            "Supervisor startup reconciliation complete: %d executions, %d workflows, %d operations, %d approvals reconciled, %d recoverable workflows found",
            len(report.reconciled_executions),
            len(report.reconciled_workflows),
            len(report.reconciled_operations),
            len(report.reconciled_approvals),
            len(report.recoverable_workflows),
        )

        return report
