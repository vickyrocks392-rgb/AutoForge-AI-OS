"""Tests for the Execution Continuity Manager.

Covers retry, retry exhaustion, failover, failover exhaustion, context
preservation, checkpoint recovery, provider switching, and canonical-event
publication. All provider behaviour is driven by deterministic test doubles
behind the real :class:`ModelExecutor` protocol.
"""

from __future__ import annotations

import uuid

import pytest

import autoforge_ai_infrastructure as ai
from autoforge_ai_infrastructure import (
    ExecutionContinuityService,
    ExecutorRegistry,
    RetryPolicy,
    RoutingRequest,
)
from autoforge_ai_infrastructure.errors import (
    FailoverExhaustedError,
    ProviderUnavailableError,
)
from autoforge_ai_infrastructure.events import AIInfrastructureEvents
from autoforge_ai_infrastructure.router import ModelRouterService
from tests.helpers import (
    AlwaysFailExecutor,
    FakeExecutor,
    RecordingEventSink,
    noop_sleeper,
)


def _service(
    registry,
    executors: list[tuple[str, object]],
    *,
    retry_policy: RetryPolicy | None = None,
    sink: RecordingEventSink | None = None,
) -> ExecutionContinuityService:
    er = ExecutorRegistry()
    for provider_id, executor in executors:
        er.bind(provider_id, executor)
    router = ModelRouterService(registry)
    events = AIInfrastructureEvents(sink=sink) if sink is not None else None
    return ExecutionContinuityService(
        router,
        er,
        retry_policy=retry_policy or RetryPolicy(max_attempts=2),
        events=events,
        sleeper=noop_sleeper,
    )


def _code_req() -> RoutingRequest:
    return RoutingRequest(required_capabilities=frozenset({"code_generation"}))


# ── success / retry ────────────────────────────────────────────────────────


async def test_successful_execution(registry):
    svc = _service(
        registry,
        [("reference-local", FakeExecutor()), ("reference-cloud", FakeExecutor())],
    )
    result = await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    assert result.model_id == "reference-local-mini-q4"
    assert result.provider_id == "reference-local"
    assert result.attempts == 1
    assert result.failovers == 0
    assert result.output["text"] == "output from reference-local-mini-q4"


async def test_retry_then_success(registry):
    # Local fails once, succeeds on retry; no failover.
    local = FakeExecutor(fail_then_succeed=1)
    svc = _service(
        registry, [("reference-local", local), ("reference-cloud", FakeExecutor())]
    )
    result = await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    assert result.model_id == "reference-local-mini-q4"
    assert result.attempts == 2
    assert result.failovers == 0
    assert [c[1].model_id for c in local.calls] == [
        "reference-local-mini-q4",
        "reference-local-mini-q4",
    ]


async def test_retry_exhaustion_triggers_failover(registry):
    # local fails every attempt; cloud succeeds → failover success.
    svc = _service(
        registry,
        [
            ("reference-local", AlwaysFailExecutor()),
            ("reference-cloud", FakeExecutor()),
        ],
        retry_policy=RetryPolicy(max_attempts=3),
    )
    result = await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    assert result.model_id == "reference-cloud-large-v2"
    assert result.provider_id == "reference-cloud"
    assert result.failovers == 1
    assert result.attempts == 4  # 3 local + 1 cloud


# ── failover / exhaustion ──────────────────────────────────────────────────


async def test_failover_success_records_provider_switch(registry, event_sink):
    svc = _service(
        registry,
        [
            ("reference-local", AlwaysFailExecutor()),
            ("reference-cloud", FakeExecutor()),
        ],
        retry_policy=RetryPolicy(max_attempts=1),
        sink=event_sink,
    )
    result = await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    assert result.provider_id == "reference-cloud"
    assert result.failovers == 1
    # A canonical failure + recovery event was published.
    assert any(e.event_type.value == "failure.detected" for e in event_sink.events)
    assert any(e.event_type.value == "service.degraded" for e in event_sink.events)


async def test_failover_exhaustion_raises(registry, event_sink):
    svc = _service(
        registry,
        [
            ("reference-local", AlwaysFailExecutor()),
            ("reference-cloud", AlwaysFailExecutor()),
        ],
        retry_policy=RetryPolicy(max_attempts=2),
        sink=event_sink,
    )
    with pytest.raises(FailoverExhaustedError) as exc_info:
        await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    assert exc_info.value.history  # full attempt history attached
    assert any(e.event_type.value == "recovery.failed" for e in event_sink.events)


# ── context preservation / resume ──────────────────────────────────────────


async def test_context_preservation_across_failover(registry):
    svc = _service(
        registry,
        [
            ("reference-local", AlwaysFailExecutor()),
            ("reference-cloud", FakeExecutor()),
        ],
        retry_policy=RetryPolicy(max_attempts=1),
    )
    result = await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    context = svc.get_preserved_context(result.execution_id)
    assert context is not None
    assert context.routing_request.required_capabilities == frozenset(
        {"code_generation"}
    )
    assert context.next_candidate_index >= 1
    assert len(context.history) >= 2


async def test_resume_from_preserved_context(registry):
    svc = _service(
        registry,
        [
            ("reference-local", AlwaysFailExecutor()),
            ("reference-cloud", FakeExecutor()),
        ],
        retry_policy=RetryPolicy(max_attempts=1),
    )
    result = await svc.execute(payload={"prompt": "hi"}, routing_request=_code_req())
    resumed = await svc.resume(result.execution_id)
    assert resumed.execution_id == result.execution_id


# ── checkpoint recovery (Runtime boundary) ─────────────────────────────────


def test_checkpoint_recovery_uses_runtime_boundary(registry):
    restored = []

    class FakeCheckpoints:
        def get_checkpoint_history(self, project_id):
            cp = type("CP", (), {"checkpoint_id": uuid.uuid4()})()
            return [cp]

        def restore_checkpoint(self, checkpoint_id, restore_type):
            restored.append((checkpoint_id, restore_type))
            return {"ok": True}

    svc = _service(registry, [("local", FakeExecutor())])
    svc._checkpoints = FakeCheckpoints()
    outcome = svc.recover_from_checkpoint(uuid.uuid4())
    assert outcome["restored"] is True
    assert restored  # delegated to the runtime boundary
    assert outcome["checkpoint_id"]


def test_checkpoint_recovery_failure(registry):
    svc = _service(registry, [("local", FakeExecutor())])
    # No runtime checkpoint port configured → actionable error.
    with pytest.raises(ai.CheckpointRecoveryError):
        svc.recover_from_checkpoint(uuid.uuid4())


# ── classification ─────────────────────────────────────────────────────────


async def test_provider_unavailable_classified_retryable(registry):
    svc = _service(registry, [("local", FakeExecutor())])
    classification = svc.classifier.classify(
        ProviderUnavailableError("down", details={})
    )
    assert classification.value == "retryable"


async def test_unsupported_capability_classified_non_retryable(registry):
    svc = _service(registry, [("local", FakeExecutor())])
    classification = svc.classifier.classify(
        ai.UnsupportedCapabilityError("no capability", details={})
    )
    assert classification.value == "non_retryable"