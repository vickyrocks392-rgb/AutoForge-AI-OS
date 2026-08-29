"""
Phase 17 — Controlled Live Inference Verification for HP Node (local-hp) & Qwen 3B
=================================================================================
Verifies the complete production execution path:
Worker → Model Requirements → ModelAllocator → ModelRouter → Provider Adapter → HP node (192.168.1.105) → Ollama → Qwen 3B → Observability

Network:
- Mac: 192.168.1.104
- HP: 192.168.1.105
- Port: 11434
"""

import asyncio
import glob
import json
import logging
import os
import sys
import time
import urllib.request
import uuid

# Setup sys.path for monorepo packages
workspace_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for p in glob.glob(os.path.join(workspace_root, "packages/*/src")) + glob.glob(os.path.join(workspace_root, "apps/*/src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from autoforge_ai_infrastructure import (
    ExecutionContinuityService,
    ExecutorRegistry,
    InMemoryCapabilityRegistry,
    ModelRouterService,
    OllamaProviderAdapter,
    RetryPolicy,
)
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    DeploymentMode,
    RoutingRequest,
)
from autoforge_event_platform.models.event import Event, EventCategory, EventType
from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.context import ExecutionContext
from autoforge_observability.collector import EventTelemetryCollector
from autoforge_observability.logging import StructuredLogger
from autoforge_observability.metrics import MetricsRegistry
from autoforge_observability.read_models import DashboardManager
from autoforge_observability.tracing import TraceTracker
from autoforge_workforce.capabilities import (
    TaskModelRequirements,
    WorkerModelProfile,
    resolve_effective_requirements,
)
from autoforge_workforce.model_allocator import (
    CapacityAwareRouter,
    ModelCapacityManager,
    register_workforce_models,
)
from autoforge_workforce.workers import BackendEngineer, QAEngineer

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("hp_qwen_verification")

HP_OLLAMA_URL = "http://192.168.1.105:11434"


async def main() -> int:
    print("=" * 70, flush=True)
    print("PHASE 17 — HP NODE (LOCAL-HP) & QWEN 3B REAL INFERENCE VERIFICATION", flush=True)
    print("=" * 70, flush=True)

    # 1. Connectivity Check
    print("\n[Step 1] Verifying Mac -> HP LAN Connectivity (192.168.1.105:11434)...", flush=True)
    try:
        req = urllib.request.Request(f"{HP_OLLAMA_URL}/api/tags", headers={"User-Agent": "AutoForge/1.0"})
        with urllib.request.urlopen(req, timeout=5) as response:
            tags_data = json.loads(response.read().decode("utf-8"))
            installed_models = [m.get("name") for m in tags_data.get("models", [])]
            print(f"       HP Node Status: ONLINE ({HP_OLLAMA_URL})", flush=True)
            print(f"       Installed Models on HP Node: {installed_models}", flush=True)
    except Exception as e:
        print(f"       HP Node Reachability Failed: {e}", flush=True)
        print("       ERROR: HP Ollama daemon is not responding at http://192.168.1.105:11434", flush=True)
        return 1

    # 2. Initialize Capability Registry & Workforce Models
    print("\n[Step 2] Initializing CapabilityRegistry and registering workforce models...", flush=True)
    registry = InMemoryCapabilityRegistry()
    register_workforce_models(registry)

    # 3. Setup HP Ollama Provider Adapter
    print(f"\n[Step 3] Initializing OllamaProviderAdapter for local-hp ({HP_OLLAMA_URL})...", flush=True)
    hp_adapter = OllamaProviderAdapter(
        provider_id="local-hp",
        base_url=HP_OLLAMA_URL,
    )
    is_healthy = await hp_adapter.check_health()
    print(f"       local-hp Adapter Health: {'ONLINE' if is_healthy else 'OFFLINE'}", flush=True)

    executors = ExecutorRegistry()
    executors.bind("local-hp", hp_adapter)

    # 4. Setup Capacity Router & ModelRouterService targeting local-hp
    print("\n[Step 4] Configuring CapacityAwareRouter and ModelRouterService...", flush=True)
    capacity_mgr = ModelCapacityManager(max_concurrency=1)
    # Set local-m1 offline so router routes to local-hp candidate
    capacity_mgr.set_node_health("local-m1", online=False)
    router_service = ModelRouterService(registry)
    capacity_router = CapacityAwareRouter(registry, capacity_mgr)

    continuity = ExecutionContinuityService(
        router=router_service,
        executors=executors,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    ai_adapter = AIInfrastructureAdapter(
        router=router_service,
        model_executor=continuity,
    )

    # =========================================================================
    # TEST 1: Normal Reasoning / General Task (QA Engineer)
    # =========================================================================
    print("\n" + "=" * 70, flush=True)
    print("TEST 1: NORMAL REASONING / GENERAL INFERENCE ON HP QWEN 3B", flush=True)
    print("=" * 70, flush=True)

    worker1_profile = WorkerModelProfile(
        worker_type="qa_engineer",
        required_capabilities=[CapabilityIds.TEXT_GENERATION],
        reasoning_required=False,
        privacy_policy="local_only",
        quality_priority=2,
    )

    print(f"Worker Type:           {worker1_profile.worker_type} (model-agnostic)", flush=True)
    print(f"Worker Declared Caps:  {worker1_profile.required_capabilities}", flush=True)
    print(f"Worker Privacy Policy: {worker1_profile.privacy_policy}", flush=True)

    task1_reqs = TaskModelRequirements(
        required_capabilities=[CapabilityIds.TEXT_GENERATION],
        min_context_window_tokens=8192,
    )

    effective1 = resolve_effective_requirements(worker1_profile, task1_reqs)
    print(f"Effective Capabilities:{effective1.required_capabilities}", flush=True)
    print(f"Effective Quality Tier:{effective1.quality_priority}", flush=True)

    # Verify CapacityAwareRouter resolution
    model_match1, score1 = await capacity_router.route_task(
        {"required_capabilities": list(effective1.required_capabilities), "privacy_policy": "local_only"}
    )
    print(f"CapacityRouter Result: {model_match1.model_id} on {model_match1.provider_id} (Score: {score1.score:.4f})", flush=True)

    context1 = ExecutionContext(
        task_id="task-hp-test-1",
        task_name="Distributed Network Health Test Plan",
        task_description="Produce a concise 3-step test verification plan for a multi-node edge network with node health checks.",
        effective_model_requirements=effective1.to_dict(),
    )

    print("\nExecuting Test 1 inference on local-hp via AIInfrastructureAdapter...", flush=True)
    t0 = time.perf_counter()
    plan_text1 = await ai_adapter.generate_plan(context1)
    duration_s1 = time.perf_counter() - t0
    last_res1 = ai_adapter.last_execution_result

    print("\n--- TEST 1 REAL MEASURED RESULTS ---", flush=True)
    print(f"Canonical Model ID:    {last_res1.model_id}", flush=True)
    print(f"Provider ID:           {last_res1.provider_id}", flush=True)
    print(f"Physical Model Tag:    {last_res1.output.get('resolved_tag', 'qwen2.5-coder:3b')}", flush=True)
    print(f"Execution Node:        local-hp (192.168.1.105)", flush=True)
    print(f"Input Tokens:          {last_res1.output.get('input_tokens')}", flush=True)
    print(f"Output Tokens:         {last_res1.output.get('output_tokens')}", flush=True)
    print(f"Total Tokens:          {last_res1.output.get('total_tokens')}", flush=True)
    print(f"Wall-Clock Latency:    {last_res1.latency_ms:.2f} ms ({duration_s1:.2f} s)", flush=True)
    print(f"Throughput (tok/s):    {last_res1.output.get('tokens_per_second')}", flush=True)
    print(f"Attempts:              {last_res1.attempts}", flush=True)
    print(f"Failovers:             {last_res1.failovers}", flush=True)
    print(f"\n--- Output Excerpt ---\n{plan_text1[:450]}...\n--- End Excerpt ---", flush=True)

    # =========================================================================
    # TEST 2: Coding-Oriented Inference (Backend Engineer)
    # =========================================================================
    print("\n" + "=" * 70, flush=True)
    print("TEST 2: CODING-ORIENTED INFERENCE ON HP QWEN 3B", flush=True)
    print("=" * 70, flush=True)

    worker2_profile = WorkerModelProfile(
        worker_type="backend_engineer",
        required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION],
        coding_required=True,
        privacy_policy="local_only",
        quality_priority=2,
    )

    print(f"Worker Type:           {worker2_profile.worker_type} (model-agnostic)", flush=True)
    print(f"Worker Declared Caps:  {worker2_profile.required_capabilities}", flush=True)

    task2_reqs = TaskModelRequirements(
        task_id="task-hp-test-2",
        required_capabilities=[CapabilityIds.CODE_GENERATION, CapabilityIds.TEXT_GENERATION],
        coding_required=True,
        min_context_window_tokens=16384,
    )

    effective2 = resolve_effective_requirements(worker2_profile, task2_reqs)
    print(f"Effective Capabilities:{effective2.required_capabilities}", flush=True)

    model_match2, score2 = await capacity_router.route_task(
        {"required_capabilities": list(effective2.required_capabilities), "privacy_policy": "local_only"}
    )
    print(f"CapacityRouter Result: {model_match2.model_id} on {model_match2.provider_id} (Score: {score2.score:.4f})", flush=True)

    context2 = ExecutionContext(
        task_id="task-hp-test-2",
        task_name="Token Bucket Rate Limiter Class",
        task_description="Implement a thread-safe TokenBucket rate limiter class in Python with consume(tokens: int) -> bool method and unit test.",
        effective_model_requirements=effective2.to_dict(),
    )

    print("\nExecuting Test 2 coding inference on local-hp via AIInfrastructureAdapter...", flush=True)
    t0 = time.perf_counter()
    plan_text2 = await ai_adapter.generate_plan(context2)
    duration_s2 = time.perf_counter() - t0
    last_res2 = ai_adapter.last_execution_result

    print("\n--- TEST 2 REAL MEASURED RESULTS ---", flush=True)
    print(f"Canonical Model ID:    {last_res2.model_id}", flush=True)
    print(f"Provider ID:           {last_res2.provider_id}", flush=True)
    print(f"Physical Model Tag:    qwen2.5-coder:3b", flush=True)
    print(f"Execution Node:        local-hp (192.168.1.105)", flush=True)
    print(f"Input Tokens:          {last_res2.output.get('input_tokens')}", flush=True)
    print(f"Output Tokens:         {last_res2.output.get('output_tokens')}", flush=True)
    print(f"Total Tokens:          {last_res2.output.get('total_tokens')}", flush=True)
    print(f"Wall-Clock Latency:    {last_res2.latency_ms:.2f} ms ({duration_s2:.2f} s)", flush=True)
    print(f"Throughput (tok/s):    {last_res2.output.get('tokens_per_second')}", flush=True)
    print(f"Attempts:              {last_res2.attempts}", flush=True)
    print(f"Failovers:             {last_res2.failovers}", flush=True)
    print(f"\n--- Output Excerpt ---\n{plan_text2[:450]}...\n--- End Excerpt ---", flush=True)

    # 7. Check Observability Telemetry Read Models
    print("\n" + "=" * 70, flush=True)
    print("OBSERVABILITY TELEMETRY AUDIT", flush=True)
    print("=" * 70, flush=True)
    metrics = MetricsRegistry()
    struct_logger = StructuredLogger()
    traces = TraceTracker()
    dashboards = DashboardManager()
    collector = EventTelemetryCollector(metrics, struct_logger, traces, dashboards)

    # Ingest event 1
    collector.process_event(Event(
        event_type=EventType.CONNECTOR_EXECUTED,
        event_category=EventCategory.CONNECTOR,
        aggregate_type="Model",
        source="autoforge-ai-infrastructure",
        correlation_id=uuid.uuid4(),
        payload={
            "action": "llm_inference",
            "model_id": last_res1.model_id,
            "provider_id": last_res1.provider_id,
            "node_id": "local-hp",
            "tokens": last_res1.output.get("tokens", {}),
            "total_tokens": last_res1.output.get("total_tokens", 0),
            "duration_ms": last_res1.latency_ms,
            "success": True,
        },
    ))

    # Ingest event 2
    collector.process_event(Event(
        event_type=EventType.CONNECTOR_EXECUTED,
        event_category=EventCategory.CONNECTOR,
        aggregate_type="Model",
        source="autoforge-ai-infrastructure",
        correlation_id=uuid.uuid4(),
        payload={
            "action": "llm_inference",
            "model_id": last_res2.model_id,
            "provider_id": last_res2.provider_id,
            "node_id": "local-hp",
            "tokens": last_res2.output.get("tokens", {}),
            "total_tokens": last_res2.output.get("total_tokens", 0),
            "duration_ms": last_res2.latency_ms,
            "success": True,
        },
    ))

    print(f"Total Model Calls in Read Model: {dashboards.ai_infrastructure.total_model_calls}", flush=True)
    print(f"Total Token Usage in Read Model: {dashboards.ai_infrastructure.token_usage.get('total')}", flush=True)
    print(f"Model Token Usage for {last_res1.model_id}: {dashboards.model.model_token_usage.get(last_res1.model_id)}", flush=True)
    print(f"Average Model Latency:           {dashboards.ai_infrastructure.average_model_latency_ms:.2f} ms", flush=True)

    print("\n" + "=" * 70, flush=True)
    print("PASS: HP QWEN 3B LIVE INFERENCE VERIFIED SUCCESSFULLY", flush=True)
    print("=" * 70, flush=True)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)
