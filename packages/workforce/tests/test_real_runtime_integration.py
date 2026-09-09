"""
End-to-End Real Runtime Integration Tests (Phase 17).

Verifies the complete runtime flow:
Worker (model-agnostic)
  ↓
Worker Model Profile / Policy
  ↓
Task Model Requirements
  ↓
Effective Model Requirements
  ↓
ModelAllocator / CapacityAwareRouter
  ↓
Phase-7 ModelRouterService
  ↓
Provider Adapter (Ollama / Local-First)
  ↓
Deployment & Node (local-m1)
  ↓
Inference Result & Token Accounting
  ↓
Observability Telemetry
"""

from __future__ import annotations

import pytest
import uuid

from autoforge_ai_infrastructure.adapters import OllamaProviderAdapter
from autoforge_ai_infrastructure.continuity import ExecutionContinuityService, RetryPolicy
from autoforge_ai_infrastructure.execution import ExecutionRequest, ExecutorRegistry, RoutedModelExecutor
from autoforge_ai_infrastructure.metadata import CapabilityIds
from autoforge_ai_infrastructure.registry import InMemoryCapabilityRegistry
from autoforge_ai_infrastructure.router import ModelRouterService
from autoforge_execution.context import ExecutionContext
from autoforge_execution.ai_adapter import AIInfrastructureAdapter
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


@pytest.mark.asyncio
async def test_full_runtime_execution_chain_for_planning_and_coding():
    # 1. Setup CapabilityRegistry and register workforce models
    registry = InMemoryCapabilityRegistry()
    register_workforce_models(registry)

    # 2. Setup Router and Capacity Manager (future M6 is offline)
    capacity_manager = ModelCapacityManager(max_concurrency=2)
    router_service = ModelRouterService(registry)
    capacity_router = CapacityAwareRouter(registry, capacity_manager)

    # 3. Setup ExecutorRegistry and deterministic Ollama adapter double
    def fake_ollama(endpoint, payload, timeout):
        model_name = payload.get("model", "")
        if "generate_implementation" in str(payload) or payload.get("format") == "json":
            return {
                "model": model_name,
                "message": {
                    "role": "assistant",
                    "content": '{"file_edits": [{"path": "main.py", "content": "from fastapi import FastAPI\\napp = FastAPI()"}]}',
                },
                "done": True,
                "prompt_eval_count": 40,
                "eval_count": 60,
                "eval_duration": 3000000000,
            }
        return {
            "model": model_name,
            "message": {
                "role": "assistant",
                "content": "Phase 17 implementation plan:\n1. Analyze requirements\n2. Build FastAPI endpoints\n3. Run tests",
            },
            "done": True,
            "prompt_eval_count": 35,
            "eval_count": 95,
            "eval_duration": 4750000000,  # 4.75s -> 20.0 tokens/sec
        }

    ollama_adapter = OllamaProviderAdapter(
        provider_id="local-m1",
        http_client=fake_ollama,
    )

    executors = ExecutorRegistry()
    executors.bind("local-m1", ollama_adapter)

    continuity = ExecutionContinuityService(
        router=router_service,
        executors=executors,
        retry_policy=RetryPolicy(max_attempts=2),
    )

    routed_executor = RoutedModelExecutor(router=router_service, executors=executors)

    # 4. Worker declares model-agnostic profile
    worker_profile = WorkerModelProfile(
        worker_type="backend_engineer",
        required_capabilities=[CapabilityIds.TEXT_GENERATION],
        coding_required=True,
        privacy_policy="local_only",
        quality_priority=3,
    )

    # 5. Task 1: Planning / Reasoning task
    task_plan_requirements = TaskModelRequirements(
        task_id="task-fastapi-plan",
        required_capabilities=[CapabilityIds.REASONING],
    )

    effective_plan_reqs = resolve_effective_requirements(worker_profile, task_plan_requirements)
    assert CapabilityIds.REASONING in effective_plan_reqs.required_capabilities
    assert effective_plan_reqs.privacy_policy == "local_only"

    # Route planning task -> routes to local reasoning model (ornith-9b on local-m1)
    plan_model, plan_cand = await capacity_router.route_task({
        "required_capabilities": [CapabilityIds.REASONING],
        "privacy_policy": "local_only",
    })
    assert plan_model.provider_id == "local-m1"
    assert plan_model.model_id == "ornith-9b"

    # 6. Task 2: Code generation task
    task_code_requirements = TaskModelRequirements(
        task_id="task-fastapi-code",
        required_capabilities=[CapabilityIds.CODE_GENERATION],
    )

    effective_code_reqs = resolve_effective_requirements(worker_profile, task_code_requirements)
    assert CapabilityIds.CODE_GENERATION in effective_code_reqs.required_capabilities

    # Route coding task -> routes to local code model (qwen2.5-coder-7b on local-m1)
    code_model, code_cand = await capacity_router.route_task({
        "required_capabilities": [CapabilityIds.CODE_GENERATION],
        "privacy_policy": "local_only",
    })
    assert code_model.provider_id == "local-m1"
    assert code_model.model_id == "qwen2.5-coder-7b"

    # 7. AIInfrastructureAdapter executes reasoning task with continuity resilience
    ai_adapter = AIInfrastructureAdapter(
        router=router_service,
        model_executor=continuity,
    )

    context = ExecutionContext(
        task_id="task-fastapi-plan",
        task_name="Build REST API for Task List",
        task_description="Requirements: Python, FastAPI, CRUD operations, validation, tests",
        effective_model_requirements={"required_capabilities": [CapabilityIds.REASONING], "privacy_policy": "local_only"},
    )

    plan = await ai_adapter.generate_plan(context)
    assert "implementation plan" in plan.lower()

    # 8. Verify Telemetry & Token Accounting
    last_res = ai_adapter.last_execution_result
    assert last_res is not None
    assert last_res.model_id == plan_model.model_id
    assert last_res.provider_id == "local-m1"
    assert last_res.output["input_tokens"] > 0
    assert last_res.output["output_tokens"] > 0
    assert last_res.output["tokens_per_second"] is not None

    # 9. Observability Collector ingestion
    metrics = MetricsRegistry()
    logger = StructuredLogger()
    traces = TraceTracker()
    dashboards = DashboardManager()
    collector = EventTelemetryCollector(metrics, logger, traces, dashboards)

    from autoforge_event_platform.models.event import Event, EventCategory, EventType
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
            "tokens": last_res.output["tokens"],
            "total_tokens": last_res.output["total_tokens"],
            "duration_ms": last_res.latency_ms,
            "success": True,
        },
    )

    collector.process_event(event)

    # Check that dashboards recorded the model call with exact token accounting
    assert dashboards.ai_infrastructure.total_model_calls == 1
    assert dashboards.ai_infrastructure.successful_model_calls == 1
    assert dashboards.ai_infrastructure.token_usage["total"] == last_res.output["total_tokens"]
    assert dashboards.model.model_token_usage[last_res.model_id] == last_res.output["total_tokens"]
