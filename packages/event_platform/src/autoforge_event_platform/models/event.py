"""
Canonical Event Model for the Event Platform.

Implements every specification-defined field from Section 8 of the
Event Platform Specification v1.0.

Events are immutable. No component may mutate an event after publication.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable

from pydantic import BaseModel, ConfigDict, Field, field_validator


# ---------------------------------------------------------------------------
# Enums (Section 8, 9, 15, 16)
# ---------------------------------------------------------------------------


class EventCategory(str, Enum):
    """Canonical event categories (Section 9.1)."""

    KERNEL = "kernel"
    RUNTIME = "runtime"
    WORKFLOW = "workflow"
    EXECUTION = "execution"
    REVIEW = "review"
    KNOWLEDGE = "knowledge"
    MEMORY = "memory"
    LEARNING = "learning"
    INFRASTRUCTURE = "infrastructure"
    CONNECTOR = "connector"
    SECURITY = "security"
    OBSERVABILITY = "observability"
    APPROVAL = "approval"
    ARTIFACT = "artifact"
    WORKER = "worker"
    TASK = "task"
    PROJECT = "project"
    CHECKPOINT = "checkpoint"
    RECOVERY = "recovery"


class EventType(str, Enum):
    """Canonical event types (Section 9.2)."""

    # Kernel events
    KERNEL_CREATED = "kernel.created"
    KERNEL_STARTING = "kernel.starting"
    KERNEL_STARTED = "kernel.started"
    KERNEL_PAUSING = "kernel.pausing"
    KERNEL_PAUSED = "kernel.paused"
    KERNEL_RESUMING = "kernel.resuming"
    KERNEL_READY = "kernel.ready"
    KERNEL_STOPPING = "kernel.stopping"
    KERNEL_STOPPED = "kernel.stopped"

    # Runtime events
    STATE_TRANSITIONED = "state.transitioned"
    STATE_CREATED = "state.created"
    STATE_UPDATED = "state.updated"
    STATE_DELETED = "state.deleted"
    STATE_RESTORED = "state.restored"

    # Workflow events
    WORKFLOW_CREATED = "workflow.created"
    WORKFLOW_STARTED = "workflow.started"
    WORKFLOW_COMPLETED = "workflow.completed"
    WORKFLOW_FAILED = "workflow.failed"
    WORKFLOW_PAUSED = "workflow.paused"
    WORKFLOW_RESUMED = "workflow.resumed"
    WORKFLOW_CANCELLED = "workflow.cancelled"

    # ── Stage / orchestration lifecycle events (Phase 18) ──────────────
    STAGE_READY = "stage.ready"
    STAGE_STARTED = "stage.started"
    STAGE_SUCCEEDED = "stage.succeeded"
    STAGE_FAILED = "stage.failed"
    STAGE_BLOCKED = "stage.blocked"
    STAGE_SKIPPED = "stage.skipped"
    STAGE_CANCELLED = "stage.cancelled"
    STAGE_RETRYING = "stage.retrying"
    STAGE_WAITING_APPROVAL = "stage.waiting_approval"
    EXECUTION_CREATED = "execution.created"
    WORKER_ASSIGNED = "worker.assigned"
    MODEL_ROUTED = "model.routed"
    INFERENCE_STARTED = "inference.started"
    INFERENCE_COMPLETED = "inference.completed"
    EVALUATION_COMPLETED = "evaluation.completed"
    DIAGNOSIS_COMPLETED = "diagnosis.completed"
    REPAIR_STARTED = "repair.started"
    REPAIR_COMPLETED = "repair.completed"
    RECTIFICATION_STARTED = "rectification.started"
    RECTIFICATION_COMPLETED = "rectification.completed"
    DEPLOYMENT_STARTED = "deployment.started"
    DEPLOYMENT_COMPLETED = "deployment.completed"
    DEPLOYMENT_UNAVAILABLE = "deployment.unavailable"

    # Execution events
    EXECUTION_STARTED = "execution.started"
    EXECUTION_COMPLETED = "execution.completed"
    EXECUTION_FAILED = "execution.failed"
    EXECUTION_PAUSED = "execution.paused"
    EXECUTION_RESUMED = "execution.resumed"
    EXECUTION_CANCELLED = "execution.cancelled"
    EXECUTION_TIMED_OUT = "execution.timed_out"

    # Review events
    REVIEW_STARTED = "review.started"
    REVIEW_COMPLETED = "review.completed"
    REVIEW_APPROVED = "review.approved"
    REVIEW_REJECTED = "review.rejected"
    REVIEW_CHANGES_REQUESTED = "review.changes_requested"
    REVIEW_ESCALATED = "review.escalated"

    # Knowledge events
    KNOWLEDGE_QUERIED = "knowledge.queried"
    KNOWLEDGE_RESEARCHED = "knowledge.researched"
    KNOWLEDGE_PROMOTED = "knowledge.promoted"
    KNOWLEDGE_UPDATED = "knowledge.updated"
    KNOWLEDGE_DELETED = "knowledge.deleted"

    # Memory events
    MEMORY_STORED = "memory.stored"
    MEMORY_UPDATED = "memory.updated"
    MEMORY_DELETED = "memory.deleted"
    MEMORY_RETRIEVED = "memory.retrieved"
    MEMORY_CONTEXT_LOADED = "memory.context_loaded"

    # Learning events
    LEARNING_ANALYZED = "learning.analyzed"
    LEARNING_VALIDATED = "learning.validated"
    LEARNING_PROMOTED = "learning.promoted"
    LEARNING_DISCARDED = "learning.discarded"

    # Infrastructure events
    SERVICE_STARTED = "service.started"
    SERVICE_STOPPED = "service.stopped"
    SERVICE_HEALTHY = "service.healthy"
    SERVICE_DEGRADED = "service.degraded"
    SERVICE_RECOVERED = "service.recovered"
    SERVICE_FAILED = "service.failed"

    # Connector events
    CONNECTOR_CONNECTED = "connector.connected"
    CONNECTOR_DISCONNECTED = "connector.disconnected"
    CONNECTOR_EXECUTED = "connector.executed"
    CONNECTOR_FAILED = "connector.failed"
    CONNECTOR_RETRYING = "connector.retrying"

    # Security events
    SECURITY_AUTHENTICATED = "security.authenticated"
    SECURITY_AUTHORIZED = "security.authorized"
    SECURITY_DENIED = "security.denied"
    SECURITY_POLICY_VIOLATED = "security.policy_violated"
    SECURITY_AUDIT = "security.audit"

    # Observability events
    OBSERVABILITY_METRIC = "observability.metric"
    OBSERVABILITY_LOG = "observability.log"
    OBSERVABILITY_TRACE = "observability.trace"
    OBSERVABILITY_SPAN = "observability.span"
    OBSERVABILITY_ALERT = "observability.alert"

    # Approval events
    APPROVAL_REQUIRED = "approval.required"
    APPROVAL_DECIDED = "approval.decided"
    APPROVAL_TIMEOUT = "approval.timeout"
    APPROVAL_ESCALATED = "approval.escalated"
    APPROVAL_CANCELLED = "approval.cancelled"

    # Artifact events
    ARTIFACT_CREATED = "artifact.created"
    ARTIFACT_UPDATED = "artifact.updated"
    ARTIFACT_DELETED = "artifact.deleted"
    ARTIFACT_PUBLISHED = "artifact.published"
    ARTIFACT_ARCHIVED = "artifact.archived"

    # Worker events
    WORKER_REGISTERED = "worker.registered"
    WORKER_DISPATCHED = "worker.dispatched"
    WORKER_STARTED = "worker.started"
    WORKER_COMPLETED = "worker.completed"
    WORKER_FAILED = "worker.failed"
    WORKER_RETIRED = "worker.retired"

    # Task events
    TASK_CREATED = "task.created"
    TASK_UPDATED = "task.updated"
    TASK_QUEUED = "task.queued"
    TASK_READY = "task.ready"
    TASK_STARTED = "task.started"
    TASK_PAUSED = "task.paused"
    TASK_RESUMED = "task.resumed"
    TASK_COMPLETED = "task.completed"
    TASK_FAILED = "task.failed"
    TASK_CANCELLED = "task.cancelled"
    TASK_BLOCKED = "task.blocked"
    TASK_DELETED = "task.deleted"
    TASK_DISPATCHED = "task.dispatched"
    TASK_RETRYING = "task.retrying"
    TASK_WAITING = "task.waiting"

    # Project events
    PROJECT_CREATED = "project.created"
    PROJECT_UPDATED = "project.updated"
    PROJECT_STARTED = "project.started"
    PROJECT_PLANNING = "project.planning"
    PROJECT_RUNNING = "project.running"
    PROJECT_REVIEWING = "project.reviewing"
    PROJECT_PAUSED = "project.paused"
    PROJECT_RESUMED = "project.resumed"
    PROJECT_COMPLETING = "project.completing"
    PROJECT_FINISHED = "project.finished"
    PROJECT_FAILED = "project.failed"
    PROJECT_CANCELLED = "project.cancelled"
    PROJECT_ARCHIVED = "project.archived"
    PROJECT_DELETED = "project.deleted"

    # Checkpoint events
    CHECKPOINT_CREATED = "checkpoint.created"
    CHECKPOINT_RESTORED = "checkpoint.restored"
    CHECKPOINT_DELETED = "checkpoint.deleted"
    CHECKPOINT_ARCHIVED = "checkpoint.archived"

    # Recovery events
    FAILURE_DETECTED = "failure.detected"
    RECOVERY_STARTED = "recovery.started"
    RECOVERY_COMPLETED = "recovery.completed"
    RECOVERY_FAILED = "recovery.failed"
    RECOVERY_ABORTED = "recovery.aborted"

    # Loop events
    LOOP_STARTED = "loop.started"
    LOOP_PLANNING = "loop.planning"
    LOOP_EXECUTING = "loop.executing"
    LOOP_REVIEWING = "loop.reviewing"
    LOOP_COMPLETED = "loop.completed"
    LOOP_REMEDIATING = "loop.remediating"
    LOOP_ESCALATED = "loop.escalated"
    LOOP_FAILED = "loop.failed"

    # Plan events
    PLAN_CREATED = "plan.created"
    PLAN_UPDATED = "plan.updated"
    RESEARCH_COMPLETED = "research.completed"

    # Intent events
    INTENT_ANALYZED = "intent.analyzed"

    # Model events
    MODEL_SELECTED = "model.selected"
    MODEL_FAILED = "model.failed"
    MODEL_SWITCHED = "model.switched"

    # Event Platform lifecycle events (Section 11.3)
    EVENT_CREATED = "event.created"
    EVENT_VALIDATED = "event.validated"
    EVENT_ENRICHED = "event.enriched"
    EVENT_PERSISTED = "event.persisted"
    EVENT_ROUTED = "event.routed"
    EVENT_DELIVERED = "event.delivered"
    EVENT_DELIVERY_FAILED = "event.delivery_failed"
    EVENT_DEAD_LETTERED = "event.dead_lettered"
    EVENT_ARCHIVED = "event.archived"
    SCHEMA_REGISTERED = "schema.registered"
    SCHEMA_UPDATED = "schema.updated"
    SUBSCRIPTION_CREATED = "subscription.created"
    SUBSCRIPTION_DELETED = "subscription.deleted"
    REPLAY_STARTED = "replay.started"
    REPLAY_COMPLETED = "replay.completed"
    REPLAY_FAILED = "replay.failed"
    ORDERING_VIOLATION = "ordering.violation"


class Priority(str, Enum):
    """Event priority levels (Section 8.2 — priority)."""

    LOW = "low"
    NORMAL = "normal"
    HIGH = "high"
    CRITICAL = "critical"


class DeliveryMode(str, Enum):
    """Delivery guarantee modes (Section 8.2 — deliveryMode, Section 15.1)."""

    AT_MOST_ONCE = "at-most-once"
    AT_LEAST_ONCE = "at-least-once"
    EXACTLY_ONCE = "exactly-once"


class OrderingGuarantee(str, Enum):
    """Ordering guarantees (Section 16.1)."""

    NONE = "none"
    PER_AGGREGATE = "per-aggregate"
    PER_STREAM = "per-stream"
    GLOBAL = "global"


class PublicationStatus(str, Enum):
    """Publication status (Section 6.1)."""

    ACCEPTED = "accepted"
    REJECTED = "rejected"
    FAILED = "failed"


class SubscriptionStatus(str, Enum):
    """Subscription status (Section 6.2)."""

    ACTIVE = "active"
    PENDING = "pending"
    FAILED = "failed"
    DELETED = "deleted"


class ReplayStatus(str, Enum):
    """Replay status (Section 6.4)."""

    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class DeliveryStatus(str, Enum):
    """Delivery status for a single subscriber delivery attempt."""

    DELIVERED = "delivered"
    FAILED = "failed"
    SKIPPED = "skipped"
    PENDING = "pending"
    RETRYING = "retrying"
    DEAD_LETTERED = "dead_lettered"


class EventLifecycleState(str, Enum):
    """Event lifecycle states (Section 11.2, 30.1)."""

    CREATED = "created"
    VALIDATING = "validating"
    REJECTED = "rejected"
    ENRICHING = "enriching"
    PERSISTING = "persisting"
    PERSISTED = "persisted"
    ROUTING = "routing"
    DELIVERING = "delivering"
    DELIVERED = "delivered"
    FAILED = "failed"
    ARCHIVED = "archived"


class ReplaySource(str, Enum):
    """Replay source types (Section 17.1)."""

    FROM_TIMESTAMP = "from_timestamp"
    FROM_EVENT_ID = "from_event_id"
    FROM_CHECKPOINT = "from_checkpoint"
    FROM_BEGINNING = "from_beginning"


# ---------------------------------------------------------------------------
# Type aliases
# ---------------------------------------------------------------------------

SubscriptionId = str
"""Unique subscription identifier."""


# ---------------------------------------------------------------------------
# Canonical Event (Section 8.1)
# ---------------------------------------------------------------------------


def _utc_now() -> datetime:
    """Return current UTC datetime."""
    return datetime.now(timezone.utc)


def _new_uuid() -> uuid.UUID:
    """Return a new UUID v4."""
    return uuid.uuid4()


class Event(BaseModel):
    """
    Canonical event model (Section 8.1).

    Every event in the platform conforms to this structure.
    Events are **immutable** — once published, they can never be modified or deleted.
    """

    model_config = ConfigDict(
        extra="forbid",
        populate_by_name=True,
        frozen=True,
        use_enum_values=False,
    )

    # --- Core identity (Section 8.1) ---
    event_id: uuid.UUID = Field(
        default_factory=_new_uuid,
        description="Unique event identifier (UUID v4). Generated by Event Platform.",
    )
    event_type: EventType = Field(
        ...,
        description="Specific event type (e.g. project.created, task.completed).",
    )
    event_category: EventCategory = Field(
        ...,
        description="High-level event category (e.g. project, task, execution).",
    )

    # --- Source ---
    source: str = Field(
        ...,
        max_length=256,
        description="Component that emitted the event.",
    )

    # --- Temporal ---
    timestamp: datetime = Field(
        default_factory=_utc_now,
        description="When the event occurred (ISO 8601). Generated by Event Platform.",
    )

    # --- Versioning ---
    version: str = Field(
        default="1.0.0",
        description="Event schema version (semantic version). Generated by Schema Registry.",
    )

    # --- Correlation / Causation ---
    correlation_id: uuid.UUID = Field(
        default_factory=_new_uuid,
        description="Correlation ID for grouping related events.",
    )
    causation_id: uuid.UUID | None = Field(
        default=None,
        description="Causation ID — event ID of the event that caused this event.",
    )

    # --- Aggregate ---
    aggregate_id: uuid.UUID = Field(
        default_factory=_new_uuid,
        description="Aggregate root identifier.",
    )
    aggregate_type: str = Field(
        ...,
        max_length=64,
        description="Aggregate root type (e.g. Project, Task, Workflow).",
    )

    # --- Payload / Metadata ---
    payload: dict[str, Any] = Field(
        default_factory=dict,
        description="Event-specific data (JSON).",
    )
    metadata: dict[str, Any] = Field(
        default_factory=dict,
        description="Extensible metadata key-value store.",
    )

    # --- Priority / Delivery ---
    priority: Priority = Field(
        default=Priority.NORMAL,
        description="Event priority (low, normal, high, critical).",
    )
    delivery_mode: DeliveryMode = Field(
        default=DeliveryMode.AT_LEAST_ONCE,
        description="Delivery guarantee (at-most-once, at-least-once, exactly-once).",
    )

    # --- Sequence number (Section 16.2) ---
    sequence_number: int | None = Field(
        default=None,
        description="Sequence number for ordering (per-aggregate, per-stream, or global).",
    )

    # ------------------------------------------------------------------
    # Validators
    # ------------------------------------------------------------------

    @field_validator("timestamp")
    @classmethod
    def _ensure_utc(cls, v: datetime) -> datetime:
        """Ensure timestamp is timezone-aware UTC."""
        if v.tzinfo is None:
            return v.replace(tzinfo=timezone.utc)
        return v

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def to_dict(self) -> dict[str, Any]:
        """Serialize to a plain dictionary."""
        return self.model_dump(mode="python")

    def to_json(self, **kwargs: Any) -> str:
        """Serialize to a JSON string."""
        return self.model_dump_json(**kwargs)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> Event:
        """Deserialize from a plain dictionary."""
        return cls.model_validate(data)


# ---------------------------------------------------------------------------
# Event Schema (Section 10)
# ---------------------------------------------------------------------------


class SchemaCompatibility(BaseModel):
    """Schema compatibility rules (Section 10.2 — compatibility)."""

    model_config = ConfigDict(frozen=True)

    backward: str = Field(
        ...,
        description="Minimum backward-compatible version.",
    )
    forward: str = Field(
        ...,
        description="Minimum forward-compatible version.",
    )


class EventSchema(BaseModel):
    """Event schema definition (Section 10.1)."""

    model_config = ConfigDict(frozen=True)

    schema_id: str = Field(
        ...,
        description="Unique schema identifier (format: {eventType}.v{version}).",
    )
    version: str = Field(
        ...,
        description="Schema version (semantic version: major.minor.patch).",
    )
    description: str = Field(
        default="",
        description="Human-readable description of the event.",
    )
    category: EventCategory = Field(
        ...,
        description="Event category.",
    )
    event_type: EventType = Field(
        ...,
        description="Specific event type.",
    )
    payload_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for event payload.",
    )
    metadata_schema: dict[str, Any] = Field(
        default_factory=dict,
        description="JSON Schema for event metadata.",
    )
    compatibility: SchemaCompatibility = Field(
        default_factory=lambda: SchemaCompatibility(backward="1.0.0", forward="1.0.0"),
        description="Schema compatibility rules.",
    )


# ---------------------------------------------------------------------------
# Validation (Section 22)
# ---------------------------------------------------------------------------


class ValidationError(BaseModel):
    """A single validation error (Section 22.2)."""

    model_config = ConfigDict(frozen=True)

    field: str = Field(..., description="The field that failed validation.")
    error: str = Field(..., description="Error code.")
    message: str = Field(..., description="Human-readable error message.")


class ValidationResult(BaseModel):
    """Result of event validation (Section 22)."""

    model_config = ConfigDict(frozen=True)

    valid: bool = Field(..., description="Whether the event is valid.")
    errors: list[ValidationError] = Field(
        default_factory=list,
        description="List of validation errors if invalid.",
    )


# ---------------------------------------------------------------------------
# Publication Result (Section 6.1)
# ---------------------------------------------------------------------------


class PublicationResult(BaseModel):
    """Result of event publication (Section 6.1)."""

    model_config = ConfigDict(frozen=True)

    event_id: uuid.UUID = Field(..., description="Unique identifier for the published event.")
    status: PublicationStatus = Field(..., description="Publication status.")
    timestamp: datetime = Field(default_factory=_utc_now, description="When the event was published.")
    errors: list[ValidationError] = Field(
        default_factory=list,
        description="Validation errors if rejected.",
    )
    warnings: list[str] = Field(
        default_factory=list,
        description="Warnings (e.g. persistence deferred).",
    )


# ---------------------------------------------------------------------------
# Subscription (Section 6.2, 14)
# ---------------------------------------------------------------------------


class SubscriptionRequest(BaseModel):
    """Subscription request specification (Section 6.2)."""

    model_config = ConfigDict(frozen=True)

    event_types: list[EventType] | None = Field(
        default=None,
        description="List of event types to subscribe to.",
    )
    event_categories: list[EventCategory] | None = Field(
        default=None,
        description="List of event categories to subscribe to.",
    )
    filter: str | None = Field(
        default=None,
        description="Optional filter expression.",
    )
    delivery_mode: DeliveryMode = Field(
        default=DeliveryMode.AT_LEAST_ONCE,
        description="Required delivery guarantee.",
    )
    ordering_guarantee: OrderingGuarantee = Field(
        default=OrderingGuarantee.NONE,
        description="Required ordering guarantee.",
    )
    callback: Callable[[Event], None] | None = Field(
        default=None,
        description="Subscriber callback handler.",
        exclude=True,
    )

    def validate_request(self) -> list[ValidationError]:
        """Validate the subscription request (Section 14.2 Step 2)."""
        errors: list[ValidationError] = []

        # At least one event type or category specified
        if not self.event_types and not self.event_categories:
            errors.append(
                ValidationError(
                    field="event_types",
                    error="required_field_missing",
                    message="At least one event type or category must be specified.",
                )
            )

        # Callback is required
        if self.callback is None:
            errors.append(
                ValidationError(
                    field="callback",
                    error="required_field_missing",
                    message="Subscriber callback is required.",
                )
            )

        return errors


class Subscription(BaseModel):
    """A registered subscription (Section 14)."""

    model_config = ConfigDict(frozen=True)

    subscription_id: SubscriptionId = Field(..., description="Unique subscription identifier.")
    event_types: list[EventType] | None = Field(
        default=None,
        description="Event types subscribed to.",
    )
    event_categories: list[EventCategory] | None = Field(
        default=None,
        description="Event categories subscribed to.",
    )
    filter: str | None = Field(
        default=None,
        description="Filter expression.",
    )
    delivery_mode: DeliveryMode = Field(
        default=DeliveryMode.AT_LEAST_ONCE,
        description="Delivery guarantee.",
    )
    ordering_guarantee: OrderingGuarantee = Field(
        default=OrderingGuarantee.NONE,
        description="Ordering guarantee.",
    )
    status: SubscriptionStatus = Field(
        default=SubscriptionStatus.ACTIVE,
        description="Subscription status.",
    )
    created_at: datetime = Field(
        default_factory=_utc_now,
        description="When the subscription was created.",
    )
    callback: Callable[[Event], None] | None = Field(
        default=None,
        description="Subscriber callback handler.",
        exclude=True,
    )


# ---------------------------------------------------------------------------
# Event Query (Section 6.3, 19)
# ---------------------------------------------------------------------------


class EventQuery(BaseModel):
    """Query specification for historical events (Section 6.3)."""

    model_config = ConfigDict(frozen=True)

    event_types: list[EventType] | None = Field(default=None, description="Filter by event types.")
    event_categories: list[EventCategory] | None = Field(
        default=None, description="Filter by event categories."
    )
    project_id: uuid.UUID | None = Field(default=None, description="Filter by project ID.")
    correlation_id: uuid.UUID | None = Field(default=None, description="Filter by correlation ID.")
    source: str | None = Field(default=None, description="Filter by source.")
    time_range: tuple[datetime, datetime] | None = Field(
        default=None, description="Filter by time range."
    )
    limit: int = Field(default=100, ge=1, description="Maximum results to return.")
    offset: int = Field(default=0, ge=0, description="Pagination offset.")
    order_by: str = Field(default="timestamp", description="Sort order.")


class EventQueryResult(BaseModel):
    """Result of an event query (Section 6.3)."""

    model_config = ConfigDict(frozen=True)

    events: list[Event] = Field(default_factory=list, description="List of matching events.")
    total_count: int = Field(default=0, description="Total number of matching events.")
    has_more: bool = Field(default=False, description="Whether more results are available.")


# ---------------------------------------------------------------------------
# Replay (Section 6.4, 17)
# ---------------------------------------------------------------------------


class ReplayRequest(BaseModel):
    """Replay specification (Section 6.4)."""

    model_config = ConfigDict(frozen=True)

    source: ReplaySource = Field(..., description="Replay source.")
    from_timestamp: datetime | None = Field(default=None, description="Start timestamp for replay.")
    from_event_id: uuid.UUID | None = Field(default=None, description="Start event ID for replay.")
    from_checkpoint: str | None = Field(default=None, description="Start checkpoint for replay.")
    event_types: list[EventType] | None = Field(default=None, description="Filter by event types.")
    event_categories: list[EventCategory] | None = Field(
        default=None, description="Filter by event categories."
    )
    project_id: uuid.UUID | None = Field(default=None, description="Filter by project ID.")
    correlation_id: uuid.UUID | None = Field(default=None, description="Filter by correlation ID.")
    speed: float = Field(default=1.0, description="Replay speed multiplier (1x, 2x, 4x, etc.).")
    subscriber: Callable[[Event], None] | None = Field(
        default=None,
        description="Subscriber to receive replayed events.",
        exclude=True,
    )
    stop_on_error: bool = Field(default=False, description="Whether to stop on error.")


class ReplayResult(BaseModel):
    """Result of a replay request (Section 6.4)."""

    model_config = ConfigDict(frozen=True)

    replay_id: str = Field(..., description="Unique replay identifier.")
    status: ReplayStatus = Field(..., description="Replay status.")
    progress: tuple[int, int] = Field(
        default=(0, 0),
        description="Replay progress (events replayed, total events).",
    )
    error: str | None = Field(default=None, description="Error message if failed.")


# ---------------------------------------------------------------------------
# Dead Letter Queue (Section 6.5, 23)
# ---------------------------------------------------------------------------


class DeadLetterEntry(BaseModel):
    """A dead letter entry (Section 23.2)."""

    model_config = ConfigDict(frozen=True)

    dead_letter_id: str = Field(..., description="Unique dead letter identifier.")
    event: Event = Field(..., description="The event that failed delivery.")
    subscriber_id: SubscriptionId | None = Field(
        default=None, description="Subscriber that failed."
    )
    error_message: str = Field(..., description="Error message.")
    retry_count: int = Field(default=0, description="Number of retries attempted.")
    failure_timestamp: datetime = Field(
        default_factory=_utc_now,
        description="When the failure occurred.",
    )
    failure_reason: str = Field(..., description="Failure reason category.")


class DeadLetterQuery(BaseModel):
    """Query for dead letter events (Section 23.2)."""

    model_config = ConfigDict(frozen=True)

    subscriber_id: SubscriptionId | None = Field(default=None, description="Filter by subscriber.")
    event_type: EventType | None = Field(default=None, description="Filter by event type.")
    failure_reason: str | None = Field(default=None, description="Filter by failure reason.")
    time_range: tuple[datetime, datetime] | None = Field(
        default=None, description="Filter by time range."
    )
    limit: int = Field(default=100, ge=1, description="Maximum results.")
    offset: int = Field(default=0, ge=0, description="Pagination offset.")


class DeadLetterResult(BaseModel):
    """Result of a dead letter query (Section 23.2)."""

    model_config = ConfigDict(frozen=True)

    entries: list[DeadLetterEntry] = Field(
        default_factory=list, description="Dead letter entries."
    )
    total_count: int = Field(default=0, description="Total count of matching entries.")
    has_more: bool = Field(default=False, description="Whether more results are available.")


class DeadLetterAnalysis(BaseModel):
    """Analysis of dead letter patterns (Section 23.3 — analyze)."""

    model_config = ConfigDict(frozen=True)

    total_entries: int = Field(default=0, description="Total dead letter entries.")
    failure_reasons: dict[str, int] = Field(
        default_factory=dict, description="Failure reason counts."
    )
    subscriber_failure_rates: dict[str, float] = Field(
        default_factory=dict, description="Subscriber failure rates."
    )
    event_type_failure_rates: dict[str, float] = Field(
        default_factory=dict, description="Event type failure rates."
    )
    recommendations: list[str] = Field(
        default_factory=list, description="Remediation recommendations."
    )


# ---------------------------------------------------------------------------
# Delivery Result (Section 15)
# ---------------------------------------------------------------------------


class DeliveryResult(BaseModel):
    """Result of a delivery attempt to a subscriber (Section 15)."""

    model_config = ConfigDict(frozen=True)

    subscription_id: SubscriptionId = Field(..., description="Subscription that was delivered to.")
    event_id: uuid.UUID = Field(..., description="Event that was delivered.")
    status: DeliveryStatus = Field(..., description="Delivery status.")
    retry_count: int = Field(default=0, description="Number of retries.")
    error: str | None = Field(default=None, description="Error message if failed.")
    timestamp: datetime = Field(
        default_factory=_utc_now, description="When the delivery attempt occurred."
    )
