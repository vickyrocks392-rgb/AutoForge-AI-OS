"""
Phase 17 Controlled Real Inference Execution Script.

Validates the complete real runtime pipeline:
real AutoForge task
  ↓
real worker policy
  ↓
real requirements
  ↓
real allocation
  ↓
real model routing
  ↓
real provider (Ollama)
  ↓
real node (local-m1)
  ↓
real model (qwen2.5-coder:7b-instruct-q3_K_M)
  ↓
real inference
  ↓
real output
  ↓
real telemetry
"""

import asyncio
import glob
import json
import os
import sys
import time
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
    print("=" * 60)
    print("PHASE 17 — CONTROLLED REAL INFERENCE EXECUTION TEST")
    print("=" * 60)

    # 1. Initialize CapabilityRegistry and workforce models
    print("\n[Step 1] Initializing CapabilityRegistry and registering workforce models...")
    registry = InMemoryCapabilityRegistry()
    register_workforce_models(registry)

    # 2. Capacity Manager & Router Service
    print("[Step 2] Initializing CapacityAwareRouter and ModelRouterService...")
    capacity_manager = ModelCapacityManager(max_concurrency=1)
    router_service = ModelRouterService(registry)
    capacity_router = CapacityAwareRouter(registry, capacity_manager)

    # 3. Setup real live Ollama Provider Adapter
    print("[Step 3] Initializing real live OllamaProviderAdapter against http://127.0.0.1:11434...")
    ollama_adapter = OllamaProviderAdapter(
        provider_id="local-m1",
        base_url="http://127.0.0.1:11434",
    )

    # Check live node health
    is_healthy = await ollama_adapter.check_health()
    installed_models = await ollama_adapter.list_installed_models()
    print(f"       Node Health: {'ONLINE' if is_healthy else 'OFFLINE'}")
    print(f"       Installed Models on node: {installed_models}")

    if not is_healthy:
        print("[ERROR] Local Ollama daemon is not reachable! Please start Ollama.")
        return 1

    executors = ExecutorRegistry()
    executors.bind("local-m1", ollama_adapter)

    continuity = ExecutionContinuityService(
        router=router_service,
        executors=executors,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    # 4. Worker Policy Declaration (Model-Agnostic)
    print("\n[Step 4] Worker declaring model-agnostic profile (BackendEngineer)...")
    worker_profile = WorkerModelProfile(
        worker_type="backend_engineer",
        required_capabilities=[CapabilityIds.TEXT_GENERATION],
        coding_required=True,
        privacy_policy="local_only",
        quality_priority=3,
    )
    print(f"       Worker Type: {worker_profile.worker_type}")
    print(f"       Privacy Policy: {worker_profile.privacy_policy}")
    print(f"       Required Caps: {worker_profile.required_capabilities}")

    # 5. Task Model Requirements
    print("\n[Step 5] Task specifying requirements for FastAPI CRUD REST API...")
    task_requirements = TaskModelRequirements(
        task_id="task-fastapi-crud-plan",
        required_capabilities=[CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION],
        privacy_policy="local_only",
    )

    # 6. Resolve Effective Model Requirements
    print("\n[Step 6] Resolving effective model requirements...")
    effective_reqs = resolve_effective_requirements(worker_profile, task_requirements)
    print(f"       Effective Caps: {sorted(effective_reqs.required_capabilities)}")
    print(f"       Effective Privacy: {effective_reqs.privacy_policy}")
    print(f"       Effective Quality Tier: {effective_reqs.quality_priority}")

    # 7. Model Allocation & Routing
    print("\n[Step 7] Allocating and routing model via CapacityAwareRouter...")
    selected_model, candidate = await capacity_router.route_task(effective_reqs.to_dict())
    print(f"       Selected Model ID: {selected_model.model_id}")
    print(f"       Selected Display Name: {selected_model.display_name}")
    print(f"       Selected Provider ID: {selected_model.provider_id}")
    print(f"       Routing Score: {candidate.score:.4f}")

    # 8. Execute Real Inference through AI Adapter
    print("\n[Step 8] Executing REAL INFERENCE via AIInfrastructureAdapter...")
    ai_adapter = AIInfrastructureAdapter(
        router=router_service,
        model_executor=continuity,
    )

    context = ExecutionContext(
        task_id="task-fastapi-crud-plan",
        task_name="Build REST API for Task List",
        task_description=(
            "Build a small REST API for a task list.\n"
            "Requirements:\n"
            "- Python\n"
            "- FastAPI\n"
            "- CRUD operations\n"
            "- validation\n"
            "- tests\n"
            "- documentation\n\n"
            "First produce the implementation plan."
        ),
        effective_model_requirements=effective_reqs.to_dict(),
    )

    start_exec = time.perf_counter()
    generated_plan = await ai_adapter.generate_plan(context)
    exec_duration_s = time.perf_counter() - start_exec

    # 9. Extract and Inspect Real Telemetry
    last_res = ai_adapter.last_execution_result
    print("\n" + "=" * 60)
    print("REAL INFERENCE RESULT & TELEMETRY")
    print("=" * 60)
    print(f"Worker Used:        backend_engineer (model-agnostic)")
    print(f"Model ID:           {last_res.model_id}")
    print(f"Provider ID:        {last_res.provider_id}")
    print(f"Physical Model Tag: {last_res.output.get('resolved_tag')}")
    print(f"Inference Node:     local-m1 (Apple Silicon M1)")
    print(f"Input Tokens:       {last_res.output.get('input_tokens')}")
    print(f"Output Tokens:      {last_res.output.get('output_tokens')}")
    print(f"Total Tokens:       {last_res.output.get('total_tokens')}")
    print(f"Throughput (tok/s): {last_res.output.get('tokens_per_second')}")
    print(f"Latency:            {last_res.latency_ms:.2f} ms ({exec_duration_s:.2f} s)")
    print(f"Attempts:           {last_res.attempts}")
    print(f"Failovers:          {last_res.failovers}")

    print("\n--- GENERATED IMPLEMENTATION PLAN ---")
    print(generated_plan)
    print("--- END OF PLAN ---\n")

    # 10. Ingest into Phase 14 Observability
    print("[Step 10] Ingesting real telemetry into Observability Platform...")
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

    print(f"       Total Model Calls in Read Model: {dashboards.ai_infrastructure.total_model_calls}")
    print(f"       Total Token Usage in Read Model: {dashboards.ai_infrastructure.token_usage.get('total')}")
    print(f"       Model Token Usage for {last_res.model_id}: {dashboards.model.model_token_usage.get(last_res.model_id)}")
    print(f"       Average Model Latency: {dashboards.ai_infrastructure.average_model_latency_ms:.2f} ms")

    print("\n" + "=" * 60)
    print("REAL INFERENCE TEST PASSED SUCCESSFULLY!")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    exit_code = asyncio.run(main())
    sys.exit(exit_code or 0)
