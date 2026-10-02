"""
Behavioral & Architectural Test Suite for AutoForge Product Experience (Phase 16).
Verifies all 17 primary behavioral invariants and API boundaries.
"""

import pytest
import threading
import time
import urllib.request
import json
from autoforge_api.models import EpistemicState, WorkspaceMode
from autoforge_api.server import create_server
from autoforge_api.service import AutoForgeApiService
from autoforge_api.redaction import redact_secrets
from autoforge_workforce.registry import WORKER_REGISTRY


# ── Test 1: Application Shell Loads Locally ──────────────────────────────────

def test_app_shell_and_server_load(autoforge_service):
    server = create_server(host="127.0.0.1", port=0, service=autoforge_service)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        url = f"http://127.0.0.1:{port}/index.html"
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            content = resp.read().decode("utf-8")
            assert "AutoForge AI OS" in content
            assert "Command Center" in content
            assert "Legacy Modernization" in content
    finally:
        server.shutdown()
        server.server_close()


# ── Test 2: Command Center Renders Authoritative State ───────────────────────

def test_command_center_authoritative_state(autoforge_service):
    status = autoforge_service.get_system_status()
    assert status.is_healthy is True
    assert status.platform_version == "0.1.0"
    assert status.workspace_mode == WorkspaceMode.GREENFIELD

    autoforge_service.set_workspace_mode(WorkspaceMode.LEGACY_MODERNIZATION)
    updated = autoforge_service.get_system_status()
    assert updated.workspace_mode == WorkspaceMode.LEGACY_MODERNIZATION


# ── Test 3: Project State Sourced From Authoritative Services ────────────────

@pytest.mark.asyncio
async def test_project_state_authoritative(autoforge_service):
    proj = await autoforge_service.create_project(
        name="Test Core Ledger",
        description="High-security ledger modernization",
        template="legacy",
    )
    assert proj.name == "Test Core Ledger"
    assert proj.status == "initializing"
    assert proj.project_id is not None

    projects = await autoforge_service.list_projects()
    matching = [p for p in projects if p.project_id == proj.project_id]
    assert len(matching) == 1
    assert matching[0].name == "Test Core Ledger"


# ── Test 4: Engineering Experience Data Correctly Projected (ADR-004) ────────

def test_engineering_experience_read_model(autoforge_service):
    experience = autoforge_service.get_engineering_experience()
    assert len(experience) >= 2
    for exp in experience:
        assert "trajectory_id" in exp
        assert "task_id" in exp
        assert "correlation_id" in exp
        assert "context_provenance" in exp
        assert "decision" in exp
        assert "tool_actions" in exp
        assert "outcome" in exp
        assert "evaluation_score" in exp


# ── Test 5: Workflow DAG Reflects Authoritative Workflow State ───────────────

def test_workflow_dag_authoritative_state(autoforge_service):
    summary = autoforge_service.get_workflows_summary()
    assert "total_workflows" in summary
    assert "active_workflows" in summary
    assert "queued_tasks" in summary
    assert "active_dags" in summary


# ── Test 6: Workforce Page Exposes All 23 Specialized Workers ────────────────

def test_workforce_exposes_all_23_workers(autoforge_service):
    workers = autoforge_service.list_workforce()
    assert len(workers) == 23, f"Expected exactly 23 specialized workers, got {len(workers)}"

    greenfield_workers = [w for w in workers if w.category == "greenfield"]
    legacy_workers = [w for w in workers if w.category == "legacy"]

    assert len(greenfield_workers) == 14, f"Expected 14 greenfield workers, got {len(greenfield_workers)}"
    assert len(legacy_workers) == 9, f"Expected 9 legacy workers, got {len(legacy_workers)}"

    # Verify each worker has capabilities, model profile, and permission structures
    for w in workers:
        assert w.worker_type in WORKER_REGISTRY.list_workers()
        assert w.display_name != ""
        assert "min_context_window_tokens" in w.model_profile
        assert "privacy_policy" in w.model_profile
        assert isinstance(w.permissions, list)


# ── Test 7 & 8: Legacy Workspace Exposes Epistemic Uncertainty ───────────────

def test_legacy_workspace_epistemic_distinction(autoforge_service):
    legacy = autoforge_service.get_legacy_workspace()
    assert "project_name" in legacy.intake
    assert legacy.analysis_coverage_percent > 90.0

    # Verify all 4 Epistemic States are distinguishable
    states_found = {r.epistemic_state for r in legacy.business_rules} | {c.epistemic_state for c in legacy.architecture_reconstruction}
    assert EpistemicState.FACT in states_found
    assert EpistemicState.INFERENCE in states_found
    assert EpistemicState.HYPOTHESIS in states_found
    assert EpistemicState.UNKNOWN in states_found

    assert legacy.uncertainty_summary["FACT"] > 0
    assert legacy.uncertainty_summary["INFERENCE"] > 0
    assert legacy.uncertainty_summary["HYPOTHESIS"] > 0
    assert legacy.uncertainty_summary["UNKNOWN"] > 0


# ── Test 9: Model/Node Dashboard Reflects Infrastructure State ───────────────

def test_infrastructure_models_and_nodes(autoforge_service):
    infra = autoforge_service.get_infrastructure_summary()
    assert "nodes" in infra
    assert "active_models" in infra
    nodes = {n["node_id"]: n for n in infra["nodes"]}

    assert "local_m1" in nodes
    assert nodes["local_m1"]["is_live_hardware"] is True
    assert nodes["local_m1"]["status"] == "online"

    assert "local_hp" in nodes
    assert nodes["local_hp"]["is_live_hardware"] is True
    assert nodes["local_hp"]["status"] == "online"


# ── Test 10: Observability Dashboard Renders All 13 Read Models ──────────────

def test_observability_13_read_models(autoforge_service):
    dashboards = autoforge_service.get_observability_dashboards()
    required_dashboards = [
        "system",
        "workflow",
        "execution",
        "workforce",
        "ai_infrastructure",
        "capability",
        "provider",
        "model",
        "inference_node",
        "artifact",
        "review",
        "legacy_modernization",
        "hitl_governance",
    ]
    for key in required_dashboards:
        assert key in dashboards, f"Missing read-model dashboard '{key}'"


# ── Test 11: HITL Approvals Displayed Correctly ──────────────────────────────

@pytest.mark.asyncio
async def test_hitl_approvals_displayed_correctly(autoforge_service):
    app = await autoforge_service.request_consequential_approval(
        action_type_str="architecture_finalization",
        resource="blueprint/core_architecture",
        requester="architecture_engineer",
        evidence="Architecture spec complete with 0 review blockers.",
        risk_level="high",
    )
    approvals = await autoforge_service.list_pending_approvals()
    matching = [a for a in approvals if a.approval_id == app.approval_id]
    assert len(matching) == 1
    assert matching[0].action_type == "architecture_finalization"
    assert matching[0].status == "pending"
    assert matching[0].risk_level == "high"


# ── Test 12: UI Cannot Bypass Governance ─────────────────────────────────────

@pytest.mark.asyncio
async def test_ui_cannot_bypass_governance(autoforge_service):
    app = await autoforge_service.request_consequential_approval(
        action_type_str="destructive_cleanup",
        resource="env/legacy_cluster",
        requester="operator_admin_01",
        evidence="Decommissioning verified by audit log.",
        risk_level="critical",
    )

    # Any AI worker ID attempting approval must be blocked
    for worker_id in ["worker_qa_engineer", "worker_security_engineer", "worker_technical_lead"]:
        with pytest.raises(PermissionError, match="Governance Violation"):
            await autoforge_service.submit_approval_decision(
                approval_id=app.approval_id,
                decision="approve",
                actor_id=worker_id,
            )


# ── Test 13: UI Cannot Directly Mutate Authoritative State ───────────────────

@pytest.mark.asyncio
async def test_ui_cannot_directly_mutate_authoritative_state(autoforge_service):
    # Verify that requesting a project creation creates state strictly via Kernel
    proj = await autoforge_service.create_project("Governed Project", "Immutable Kernel Created")
    # Verify state exists in authoritative runtime
    from autoforge_runtime.models import EntityType
    import uuid
    stored = autoforge_service.system.runtime._persistence.read_state(EntityType.PROJECT, uuid.UUID(proj.project_id))
    assert stored is not None
    assert stored.project_id == uuid.UUID(proj.project_id)


# ── Test 14: Secrets Redaction ───────────────────────────────────────────────

def test_secrets_redaction():
    payload = {
        "project": "Secret Core",
        "api_key": "sk-live-super-secret-9999",
        "auth_token": "bearer-secret-token",
        "nested": {
            "password": "db_password_1234",
            "safe_value": "hello_world",
        },
        "items": [
            {"access_key": "aws_secret_key", "name": "S3 Storage"}
        ]
    }
    sanitized = redact_secrets(payload)
    assert sanitized["api_key"] == "[REDACTED]"
    assert sanitized["auth_token"] == "[REDACTED]"
    assert sanitized["nested"]["password"] == "[REDACTED]"
    assert sanitized["nested"]["safe_value"] == "hello_world"
    assert sanitized["items"][0]["access_key"] == "[REDACTED]"
    assert sanitized["items"][0]["name"] == "S3 Storage"


# ── Test 15: Future M6 is Compatibility Spec Only ────────────────────────────

def test_future_m6_hardware_representation(autoforge_service):
    infra = autoforge_service.get_infrastructure_summary()
    nodes = {n["node_id"]: n for n in infra["nodes"]}
    assert "future_m6" in nodes
    m6 = nodes["future_m6"]
    assert m6["is_live_hardware"] is False
    assert m6["status"] == "planned_spec"
    assert "not connected" in m6["notes"].lower() or "offline" in m6["notes"].lower()


# ── Test 16: Self-Improvement Center is Gated and Non-Autonomous ──────────────

def test_self_improvement_center_is_non_autonomous(autoforge_service):
    """Phase 19B-1 Gate 9 (GAP-12): truthful telemetry.

    This test previously asserted ``len(si.learned_items) > 0`` and
    ``len(si.regression_results) > 0``. Those assertions only held because the
    service returned two hardcoded "heuristics" and a hardcoded
    ``{"suite": ..., "passed": 1135, "status": "green"}`` block -- fabricated
    claims about learning that had never happened.

    Asserting that fabricated content is present is itself the defect, so the
    assertions are inverted: the security properties are unchanged and now
    also enforced, while the telemetry must be *derived from real state*
    (zero when nothing has been learned, and never a manufactured pass count).
    """
    si = autoforge_service.get_self_improvement_center()

    # Unchanged security posture.
    assert si.is_autonomous_active is False
    assert si.gated_policy_enforced is True
    assert si.safety_gating_mode == "STRICT_HUMAN_IN_THE_LOOP"

    # Truthful telemetry: no fabricated heuristics or regression results.
    assert si.learned_heuristics_count == 0
    assert si.learned_heuristics == []
    assert si.learned_items == []
    assert si.regression_results == []

    # A regression status must never be manufactured as green/passing when no
    # regression harness ran.
    assert si.last_regression_status == "UNAVAILABLE"
    assert "1119" not in si.last_regression_status
    assert "1135" not in si.last_regression_status


# ── Test 17: Local-First HTTP API E2E Integration ────────────────────────────

def test_local_first_http_api_e2e(autoforge_service):
    server = create_server(host="127.0.0.1", port=0, service=autoforge_service)
    port = server.server_address[1]
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    try:
        # GET /api/system/status
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/system/status")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            data = json.loads(resp.read().decode("utf-8"))
            assert data["is_healthy"] is True

        # GET /api/workforce
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/workforce")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            workers = json.loads(resp.read().decode("utf-8"))
            assert len(workers) == 23

        # GET /api/legacy
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/legacy")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            legacy = json.loads(resp.read().decode("utf-8"))
            assert "uncertainty_summary" in legacy
            assert legacy["uncertainty_summary"]["FACT"] > 0

        # GET /api/observability/dashboards
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/observability/dashboards")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            dashboards = json.loads(resp.read().decode("utf-8"))
            assert "system" in dashboards
            assert "workforce" in dashboards
            assert "ai_infrastructure" in dashboards
            assert len(dashboards) == 13

        # GET /api/activity
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/activity")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            acts = json.loads(resp.read().decode("utf-8"))
            assert len(acts) > 0
            assert "worker_type" in acts[0]
            assert "safe_input" in acts[2] or "safe_output" in acts[3]

        # GET /api/executions/drilldown
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/executions/drilldown")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            dd = json.loads(resp.read().decode("utf-8"))
            assert "router_decision" in dd
            assert "inference_metrics" in dd
            assert dd["inference_metrics"]["gpu_temperature_celsius"] == "UNAVAILABLE"

        # GET /api/models & POST /api/models
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/models")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            models = json.loads(resp.read().decode("utf-8"))
            assert len(models) >= 3

        # GET /api/nodes
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/nodes")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            nodes = json.loads(resp.read().decode("utf-8"))
            assert len(nodes) == 3
            node_ids = {n["node_id"] for n in nodes}
            assert "local_m1" in node_ids
            assert "local_hp" in node_ids
            assert "future_m6" in node_ids

        # GET /api/knowledge/pipeline, telemetry, traces
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/knowledge/pipeline")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            stages = json.loads(resp.read().decode("utf-8"))
            assert len(stages) == 10

        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/knowledge/telemetry")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            telem = json.loads(resp.read().decode("utf-8"))
            assert telem["cache"]["cache_hit_rate"] == "UNAVAILABLE"

        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/knowledge/traces")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            traces = json.loads(resp.read().decode("utf-8"))
            assert len(traces) >= 2

        # POST /api/capabilities/execute
        cap_payload = json.dumps({
            "capability": "planning",
            "prompt": "Design a clean microservices architecture",
        }).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/capabilities/execute", data=cap_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            cap_res = json.loads(resp.read().decode("utf-8"))
            assert cap_res["status"] == "completed"
            assert len(cap_res["activities"]) > 0
            assert len(cap_res["artifacts"]) > 0

        # POST /api/projects/upload
        up_payload = json.dumps({
            "name": "Test Ingestion Project",
            "description": "Integration testing folder upload",
            "files": [
                {"path": "src/app.py", "content": "print('hello')\n"},
                {"path": "docs/arch.md", "content": "# Architecture\n"},
            ],
        }).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/projects/upload", data=up_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 201
            up_res = json.loads(resp.read().decode("utf-8"))
            assert up_res["status"] == "knowledge_ready"
            assert len(up_res["ingestion_lifecycle"]) == 8

        # GET /api/knowledge/documents & GET /api/knowledge/chunks
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/knowledge/documents")
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            kdocs = json.loads(resp.read().decode("utf-8"))
            assert len(kdocs) >= 2

        # POST /api/knowledge/query
        kquery_payload = json.dumps({"query": "architecture", "top_k": 3}).encode("utf-8")
        req = urllib.request.Request(f"http://127.0.0.1:{port}/api/knowledge/query", data=kquery_payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req) as resp:
            assert resp.status == 200
            kq_res = json.loads(resp.read().decode("utf-8"))
            assert kq_res["total_matches"] > 0

    finally:
        server.shutdown()
        server.server_close()


# ── Test 17: Canonical Model Inventory Invariants (Requirement 10) ───────────

def test_canonical_model_inventory_invariants(autoforge_service):
    models = autoforge_service.list_models()
    model_ids = {m.model_id for m in models}

    # Canonical models must be present
    assert "qwen2.5-coder-7b" in model_ids
    assert "ornith-9b" in model_ids
    assert "qwen2.5-coder-3b" in model_ids

    # Future Apple Silicon M6 must NOT be a model in the capability registry
    assert "mac-mini-m6-node" not in model_ids
    assert "qwen3-72b" not in model_ids
    assert "deepseek-v3-moe" not in model_ids

    # Nodes must contain local_m1, local_hp, and future_m6 as planned spec
    nodes = autoforge_service.list_nodes_detail()
    node_map = {n.node_id: n for n in nodes}
    assert node_map["local_m1"].is_live_hardware is True
    assert node_map["local_hp"].is_live_hardware is True
    assert node_map["future_m6"].is_live_hardware is False
    assert node_map["future_m6"].status == "planned_spec"


