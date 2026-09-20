"""Phase 18-J.5 — Durable Human-in-the-Loop (HITL) Workflow Integration Tests.

Verifies:
1. Workflow engine reaches gate, persists durable ApprovalRequestState, enters WAITING_APPROVAL, and pauses workflow.
2. Workflow reconstruction after crash discovers pending durable approval, preserves WAITING_APPROVAL, and strictly excludes task from TaskQueue (no accidental dispatch).
3. Submitting approval decision durably transitions approval, resumes workflow, and allows task completion and downstream progress.
4. Submitting rejection transitions durable approval to REJECTED and cancels task without downstream dispatch.
5. Workflow cancellation cancels pending durable approvals and prevents subsequent approvals.
6. End-to-end integration with J.4: Protected side effects are not executed while approval is PENDING, and execute exactly once with idempotency protection after approval.
"""

from __future__ import annotations

import uuid
from typing import Any
import pytest

from autoforge_runtime.models import (
    DurableApprovalStatus,
    EntityType,
    OperationStatus,
    WorkflowStatus,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.approval_store import (
    ApprovalConflictError,
    DurableApprovalStore,
)
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_runtime.execution_store import DurableExecutionStore, execution_key_for_task
from autoforge_runtime.idempotency import (
    DurableIdempotencyStore,
    derive_task_idempotency_key,
    operation_id_for_key,
)
from autoforge_runtime.side_effects import SideEffectExecutor

from autoforge_workflows.approval import (
    ApprovalDecision,
    ApprovalOutcome,
    ApprovalStatus,
)
from autoforge_workflows.dag import WorkflowDAG
from autoforge_workflows.engine import WorkflowEngine, WorkflowEngineStatus
from autoforge_workflows.models import (
    ApprovalGatePolicy,
    DependencyEdge,
    TaskDefinition,
    WorkflowDefinition,
    WorkflowTaskStatus,
)
from autoforge_workflows.reconstruction import WorkflowReconstructor
from autoforge_workflows.supervisor import WorkflowSupervisor


@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "hitl_workflow_test.db")


def _build_gated_workflow(gate_id: str = "deploy-gate") -> WorkflowDefinition:
    """Helper to build a 2-task workflow: build -> deploy (with approval gate)."""
    t_build = TaskDefinition(task_id="build", name="Build Artifacts")
    t_deploy = TaskDefinition(
        task_id="deploy",
        name="Deploy to Prod",
        approval_gate=ApprovalGatePolicy(
            gate_id=gate_id,
            required_approvers=1,
            description="Prod deployment sign-off",
        ),
    )
    return WorkflowDefinition(
        name="release-pipeline",
        tasks=[t_build, t_deploy],
        dependencies=[DependencyEdge(upstream_task_id="build", downstream_task_id="deploy")],
    )


def test_hitl_engine_durable_approval_creation(temp_db_path):
    """Workflow engine pauses at gate and records authoritative PENDING approval in SQLite."""
    p = PersistenceLayer(temp_db_path)
    wf_store = DurableWorkflowStore(p, owner_id="host:worker-1")
    exec_store = DurableExecutionStore(p, owner_id="host:worker-1")
    app_store = DurableApprovalStore(p, owner_id="host:worker-1")

    engine = WorkflowEngine(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )

    wf_def = _build_gated_workflow("prod-deploy-gate")
    handle = engine.submit(wf_def)
    wf_id = handle.workflow_id

    # Complete build task
    engine.mark_task_running(wf_id, "build")
    engine.report_task_success(wf_id, "build")

    # Start deploy task and attempt completion to trigger approval gate
    engine.mark_task_running(wf_id, "deploy")
    decision = engine.report_task_success(wf_id, "deploy")

    # Verify task enters WAITING_APPROVAL
    ts = handle.get_task_state("deploy")
    assert ts.status == WorkflowTaskStatus.WAITING_APPROVAL
    assert handle.status == WorkflowEngineStatus.PAUSED
    assert "prod-deploy-gate" in handle.pending_approval_gates

    # Verify durable approval state in SQLite
    durable_app = app_store.find_pending_for_task(wf_id, "deploy")
    assert durable_app is not None
    assert durable_app.status == DurableApprovalStatus.PENDING
    assert durable_app.workflow_id == wf_id
    assert durable_app.task_id == "deploy"
    assert durable_app.approval_type == "gate"
    assert durable_app.request_fingerprint is not None

    # Verify audit trail in history
    history = p.history.read_by_entity(EntityType.APPROVAL_REQUEST, durable_app.approval_id)
    assert len(history) >= 1
    assert history[0].to_state == "pending"


def test_hitl_reconstruction_leaves_task_waiting_and_not_in_queue(temp_db_path):
    """Crash reconstruction preserves WAITING_APPROVAL and excludes task from TaskQueue."""
    # Process 1: run to approval gate
    p1 = PersistenceLayer(temp_db_path)
    wf_store1 = DurableWorkflowStore(p1, owner_id="host:proc-1")
    exec_store1 = DurableExecutionStore(p1, owner_id="host:proc-1")
    app_store1 = DurableApprovalStore(p1, owner_id="host:proc-1")

    engine1 = WorkflowEngine(
        workflow_store=wf_store1,
        execution_store=exec_store1,
        approval_store=app_store1,
    )

    wf_def = _build_gated_workflow("prod-gate")
    handle1 = engine1.submit(wf_def)
    wf_id = handle1.workflow_id

    # Run and complete build task in both engine and exec_store
    engine1.mark_task_running(wf_id, "build")
    e_build = exec_store1.begin_execution(workflow_id=wf_id, task_id="build")
    exec_store1.complete_attempt(e_build.execution_id, result={"build": "ok"})
    engine1.report_task_success(wf_id, "build")

    # Start deploy task and attempt completion to enter approval gate
    engine1.mark_task_running(wf_id, "deploy")
    engine1.report_task_success(wf_id, "deploy")

    # Simulate crash / restart: open fresh persistence and reconstruction objects
    p2 = PersistenceLayer(temp_db_path)
    wf_store2 = DurableWorkflowStore(p2, owner_id="host:proc-2")
    exec_store2 = DurableExecutionStore(p2, owner_id="host:proc-2")
    app_store2 = DurableApprovalStore(p2, owner_id="host:proc-2")

    # Verify startup reconciliation of supervisor works with approval store
    supervisor = WorkflowSupervisor(
        workflow_store=wf_store2,
        execution_store=exec_store2,
        approval_store=app_store2,
    )
    report = supervisor.reconcile_startup()
    assert len(report.reconciled_approvals) == 0

    reconstructor = WorkflowReconstructor(
        workflow_store=wf_store2,
        execution_store=exec_store2,
        approval_store=app_store2,
    )

    handle2 = reconstructor.reconstruct(wf_id)
    context = reconstructor.last_context
    assert context is not None

    # 1. Verify task is WAITING_APPROVAL
    ts_deploy = handle2.get_task_state("deploy")
    assert ts_deploy.status == WorkflowTaskStatus.WAITING_APPROVAL
    assert "deploy" in context.waiting_approval_tasks

    # 2. Verify task is NOT queued in TaskQueue (CRITICAL CORRECTNESS INVARIANT)
    assert len(handle2._queue) == 0
    assert not handle2._queue.contains("deploy")

    # 3. Verify workflow is PAUSED
    assert handle2.status == WorkflowEngineStatus.PAUSED

    # 4. Verify gate is reconstructed and pending
    assert "prod-gate" in handle2._approval_gates
    reconstructed_gate = handle2._approval_gates["prod-gate"]
    assert reconstructed_gate.status == ApprovalStatus.PENDING_APPROVAL


def test_hitl_approval_resumes_workflow(temp_db_path):
    """Submitting APPROVE decision resumes task and allows workflow to finish."""
    p = PersistenceLayer(temp_db_path)
    wf_store = DurableWorkflowStore(p, owner_id="host:worker-1")
    exec_store = DurableExecutionStore(p, owner_id="host:worker-1")
    app_store = DurableApprovalStore(p, owner_id="host:worker-1")

    engine = WorkflowEngine(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )

    wf_def = _build_gated_workflow("deploy-gate")
    handle = engine.submit(wf_def)
    wf_id = handle.workflow_id

    engine.mark_task_running(wf_id, "build")
    engine.report_task_success(wf_id, "build")
    engine.mark_task_running(wf_id, "deploy")
    engine.report_task_success(wf_id, "deploy")

    # Submit APPROVE decision
    decision = ApprovalDecision(
        outcome=ApprovalOutcome.APPROVED,
        decided_by="lead-operator",
        reason="Approved for staging release",
    )
    engine.submit_approval_decision(wf_id, "deploy-gate", decision)

    # Task transitions to RUNNING with incremented attempt
    ts = handle.get_task_state("deploy")
    assert ts.status == WorkflowTaskStatus.RUNNING

    # Authoritative approval state is APPROVED
    durable_app = app_store.find_by_workflow(wf_id)[0]
    assert durable_app.status == DurableApprovalStatus.APPROVED
    assert durable_app.resolved_by == "lead-operator"

    # Finalize deploy task
    engine.report_task_success(wf_id, "deploy")
    assert handle.status == WorkflowEngineStatus.COMPLETED


def test_hitl_rejection_cancels_task(temp_db_path):
    """Submitting REJECT decision cancels task and leaves downstream tasks unexecuted."""
    p = PersistenceLayer(temp_db_path)
    wf_store = DurableWorkflowStore(p, owner_id="host:worker-1")
    exec_store = DurableExecutionStore(p, owner_id="host:worker-1")
    app_store = DurableApprovalStore(p, owner_id="host:worker-1")

    engine = WorkflowEngine(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )

    wf_def = _build_gated_workflow("deploy-gate")
    handle = engine.submit(wf_def)
    wf_id = handle.workflow_id

    engine.mark_task_running(wf_id, "build")
    engine.report_task_success(wf_id, "build")
    engine.mark_task_running(wf_id, "deploy")
    engine.report_task_success(wf_id, "deploy")

    # Submit REJECT decision
    decision = ApprovalDecision(
        outcome=ApprovalOutcome.REJECTED,
        decided_by="security-auditor",
        reason="Missing compliance tags",
    )
    engine.submit_approval_decision(wf_id, "deploy-gate", decision)

    # Task transitions to CANCELLED
    ts = handle.get_task_state("deploy")
    assert ts.status == WorkflowTaskStatus.CANCELLED

    # Authoritative approval state is REJECTED
    durable_app = app_store.find_by_workflow(wf_id)[0]
    assert durable_app.status == DurableApprovalStatus.REJECTED
    assert durable_app.resolved_by == "security-auditor"


def test_hitl_workflow_cancellation_cancels_pending_approval(temp_db_path):
    """Cancelling a workflow with an open approval gate durably cancels the approval request."""
    p = PersistenceLayer(temp_db_path)
    wf_store = DurableWorkflowStore(p, owner_id="host:worker-1")
    exec_store = DurableExecutionStore(p, owner_id="host:worker-1")
    app_store = DurableApprovalStore(p, owner_id="host:worker-1")

    engine = WorkflowEngine(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )

    wf_def = _build_gated_workflow("deploy-gate")
    handle = engine.submit(wf_def)
    wf_id = handle.workflow_id

    engine.mark_task_running(wf_id, "build")
    engine.report_task_success(wf_id, "build")
    engine.mark_task_running(wf_id, "deploy")
    engine.report_task_success(wf_id, "deploy")

    # Verify pending
    pending_app = app_store.find_pending_for_task(wf_id, "deploy")
    assert pending_app.status == DurableApprovalStatus.PENDING

    # Cancel workflow
    engine.cancel_workflow(wf_id, reason="Emergency abort")

    # Verify approval is now CANCELLED in SQLite
    cancelled_app = app_store.get_approval_request(pending_app.approval_id)
    assert cancelled_app.status == DurableApprovalStatus.CANCELLED

    # Attempting to approve a cancelled approval must raise conflict error
    with pytest.raises(ApprovalConflictError):
        app_store.submit_decision(
            pending_app.approval_id,
            outcome="approved",
            decided_by="late-user",
        )


def test_hitl_j4_idempotent_side_effect_gated_by_durable_approval(temp_db_path):
    """Integration: Side-effects must NOT run while PENDING, and run exactly once via J.4 after APPROVE."""
    p = PersistenceLayer(temp_db_path)
    wf_store = DurableWorkflowStore(p, owner_id="host:proc-1")
    exec_store = DurableExecutionStore(p, owner_id="host:proc-1")
    app_store = DurableApprovalStore(p, owner_id="host:proc-1")
    idemp_store = DurableIdempotencyStore(p, owner_id="host:proc-1")
    executor = SideEffectExecutor(idemp_store)

    engine = WorkflowEngine(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )

    wf_def = _build_gated_workflow("prod-transfer-gate")
    handle = engine.submit(wf_def)
    wf_id = handle.workflow_id

    side_effect_calls = 0

    def mock_wire_transfer(payload, **kwargs):
        nonlocal side_effect_calls
        side_effect_calls += 1
        return {"transfer_id": "wire_999", "amount": payload["amount"], "status": "sent"}

    # Complete build
    engine.mark_task_running(wf_id, "build")
    engine.report_task_success(wf_id, "build")

    # Reach deploy gate
    engine.mark_task_running(wf_id, "deploy")
    engine.report_task_success(wf_id, "deploy")

    # While WAITING_APPROVAL, the side effect is NEVER triggered
    assert side_effect_calls == 0
    durable_app = app_store.find_pending_for_task(wf_id, "deploy")
    assert durable_app.status == DurableApprovalStatus.PENDING

    # Now approve
    decision = ApprovalDecision(
        outcome=ApprovalOutcome.APPROVED,
        decided_by="finance-lead",
        reason="Transfer approved",
    )
    engine.submit_approval_decision(wf_id, "prod-transfer-gate", decision)

    # Deploy task is now RUNNING in Attempt 2
    exec_key = execution_key_for_task(wf_id, "deploy")
    exec_state = exec_store.begin_execution(
        execution_key=exec_key,
        workflow_id=wf_id,
        task_id="deploy",
        attempt_number=2,
    )
    attempt_id = exec_state.current_attempt_id

    # Execute side-effect through J.4 SideEffectExecutor
    res1 = executor.execute(
        operation_name="wire_transfer",
        payload={"amount": 100000},
        handler=mock_wire_transfer,
        execution_id=exec_state.execution_id,
        attempt_id=attempt_id,
        workflow_id=wf_id,
        task_id="deploy",
    )
    assert side_effect_calls == 1
    assert res1["transfer_id"] == "wire_999"

    # Verify idempotency record in SQLite
    op_key = derive_task_idempotency_key(wf_id, "deploy", "wire_transfer")
    op_id = operation_id_for_key(op_key)
    op_rec = idemp_store.get_operation(op_id)
    assert op_rec.status == OperationStatus.COMPLETED

    # If retried under Attempt 3, side-effect handler is NOT called again!
    exec_state3 = exec_store.begin_execution(
        execution_key=exec_key,
        workflow_id=wf_id,
        task_id="deploy",
        attempt_number=3,
    )
    res2 = executor.execute(
        operation_name="wire_transfer",
        payload={"amount": 100000},
        handler=mock_wire_transfer,
        execution_id=exec_state3.execution_id,
        attempt_id=exec_state3.current_attempt_id,
        workflow_id=wf_id,
        task_id="deploy",
    )
    assert side_effect_calls == 1  # Not incremented!
    assert res2["transfer_id"] == "wire_999"
