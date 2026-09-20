"""Phase 18-J.5 — Real OS Subprocess Crash & Recovery Test.

Tests genuine OS process-boundary durability using `os._exit(0)`.

Process A (Independent OS process):
- Opens SQLite database.
- Registers durable workflow (build -> deploy [gated] -> notify).
- Completes 'build' task in durable store.
- Begins execution of 'deploy' task.
- Creates durable ApprovalRequestState in PENDING status in DurableApprovalStore.
- Records WAITING_APPROVAL state.
- Abruptly terminates via genuine OS process boundary: os._exit(0).

Process B (Test process):
- Opens identical SQLite database.
- Runs WorkflowSupervisor.reconcile_startup().
- Runs WorkflowReconstructor.reconstruct().
- Asserts durable approval exists and remains PENDING.
- Asserts waiting task is NOT queued in TaskQueue.
- Resolves approval with APPROVE decision.
- Resumes workflow deterministically.
- Verifies 'deploy' and downstream 'notify' proceed exactly once to completion.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path
import pytest

from autoforge_runtime.approval_store import DurableApprovalStore
from autoforge_runtime.execution_store import DurableExecutionStore, execution_key_for_task
from autoforge_runtime.models import (
    DurableApprovalStatus,
    ExecutionStatus,
    WorkflowStatus,
)
from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_workflows.approval import ApprovalDecision, ApprovalOutcome
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
def test_db_path(tmp_path: Path) -> Path:
    return tmp_path / "hitl_os_crash_test.db"


def test_real_os_subprocess_crash_and_hitl_recovery(test_db_path: Path):
    """Verify that an in-flight HITL approval survives genuine OS process death."""
    workflow_id = uuid.uuid4()
    script = f"""
import os
import sys
import uuid
from pathlib import Path

# Add paths to sys.path
sys.path.insert(0, "packages/runtime/src")
sys.path.insert(0, "packages/workflows/src")
sys.path.insert(0, "packages/shared/src")
sys.path.insert(0, ".")

from autoforge_runtime.persistence import PersistenceLayer
from autoforge_runtime.workflow_store import DurableWorkflowStore
from autoforge_runtime.execution_store import DurableExecutionStore, execution_key_for_task
from autoforge_runtime.approval_store import DurableApprovalStore
from autoforge_workflows.models import (
    WorkflowDefinition,
    TaskDefinition,
    DependencyEdge,
    ApprovalGatePolicy,
)
from autoforge_workflows.engine import WorkflowEngine

db_path = Path({repr(str(test_db_path))})
persistence = PersistenceLayer(db_path)
wf_store = DurableWorkflowStore(persistence, owner_id="host:proc-a")
exec_store = DurableExecutionStore(persistence, owner_id="host:proc-a")
app_store = DurableApprovalStore(persistence, owner_id="host:proc-a")

wid = uuid.UUID({repr(str(workflow_id))})

# Define 3-task pipeline: build -> deploy (gated) -> notify
t_build = TaskDefinition(task_id="build", name="Build")
t_deploy = TaskDefinition(
    task_id="deploy",
    name="Deploy",
    approval_gate=ApprovalGatePolicy(
        gate_id="deploy-gate",
        required_approvers=1,
        description="Gate for deployment",
    ),
)
t_notify = TaskDefinition(task_id="notify", name="Notify")

edges = [
    DependencyEdge(upstream_task_id="build", downstream_task_id="deploy"),
    DependencyEdge(upstream_task_id="deploy", downstream_task_id="notify"),
]

defn = WorkflowDefinition(
    workflow_id=wid,
    name="subprocess_pipeline",
    tasks=[t_build, t_deploy, t_notify],
    dependencies=edges,
)

# Register workflow
wf_store.register_workflow(wid, definition=defn)

# Task 'build' completes
e_build = exec_store.begin_execution(workflow_id=wid, task_id="build")
exec_store.complete_attempt(e_build.execution_id, result={{"build": "success"}})

# Task 'deploy' starts Attempt 1
e_deploy = exec_store.begin_execution(workflow_id=wid, task_id="deploy")

# Task 'deploy' creates durable approval request
req = app_store.create_approval_request(
    gate_id="deploy-gate",
    workflow_id=wid,
    task_id="deploy",
    execution_id=e_deploy.execution_id,
    attempt_id=e_deploy.current_attempt_id,
    approval_type="gate",
    request_payload={{"target_env": "production", "image_tag": "v1.2.3"}},
    requested_by="ci-deployer",
)

# Abruptly kill the process at genuine OS boundary
os._exit(0)
"""

    # Spawn Process A
    env = dict(os.environ)
    env["PYTHONPATH"] = (
        "packages/runtime/src:packages/workflows/src:packages/composition/src:"
        "packages/kernel/src:packages/execution/src:packages/shared/src:."
    )
    result = subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        env=env,
    )
    assert result.returncode == 0, f"Process A crashed unexpectedly: {result.stderr}"

    # ── Process B: Inspect, reconcile, reconstruct, resolve, and resume ───
    persistence = PersistenceLayer(test_db_path)
    wf_store = DurableWorkflowStore(persistence, owner_id="host:proc-b")
    exec_store = DurableExecutionStore(persistence, owner_id="host:proc-b")
    app_store = DurableApprovalStore(persistence, owner_id="host:proc-b")

    # 1. Startup reconciliation
    supervisor = WorkflowSupervisor(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )
    report = supervisor.reconcile_startup()

    # The interrupted execution of 'deploy' is reconciled
    assert len(report.reconciled_executions) >= 1

    # 2. Verify durable approval request survived OS process crash and remains PENDING
    pending_apps = app_store.find_by_workflow(workflow_id)
    assert len(pending_apps) == 1
    durable_app = pending_apps[0]
    assert durable_app.status == DurableApprovalStatus.PENDING
    assert durable_app.task_id == "deploy"
    assert "deploy-gate" in durable_app.approval_key
    assert durable_app.requested_by == "ci-deployer"
    assert durable_app.request_payload["target_env"] == "production"

    # 3. Reconstruct workflow
    reconstructor = WorkflowReconstructor(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )
    handle = reconstructor.reconstruct(workflow_id)
    context = reconstructor.last_context
    assert context is not None

    # Verify task state is WAITING_APPROVAL
    ts_deploy = handle.get_task_state("deploy")
    assert ts_deploy.status == WorkflowTaskStatus.WAITING_APPROVAL
    assert "deploy" in context.waiting_approval_tasks

    # Verify task is NOT queued in TaskQueue (CRITICAL CORRECTNESS INVARIANT)
    assert not handle._queue.contains("deploy")
    assert not handle._queue.contains("notify")

    # Workflow is PAUSED waiting for human decision
    assert handle.status == WorkflowEngineStatus.PAUSED

    # 4. Human arrives and APPROVES the deployment
    engine = WorkflowEngine(
        workflow_store=wf_store,
        execution_store=exec_store,
        approval_store=app_store,
    )
    engine._handles[workflow_id] = handle

    decision = ApprovalDecision(
        outcome=ApprovalOutcome.APPROVED,
        decided_by="ops-director-jane",
        reason="Change window approved",
    )
    engine.submit_approval_decision(workflow_id, "deploy-gate", decision)

    # 5. Verify authoritative approval state in SQLite transitioned to APPROVED
    updated_app = app_store.get_approval_request(durable_app.approval_id)
    assert updated_app.status == DurableApprovalStatus.APPROVED
    assert updated_app.resolved_by == "ops-director-jane"
    assert updated_app.decision == "approved"

    # 6. Deploy task resumed (Attempt 2)
    assert ts_deploy.status == WorkflowTaskStatus.RUNNING

    # Complete deploy task (using J.3 resume_execution)
    e_deploy2, _ = exec_store.resume_execution(
        durable_app.execution_id,
        attempt_number=2,
    )
    exec_store.complete_attempt(e_deploy2.execution_id, result={"deploy": "success"})
    decision_deploy = engine.report_task_success(workflow_id, "deploy")

    # 7. Downstream 'notify' task is now eligible and dispatched
    ts_notify = handle.get_task_state("notify")
    assert ts_notify.status == WorkflowTaskStatus.READY
    assert any(e.task_id == "notify" for e in decision_deploy.dispatch)

    engine.mark_task_running(workflow_id, "notify")
    engine.report_task_success(workflow_id, "notify")

    # Entire workflow finishes cleanly
    assert handle.status == WorkflowEngineStatus.COMPLETED
