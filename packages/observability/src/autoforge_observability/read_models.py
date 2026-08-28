"""
Programmatic dashboard read-models for AutoForge AI OS.
"""

from __future__ import annotations
import threading
import uuid
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
)


class DashboardManager:
    """
    Manages and exposes the 13 required AutoForge read-model dashboards.
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
