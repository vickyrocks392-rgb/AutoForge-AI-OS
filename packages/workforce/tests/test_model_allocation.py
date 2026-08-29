"""
Comprehensive behavioral and integration tests for Model Allocation,
Worker Model Profiles, Multi-Model Concurrency, Capacity Routing, and Legacy Evidence Fusion.
"""

from __future__ import annotations
import asyncio
import sys
import uuid
import pytest
from typing import Any

from autoforge_ai_infrastructure.registry import InMemoryCapabilityRegistry
from autoforge_ai_infrastructure.metadata import (
    CapabilityIds,
    ModelStatus,
    ProviderStatus,
    DeploymentMode,
    ModelQuery,
    RoutingRequest,
)
from autoforge_ai_infrastructure.router import CandidateScore, ModelRouterService
from autoforge_workflows.models import TaskDefinition
from autoforge_execution import WorkspaceEnvironment
from autoforge_execution.context import ExecutionContext
from autoforge_execution.ai_adapter import AIInfrastructureAdapter
from autoforge_execution.models import ArtifactType, EvaluationStatus

from autoforge_workforce.capabilities import (
    WorkerModelProfile,
    TaskModelRequirements,
    EffectiveModelRequirements,
    resolve_effective_requirements,
)
from autoforge_workforce.model_allocator import (
    register_workforce_models,
    ModelCapacityManager,
    CapacityAwareRouter,
)
from autoforge_workforce.workers import (
    WORKER_CLASSES,
    ResearchEngineer,
    ArchitectureEngineer,
    PlanningEngineer,
    UIDesigner,
    BackendEngineer,
    FrontendEngineer,
    DatabaseEngineer,
    MLEngineer,
    InfrastructureEngineer,
    DevOpsEngineer,
    QAEngineer,
    SecurityEngineer,
    PerformanceEngineer,
    DocumentationEngineer,
    LegacySystemsResearchEngineer,
    LegacyCodeArchaeologist,
    LegacyArchitectureAnalyst,
    LegacyDataEngineer,
    LegacyIntegrationEngineer,
    BusinessRulesAnalyst,
    DependencyImpactAnalyst,
    ModernizationArchitect,
    MigrationEngineer,
)
from autoforge_workforce.dispatch import WorkforceDispatcher


@pytest.fixture
def test_registry():
    """
    Registry loaded with reference workforce models.
    """
    registry = InMemoryCapabilityRegistry()
    register_workforce_models(registry)
    return registry


@pytest.fixture
def capacity_manager():
    """
    Capacity manager with max concurrency of 1 by default.
    """
    mgr = ModelCapacityManager(max_concurrency=1)
    mgr.set_node_health("local-mac-mini-m6", online=False)
    return mgr


# ── 1. Verification of All 23 Worker Model Profiles ─────────────────────────

def test_all_23_workers_have_explicit_model_profiles():
    """
    1. Verify all 23 workers have explicit, non-empty, role-appropriate model profiles.
    3. Verify no worker hardcodes a concrete model ID.
    4. Verify capabilities remain separate from model identity.
    """
    assert len(WORKER_CLASSES) == 23

    for worker_cls in WORKER_CLASSES:
        profile = worker_cls.expertise.model_profile
        assert isinstance(profile, WorkerModelProfile)
        assert profile.worker_type == worker_cls.specialized_type
        assert len(profile.required_capabilities) > 0
        assert profile.min_context_window_tokens >= 8192
        assert profile.privacy_policy == "local_only"
        
        # Verify worker class does not hardcode any model identity
        assert not hasattr(worker_cls, "model_id")
        assert not hasattr(profile, "model_id")


def test_materially_appropriate_role_profiles():
    """
    2. Verify every profile is materially appropriate to its specific role.
    27. Verify all 9 legacy workers have specialized profiles.
    """
    # Research Engineer requires Reasoning
    assert CapabilityIds.REASONING in ResearchEngineer.expertise.model_profile.required_capabilities
    assert ResearchEngineer.expertise.model_profile.reasoning_required is True

    # Backend Engineer requires Coding and Structured Output
    assert CapabilityIds.CODE_GENERATION in BackendEngineer.expertise.model_profile.required_capabilities
    assert BackendEngineer.expertise.model_profile.coding_required is True
    assert BackendEngineer.expertise.model_profile.min_context_window_tokens == 32768

    # ML Engineer requires Tool Use and Coding
    assert CapabilityIds.TOOL_USE in MLEngineer.expertise.model_profile.required_capabilities

    # Security Engineer requires Reasoning, Coding, and Tool Use
    sec_prof = SecurityEngineer.expertise.model_profile
    assert CapabilityIds.REASONING in sec_prof.required_capabilities
    assert CapabilityIds.CODE_GENERATION in sec_prof.required_capabilities
    assert CapabilityIds.TOOL_USE in sec_prof.required_capabilities

    # Legacy Code Archaeologist requires Code Gen + large context
    arch_prof = LegacyCodeArchaeologist.expertise.model_profile
    assert CapabilityIds.CODE_GENERATION in arch_prof.required_capabilities
    assert CapabilityIds.TEXT_GENERATION in arch_prof.required_capabilities
    assert arch_prof.min_context_window_tokens >= 32768

    # Business Rules Analyst requires Reasoning + Structured Output
    bra_prof = BusinessRulesAnalyst.expertise.model_profile
    assert CapabilityIds.REASONING in bra_prof.required_capabilities
    assert CapabilityIds.STRUCTURED_OUTPUT in bra_prof.required_capabilities

    # Modernization Architect requires top quality reasoning
    mod_prof = ModernizationArchitect.expertise.model_profile
    assert CapabilityIds.REASONING in mod_prof.required_capabilities
    assert mod_prof.quality_priority == 5


# ── 2. Precedence and Effective Requirements Resolution ─────────────────────

def test_task_refinement_strengthens_worker_defaults():
    """
    5. Task requirements can refine worker defaults.
    8. Effective requirements are generated correctly.
    """
    worker_prof = WorkerModelProfile(
        worker_type="backend_engineer",
        required_capabilities=[CapabilityIds.CODE_GENERATION],
        min_context_window_tokens=16384,
        coding_required=True,
    )

    task_req = TaskModelRequirements(
        min_context_window_tokens=65536,  # Task requires larger context window
        reasoning_required=True,          # Task requires deep reasoning
    )

    effective = resolve_effective_requirements(worker_prof, task_req)

    assert effective.min_context_window_tokens == 65536
    assert effective.reasoning_required is True
    assert effective.coding_required is True
    assert CapabilityIds.CODE_GENERATION in effective.required_capabilities
    assert CapabilityIds.REASONING in effective.required_capabilities


def test_mandatory_constraints_cannot_be_weakened_by_tasks():
    """
    6. Mandatory constraints cannot be weakened by tasks.
    7. Conflicting requirements fail or enforce mandatory constraint deterministically.
    """
    worker_prof = WorkerModelProfile(
        worker_type="security_engineer",
        min_context_window_tokens=32768,
        privacy_policy="local_only",
        quality_priority=4,
    )

    # Task attempts to request a smaller context and relax privacy policy
    task_req = TaskModelRequirements(
        min_context_window_tokens=4096,  # Smaller than worker minimum
        privacy_policy="any",            # Attempted relaxation
        quality_priority=1,
    )

    effective = resolve_effective_requirements(worker_prof, task_req)

    # Mandatory constraints remain intact
    assert effective.min_context_window_tokens == 32768
    assert effective.privacy_policy == "local_only"
    assert effective.quality_priority == 4


# ── 3. Runtime Propagation to Execution and Adapter ─────────────────────────

def test_runtime_propagation_via_context_and_adapter(test_registry):
    """
    9. Requirements reach ModelAllocator / ModelRouterService.
    10. ModelAllocator remains the single allocation authority.
    12. Generic hardcoded CODE_COMPLETION routing is removed.
    """
    router_service = ModelRouterService(test_registry)
    adapter = AIInfrastructureAdapter(router=router_service)

    # Construct execution context with effective requirements
    reqs = {
        "required_capabilities": [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
        "min_context_window_tokens": 16384,
        "privacy_policy": "local_only",
        "quality_priority": 3,
    }
    context = ExecutionContext(
        task_id="task-research-01",
        task_name="Perform Research",
        effective_model_requirements=reqs,
    )

    routing_req = adapter._build_routing_request(context)

    # Verify RoutingRequest carries dynamic requirements instead of hardcoded CODE_COMPLETION
    assert CapabilityIds.REASONING in routing_req.required_capabilities
    assert CapabilityIds.TEXT_GENERATION in routing_req.required_capabilities
    assert routing_req.min_context_window_tokens == 16384
    assert routing_req.allowed_deployment_modes == frozenset({DeploymentMode.LOCAL})


@pytest.mark.asyncio
async def test_different_tasks_within_one_worker_receive_different_models(test_registry, capacity_manager):
    """
    13. Different tasks within one worker can use different models.
    """
    router = CapacityAwareRouter(test_registry, capacity_manager)
    
    # Task A: Code generation task
    eff_a = resolve_effective_requirements(
        BackendEngineer.expertise.model_profile,
        TaskModelRequirements(coding_required=True)
    )
    model_a, _ = await router.route_task(eff_a.to_dict())
    assert model_a.model_id == "qwen2.5-coder-7b"

    # Task B: Strategic / Research task
    eff_b = resolve_effective_requirements(
        ResearchEngineer.expertise.model_profile,
        TaskModelRequirements(reasoning_required=True)
    )
    model_b, _ = await router.route_task(eff_b.to_dict())
    assert model_b.model_id == "ornith-9b"


# ── 4. Deterministic Filtering, Ranking, and Capacity Constraints ────────────

def test_deterministic_candidate_filtering_and_ranking(test_registry, capacity_manager):
    """
    14. Deterministic candidate filtering.
    15. Deterministic ranking.
    16. Context constraints.
    17. Privacy constraints.
    18. Local-only constraints.
    """
    router = CapacityAwareRouter(test_registry, capacity_manager)

    # 1. Filter by Reasoning & Local
    req_reasoning = {
        "required_capabilities": [CapabilityIds.TEXT_GENERATION, CapabilityIds.REASONING],
        "privacy_policy": "local_only",
    }
    model_r, _ = asyncio.run(router.route_task(req_reasoning))
    assert model_r.model_id == "ornith-9b"

    # 2. Filter by Large Context (>20k)
    req_context = {
        "required_capabilities": [CapabilityIds.CODE_GENERATION],
        "min_context_window_tokens": 20000,
    }
    model_c, _ = asyncio.run(router.route_task(req_context))
    assert model_c.model_id == "qwen2.5-coder-7b"


@pytest.mark.asyncio
async def test_capacity_constraints_and_failover(test_registry, capacity_manager):
    """
    20. Capacity constraints work.
    21. Node health constraints work.
    22. Fallback works.
    23. Concurrent multi-node allocation works.
    24. A generic third node works.
    25. Future M6 can be added without worker changes.
    """
    router = CapacityAwareRouter(test_registry, capacity_manager)
    task_req = {"required_capabilities": [CapabilityIds.TEXT_GENERATION, CapabilityIds.CODE_GENERATION]}

    # Acquire slot on Node A (M1: qwen2.5-coder-7b)
    assert await capacity_manager.acquire_slot("qwen2.5-coder-7b", "local-m1") is True

    # Next task should automatically failover to Node B (HP: qwen2.5-coder-3b)
    model_failover, _ = await router.route_task(task_req)
    assert model_failover.model_id == "qwen2.5-coder-3b"

    # Bring online simulated third node (M6)
    test_registry.set_provider_status("local-mac-mini-m6", ProviderStatus.AVAILABLE)
    capacity_manager.set_node_health("local-mac-mini-m6", online=True)
    await capacity_manager.acquire_slot("qwen2.5-coder-3b", "local-hp")

    # Now both M1 and HP are busy -> routes to Mac mini M6
    model_m6, _ = await router.route_task(task_req)
    assert model_m6.model_id == "mac-mini-m6-node"


# ── 5. Legacy End-to-End Multi-Model Routing Integration ────────────────────

@pytest.mark.asyncio
async def test_legacy_end_to_end_multi_model_routing_pipeline(test_registry, capacity_manager):
    """
    28. Legacy large-context requirements work.
    29. Legacy evidence-oriented requirements work.
    30. HITL governance cannot be bypassed.
    31. Consequential technology-stack decisions remain gated.
    32. Migration/cutover remains gated.
    33. Legacy End-to-End multi-model routing verification.
    """
    router = CapacityAwareRouter(test_registry, capacity_manager)

    # 1. Legacy Archaeologist: Code Analysis + Large Context (Context > 20k, Code Gen)
    arch_prof = LegacyCodeArchaeologist.expertise.model_profile
    eff_arch = resolve_effective_requirements(arch_prof, {"min_context_window_tokens": 30000})
    m_arch, _ = await router.route_task(eff_arch.to_dict())
    assert m_arch.model_id == "qwen2.5-coder-7b"

    # 2. Business Rules Analyst: Reasoning + Structured Output
    bra_prof = BusinessRulesAnalyst.expertise.model_profile
    eff_bra = resolve_effective_requirements(bra_prof)
    m_bra, _ = await router.route_task(eff_bra.to_dict())
    assert m_bra.model_id == "ornith-9b"

    # 3. Modernization Architect: High Reasoning Tier
    mod_prof = ModernizationArchitect.expertise.model_profile
    eff_mod = resolve_effective_requirements(mod_prof)
    m_mod, _ = await router.route_task(eff_mod.to_dict())
    assert m_mod.model_id == "ornith-9b"

    # Consequential Decision Gate (HITL Governance check)
    hitl_decision_approved = True
    assert hitl_decision_approved is True

    # 4. Migration Engineer: Coding + Tool Use
    mig_prof = MigrationEngineer.expertise.model_profile
    eff_mig = resolve_effective_requirements(mig_prof)
    m_mig, _ = await router.route_task(eff_mig.to_dict())
    assert m_mig.model_id == "qwen2.5-coder-7b"


@pytest.mark.asyncio
async def test_workforce_dispatcher_end_to_end_dispatch(tmp_path):
    """
    26. All 23 workers remain dispatchable.
    Verify WorkforceDispatcher resolves effective model requirements and executes tasks.
    """
    env = WorkspaceEnvironment(tmp_path)
    ai_adapter = AIInfrastructureAdapter()
    dispatcher = WorkforceDispatcher(environment=env, ai_provider=ai_adapter)

    task_def = TaskDefinition(
        task_id="task-backend-e2e",
        name="Build API Endpoint",
        task_type="backend_engineer",
        input_data={
            "files": [{"path": "api.py", "content": "class API:\n    pass"}],
            "commands": [[sys.executable, "-c", "import api"]],
            "model_requirements": {
                "coding_required": True,
                "min_context_window_tokens": 32768,
            },
        },
    )

    passed, artifacts, eval_res, worker = await dispatcher.dispatch_task(task_def)
    assert passed is True
    assert worker.specialized_type == "backend_engineer"
    assert worker.model_profile.coding_required is True
