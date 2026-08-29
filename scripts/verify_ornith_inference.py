"""
Verification script for real live inference using canonical model 'ornith-9b' (Phase 17).

Validates the complete production path:
Worker (planning_engineer / model-agnostic)
  ↓
Worker Model Profile / Policy (reasoning_required=True, privacy_policy="local_only")
  ↓
Task Model Requirements (task_id="task-distributed-cache-design", required_capabilities=[REASONING])
  ↓
Effective Model Requirements (resolved)
  ↓
ModelAllocator / CapacityAwareRouter (evaluates local node capacity and policies)
  ↓
ModelRouterService (routes to ornith-9b on local-m1)
  ↓
Ollama Provider Adapter (interfaces with http://127.0.0.1:11434)
  ↓
Inference Node: local-m1 (Apple Silicon host)
  ↓
Model: ornith-9b (mapped to physical tag maxwell1500/ornith-9b:IQ3_M)
  ↓
Real Inference Execution
  ↓
Real Output & Exact Token Accounting
  ↓
Observability Telemetry Ingestion (DashboardManager / ModelDashboardReadModel)
"""

import asyncio
import json
import os
import sys
import time
import uuid

from autoforge_ai_infrastructure import (
    ExecutionContinuityService,
    ExecutorRegistry,
    InMemoryCapabilityRegistry,
    ModelRouterService,
    OllamaProviderAdapter,
    RetryPolicy,
)
from autoforge_ai_infrastructure.metadata import CapabilityIds
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
from autoforge_event_platform.models.event import Event, EventCategory, EventType


async def main():
    print("=" * 70, flush=True)
    print("PHASE 17 — ORNITH-9B LIVE INFERENCE VERIFICATION", flush=True)
    print("=" * 70, flush=True)

    # 1. Initialize CapabilityRegistry and workforce models
    print("\n[Step 1] Initializing CapabilityRegistry and registering workforce models...", flush=True)
    registry = InMemoryCapabilityRegistry()
    register_workforce_models(registry)

    # 2. Setup Capacity Manager & Router Service
    print("[Step 2] Initializing CapacityAwareRouter and ModelRouterService...", flush=True)
    capacity_manager = ModelCapacityManager(max_concurrency=1)
    router_service = ModelRouterService(registry)
    capacity_router = CapacityAwareRouter(registry, capacity_manager)

    # 3. Setup real live Ollama Provider Adapter
    print("[Step 3] Initializing OllamaProviderAdapter for local-m1...", flush=True)
    ollama_adapter = OllamaProviderAdapter(
        provider_id="local-m1",
        base_url="http://127.0.0.1:11434",
    )

    is_healthy = await ollama_adapter.check_health()
    installed_models = await ollama_adapter.list_installed_models()
    resolved_tag = ollama_adapter.resolve_model_tag("ornith-9b")

    print(f"       Node Status: {'ONLINE' if is_healthy else 'OFFLINE'}", flush=True)
    print(f"       Canonical Model ID: ornith-9b", flush=True)
    print(f"       Resolved Physical Tag: {resolved_tag}", flush=True)
    print(f"       Installed Models on Node: {installed_models}", flush=True)

    if not is_healthy:
        print("[FAIL] Local Ollama daemon is not reachable at http://127.0.0.1:11434", flush=True)
        return 1

    executors = ExecutorRegistry()
    executors.bind("local-m1", ollama_adapter)

    continuity = ExecutionContinuityService(
        router=router_service,
        executors=executors,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    # 4. Worker declares model-agnostic profile (PlanningEngineer)
    print("\n[Step 4] Worker declares model-agnostic profile (PlanningEngineer)...", flush=True)
    worker_profile = WorkerModelProfile(
        worker_type="planning_engineer",
        required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
        reasoning_required=True,
        privacy_policy="local_only",
        quality_priority=3,
    )
    print(f"       Worker Type: {worker_profile.worker_type}", flush=True)
    print(f"       Worker Model Agnostic: True (declares capabilities, NO hardcoded model ID)", flush=True)
    print(f"       Worker Declared Caps: {worker_profile.required_capabilities}", flush=True)
    print(f"       Worker Privacy Policy: {worker_profile.privacy_policy}", flush=True)

    # 5. Task requirements (Reasoning / Strategic Architecture Design)
    print("\n[Step 5] Task specifies reasoning requirements...", flush=True)
    task_requirements = TaskModelRequirements(
        task_id="task-cache-architecture-design",
        required_capabilities=[CapabilityIds.REASONING],
        reasoning_required=True,
        privacy_policy="local_only",
    )

    # 6. Resolve Effective Model Requirements
    print("\n[Step 6] Resolving effective model requirements...", flush=True)
    effective_reqs = resolve_effective_requirements(worker_profile, task_requirements)
    print(f"       Effective Caps: {sorted(effective_reqs.required_capabilities)}", flush=True)
    print(f"       Effective Privacy Policy: {effective_reqs.privacy_policy}", flush=True)
    print(f"       Effective Quality Tier: {effective_reqs.quality_priority}", flush=True)

    # 7. Model Allocation & Routing
    print("\n[Step 7] ModelAllocator & ModelRouter resolving candidate...", flush=True)
    selected_model, candidate = await capacity_router.route_task(effective_reqs.to_dict())
    print(f"       Allocated Model ID: {selected_model.model_id}", flush=True)
    print(f"       Allocated Model Name: {selected_model.display_name}", flush=True)
    print(f"       Allocated Provider ID: {selected_model.provider_id}", flush=True)
    print(f"       Routing Score: {candidate.score:.4f}", flush=True)

    if selected_model.model_id != "ornith-9b":
        print(f"[FAIL] Expected ornith-9b to be selected, but got {selected_model.model_id}", flush=True)
        return 1

    # 8. Execute Real Live Inference through AI Adapter
    print("\n[Step 8] Executing REAL LIVE INFERENCE on ornith-9b...", flush=True)
    ai_adapter = AIInfrastructureAdapter(
        router=router_service,
        model_executor=continuity,
    )

    context = ExecutionContext(
        task_id="task-cache-architecture-design",
        task_name="Distributed In-Memory Cache Invalidation Strategy",
        task_description=(
            "Design a distributed in-memory cache invalidation architecture for a high-concurrency microservice system.\n"
            "Requirements:\n"
            "- Cache-aside with write-through hybrid pattern\n"
            "- Distributed pub/sub invalidation bus (Redis/Kafka)\n"
            "- Consistency guarantees (eventual vs read-your-writes)\n"
            "- Partition failure resilience & thundering herd mitigation\n\n"
            "Produce the concise architectural reasoning and trade-off analysis."
        ),
        effective_model_requirements=effective_reqs.to_dict(),
    )

    start_exec = time.perf_counter()
    generated_plan = await ai_adapter.generate_plan(context)
    exec_duration_s = time.perf_counter() - start_exec

    # 9. Extract and Inspect Real Telemetry
    last_res = ai_adapter.last_execution_result
    print("\n" + "=" * 70, flush=True)
    print("REAL INFERENCE RESULT & TELEMETRY FOR ORNITH-9B", flush=True)
    print("=" * 70, flush=True)
    print(f"Worker Used:             planning_engineer (model-agnostic)", flush=True)
    print(f"Canonical Model ID:      {last_res.model_id}", flush=True)
    print(f"Provider ID:             {last_res.provider_id}", flush=True)
    print(f"Physical Ollama Tag:     {last_res.output.get('resolved_tag')}", flush=True)
    print(f"Inference Node:          local-m1 (Apple Silicon M1)", flush=True)
    print(f"Input Tokens:            {last_res.output.get('input_tokens')}", flush=True)
    print(f"Output Tokens:           {last_res.output.get('output_tokens')}", flush=True)
    print(f"Total Tokens:            {last_res.output.get('total_tokens')}", flush=True)
    print(f"Throughput (tok/s):      {last_res.output.get('tokens_per_second')}", flush=True)
    print(f"Inference Latency:       {last_res.latency_ms:.2f} ms ({exec_duration_s:.2f} s)", flush=True)
    print(f"Execution Attempts:      {last_res.attempts}", flush=True)
    print(f"Failovers:               {last_res.failovers}", flush=True)

    print("\n--- GENERATED REASONING / ARCHITECTURE RESPONSE ---", flush=True)
    print(generated_plan, flush=True)
    print("--- END OF RESPONSE ---\n", flush=True)

    # 10. Observability Ingestion Check
    print("[Step 10] Ingesting real telemetry into Observability Platform...", flush=True)
    metrics = MetricsRegistry()
    logger = StructuredLogger()
    traces = TraceTracker()
    dashboards = DashboardManager()
    collector = EventTelemetryCollector(metrics, logger, traces, dashboards)

    event = Event(
        event_type=EventType.CONNECTOR_EXECUTED,
        event_category=EventCategory.CONNECTOR,
        aggregate_type="Model",
        source="autoforge-ai-infrastructure",
        correlation_id=uuid.uuid4(),
        payload={
            "action": "llm_inference",
            "model_id": last_res.model_id,
            "provider_id": last_res.provider_id,
            "node_id": "local-m1",
            "tokens": last_res.output["tokens"],
            "total_tokens": last_res.output["total_tokens"],
            "duration_ms": last_res.latency_ms,
            "success": True,
        },
    )
    collector.process_event(event)

    total_calls = dashboards.ai_infrastructure.total_model_calls
    total_tokens = dashboards.ai_infrastructure.token_usage.get("total")
    model_tokens = dashboards.model.model_token_usage.get("ornith-9b")

    print(f"       Total Model Calls Recorded: {total_calls}", flush=True)
    print(f"       Total Token Usage Recorded: {total_tokens}", flush=True)
    print(f"       Model Token Usage for ornith-9b: {model_tokens}", flush=True)

    assert total_calls == 1, "Expected 1 model call in dashboard"
    assert model_tokens == last_res.output["total_tokens"], "Token mismatch in read model"

    print("\n" + "=" * 70, flush=True)
    print("PASS: ORNITH-9B LIVE INFERENCE VERIFICATION SUCCESSFUL", flush=True)
    print("=" * 70, flush=True)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)
