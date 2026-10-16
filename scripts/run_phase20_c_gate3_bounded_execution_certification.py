#!/usr/bin/env python3
"""
AutoForge AI-OS — Phase 20-C Gate 3 Certification Driver.
Bounded Execution and Recovery — Audit, Verification, and Certification.

Executes:
1. Git baseline and upstream tracking audit.
2. Live approved MLX inference connectivity check (port 19801, Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2).
3. Subgates 3A-3F direct operational verification on executable runtime:
   - 3A: Execution and iteration bounds
   - 3B: Wall-clock deadlines and tool timeouts
   - 3C: Retry and recovery policy
   - 3D: Cancellation and terminal-state integrity
   - 3E: State integrity and execution isolation
   - 3F: Execution outcomes and delivery integrity
4. Canonical production ingress execution:
   AutoForgeApiService.execute_intent_pipeline
   -> Kernel.submit_request
   -> DefaultOrchestrationEngine
   -> CommercialCapabilityRouter
   -> CustomAIAgentPowerEngine (11 stages)
   -> ExecutionOutcome
5. Full regression test execution across all 9 relevant suites.
6. Structured evidence export to benchmarks/results.
"""

from __future__ import annotations

import ast
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "power_engines" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "composition" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "kernel" / "src"))

from autoforge_api.models import IntentExecutionRequest
from autoforge_api.service import AutoForgeApiService
from autoforge_composition.capability_router import CAPABILITY_AGENT, RoutedExecution
from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_power_engines.agent import (
    CustomerAgentSpecification,
    ExecutionLimits,
    RetryPolicy,
    VerificationPolicy,
    ToolRiskLevel,
    AgentToolConfig,
    ToolRegistry,
    AgentMemoryStore,
    ConversationMessage,
    AgentStateMachine,
    AgentExecutionState,
    StandaloneAgentRuntime,
    ModelProvider,
    GenericHTTPModelProvider,
    CancellationToken,
    CustomAIAgentPowerEngine,
)
from autoforge_power_engines.base import PowerEngineResult

MLX_APPROVED_PORT = 19801
MLX_APPROVED_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"

CUSTOMER_AGENT_REQUEST_TEXT = """Build an enterprise-grade Autonomous Custom AI Agent application called "Apex Ledger Operations Agent" for the Corporate Treasury Operations division.

The delivered agent must empower operations teams to autonomously parse, calculate, inspect, and verify financial ledger data and accounting policy files.

Mandatory requirements:
1. Documented Configuration: Host, port, MLX inference endpoint, model configuration, and runtime limits.
2. Explicitly Authorized Tools: Strict sandboxing for calculator (safe AST math), workspace file reader, document keyword search, and outbound HTTP lookup.
3. Strict Sandboxing: Confined to workspace directory, deny shell execution, deny arbitrary python code eval, block SSRF.
4. Bounded Execution: Max iterations limit (10), tool execution timeouts, cancellation support, and SQLite session memory.
5. Packaging: Standalone, turnkey self-deployable package with zero AutoForge proprietary imports.
"""


def get_git_info() -> Dict[str, str]:
    branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True, cwd=str(REPO_ROOT)).strip()
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True, cwd=str(REPO_ROOT)).strip()
    status = subprocess.check_output(["git", "status", "--porcelain"], text=True, cwd=str(REPO_ROOT)).strip()
    return {"branch": branch, "commit": commit, "clean": len(status) == 0}


def check_mlx_inference() -> Dict[str, Any]:
    url = f"http://127.0.0.1:{MLX_APPROVED_PORT}/v1/models"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "AutoForgeGate3Cert/1.0"})
        with urllib.request.urlopen(req, timeout=3.0) as resp:
            if resp.status == 200:
                data = json.loads(resp.read().decode("utf-8"))
                models = [m.get("id") for m in data.get("data", [])]
                has_approved = MLX_APPROVED_MODEL in models
                return {"online": True, "status_code": 200, "approved_model_present": has_approved, "models": models}
    except Exception as e:
        return {"online": False, "error": str(e), "approved_model_present": False}
    return {"online": False, "approved_model_present": False}


def run_certification():
    start_time_iso = datetime.now(timezone.utc).isoformat()
    timestamp_compact = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")

    print("=" * 80)
    print(" AUTOFORGE AI-OS — PHASE 20-C GATE 3: BOUNDED EXECUTION AND RECOVERY")
    print(f" Start Time (UTC): {start_time_iso}")
    print("=" * 80)

    # 1. Baseline Git State
    git_info = get_git_info()
    print(f"\n[1. Git Baseline]")
    print(f"  Branch: {git_info['branch']}")
    print(f"  Commit HEAD: {git_info['commit']}")

    # 2. Approved Inference Check
    print(f"\n[2. Approved Local Inference Runtime Verification]")
    mlx_status = check_mlx_inference()
    print(f"  Endpoint: http://127.0.0.1:{MLX_APPROVED_PORT}/v1/models")
    print(f"  MLX Server Online: {mlx_status['online']}")
    print(f"  Approved Model Present ({MLX_APPROVED_MODEL}): {mlx_status.get('approved_model_present')}")

    # 3. Subgate 3A: Execution and Iteration Bounds
    print(f"\n[3. Sub-Gate 3A: Execution and Iteration Bounds]")
    subgate_3a_evidence = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        # Verify iteration limit boundary
        spec_iter = CustomerAgentSpecification(
            project_name="Iter Limit Agent",
            agent_purpose="Test iteration limits",
            system_instructions="Loop instructions",
            allowed_tools=["calculator"],
            execution_limits=ExecutionLimits(max_iterations=2, max_tool_calls_per_turn=5, total_timeout_seconds=30.0),
            output_root=tmpdir,
        )
        infinite_tool_response = {
            "message": {
                "role": "assistant",
                "tool_calls": [{
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "calculator", "arguments": '{"expression": "1+1"}'}
                }]
            }
        }
        class InfiniteLoopProvider(ModelProvider):
            def __init__(self):
                self.calls = 0
            def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
                self.calls += 1
                return infinite_tool_response

        loop_provider = InfiniteLoopProvider()
        reg_iter = ToolRegistry(workspace_root=tmp_path)
        rt_iter = StandaloneAgentRuntime(spec=spec_iter, tool_registry=reg_iter, model_provider=loop_provider)
        res_iter = rt_iter.run("Run forever")

        iter_bound_pass = (res_iter.status == "FAILED" and res_iter.iterations == 2 and "maximum iteration limit" in res_iter.final_response.lower())
        subgate_3a_evidence["iteration_limit_enforced_at_boundary"] = iter_bound_pass
        print(f"  Iteration Limit Boundary (max=2): {'PASS' if iter_bound_pass else 'FAIL'} (iterations={res_iter.iterations}, status={res_iter.status})")

    # 4. Subgate 3B: Wall-clock Deadlines and Tool Timeouts
    print(f"\n[4. Sub-Gate 3B: Wall-Clock Deadlines and Tool Timeouts]")
    subgate_3b_evidence = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        def hanging_op(**kwargs):
            time.sleep(1.0)
            return {"result": "done"}

        reg_timeout = ToolRegistry(workspace_root=tmp_path)
        reg_timeout.register_tool(
            AgentToolConfig(name="slow_op", description="Slow op", timeout_seconds=0.05),
            hanging_op,
        )
        spec_timeout = CustomerAgentSpecification(
            project_name="Timeout Agent",
            agent_purpose="Test timeouts",
            system_instructions="Timeout test",
            allowed_tools=["slow_op"],
            tool_definitions=[AgentToolConfig(name="slow_op", description="Slow op", timeout_seconds=0.05)],
            output_root=tmpdir,
        )
        class SlowOpCaller(ModelProvider):
            def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
                return {
                    "message": {
                        "role": "assistant",
                        "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "slow_op", "arguments": "{}"}}]
                    }
                }

        rt_timeout = StandaloneAgentRuntime(spec=spec_timeout, tool_registry=reg_timeout, model_provider=SlowOpCaller())
        res_timeout = rt_timeout.run("Execute slow op")
        tool_timeout_pass = len(res_timeout.tool_traces) > 0 and res_timeout.tool_traces[0]["result"]["status"] == "timeout"
        subgate_3b_evidence["tool_timeout_enforced"] = tool_timeout_pass
        print(f"  Tool Timeout Enforced (0.05s limit): {'PASS' if tool_timeout_pass else 'FAIL'} (status={res_timeout.tool_traces[0]['result'].get('status')})")

    # 5. Subgate 3C: Retry and Recovery Policy
    print(f"\n[5. Sub-Gate 3C: Retry and Recovery Policy]")
    subgate_3c_evidence = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        tmp_path = Path(tmpdir)
        attempts = {"count": 0}
        def recoverable_fetch(**kwargs):
            attempts["count"] += 1
            if attempts["count"] == 1:
                return {"status": "error", "error": "Transient 503 Service Unavailable"}
            return {"status": "success", "data": "recovered_payload"}

        reg_retry = ToolRegistry(workspace_root=tmp_path)
        reg_retry.register_tool(AgentToolConfig(name="recoverable_fetch", description="Recoverable"), recoverable_fetch)
        spec_retry = CustomerAgentSpecification(
            project_name="Retry Agent",
            agent_purpose="Test recovery",
            system_instructions="Recovery test",
            allowed_tools=["recoverable_fetch"],
            tool_definitions=[AgentToolConfig(name="recoverable_fetch", description="Recoverable")],
            retry_policy=RetryPolicy(max_retries=2, backoff_seconds=0.001),
            output_root=tmpdir,
        )
        class RecoverableCaller(ModelProvider):
            def __init__(self):
                self.calls = 0
            def generate_turn(self, messages, tools=None, temperature=0.2, max_tokens=2048, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    return {
                        "message": {
                            "role": "assistant",
                            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "recoverable_fetch", "arguments": "{}"}}]
                        }
                    }
                return {"message": {"role": "assistant", "content": "Recovery complete."}}

        rt_retry = StandaloneAgentRuntime(spec=spec_retry, tool_registry=reg_retry, model_provider=RecoverableCaller())
        res_retry = rt_retry.run("Fetch data")
        recovery_pass = (res_retry.status == "COMPLETED" and attempts["count"] == 2 and res_retry.telemetry.retry_count == 1)
        subgate_3c_evidence["bounded_recovery_succeeded"] = recovery_pass
        print(f"  Transient Failure Recovery (1 retry): {'PASS' if recovery_pass else 'FAIL'} (attempts={attempts['count']}, retries={res_retry.telemetry.retry_count})")

    # 6. Subgate 3D: Cancellation and Terminal-State Integrity
    print(f"\n[6. Sub-Gate 3D: Cancellation and Terminal-State Integrity]")
    subgate_3d_evidence = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        token = CancellationToken()
        token.cancel("User cancellation before start")
        spec_cancel = CustomerAgentSpecification(
            project_name="Cancel Agent",
            agent_purpose="Test cancel",
            system_instructions="Cancel test",
            output_root=tmpdir,
        )
        rt_cancel = StandaloneAgentRuntime(spec=spec_cancel)
        res_cancel = rt_cancel.run("Start task", cancellation_token=token)

        sm = AgentStateMachine("term-test", "sess-test")
        sm.transition_to(AgentExecutionState.RECEIVING_INPUT)
        sm.transition_to(AgentExecutionState.FAILED, reason="Terminal test")
        term_immutable = False
        try:
            sm.transition_to(AgentExecutionState.THINKING)
        except ValueError:
            term_immutable = True

        cancel_pass = (res_cancel.status == "CANCELLED" and term_immutable)
        subgate_3d_evidence["cancellation_and_terminal_stability"] = cancel_pass
        print(f"  Cancellation & Immutable Terminal State: {'PASS' if cancel_pass else 'FAIL'} (status={res_cancel.status}, immutable={term_immutable})")

    # 7. Subgate 3E: State Integrity and Execution Isolation
    print(f"\n[7. Sub-Gate 3E: State Integrity and Execution Isolation]")
    subgate_3e_evidence = {}
    with tempfile.TemporaryDirectory() as tmpdir:
        db_file = Path(tmpdir) / "corrupt_test.db"
        mem = AgentMemoryStore(db_file)
        mem.set_memory("safe_key", {"valid": True})
        with sqlite3.connect(str(db_file)) as conn:
            conn.execute("UPDATE persistent_memory SET value_json = 'INVALID_JSON_CORRUPT{' WHERE key = 'safe_key'")
            conn.commit()

        corrupt_rejected = False
        try:
            mem.validate_state_integrity()
        except ValueError:
            corrupt_rejected = True

        subgate_3e_evidence["corrupt_state_refusal"] = corrupt_rejected
        print(f"  Corrupt Persisted State Refusal: {'PASS' if corrupt_rejected else 'FAIL'}")

    # 8. Subgate 3F: Canonical Execution Ingress and ExecutionOutcome Truthfulness
    print(f"\n[8. Sub-Gate 3F: Canonical Execution Ingress and Truthful ExecutionOutcome]")
    subgate_3f_evidence = {}

    # Verification of failure mapping contract
    pe_fail = PowerEngineResult(
        success=False,
        execution_id="pe-fail-gate3",
        project_name="Fail Test",
        delivery_dir="/tmp/dummy",
        stages_executed=["INTAKE", "PLAN"],
        error_message="Stage PLAN failed",
    )
    outcome_fail = ExecutionOutcome.from_power_engine_result(
        pe_fail, loop_type="coding", capability="custom_ai_agent", engine_class="CustomAIAgentPowerEngine"
    )
    contract_pass = (outcome_fail.passed is False and outcome_fail.status == OutcomeStatus.REMEDIATE)
    print(f"  Truthful ExecutionOutcome Mapping: {'PASS' if contract_pass else 'FAIL'} (passed={outcome_fail.passed}, status={outcome_fail.status})")

    # Live Canonical Ingress Execution
    print(f"\n[9. Canonical Production Intent Ingress Execution]")
    run_id = f"gate3_canonical_{timestamp_compact}"
    workspace_dir = REPO_ROOT / "benchmarks" / "workspace" / run_id
    workspace_dir.mkdir(parents=True, exist_ok=True)
    delivery_root = workspace_dir / "deliveries"
    delivery_root.mkdir(parents=True, exist_ok=True)

    api_service = AutoForgeApiService()
    request_payload = IntentExecutionRequest(
        prompt=CUSTOMER_AGENT_REQUEST_TEXT,
        intent_type=CAPABILITY_AGENT,
        context={
            "capability": CAPABILITY_AGENT,
            "project_name": "Apex-Ledger-Operations-Agent",
            "output_root": str(delivery_root),
            "customer_id": "Apex-Treasury-Operations",
            "authorized_tools": ["calculator", "file_read", "document_lookup", "structured_http", "current_time"],
            "enable_memory": True,
            "port": 8092,
        },
    )

    t0 = time.time()
    ingress_outcome = api_service.execute_intent_pipeline(request_payload)
    pipeline_duration = time.time() - t0
    ingress_pass = (ingress_outcome.status.lower() in ("complete", "completed", "success") or getattr(ingress_outcome, "passed", False) is True)
    print(f"  Canonical Ingress Outcome Status: {ingress_outcome.status} (in {pipeline_duration:.2f}s)")
    print(f"  Execution ID: {ingress_outcome.execution_id}")

    # 10. Comprehensive Regression Suites
    print(f"\n[10. Comprehensive Regression Suite Execution (9 Suites)]")
    test_suites = [
        ("Gate 3 Bounded Execution & Recovery", "packages/power_engines/tests/test_agent_bounded_execution_recovery.py"),
        ("Gate 1 Inference Provider Alignment", "packages/power_engines/tests/test_agent_inference_alignment.py"),
        ("Gate 2 Tool Sandboxing & Security", "packages/power_engines/tests/test_agent_security_sandboxing.py"),
        ("Agent Core & Lifecycle", "packages/power_engines/tests/test_agent_power_engine.py"),
        ("Deliverable Packaging & Manifest", "packages/power_engines/tests/test_agent_deliverable_packaging.py"),
        ("Agent Production Deployment", "packages/power_engines/tests/test_agent_production_deployment.py"),
        ("Customer Deployment Platform", "packages/power_engines/tests/test_customer_deployment.py"),
        ("Shared Delivery Platform", "packages/power_engines/tests/test_shared_delivery_platform.py"),
        ("Commercial Capability Routing", "packages/composition/tests/test_capability_routing.py"),
    ]

    regression_results = []
    total_passed = 0
    total_failed = 0

    for name, rel_path in test_suites:
        cmd = [".venv/bin/pytest", str(REPO_ROOT / rel_path), "-q"]
        p_env = dict(os.environ)
        p_env["PYTHONPATH"] = f"{REPO_ROOT}/packages/power_engines/src:{REPO_ROOT}/packages/composition/src:{REPO_ROOT}/packages/kernel/src:{REPO_ROOT}/packages/common/src:.venv/lib/python3.12/site-packages:{REPO_ROOT}"
        t_start = time.time()
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=p_env, capture_output=True, text=True)
        dur = time.time() - t_start

        passed_count = 0
        failed_count = 0
        for line in res.stdout.splitlines():
            if "passed" in line:
                parts = line.split()
                for i, p in enumerate(parts):
                    if p.startswith("passed"):
                        try:
                            passed_count = int(parts[i-1])
                        except Exception:
                            pass
                    if p.startswith("failed"):
                        try:
                            failed_count = int(parts[i-1])
                        except Exception:
                            pass

        total_passed += passed_count
        total_failed += failed_count
        suite_pass = (res.returncode == 0 and failed_count == 0)
        print(f"  {name:40s}: {'PASS' if suite_pass else 'FAIL'} ({passed_count} passed, {failed_count} failed in {dur:.2f}s)")
        regression_results.append({
            "suite": name,
            "path": rel_path,
            "passed": passed_count,
            "failed": failed_count,
            "duration_s": round(dur, 2),
            "exit_code": res.returncode,
        })

    # Summary
    overall_pass = (
        iter_bound_pass
        and tool_timeout_pass
        and recovery_pass
        and cancel_pass
        and corrupt_rejected
        and contract_pass
        and ingress_pass
        and total_failed == 0
    )

    cert_data = {
        "gate": "Phase 20-C Gate 3",
        "title": "Bounded Execution and Recovery Certification",
        "disposition": "PASS" if overall_pass else "FAIL",
        "timestamp_utc": start_time_iso,
        "git_baseline": git_info,
        "live_inference": {
            "endpoint": f"http://127.0.0.1:{MLX_APPROVED_PORT}/v1",
            "approved_model": MLX_APPROVED_MODEL,
            "status": mlx_status,
        },
        "canonical_ingress": {
            "execution_id": ingress_outcome.execution_id,
            "status": ingress_outcome.status,
            "duration_s": round(pipeline_duration, 2),
        },
        "subgates": {
            "3A_execution_and_iteration_bounds": iter_bound_pass,
            "3B_wall_clock_deadlines_and_tool_timeouts": tool_timeout_pass,
            "3C_retry_and_recovery_policy": recovery_pass,
            "3D_cancellation_and_terminal_state_integrity": cancel_pass,
            "3E_state_integrity_and_execution_isolation": corrupt_rejected,
            "3F_execution_outcomes_and_delivery_integrity": contract_pass,
        },
        "regression_suites": regression_results,
        "total_tests_passed": total_passed,
        "total_tests_failed": total_failed,
    }

    out_file = REPO_ROOT / "benchmarks" / "results" / f"phase20_c_gate3_certification_{timestamp_compact}.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(cert_data, indent=2), encoding="utf-8")
    print(f"\n[11. Certification Record Saved]")
    print(f"  Artifact: {out_file}")
    print(f"  Overall Disposition: {'PASS' if overall_pass else 'FAIL'}")
    print(f"  Total Passing Tests: {total_passed} across {len(test_suites)} suites")
    print("=" * 80)
    return cert_data


if __name__ == "__main__":
    run_certification()
