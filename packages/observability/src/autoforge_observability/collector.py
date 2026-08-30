"""
Event processing and read-model collector for AutoForge events.
"""

from __future__ import annotations
import uuid
from typing import Any, Dict, Optional
from autoforge_event_platform.models.event import Event, EventType, EventCategory
from autoforge_observability.metrics import MetricsRegistry
from autoforge_observability.logging import StructuredLogger
from autoforge_observability.tracing import TraceTracker
from autoforge_observability.read_models import DashboardManager
from autoforge_observability.models import Severity, RoutingDecisionRecord, NodeStatusEnum


class EventTelemetryCollector:
    """
    Ingests transport events and updates metrics, structured log streams,
    traces, and dashboard projections.
    """

    def __init__(
        self,
        metrics: MetricsRegistry,
        logger: StructuredLogger,
        traces: TraceTracker,
        dashboards: DashboardManager,
    ) -> None:
        self.metrics = metrics
        self.logger = logger
        self.traces = traces
        self.dashboards = dashboards

    def process_event(self, event: Event) -> None:
        """Process a single event published to the Event Platform."""
        # Determine the logical event type (domain event type)
        etype = event.event_type.value
        canonical = event.payload.get("_canonical") if event.payload else None
        if isinstance(canonical, dict):
            etype = str(canonical.get("event_type", etype))
        elif event.payload and "event_type" in event.payload:
            etype = str(event.payload.get("event_type"))

        # 1. Structured Log entry
        metadata = event.metadata or {}
        payload = event.payload or {}
        
        # Merge payload keys for logging context
        ctx = {**metadata, **payload}
        
        # Determine Severity
        sev = Severity.INFO
        if event.event_type.value.endswith("failed") or event.event_type.value.endswith("violated") or event.event_type.value.endswith("denied"):
            sev = Severity.ERROR
        elif event.event_type.value.endswith("started") or event.event_type.value.endswith("created"):
            sev = Severity.INFO
        else:
            sev = Severity.DEBUG

        def _safe_uuid(v: Any) -> Optional[uuid.UUID]:
            if not v:
                return None
            if isinstance(v, uuid.UUID):
                return v
            try:
                return uuid.UUID(str(v))
            except (ValueError, TypeError):
                return None

        # Log structure
        log_entry = self.logger.log(
            severity=sev,
            component=event.source or "unknown",
            message=f"Event {etype} occurred: {event.payload}",
            correlation_id=event.correlation_id,
            project_id=_safe_uuid(ctx.get("project_id")),
            workflow_id=_safe_uuid(ctx.get("workflow_id")),
            task_id=_safe_uuid(ctx.get("task_id")),
            execution_id=_safe_uuid(ctx.get("execution_id")),
            attempt_id=_safe_uuid(ctx.get("attempt_id")),
            worker_id=str(ctx.get("worker_id") or ""),
            model_id=str(ctx.get("model_id") or ""),
            provider_id=str(ctx.get("provider_id") or ""),
            deployment_id=str(ctx.get("deployment_id") or ""),
            node_id=str(ctx.get("node_id") or ""),
            artifact_id=_safe_uuid(ctx.get("artifact_id")),
            review_id=_safe_uuid(ctx.get("review_id")),
            approval_id=_safe_uuid(ctx.get("approval_id")),
            error_category=ctx.get("error_category"),
            retryable=ctx.get("retryable"),
            duration_ms=ctx.get("duration_ms"),
            metadata=ctx,
        )

        # 2. Trace Span correlation
        if event.correlation_id:
            span = self.traces.get_span_by_correlation(event.correlation_id)
            if not span:
                # Start new span for the correlation root
                span = self.traces.start_span(
                    name=f"trace-{event.event_category.value}",
                    trace_id=event.correlation_id,
                    correlation_id=event.correlation_id,
                    project_id=_safe_uuid(ctx.get("project_id")),
                    workflow_id=_safe_uuid(ctx.get("workflow_id")),
                    task_id=_safe_uuid(ctx.get("task_id")),
                    execution_id=_safe_uuid(ctx.get("execution_id")),
                )
            
            # Append log to span
            self.traces.add_log_to_span(span.span_id, log_entry)

            # End span if the lifecycle completed
            if event.event_type.value.endswith("completed") or event.event_type.value.endswith("finished"):
                self.traces.end_span(span.span_id, status="completed")
            elif event.event_type.value.endswith("failed"):
                self.traces.end_span(span.span_id, status="failed")

        # 3. Aggregated Metrics and Dashboard update based on Event Types
        self._dispatch_metrics_and_dashboards(event, ctx)

    def _dispatch_metrics_and_dashboards(self, event: Event, ctx: Dict[str, Any]) -> None:
        etype = event.event_type.value
        canonical = event.payload.get("_canonical") if event.payload else None
        if isinstance(canonical, dict):
            etype = str(canonical.get("event_type", etype))
        elif event.payload and "event_type" in event.payload:
            etype = str(event.payload.get("event_type"))

        # Workflow lifecycle
        if etype == "workflow.started":
            self.metrics.record_counter("workflow.started")
            self.dashboards.record_workflow_started()
        elif etype == "workflow.completed":
            self.metrics.record_counter("workflow.completed")
            self.dashboards.record_workflow_completed()
            if "duration_ms" in ctx:
                self.metrics.record_histogram("workflow.duration", ctx["duration_ms"] / 1000.0)
        elif etype == "workflow.failed":
            self.metrics.record_counter("workflow.failed")
            self.dashboards.record_workflow_failed()
        elif etype == "workflow.paused" or etype == "workflow.resumed":
            self.metrics.record_counter(etype)
        elif etype == "workflow.cancelled":
            self.metrics.record_counter("workflow.cancelled")
            self.dashboards.record_execution_cancelled()

        # Stage lifecycle
        elif etype == "stage.ready" or etype == "stage.started":
            self.metrics.record_counter("stage.started")
        elif etype == "stage.succeeded":
            self.metrics.record_counter("stage.succeeded")
        elif etype == "stage.failed":
            self.metrics.record_counter("stage.failed")
        elif etype == "stage.retrying":
            self.metrics.record_counter("stage.retrying")
        elif etype == "stage.waiting_approval":
            self.metrics.record_counter("stage.waiting_approval")
            worker_id = str(ctx.get("worker_id") or "")
            app_type = str(ctx.get("approval_type") or "general")
            self.dashboards.record_hitl_approval_requested(worker_id, app_type)
        elif etype == "stage.blocked":
            self.metrics.record_counter("stage.blocked")
        elif etype == "stage.skipped":
            self.metrics.record_counter("stage.skipped")
        elif etype == "stage.cancelled":
            self.metrics.record_counter("stage.cancelled")

        # Orchestration allocation / reasoning telemetry
        elif etype == "execution.created":
            self.metrics.record_counter("execution.created")
        elif etype == "worker.assigned":
            self.metrics.record_counter("worker.assigned")
        elif etype == "model.routed":
            self.metrics.record_counter("model.routed")
            node_id = str(ctx.get("node_id") or ctx.get("provider_id") or "")
            model_id = str(ctx.get("model_id") or "")
            if node_id and model_id:
                self.dashboards.record_node_model_active(node_id, model_id)
        elif etype == "inference.started":
            self.metrics.record_counter("inference.started")
        elif etype == "inference.completed":
            self.metrics.record_counter("inference.completed")
        elif etype == "evaluation.completed":
            self.metrics.record_counter("evaluation.completed")
            if "duration_ms" in ctx:
                self.metrics.record_histogram("evaluation.duration", ctx["duration_ms"] / 1000.0)
        elif etype == "diagnosis.completed":
            self.metrics.record_counter("diagnosis.completed")
        elif etype == "repair.started":
            self.metrics.record_counter("repair.started")
        elif etype == "repair.completed":
            self.metrics.record_counter("repair.completed")
        elif etype == "rectification.started":
            self.metrics.record_counter("rectification.started")
        elif etype == "rectification.completed":
            self.metrics.record_counter("rectification.completed")

        # Deployment telemetry
        elif etype == "deployment.started":
            self.metrics.record_counter("deployment.started")
        elif etype == "deployment.completed":
            self.metrics.record_counter("deployment.completed")
        elif etype == "deployment.unavailable":
            self.metrics.record_counter("deployment.unavailable")

        # Task lifecycle
        elif etype == "task.created":
            self.dashboards.record_task_created()
        elif etype == "task.queued":
            self.dashboards.record_task_queued()
        elif etype == "task.started":
            self.metrics.record_counter("task.started")
            self.dashboards.record_task_started()
        elif etype == "task.completed":
            self.metrics.record_counter("task.completed")
            self.dashboards.record_task_completed()
            if "duration_ms" in ctx:
                self.metrics.record_histogram("task.duration", ctx["duration_ms"] / 1000.0)
        elif etype == "task.failed":
            self.metrics.record_counter("task.failed")
            self.dashboards.record_task_failed()
        elif etype == "task.retrying":
            self.dashboards.record_task_retry()

        # Execution lifecycle
        elif etype == "execution.started":
            self.metrics.record_counter("execution.started")
            self.dashboards.record_execution_started()
            self.dashboards.record_execution_attempt()
        elif etype == "execution.completed":
            self.metrics.record_counter("execution.completed")
            self.dashboards.record_execution_completed()
            if "duration_ms" in ctx:
                self.metrics.record_histogram("execution.duration", ctx["duration_ms"] / 1000.0)
        elif etype == "execution.failed":
            self.metrics.record_counter("execution.failed")
            self.dashboards.record_execution_failed()
        elif etype == "execution.cancelled":
            self.dashboards.record_execution_cancelled()
        elif etype == "execution.timed_out":
            self.dashboards.record_execution_timeout()

        # Checkpoints & Recoveries
        elif etype == "checkpoint.restored":
            self.dashboards.record_execution_recovery()

        # Worker lifecycle
        elif etype == "worker.registered":
            worker_id = str(ctx.get("worker_id") or "")
            if worker_id:
                self.dashboards.register_worker(worker_id)
        elif etype == "worker.dispatched":
            worker_id = str(ctx.get("worker_id") or "")
            worker_type = str(ctx.get("worker_type") or "general")
            self.dashboards.record_worker_dispatch(worker_id, worker_type)
        elif etype == "worker.completed":
            worker_id = str(ctx.get("worker_id") or "")
            worker_type = str(ctx.get("worker_type") or "general")
            self.dashboards.record_worker_completed(worker_id, worker_type, success=True)
        elif etype == "worker.failed":
            worker_id = str(ctx.get("worker_id") or "")
            worker_type = str(ctx.get("worker_type") or "general")
            self.dashboards.record_worker_completed(worker_id, worker_type, success=False)
        elif etype == "loop.started":
            worker_id = str(ctx.get("worker_id") or "")
            self.dashboards.record_worker_loop_iteration(worker_id)
        elif etype == "recovery.started":
            worker_id = str(ctx.get("worker_id") or "")
            self.dashboards.record_worker_remediation(worker_id)

        # AI Infrastructure / Routing
        elif etype == "model.selected":
            self.metrics.record_counter("model.routing")
            req_caps = ctx.get("capabilities", [])
            selected = str(ctx.get("model_id") or "")
            rejected = ctx.get("rejected", {})
            self.dashboards.record_routing_decision(req_caps, selected, rejected)
            
            node_id = str(ctx.get("node_id") or ctx.get("provider_id") or "")
            if node_id and selected:
                self.dashboards.record_node_model_active(node_id, selected)

            # Record detailed routing decision record for fleet observability
            routing_rec = RoutingDecisionRecord(
                correlation_id=str(event.correlation_id or ""),
                task_id=str(ctx.get("task_id") or ""),
                worker_id=str(ctx.get("worker_id") or ""),
                worker_type=str(ctx.get("worker_type") or ""),
                required_capabilities=[str(c) for c in req_caps],
                min_context_window_tokens=int(ctx.get("min_context_window_tokens", 1024)),
                privacy_policy=str(ctx.get("privacy_policy") or "local_only"),
                candidate_scores=ctx.get("candidates", []),
                selected_node_id=node_id,
                selected_model_id=selected,
                selected_provider_id=str(ctx.get("provider_id") or node_id),
                outcome="success" if selected else "failed",
                failover_occurred=bool(ctx.get("failover_occurred", False)),
                notes=str(ctx.get("notes") or ""),
            )
            self.dashboards.record_routing_trail(routing_rec)

        # Model invocation completed (captured in connector/LLM call events)
        elif etype == "connector.executed":
            # Check if this connector action represents an LLM inference call
            if ctx.get("action") == "llm_inference" or "model_id" in ctx:
                model_id = str(ctx.get("model_id") or "")
                provider_id = str(ctx.get("provider_id") or "")
                node_id = str(ctx.get("node_id") or provider_id or "")
                success = ctx.get("success", True)
                
                # Token extraction (handling dict or int)
                tokens_raw = ctx.get("tokens") or ctx.get("total_tokens") or 0
                input_tokens = 0
                output_tokens = 0
                if isinstance(tokens_raw, dict):
                    t_val = tokens_raw.get("total_tokens", 0)
                    tokens = int(t_val) if isinstance(t_val, (int, float)) else 0
                    input_tokens = int(tokens_raw.get("prompt_eval_count") or tokens_raw.get("input_tokens") or 0)
                    output_tokens = int(tokens_raw.get("eval_count") or tokens_raw.get("output_tokens") or 0)
                elif isinstance(tokens_raw, (int, float)):
                    tokens = int(tokens_raw)
                    input_tokens = int(ctx.get("input_tokens", 0))
                    output_tokens = int(ctx.get("output_tokens", 0))
                else:
                    tokens = 0
                
                cost = float(ctx.get("cost", 0.0))
                latency_ms = float(ctx.get("duration_ms", 0.0))
                throughput_tps = float(ctx.get("throughput_tps") or ctx.get("tokens_per_second") or 0.0)
                retry_count = int(ctx.get("attempts", 1)) - 1 if int(ctx.get("attempts", 1)) > 1 else int(ctx.get("retries", 0))
                failover_count = int(ctx.get("failovers", 0))

                self.metrics.record_counter("model.calls")
                self.metrics.record_histogram("model.latency", latency_ms)
                
                # Update 13 standard read models + Dual-Level Node & Fleet read models
                self.dashboards.record_node_inference(
                    node_id=node_id,
                    model_id=model_id,
                    provider_id=provider_id,
                    success=success,
                    tokens=tokens,
                    cost=cost,
                    latency_ms=latency_ms,
                    input_tokens=input_tokens,
                    output_tokens=output_tokens,
                    throughput_tps=throughput_tps,
                    retry_count=retry_count,
                    failover_count=failover_count,
                    task_id=str(ctx.get("task_id") or ""),
                    worker_id=str(ctx.get("worker_id") or ""),
                    correlation_id=str(event.correlation_id or ""),
                )

        elif etype == "model.failed":
            self.metrics.record_counter("model.failed")
            self.dashboards.record_fallback()

        # Infrastructure / Service / Node Status
        elif etype == "service.healthy" or etype == "node.healthy":
            provider_id = str(ctx.get("provider_id") or ctx.get("node_id") or "")
            self.dashboards.set_provider_health(provider_id, online=True)
            self.dashboards.set_node_health(provider_id, NodeStatusEnum.HEALTHY)
        elif etype == "service.degraded" or etype == "node.degraded":
            provider_id = str(ctx.get("provider_id") or ctx.get("node_id") or "")
            self.dashboards.set_provider_health(provider_id, online=False)
            self.dashboards.set_node_health(provider_id, NodeStatusEnum.DEGRADED)
            self.dashboards.increment_system_errors(etype)
        elif etype == "service.failed" or etype == "node.offline":
            provider_id = str(ctx.get("provider_id") or ctx.get("node_id") or "")
            self.dashboards.set_provider_health(provider_id, online=False)
            self.dashboards.set_node_health(provider_id, NodeStatusEnum.OFFLINE)
            self.dashboards.increment_system_errors(etype)

        # Artifact lifecycle
        elif etype == "artifact.created":
            art_type = str(ctx.get("artifact_type") or "unknown")
            self.dashboards.record_artifact_created(art_type)
            self.dashboards.record_artifact_version()
        elif etype == "artifact.updated":
            self.dashboards.record_artifact_version()
        elif etype == "artifact.published":
            self.dashboards.record_artifact_published()
        elif etype == "artifact.rollback" or etype == "artifact.rolled_back":
            self.dashboards.record_artifact_rollback()
        elif etype == "artifact.integrity_failed":
            self.dashboards.record_artifact_integrity_failure()

        # Review lifecycle
        elif etype == "review.started":
            self.dashboards.record_review_started()
        elif etype == "review.completed":
            passed = ctx.get("passed", True)
            duration_ms = float(ctx.get("duration_ms", 0.0))
            self.dashboards.record_review_completed(passed, duration_ms)
        elif etype == "review.rejected" or etype == "review.changes_requested":
            self.dashboards.record_review_repair_loop()

        # Governance / HITL
        elif etype == "approval.required":
            worker_id = str(ctx.get("worker_id") or "")
            app_type = str(ctx.get("approval_type") or "general")
            self.dashboards.record_hitl_approval_requested(worker_id, app_type)
        elif etype == "approval.decided":
            self.dashboards.record_hitl_approval_decided()
        elif etype == "approval.timeout":
            self.dashboards.record_hitl_timeout()

        # Legacy Modernization telemetry
        elif etype == "legacy.system_analyzed" or etype == "archeology.started":
            self.dashboards.record_legacy_system_analyzed()
        elif etype == "evidence.discovered":
            epistemic_type = str(ctx.get("epistemic_type") or "FACT")
            self.dashboards.record_legacy_evidence(epistemic_type)
        elif etype == "analysis.gap_detected":
            self.dashboards.record_legacy_analysis_gap()
        elif etype == "unknown.technology_encountered":
            self.dashboards.record_legacy_unknown()
        elif etype == "business_rule.extracted":
            self.dashboards.record_legacy_business_rule()
        elif etype == "modernization.decision_made":
            self.dashboards.record_legacy_modernization_decision()
        elif etype == "migration.plan_created":
            self.dashboards.record_legacy_migration_plan()

        # Security Events
        elif etype == "security.denied" or etype == "security.policy_violated":
            self.dashboards.increment_security_violation()
