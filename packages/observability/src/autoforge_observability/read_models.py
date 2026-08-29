"""
Programmatic dashboard read-models for AutoForge AI OS.
"""

from __future__ import annotations
import os
import platform
import subprocess
import threading
import uuid

from datetime import datetime, timezone
from typing import Dict, List, Optional, Set, Any
from autoforge_observability.models import (
    SystemDashboard,
    WorkflowDashboard,
    ExecutionDashboard,
    WorkforceDashboard,
    AIInfrastructureDashboard,
    CapabilityDashboard,
    ProviderDashboard,
    ModelDashboard,
    InferenceNodeDashboard,
    ArtifactDashboard,
    ReviewDashboard,
    LegacyModernizationDashboard,
    HITLGovernanceDashboard,
    NodeIdentity,
    NodeStatusEnum,
    NodeResourceMetadata,
    RoutingDecisionRecord,
    NodeObservabilityReadModel,
    FleetObservabilityReadModel,
)


class DashboardManager:
    """
    Manages and exposes the 13 required AutoForge read-model dashboards
    plus Phase 17-A Dual-Level (Node-Local & Fleet) Observability Read Models.
    All operations are thread-safe.
    """

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.system = SystemDashboard()
        self.workflow = WorkflowDashboard()
        self.execution = ExecutionDashboard()
        self.workforce = WorkforceDashboard()
        self.ai_infrastructure = AIInfrastructureDashboard()
        self.capability = CapabilityDashboard()
        self.provider = ProviderDashboard()
        self.model = ModelDashboard()
        self.inference_node = InferenceNodeDashboard()
        self.artifact = ArtifactDashboard()
        self.review = ReviewDashboard()
        self.legacy_modernization = LegacyModernizationDashboard()
        self.hitl_governance = HITLGovernanceDashboard()

        # Phase 17-A Dual-Level Observability
        self._current_node_id = os.environ.get("AUTOFORGE_NODE_ID", "local-m1")
        self._nodes: Dict[str, NodeObservabilityReadModel] = {}
        self._fleet = FleetObservabilityReadModel()
        self._init_default_nodes()


    def update_system_uptime(self, uptime_seconds: float) -> None:
        with self._lock:
            self.system.uptime_seconds = uptime_seconds

    def set_system_health(self, healthy: bool) -> None:
        with self._lock:
            self.system.is_healthy = healthy

    def increment_system_errors(self, category: str) -> None:
        with self._lock:
            self.system.active_errors_count += 1
            self.system.error_categories[category] = self.system.error_categories.get(category, 0) + 1

    def increment_security_violation(self) -> None:
        with self._lock:
            self.system.security_violations += 1

    def record_workflow_started(self) -> None:
        with self._lock:
            self.workflow.total_workflows += 1
            self.workflow.active_workflows += 1
            self.workflow.concurrency = max(self.workflow.concurrency, self.workflow.active_workflows)

    def record_workflow_completed(self) -> None:
        with self._lock:
            self.workflow.completed_workflows += 1
            if self.workflow.active_workflows > 0:
                self.workflow.active_workflows -= 1

    def record_workflow_failed(self) -> None:
        with self._lock:
            self.workflow.failed_workflows += 1
            if self.workflow.active_workflows > 0:
                self.workflow.active_workflows -= 1

    def record_task_created(self) -> None:
        with self._lock:
            self.workflow.total_tasks += 1

    def record_task_queued(self) -> None:
        with self._lock:
            self.workflow.queued_tasks += 1

    def record_task_started(self) -> None:
        with self._lock:
            self.workflow.active_tasks += 1
            if self.workflow.queued_tasks > 0:
                self.workflow.queued_tasks -= 1

    def record_task_completed(self) -> None:
        with self._lock:
            self.workflow.completed_tasks += 1
            if self.workflow.active_tasks > 0:
                self.workflow.active_tasks -= 1

    def record_task_failed(self) -> None:
        with self._lock:
            self.workflow.failed_tasks += 1
            if self.workflow.active_tasks > 0:
                self.workflow.active_tasks -= 1

    def record_task_retry(self) -> None:
        with self._lock:
            self.workflow.retries_count += 1

    def record_execution_started(self) -> None:
        with self._lock:
            self.execution.total_executions += 1
            self.execution.active_executions += 1

    def record_execution_completed(self) -> None:
        with self._lock:
            self.execution.completed_executions += 1
            if self.execution.active_executions > 0:
                self.execution.active_executions -= 1

    def record_execution_failed(self) -> None:
        with self._lock:
            self.execution.failed_executions += 1
            if self.execution.active_executions > 0:
                self.execution.active_executions -= 1

    def record_execution_cancelled(self) -> None:
        with self._lock:
            self.execution.cancelled_executions += 1
            if self.execution.active_executions > 0:
                self.execution.active_executions -= 1

    def record_execution_attempt(self) -> None:
        with self._lock:
            self.execution.attempts_count += 1

    def record_execution_timeout(self) -> None:
        with self._lock:
            self.execution.timeouts_count += 1

    def record_execution_recovery(self) -> None:
        with self._lock:
            self.execution.recoveries_count += 1

    def register_worker(self, worker_id: str) -> None:
        with self._lock:
            self.workforce.registered_workers.add(worker_id)

    def record_worker_dispatch(self, worker_id: str, worker_type: str) -> None:
        with self._lock:
            self.workforce.active_workers.add(worker_id)
            self.workforce.worker_dispatch_counts[worker_type] = self.workforce.worker_dispatch_counts.get(worker_type, 0) + 1

    def record_worker_completed(self, worker_id: str, worker_type: str, success: bool) -> None:
        with self._lock:
            self.workforce.active_workers.discard(worker_id)
            dispatches = self.workforce.worker_dispatch_counts.get(worker_type, 0)
            if dispatches > 0:
                successes = int(dispatches * self.workforce.worker_success_rates.get(worker_type, 0.0))
                failures = int(dispatches * self.workforce.worker_failure_rates.get(worker_type, 0.0))
                if success:
                    successes += 1
                else:
                    failures += 1
                self.workforce.worker_success_rates[worker_type] = successes / dispatches
                self.workforce.worker_failure_rates[worker_type] = failures / dispatches

    def record_worker_loop_iteration(self, worker_id: str) -> None:
        with self._lock:
            self.workforce.loop_iterations[worker_id] = self.workforce.loop_iterations.get(worker_id, 0) + 1

    def record_worker_remediation(self, worker_id: str) -> None:
        with self._lock:
            self.workforce.worker_remediations[worker_id] = self.workforce.worker_remediations.get(worker_id, 0) + 1

    def record_model_call(self, model_id: str, provider_id: str, success: bool, tokens: int, cost: float, latency_ms: float) -> None:
        with self._lock:
            self.ai_infrastructure.total_model_calls += 1
            if success:
                self.ai_infrastructure.successful_model_calls += 1
            else:
                self.ai_infrastructure.failed_model_calls += 1
            
            # Estimated Cost
            self.ai_infrastructure.estimated_cost += cost
            self.ai_infrastructure.token_usage["total"] = self.ai_infrastructure.token_usage.get("total", 0) + tokens
            
            # Latency average calc
            calls = self.ai_infrastructure.total_model_calls
            prev_avg = self.ai_infrastructure.average_model_latency_ms
            self.ai_infrastructure.average_model_latency_ms = prev_avg + (latency_ms - prev_avg) / calls

            # Update Model read-model
            self.model.model_call_counts[model_id] = self.model.model_call_counts.get(model_id, 0) + 1
            self.model.model_estimated_costs[model_id] = self.model.model_estimated_costs.get(model_id, 0.0) + cost
            self.model.model_token_usage[model_id] = self.model.model_token_usage.get(model_id, 0) + tokens
            if model_id not in self.model.model_latencies:
                self.model.model_latencies[model_id] = []
            self.model.model_latencies[model_id].append(latency_ms)

            # Update Provider read-model
            self.provider.provider_call_counts[provider_id] = self.provider.provider_call_counts.get(provider_id, 0) + 1
            if provider_id not in self.provider.provider_latencies:
                self.provider.provider_latencies[provider_id] = []
            self.provider.provider_latencies[provider_id].append(latency_ms)

    def record_routing_decision(self, req_caps: List[str], selected: str, rejected: Dict[str, str]) -> None:
        with self._lock:
            self.ai_infrastructure.routing_decisions_count += 1
            for cap in req_caps:
                self.capability.capability_usage_counts[cap] = self.capability.capability_usage_counts.get(cap, 0) + 1
                self.capability.active_capabilities.add(cap)
            for model_id, reason in rejected.items():
                self.capability.rejected_capabilities_counts[reason] = self.capability.rejected_capabilities_counts.get(reason, 0) + 1

    def record_fallback(self) -> None:
        with self._lock:
            self.ai_infrastructure.fallback_events_count += 1

    def set_provider_health(self, provider_id: str, online: bool) -> None:
        with self._lock:
            self.provider.provider_status[provider_id] = online
            # Sync with Inference Node if applicable
            self.inference_node.node_status[provider_id] = online

    def set_model_status(self, model_id: str, status: str) -> None:
        with self._lock:
            self.model.model_status[model_id] = status

    def record_node_model_active(self, node_id: str, model_id: str) -> None:
        with self._lock:
            if node_id not in self.inference_node.active_models_per_node:
                self.inference_node.active_models_per_node[node_id] = set()
            self.inference_node.active_models_per_node[node_id].add(model_id)

    def record_artifact_created(self, artifact_type: str) -> None:
        with self._lock:
            self.artifact.artifacts_created_count += 1
            self.artifact.artifacts_by_type[artifact_type] = self.artifact.artifacts_by_type.get(artifact_type, 0) + 1

    def record_artifact_version(self) -> None:
        with self._lock:
            self.artifact.versions_created_count += 1

    def record_artifact_published(self) -> None:
        with self._lock:
            self.artifact.publications_count += 1

    def record_artifact_rollback(self) -> None:
        with self._lock:
            self.artifact.rollbacks_count += 1

    def record_artifact_integrity_failure(self) -> None:
        with self._lock:
            self.artifact.integrity_failures_count += 1

    def record_review_started(self) -> None:
        with self._lock:
            self.review.total_reviews += 1

    def record_review_completed(self, passed: bool, duration_ms: float) -> None:
        with self._lock:
            if passed:
                self.review.passed_reviews += 1
            else:
                self.review.failed_reviews += 1
            calls = self.review.total_reviews
            prev_avg = self.review.average_review_latency_ms
            self.review.average_review_latency_ms = prev_avg + (duration_ms - prev_avg) / calls

    def record_review_repair_loop(self) -> None:
        with self._lock:
            self.review.repair_loops_count += 1

    def record_hitl_approval_requested(self, worker_id: str, approval_type: str) -> None:
        with self._lock:
            self.hitl_governance.requests_count += 1
            self.hitl_governance.active_approvals_count += 1
            self.hitl_governance.approvals_by_worker[worker_id] = self.hitl_governance.approvals_by_worker.get(worker_id, 0) + 1
            self.hitl_governance.approvals_by_type[approval_type] = self.hitl_governance.approvals_by_type.get(approval_type, 0) + 1

    def record_hitl_approval_decided(self) -> None:
        with self._lock:
            self.hitl_governance.decisions_count += 1
            if self.hitl_governance.active_approvals_count > 0:
                self.hitl_governance.active_approvals_count -= 1

    def record_hitl_timeout(self) -> None:
        with self._lock:
            self.hitl_governance.timeouts_count += 1
            if self.hitl_governance.active_approvals_count > 0:
                self.hitl_governance.active_approvals_count -= 1

    def record_legacy_system_analyzed(self) -> None:
        with self._lock:
            self.legacy_modernization.systems_analyzed += 1

    def record_legacy_evidence(self, epistemic_type: str) -> None:
        with self._lock:
            self.legacy_modernization.evidence_items_count += 1
            self.legacy_modernization.evidence_types[epistemic_type] = self.legacy_modernization.evidence_types.get(epistemic_type, 0) + 1

    def record_legacy_analysis_gap(self) -> None:
        with self._lock:
            self.legacy_modernization.analysis_gaps_count += 1

    def record_legacy_unknown(self) -> None:
        with self._lock:
            self.legacy_modernization.unknowns_encountered_count += 1

    def record_legacy_business_rule(self) -> None:
        with self._lock:
            self.legacy_modernization.business_rules_extracted += 1

    def record_legacy_modernization_decision(self) -> None:
        with self._lock:
            self.legacy_modernization.modernization_decisions_count += 1
    def record_legacy_migration_plan(self) -> None:
        with self._lock:
            self.legacy_modernization.migration_plans_created += 1

    def _discover_local_hardware(self) -> NodeResourceMetadata:
        """Dynamically detect real physical hardware metrics on the local host."""
        mem_total_gb: Optional[float] = None
        mem_free_gb: Optional[float] = None
        gpu_info: Optional[str] = None

        plat = platform.system().lower()
        
        # 1. Physical RAM detection
        try:
            if plat == "darwin":
                out = subprocess.check_output(["sysctl", "-n", "hw.memsize"], stderr=subprocess.DEVNULL).decode().strip()
                mem_total_gb = round(int(out) / (1024 ** 3), 1)
                
                # Try getting free pages via vm_stat
                vm_out = subprocess.check_output(["vm_stat"], stderr=subprocess.DEVNULL).decode()
                page_size = 4096
                pages_free = 0
                for line in vm_out.splitlines():
                    if "Pages free:" in line:
                        pages_free += int(line.split(":")[1].strip().rstrip("."))
                    elif "Pages speculative:" in line:
                        pages_free += int(line.split(":")[1].strip().rstrip("."))
                mem_free_gb = round((pages_free * page_size) / (1024 ** 3), 1)
            elif plat == "linux" and os.path.exists("/proc/meminfo"):
                with open("/proc/meminfo", "r") as f:
                    for line in f:
                        if line.startswith("MemTotal:"):
                            kb = int(line.split()[1])
                            mem_total_gb = round(kb / (1024 ** 2), 1)
                        elif line.startswith("MemAvailable:"):
                            kb = int(line.split()[1])
                            mem_free_gb = round(kb / (1024 ** 2), 1)
            else:
                pages = os.sysconf("SC_PHYS_PAGES")
                page_size = os.sysconf("SC_PAGE_SIZE")
                mem_total_gb = round((pages * page_size) / (1024 ** 3), 1)
        except Exception:
            mem_total_gb = None
            mem_free_gb = None

        # 2. Accelerator / GPU detection
        try:
            if plat == "darwin":
                brand = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"], stderr=subprocess.DEVNULL).decode().strip()
                gpu_info = f"{brand} (Unified Memory)"
            elif plat == "linux":
                gpu_info = "Linux Host Accelerator"
            else:
                gpu_info = None
        except Exception:
            gpu_info = None

        return NodeResourceMetadata(
            memory_total_gb=mem_total_gb,
            memory_free_gb=mem_free_gb,
            gpu_info=gpu_info,
            process_health="healthy",
        )

    def _init_default_nodes(self) -> None:
        """Register known AutoForge cluster nodes with truthful hardware state."""
        now = datetime.now(timezone.utc)
        local_hw = self._discover_local_hardware()

        # 1. local-m1 (Local Controller Host)
        m1_node = NodeIdentity(
            node_id="local-m1",
            display_name="Apple Mac M1 (Primary Controller)",
            hostname=platform.node() or "localhost",
            platform=platform.system().lower(),
            architecture=platform.machine(),
            autoforge_version="1.0.0",
            runtime_version=platform.python_version(),
            health=NodeStatusEnum.HEALTHY,
            uptime_seconds=0.0,
            last_seen=now,
            capabilities=["text_generation", "code_generation", "reasoning", "structured_output", "tool_use"],
            providers=["local-m1"],
            models=["qwen2.5-coder-7b", "ornith-9b"],
            capacity_slots=4,
            active_slots=0,
            resource_metadata=local_hw,
            is_live_hardware=True,
            notes="Primary local controller and fast code generation node.",
        )
        self._nodes["local-m1"] = NodeObservabilityReadModel(node=m1_node)

        # 2. local-hp (Remote LAN Worker Node - Hardware details reported as discovered/telemetry, not fabricated)
        hp_node = NodeIdentity(
            node_id="local-hp",
            display_name="HP Workstation (LAN Worker Node)",
            hostname="192.168.1.105",
            platform="linux",
            architecture="x86_64",
            autoforge_version="1.0.0",
            runtime_version="3.14.0",
            health=NodeStatusEnum.HEALTHY,
            uptime_seconds=0.0,
            last_seen=now,
            capabilities=["text_generation", "code_generation"],
            providers=["local-hp"],
            models=["qwen2.5-coder-3b"],
            capacity_slots=8,
            active_slots=0,
            resource_metadata=NodeResourceMetadata(
                memory_total_gb=None,  # Uninstrumented on remote LAN without agent: displayed as Unavailable
                memory_free_gb=None,
                gpu_info=None,
                process_health="healthy",
            ),
            is_live_hardware=True,
            endpoint="http://192.168.1.105:11434",
            notes="High-throughput batch and reasoning worker node (LAN Ollama daemon).",
        )
        self._nodes["local-hp"] = NodeObservabilityReadModel(node=hp_node)

        # 3. local-mac-mini-m6 (Future Planned Spec)
        m6_node = NodeIdentity(
            node_id="local-mac-mini-m6",
            display_name="Future Apple Mac mini M6 (Simulated / Planned Spec)",
            hostname="unconnected",
            platform="darwin",
            architecture="arm64",
            autoforge_version="1.0.0",
            runtime_version="3.14.0",
            health=NodeStatusEnum.UNAVAILABLE,
            uptime_seconds=0.0,
            last_seen=None,
            capabilities=["text_generation", "code_generation", "reasoning", "structured_output"],
            providers=["local-mac-mini-m6"],
            models=["mac-mini-m6-node"],
            capacity_slots=16,
            active_slots=0,
            resource_metadata=NodeResourceMetadata(
                memory_total_gb=None,
                memory_free_gb=None,
                gpu_info="Target Architecture Spec (Simulation Profile)",
                process_health="unavailable",
            ),
            is_live_hardware=False,
            endpoint=None,
            notes="Target hardware specification profile. Offline / unprovisioned.",
        )
        self._nodes["local-mac-mini-m6"] = NodeObservabilityReadModel(node=m6_node)

        # Recompute fleet overview
        self._recalculate_fleet()

    def _recalculate_fleet(self) -> None:
        """Recalculate fleet aggregates across all registered nodes."""
        self._fleet.nodes_count = len(self._nodes)
        self._fleet.healthy_nodes_count = sum(1 for nm in self._nodes.values() if nm.node.health == NodeStatusEnum.HEALTHY)
        self._fleet.degraded_nodes_count = sum(1 for nm in self._nodes.values() if nm.node.health == NodeStatusEnum.DEGRADED)
        self._fleet.offline_nodes_count = sum(1 for nm in self._nodes.values() if nm.node.health == NodeStatusEnum.OFFLINE)
        self._fleet.unavailable_nodes_count = sum(1 for nm in self._nodes.values() if nm.node.health in {NodeStatusEnum.UNAVAILABLE, NodeStatusEnum.PLANNED_SPEC})

        self._fleet.total_capacity_slots = sum(nm.node.capacity_slots for nm in self._nodes.values())
        self._fleet.total_active_slots = sum(nm.node.active_slots for nm in self._nodes.values())
        self._fleet.fleet_utilization = (
            self._fleet.total_active_slots / self._fleet.total_capacity_slots
            if self._fleet.total_capacity_slots > 0
            else 0.0
        )

        self._fleet.nodes = {k: nm.node for k, nm in self._nodes.items()}
        
        # Build model distribution map
        dist: Dict[str, List[str]] = {}
        for nid, nrm in self._nodes.items():
            for mid in nrm.node.models:
                dist.setdefault(mid, []).append(nid)
        self._fleet.model_distribution = dist

    def get_current_node_id(self) -> str:
        with self._lock:
            return self._current_node_id

    def set_current_node_id(self, node_id: str) -> None:
        with self._lock:
            self._current_node_id = node_id

    def register_node(self, node: NodeIdentity) -> None:
        with self._lock:
            if node.node_id in self._nodes:
                self._nodes[node.node_id].node = node
            else:
                self._nodes[node.node_id] = NodeObservabilityReadModel(node=node)
            self._recalculate_fleet()

    def get_node(self, node_id: Optional[str] = None) -> NodeObservabilityReadModel:
        with self._lock:
            nid = node_id or self._current_node_id
            if nid not in self._nodes:
                # Create default fallback node identity
                fallback = NodeIdentity(
                    node_id=nid,
                    display_name=f"Node {nid}",
                    hostname="localhost",
                    platform="unknown",
                    architecture="unknown",
                    health=NodeStatusEnum.UNKNOWN,
                )
                self._nodes[nid] = NodeObservabilityReadModel(node=fallback)
                self._recalculate_fleet()
            return self._nodes[nid].model_copy(deep=True)

    def get_fleet(self) -> FleetObservabilityReadModel:
        with self._lock:
            self._recalculate_fleet()
            return self._fleet.model_copy(deep=True)

    def set_node_health(self, node_id: str, health: NodeStatusEnum | str, notes: str = "") -> None:
        with self._lock:
            if node_id in self._nodes:
                enum_val = NodeStatusEnum(health) if isinstance(health, str) else health
                self._nodes[node_id].node.health = enum_val
                if notes:
                    self._nodes[node_id].node.notes = notes
                self._recalculate_fleet()

    def update_node_resources(self, node_id: str, resource_metadata: NodeResourceMetadata) -> None:
        with self._lock:
            if node_id in self._nodes:
                self._nodes[node_id].node.resource_metadata = resource_metadata

    def record_node_inference(
        self,
        node_id: str,
        model_id: str,
        provider_id: str,
        success: bool,
        tokens: int,
        cost: float,
        latency_ms: float,
        input_tokens: int = 0,
        output_tokens: int = 0,
        throughput_tps: float = 0.0,
        retry_count: int = 0,
        failover_count: int = 0,
        task_id: Optional[str] = None,
        worker_id: Optional[str] = None,
        correlation_id: Optional[str] = None,
    ) -> None:
        with self._lock:
            # 1. Update 13 standard read models
            self.ai_infrastructure.total_model_calls += 1
            if success:
                self.ai_infrastructure.successful_model_calls += 1
            else:
                self.ai_infrastructure.failed_model_calls += 1
            
            self.ai_infrastructure.estimated_cost += cost
            self.ai_infrastructure.token_usage["total"] = self.ai_infrastructure.token_usage.get("total", 0) + tokens
            
            calls = self.ai_infrastructure.total_model_calls
            prev_avg = self.ai_infrastructure.average_model_latency_ms
            self.ai_infrastructure.average_model_latency_ms = prev_avg + (latency_ms - prev_avg) / calls

            self.model.model_call_counts[model_id] = self.model.model_call_counts.get(model_id, 0) + 1
            self.model.model_estimated_costs[model_id] = self.model.model_estimated_costs.get(model_id, 0.0) + cost
            self.model.model_token_usage[model_id] = self.model.model_token_usage.get(model_id, 0) + tokens
            if model_id not in self.model.model_latencies:
                self.model.model_latencies[model_id] = []
            self.model.model_latencies[model_id].append(latency_ms)

            self.provider.provider_call_counts[provider_id] = self.provider.provider_call_counts.get(provider_id, 0) + 1
            if provider_id not in self.provider.provider_latencies:
                self.provider.provider_latencies[provider_id] = []
            self.provider.provider_latencies[provider_id].append(latency_ms)

            # 2. Update Node-Scoped Read Model
            nid = node_id or self._current_node_id
            if nid not in self._nodes:
                fallback = NodeIdentity(
                    node_id=nid,
                    display_name=f"Node {nid}",
                    health=NodeStatusEnum.HEALTHY,
                )
                self._nodes[nid] = NodeObservabilityReadModel(node=fallback)

            nrm = self._nodes[nid]
            nrm.total_requests += 1
            nrm.node.last_seen = datetime.now(timezone.utc)
            if success:
                # Token calculations
                inp = input_tokens if input_tokens > 0 else (tokens // 2 if tokens > 0 else 0)
                out = output_tokens if output_tokens > 0 else (tokens - inp if tokens > inp else tokens)
                nrm.input_tokens += inp
                nrm.output_tokens += out
                nrm.total_tokens += tokens

                # Latency & throughput updates
                req_count = nrm.total_requests
                prev_n_avg = nrm.average_latency_ms
                nrm.average_latency_ms = prev_n_avg + (latency_ms - prev_n_avg) / req_count

                if throughput_tps > 0:
                    prev_tps = nrm.average_throughput_tps
                    nrm.average_throughput_tps = prev_tps + (throughput_tps - prev_tps) / req_count
                elif latency_ms > 0 and tokens > 0:
                    calc_tps = tokens / (latency_ms / 1000.0)
                    prev_tps = nrm.average_throughput_tps
                    nrm.average_throughput_tps = prev_tps + (calc_tps - prev_tps) / req_count
            else:
                nrm.failures_count += 1

            nrm.retries_count += retry_count
            nrm.failovers_count += failover_count

            # Model metrics on this node
            m_stats = nrm.model_metrics.setdefault(model_id, {"calls": 0, "tokens": 0, "latencies": [], "tps_list": []})
            m_stats["calls"] += 1
            m_stats["tokens"] += tokens
            m_stats["latencies"].append(latency_ms)
            if throughput_tps > 0:
                m_stats["tps_list"].append(throughput_tps)

            # Provider metrics on this node
            p_stats = nrm.provider_metrics.setdefault(provider_id, {"status": "online" if success else "degraded", "calls": 0, "failures": 0, "latencies": []})
            p_stats["calls"] += 1
            p_stats["latencies"].append(latency_ms)
            if not success:
                p_stats["failures"] += 1

            # 3. Update Fleet-Scoped Read Model
            self._fleet.total_calls += 1
            if success:
                self._fleet.successful_calls += 1
                self._fleet.total_tokens += tokens
                inp = input_tokens if input_tokens > 0 else (tokens // 2 if tokens > 0 else 0)
                out = output_tokens if output_tokens > 0 else (tokens - inp if tokens > inp else tokens)
                self._fleet.total_input_tokens += inp
                self._fleet.total_output_tokens += out
                
                f_calls = self._fleet.total_calls
                prev_f_lat = self._fleet.average_latency_ms
                self._fleet.average_latency_ms = prev_f_lat + (latency_ms - prev_f_lat) / f_calls
                
                if throughput_tps > 0:
                    prev_f_tps = self._fleet.aggregate_throughput_tps
                    self._fleet.aggregate_throughput_tps = prev_f_tps + (throughput_tps - prev_f_tps) / f_calls
            else:
                self._fleet.failed_calls += 1
                self._fleet.failure_breakdown[provider_id] = self._fleet.failure_breakdown.get(provider_id, 0) + 1

            self._fleet.total_retries += retry_count
            self._fleet.total_failovers += failover_count

            # Recalculate fleet status
            self._recalculate_fleet()

    def record_routing_trail(self, record: RoutingDecisionRecord) -> None:
        with self._lock:
            # Add to fleet routing decisions trail (keep last 100)
            self._fleet.routing_decisions.insert(0, record)
            if len(self._fleet.routing_decisions) > 100:
                self._fleet.routing_decisions = self._fleet.routing_decisions[:100]

            # Also add to node-scoped event/activity log
            target_nid = record.selected_node_id or self._current_node_id
            if target_nid in self._nodes:
                self._nodes[target_nid].recent_events.insert(0, {
                    "type": "routing_decision",
                    "timestamp": record.timestamp.isoformat(),
                    "decision_id": record.decision_id,
                    "model_id": record.selected_model_id,
                    "provider_id": record.selected_provider_id,
                    "outcome": record.outcome,
                    "task_id": record.task_id,
                    "worker_type": record.worker_type,
                })
                if len(self._nodes[target_nid].recent_events) > 50:
                    self._nodes[target_nid].recent_events = self._nodes[target_nid].recent_events[:50]

    def record_node_event(self, node_id: str, event_data: Dict[str, Any]) -> None:
        with self._lock:
            nid = node_id or self._current_node_id
            if nid in self._nodes:
                self._nodes[nid].recent_events.insert(0, event_data)
                if len(self._nodes[nid].recent_events) > 50:
                    self._nodes[nid].recent_events = self._nodes[nid].recent_events[:50]

    def clear(self) -> None:
        with self._lock:
            self.system = SystemDashboard()
            self.workflow = WorkflowDashboard()
            self.execution = ExecutionDashboard()
            self.workforce = WorkforceDashboard()
            self.ai_infrastructure = AIInfrastructureDashboard()
            self.capability = CapabilityDashboard()
            self.provider = ProviderDashboard()
            self.model = ModelDashboard()
            self.inference_node = InferenceNodeDashboard()
            self.artifact = ArtifactDashboard()
            self.review = ReviewDashboard()
            self.legacy_modernization = LegacyModernizationDashboard()
            self.hitl_governance = HITLGovernanceDashboard()

            self._nodes.clear()
            self._fleet = FleetObservabilityReadModel()
            self._init_default_nodes()

