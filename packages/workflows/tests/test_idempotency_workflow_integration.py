"""Workflow and Supervisor Integration Tests with Durable Idempotency (Phase 18-J.4).

Matrix J:
- Workflow Resume + Idempotent Side Effects
- Attempt 1 executes external side effect and commits idempotency record, then crashes.
- Supervisor reconciles abandoned workflows, executions, and operations.
- Resumed Attempt 2 reaches the same logical operation, receives cached result without duplicate execution.
- Verifies end-to-end provenance and absence of duplicate side effects.
"""

import uuid
import pytest

from autoforge_runtime.execution_store import (
    DurableExecutionStore,
    execution_key_for_task,
)
from autoforge_runtime.idempotency import (
    DurableIdempotencyStore,
    derive_task_idempotency_key,
    operation_id_for_key,
)
from autoforge_runtime.models import (
    EntityType,
    ExecutionStatus,
    IdempotentOperationState,
    OperationStatus,
    WorkflowState,
    WorkflowStatus,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.side_effects import SideEffectExecutor
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_workflows.supervisor import WorkflowSupervisor


@pytest.fixture
def temp_db_path(tmp_path):
    return str(tmp_path / "wf_idempotency_integration.db")


def test_matrix_j_workflow_resume_prevents_duplicate_side_effect(temp_db_path):
    """Verify that a resumed workflow task does not duplicate side effects executed before crash."""
    # ── Phase 1: Attempt 1 execution before crash ─────────────────────────
    p1 = PersistenceLayer(temp_db_path)
    wf_store1 = DurableWorkflowStore(p1, owner_id="host:worker-proc-1")
    exec_store1 = DurableExecutionStore(p1, owner_id="host:worker-proc-1")
    idemp_store1 = DurableIdempotencyStore(p1, owner_id="host:worker-proc-1")
    executor1 = SideEffectExecutor(idemp_store1)

    wf_id = uuid.uuid4()
    task_id = "dispatch-payment"

    # Register durable workflow in RUNNING status
    wf_store1.register_workflow(
        workflow_id=wf_id,
        status=WorkflowStatus.RUNNING,
    )

    # Start Attempt 1 of execution
    exec_key = execution_key_for_task(wf_id, task_id)
    exec_state = exec_store1.begin_execution(
        execution_key=exec_key,
        workflow_id=wf_id,
        task_id=task_id,
        attempt_number=1,
    )
    assert exec_state.current_attempt_number == 1
    attempt_1_id = exec_state.current_attempt_id

    # Execute side-effect in Attempt 1
    external_calls = 0

    def mock_stripe_charge(req, **kwargs):
        nonlocal external_calls
        external_calls += 1
        return {"charge_id": "ch_stripe_abc123", "amount": req["amount"], "status": "succeeded"}

    charge_payload = {"amount": 5000, "customer": "cust_456"}

    # Attempt 1 performs the charge
    result_attempt_1 = executor1.execute(
        operation_name="charge_customer",
        payload=charge_payload,
        handler=mock_stripe_charge,
        execution_id=exec_state.execution_id,
        attempt_id=attempt_1_id,
        workflow_id=wf_id,
        task_id=task_id,
    )
    assert external_calls == 1
    assert result_attempt_1["charge_id"] == "ch_stripe_abc123"

    # Verify idempotency record is COMPLETED in SQLite
    op_key = derive_task_idempotency_key(wf_id, task_id, "charge_customer")
    op_id = operation_id_for_key(op_key)
    op_record = idemp_store1.get_operation(op_id)
    assert op_record.status == OperationStatus.COMPLETED
    assert op_record.result["charge_id"] == "ch_stripe_abc123"

    # ── Simulate Process 1 Crash ──────────────────────────────────────────
    # The process dies right after the external side effect succeeded,
    # BEFORE the task or workflow execution could commit final completion.
    p1.close()

    # ── Phase 2: Process 2 Starts, Reconciles, and Resumes ────────────────
    p2 = PersistenceLayer(temp_db_path)
    wf_store2 = DurableWorkflowStore(p2, owner_id="host:supervisor-proc-2")
    exec_store2 = DurableExecutionStore(p2, owner_id="host:supervisor-proc-2")
    idemp_store2 = DurableIdempotencyStore(p2, owner_id="host:supervisor-proc-2")

    # Supervisor startup reconciliation
    supervisor = WorkflowSupervisor(
        workflow_store=wf_store2,
        execution_store=exec_store2,
        idempotency_store=idemp_store2,
    )
    report = supervisor.reconcile_startup()

    assert wf_id in report.reconciled_workflows
    assert exec_state.execution_id in report.reconciled_executions
    # Operation was already COMPLETED before crash, so it is NOT interrupted:
    assert op_id not in report.reconciled_operations

    # Verify workflow and execution are now safely INTERRUPTED
    wf_reconciled = wf_store2.get_workflow(wf_id)
    assert wf_reconciled.status == WorkflowStatus.INTERRUPTED
    exec_reconciled = exec_store2.get_execution(exec_state.execution_id)
    assert exec_reconciled.status == ExecutionStatus.INTERRUPTED

    # Controlled resume: claim workflow and resume execution (Attempt 2)
    wf_store2.claim_workflow_for_resume(wf_id)
    resumed_exec, resumed_attempt = exec_store2.resume_execution(exec_state.execution_id)
    assert resumed_exec.status == ExecutionStatus.RUNNING
    assert resumed_exec.attempt_count == 2
    assert resumed_exec.current_attempt_number == 2
    attempt_2_id = resumed_exec.current_attempt_id
    assert attempt_2_id != attempt_1_id

    # ── Attempt 2 reaches the side effect ─────────────────────────────────
    executor2 = SideEffectExecutor(idemp_store2)

    # When Attempt 2 runs the exact same logical operation with the same payload:
    result_attempt_2 = executor2.execute(
        operation_name="charge_customer",
        payload=charge_payload,
        handler=mock_stripe_charge,
        execution_id=resumed_exec.execution_id,
        attempt_id=attempt_2_id,
        workflow_id=wf_id,
        task_id=task_id,
    )

    # CRITICAL INVARIANT: The external handler was NOT called again!
    assert external_calls == 1, "External side effect must NOT be called twice!"
    assert result_attempt_2 == result_attempt_1
    assert result_attempt_2["charge_id"] == "ch_stripe_abc123"

    # Now complete Attempt 2 and workflow
    exec_store2.complete_attempt(resumed_exec.execution_id, result=result_attempt_2)
    wf_store2.complete_workflow(wf_id)

    final_wf = wf_store2.get_workflow(wf_id)
    assert final_wf.status == WorkflowStatus.FINISHED
    final_exec = exec_store2.get_execution(exec_state.execution_id)
    assert final_exec.status == ExecutionStatus.COMPLETED

    p2.close()


def test_supervisor_reconciles_interrupted_running_operations(temp_db_path):
    """Verify that operations left in RUNNING by a dead process are reconciled by supervisor."""
    p1 = PersistenceLayer(temp_db_path)
    wf_store1 = DurableWorkflowStore(p1, owner_id="host:crashed-proc")
    exec_store1 = DurableExecutionStore(p1, owner_id="host:crashed-proc")
    idemp_store1 = DurableIdempotencyStore(p1, owner_id="host:crashed-proc")

    # Claim an operation without completing it
    key = "op:upload:push_artifact"
    payload = {"artifact": "archive.tar.gz"}
    claim = idemp_store1.claim_operation(
        key,
        request_payload=payload,
        supports_provider_idempotency=False,  # Unsafe / ambiguous provider
    )
    assert claim.status == OperationStatus.RUNNING
    op_id = claim.operation_id
    p1.close()

    # Supervisor starts in new process
    p2 = PersistenceLayer(temp_db_path)
    wf_store2 = DurableWorkflowStore(p2, owner_id="host:new-supervisor")
    exec_store2 = DurableExecutionStore(p2, owner_id="host:new-supervisor")
    idemp_store2 = DurableIdempotencyStore(p2, owner_id="host:new-supervisor")

    supervisor = WorkflowSupervisor(
        workflow_store=wf_store2,
        execution_store=exec_store2,
        idempotency_store=idemp_store2,
    )
    report = supervisor.reconcile_startup()

    assert op_id in report.reconciled_operations

    # Verify operation is marked INTERRUPTED and ambiguous
    reconciled_op = idemp_store2.get_operation(op_id)
    assert reconciled_op.status == OperationStatus.INTERRUPTED
    assert reconciled_op.is_ambiguous is True

    p2.close()
