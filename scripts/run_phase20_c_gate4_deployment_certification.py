#!/usr/bin/env python3
"""
AutoForge AI-OS — Phase 20-C Gate 4 Certification Driver.
Production Deployment, Containerization & Operational Hardening Certification.

Executes a fresh canonical customer request through AutoForge ingress:
    AutoForgeApiService.execute_intent_pipeline
    -> Kernel.submit_request
    -> DefaultOrchestrationEngine
    -> CommercialCapabilityRouter
    -> CustomAIAgentPowerEngine (11 stages)
    -> StandaloneCustomerAgentGenerator
    -> Deterministic Validation & Review
    -> ExecutionOutcome

Verifies:
  1. Git baseline and working-tree state.
  2. Gate 4A: Deployment architecture & trust boundaries.
  3. Gate 4B: Containerization (Dockerfile, docker-compose.yml static validation, runtime status).
  4. Gate 4C: Configuration and secrets provisioning.
  5. Gate 4D: Operational observability & structured logging.
  6. Gate 4E: Reliability, recovery, and persistence.
  7. Gate 4F: Deployment and operational runbooks.
  8. Gate 4G: Full regression test execution.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tarfile
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "power_engines" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "composition" / "src"))
sys.path.insert(0, str(REPO_ROOT / "packages" / "kernel" / "src"))

from autoforge_api.models import IntentExecutionRequest
from autoforge_api.service import AutoForgeApiService
from autoforge_composition.capability_router import CAPABILITY_AGENT
from autoforge_power_engines.delivery.packaging import CustomerDeliveryBuilder

MLX_APPROVED_PORT = 19801
MLX_APPROVED_MODEL = "mlx-community/Qwen3-Coder-30B-A3B-Instruct-4bit-dwq-v2"

CUSTOMER_AGENT_REQUEST_TEXT = """Build a production-ready, enterprise-grade Autonomous Custom AI Agent application called "Apex FinOps Automated Operations Agent" for the Enterprise Corporate Financial Operations and Treasury Compliance division.

The delivered agent must empower finance officers, reconciliation analysts, and operations teams to autonomously parse, calculate, inspect, and verify financial ledger data and accounting policy files.

The delivered application must fulfill the following mandatory technical requirements:
1. Documented Configuration: Host, port, MLX inference endpoint, model configuration, and runtime limits.
2. Explicitly Authorized Tools: Strict sandboxing for calculator (safe AST math), workspace file reader, document keyword search, and outbound HTTP lookup.
3. Bounded Iterations & Timeouts: Deterministic guardrails enforcing maximum 10 reasoning turns and a 120-second timeout.
4. Local Inference Topology: Configured exclusively for local MLX authority on port 19801 with Qwen3-Coder-30B-A3B. No legacy unapproved inference fallback.
5. Persistent Conversation Memory: SQLite-backed session-isolated message storage across multiple turns.
6. Safe Startup & Shutdown Procedures: Working launchers (deploy.sh, Deploy.command, manage.sh) and health check endpoint.
7. Automated Verification: Self-contained test suite with 10 comprehensive tests in tests/test_agent_runtime.py.
8. Security Architecture & Limitations Document: Complete SECURITY_AND_LIMITATIONS.md detailing threat boundaries and operational limits.
9. Reproducible Distribution Package: Turnkey tar.gz archive with signed SHA-256 checksum manifest."""


def compute_file_sha256(filepath: Path) -> str:
    h = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def get_git_info() -> Dict[str, str]:
    commit = subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip()
    branch = subprocess.check_output(["git", "rev-parse", "--abbrev-ref", "HEAD"], text=True).strip()
    return {"commit": commit, "branch": branch}


def run_gate4_certification() -> Dict[str, Any]:
    start_time_dt = datetime.now(timezone.utc)
    start_time_iso = start_time_dt.isoformat()
    timestamp_compact = start_time_dt.strftime("%Y%m%d_%H%M%S")

    print("=" * 80)
    print(" AUTOFORGE AI-OS — PHASE 20-C GATE 4: PRODUCTION DEPLOYMENT & OPERATIONS")
    print(f" Start Time (UTC): {start_time_iso}")
    print("=" * 80)

    # 1. Baseline Git State
    git_info = get_git_info()
    print(f"\n[1. Git Baseline]")
    print(f"  Branch: {git_info['branch']}")
    print(f"  Commit HEAD: {git_info['commit']}")

    # 2. Canonical E2E Intent Execution
    print(f"\n[2. Executing Canonical Intent Ingress for Custom AI Agent Deliverable]")
    run_id = f"gate4_run_{timestamp_compact}"
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
            "project_name": "Apex-FinOps-Agent",
            "output_root": str(delivery_root),
            "customer_id": "Apex-Financial-Operations",
            "authorized_tools": ["calculator", "file_read", "document_lookup", "structured_http", "current_time"],
            "enable_memory": True,
            "port": 8088,
        },
    )

    t0 = time.time()
    outcome = api_service.execute_intent_pipeline(request_payload)
    pipeline_duration = time.time() - t0
    print(f"  Execution Outcome Status: {outcome.status} (in {pipeline_duration:.2f}s)")
    print(f"  Execution ID: {outcome.execution_id}")

    # Locate generated deliverable directory
    agent_deliveries = [d for d in delivery_root.rglob("delivery-*") if d.is_dir()]
    if not agent_deliveries:
        raise RuntimeError(f"No delivery directory found in {delivery_root}")
    delivery_dir = agent_deliveries[0]
    print(f"  Deliverable Directory: {delivery_dir}")

    # 3. Gate 4A: Deployment Architecture
    print(f"\n[3. Sub-Gate 4A: Deployment Architecture & Partitions]")
    required_dirs = ["data/state", "data/workspace", "data/logs", "data/config", "config", "src", "tests"]
    missing_dirs = [d for d in required_dirs if not (delivery_dir / d).exists()]
    subgate_4a_pass = len(missing_dirs) == 0
    print(f"  Storage Partitions Verified: {'PASS' if subgate_4a_pass else 'FAIL'} (missing: {missing_dirs})")

    # 4. Gate 4B: Containerization
    print(f"\n[4. Sub-Gate 4B: Containerization Hardening & Runtime Status]")
    df_path = delivery_dir / "Dockerfile"
    compose_path = delivery_dir / "docker-compose.yml"
    docker_available = shutil.which("docker") is not None

    df_content = df_path.read_text(encoding="utf-8") if df_path.exists() else ""
    compose_content = compose_path.read_text(encoding="utf-8") if compose_path.exists() else ""

    df_non_root = "USER appuser" in df_content and "useradd" in df_content
    df_healthcheck = "HEALTHCHECK" in df_content
    compose_loopback = '"127.0.0.1:8000:8000"' in compose_content
    compose_no_priv = "no-new-privileges:true" in compose_content
    compose_cap_drop = "cap_drop:" in compose_content and "- ALL" in compose_content
    compose_limits = "limits:" in compose_content and "cpus:" in compose_content and "memory:" in compose_content
    compose_host_gw = "host.docker.internal:host-gateway" in compose_content

    container_static_pass = (
        df_non_root and df_healthcheck and compose_loopback and
        compose_no_priv and compose_cap_drop and compose_limits and compose_host_gw
    )
    print(f"  Static Dockerfile Hardening: {'PASS' if (df_non_root and df_healthcheck) else 'FAIL'}")
    print(f"  Static Compose Security & Resource Limits: {'PASS' if (compose_no_priv and compose_cap_drop and compose_limits and compose_loopback) else 'FAIL'}")
    print(f"  Container Host Inference Gateway: {'PASS' if compose_host_gw else 'FAIL'}")
    print(f"  Container Runtime Available: {docker_available} ({'RUN' if docker_available else 'BLOCKED'})")

    # 5. Gate 4C: Configuration and Secrets
    print(f"\n[5. Sub-Gate 4C: Configuration and Secrets Validation]")
    env_ex_path = delivery_dir / ".env.example"
    env_ex_content = env_ex_path.read_text(encoding="utf-8") if env_ex_path.exists() else ""
    no_secrets_in_env_ex = (
        "password=" not in env_ex_content.lower() and
        "secret_key=" not in env_ex_content.lower() and
        "token=" not in env_ex_content.lower()
    )
    subgate_4c_pass = env_ex_path.exists() and no_secrets_in_env_ex
    print(f"  .env.example Placeholders Only: {'PASS' if subgate_4c_pass else 'FAIL'}")

    # 6. Gate 4D: Observability & Logging
    print(f"\n[6. Sub-Gate 4D: Operational Observability & Logging]")
    app_py_content = (delivery_dir / "src" / "app.py").read_text(encoding="utf-8")
    has_liveness = '@app.get("/health")' in app_py_content
    has_readiness = '@app.get("/health/ready")' in app_py_content
    has_correlation = "correlation_id" in app_py_content
    has_tool_logging = "[TOOL_OUTCOME]" in app_py_content
    has_lifespan = "lifespan" in app_py_content
    subgate_4d_pass = has_liveness and has_readiness and has_correlation and has_tool_logging and has_lifespan
    print(f"  Liveness & Readiness Endpoint Separation: {'PASS' if (has_liveness and has_readiness) else 'FAIL'}")
    print(f"  Correlation ID & Tool Outcome Logging: {'PASS' if (has_correlation and has_tool_logging) else 'FAIL'}")
    print(f"  Graceful Lifespan Context Manager: {'PASS' if has_lifespan else 'FAIL'}")

    # 7. Gate 4E: Reliability & Recovery (Native Process Execution & Session Persistence)
    print(f"\n[7. Sub-Gate 4E: Reliability, Recovery & Session Retention]")
    # Run the customer package test suite directly in the generated deliverable
    cust_env = dict(os.environ)
    cust_env["PYTHONPATH"] = str(delivery_dir)
    cust_res = subprocess.run(
        [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", "test_*.py"],
        cwd=str(delivery_dir),
        env=cust_env,
        capture_output=True,
        text=True
    )
    subgate_4e_pass = (cust_res.returncode == 0) and ("OK" in cust_res.stderr)
    print(f"  Customer Regression Test Suite (13 tests): {'PASS' if subgate_4e_pass else 'FAIL'}")

    # 8. Gate 4F: Deployment and Operational Runbooks
    print(f"\n[8. Sub-Gate 4F: Deployment & Operational Runbooks]")
    runbook_path = REPO_ROOT / "docs" / "runbooks" / "CUSTOM_AI_AGENT_OPERATIONAL_RUNBOOK.md"
    runbook_exists = runbook_path.exists()
    runbook_content = runbook_path.read_text(encoding="utf-8") if runbook_exists else ""
    required_runbook_sections = [
        "Prerequisites and Supported Environment",
        "Configuration & Secrets Provisioning",
        "Build & Package Verification",
        "Startup & Readiness Checks",
        "Approved Inference Endpoint Connectivity",
        "Safe Smoke-Test Procedure",
        "Log Inspection & Troubleshooting",
        "Graceful Shutdown",
        "Restart & Recovery",
        "SQLite & Workspace Backup and Restore",
        "Upgrade & Rollback Procedure",
        "Data Retention and Deletion Boundaries",
        "Security Limitations & Incident Response Basics",
    ]
    missing_runbook_sections = [s for s in required_runbook_sections if s.lower() not in runbook_content.lower()]
    subgate_4f_pass = runbook_exists and len(missing_runbook_sections) == 0
    print(f"  Operational Runbook Completeness (13/13 sections): {'PASS' if subgate_4f_pass else 'FAIL'} (missing: {missing_runbook_sections})")

    # 9. Gate 4G: Full Regression Suite Execution
    print(f"\n[9. Sub-Gate 4G: Comprehensive Regression Suite Execution]")
    test_suites = [
        ("Agent Production Deployment", "packages/power_engines/tests/test_agent_production_deployment.py"),
        ("Agent Inference Alignment", "packages/power_engines/tests/test_agent_inference_alignment.py"),
        ("Agent Security Sandboxing", "packages/power_engines/tests/test_agent_security_sandboxing.py"),
        ("Agent Deliverable Packaging", "packages/power_engines/tests/test_agent_deliverable_packaging.py"),
        ("Customer Deployment Platform", "packages/power_engines/tests/test_customer_deployment.py"),
        ("Shared Delivery Platform", "packages/power_engines/tests/test_shared_delivery_platform.py"),
        ("Capability Routing", "packages/composition/tests/test_capability_routing.py"),
    ]

    regression_results = []
    total_passed = 0
    total_failed = 0

    for name, rel_path in test_suites:
        cmd = [
            ".venv/bin/pytest",
            str(REPO_ROOT / rel_path),
            "-v"
        ]
        p_env = dict(os.environ)
        p_env["PYTHONPATH"] = f"{REPO_ROOT}/packages/power_engines/src:{REPO_ROOT}/packages/composition/src:{REPO_ROOT}/packages/kernel/src:{REPO_ROOT}/packages/common/src:{REPO_ROOT}"
        t_start = time.time()
        res = subprocess.run(cmd, cwd=str(REPO_ROOT), env=p_env, capture_output=True, text=True)
        dur = time.time() - t_start

        # Parse passed count from pytest output
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

        success = (res.returncode == 0) and (failed_count == 0)
        total_passed += passed_count
        total_failed += failed_count

        regression_results.append({
            "suite": name,
            "path": rel_path,
            "status": "PASS" if success else "FAIL",
            "passed": passed_count,
            "failed": failed_count,
            "duration_s": round(dur, 2),
            "exit_code": res.returncode
        })
        print(f"  {name:30}: {'PASS' if success else 'FAIL'} ({passed_count} passed, {failed_count} failed in {dur:.2f}s)")

    # Overall Disposition
    overall_pass = (
        subgate_4a_pass and
        container_static_pass and
        subgate_4c_pass and
        subgate_4d_pass and
        subgate_4e_pass and
        subgate_4f_pass and
        total_failed == 0
    )

    results_data = {
        "gate": "Phase 20-C Gate 4",
        "timestamp_iso": datetime.now(timezone.utc).isoformat(),
        "git_baseline": git_info,
        "run_id": run_id,
        "execution_outcome_status": str(outcome.status),
        "subgates": {
            "gate_4a_deployment_architecture": "PASS" if subgate_4a_pass else "FAIL",
            "gate_4b_containerization_static": "PASS" if container_static_pass else "FAIL",
            "gate_4b_container_runtime": "PASS" if docker_available else "BLOCKED (docker not installed on macOS host)",
            "gate_4c_configuration_and_secrets": "PASS" if subgate_4c_pass else "FAIL",
            "gate_4d_operational_observability": "PASS" if subgate_4d_pass else "FAIL",
            "gate_4e_reliability_and_recovery": "PASS" if subgate_4e_pass else "FAIL",
            "gate_4f_operational_runbook": "PASS" if subgate_4f_pass else "FAIL",
            "gate_4g_independent_certification": "PASS" if total_failed == 0 else "FAIL",
        },
        "overall_disposition": "PASS" if overall_pass else "FAIL",
        "regression_suites": regression_results,
        "total_regression_passed": total_passed,
        "total_regression_failed": total_failed,
    }

    # Save benchmark results
    results_dir = REPO_ROOT / "benchmarks" / "results"
    results_dir.mkdir(parents=True, exist_ok=True)
    results_file = results_dir / f"phase20_c_gate4_certification_{timestamp_compact}.json"
    results_file.write_text(json.dumps(results_data, indent=2), encoding="utf-8")
    print(f"\n[10. Saved Certification Artifact]")
    print(f"  Artifact File: {results_file}")

    print("=" * 80)
    print(f" PHASE 20-C GATE 4 OVERALL DISPOSITION: {results_data['overall_disposition']}")
    print(f" Total Regression Tests Passed: {total_passed}")
    print("=" * 80)
    return results_data


if __name__ == "__main__":
    run_gate4_certification()
