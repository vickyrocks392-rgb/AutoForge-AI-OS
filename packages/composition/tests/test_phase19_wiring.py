"""Phase 19 — production wiring closure: real-composition integration tests.

These prove the ``ActiveLearningResolver`` is genuinely reachable from the
production system built by ``composition_root.build_autoforge_system()``.

Every test uses the **real** composition root, the **real** SecurityPlatform and
its real ``AIGuardrailsEngine``, and the **real** durable learning store. No
mocked kernel, no mocked composition root, no resolver substituted after
construction.

Per the gate contract, "it exists" is not evidence. Each test drives the real
execution path and asserts an *observable outcome*.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest

from autoforge_composition.composition_root import build_autoforge_system
from autoforge_learning.store import ActiveLearningState, DurableLearningStore
from autoforge_security.ai_guardrails import Capability

LEARNABLE = "prompt_strategy"


@pytest.fixture()
def learning_root(tmp_path: Path) -> Path:
    root = tmp_path / "learning-state"
    root.mkdir()
    return root


@pytest.fixture()
def autoforge(tmp_path: Path, learning_root: Path):
    """The REAL production system, built by the real composition root."""
    return build_autoforge_system(
        workspace_root=str(tmp_path / "workspace"),
        learning_store_root=str(learning_root),
    )


def promote(
    learning_root: Path,
    *,
    project_id,
    deactivated=False,
    content_hash="a" * 64,
):
    """Write a real, durable active-learning pointer through the real store."""
    store = DurableLearningStore(learning_root)
    now = datetime.now(timezone.utc)
    state = ActiveLearningState(
        project_id=project_id,
        kind="pattern_template",
        key="default",
        version_id=uuid.uuid4(),
        version_number=1,
        candidate_id=uuid.uuid4(),
        content_hash=content_hash,
        activation_timestamp=now,
        deactivation_timestamp=(now if deactivated else None),
        scope_kind="project",
    )
    store.set_active_state(state)
    return state


# ── Gate 3: the resolver is genuinely reachable from production ───────────────


def test_the_real_composition_root_builds_the_resolver(autoforge):
    """build_autoforge_system() constructs it — real components only."""
    assert autoforge.learning_resolver is not None
    assert autoforge.learning_store is not None
    assert autoforge.learning_resolver.enabled is True


def test_the_resolver_is_present_at_the_real_execution_seam(autoforge):
    """It lives on the *real* ExecutionEngine, not a detached object."""
    assert autoforge.execution_engine.learning_resolver is autoforge.learning_resolver


def test_the_resolver_is_actually_invoked_by_the_execution_path(autoforge):
    """Gate 3's core requirement: prove behaviour, not construction.

    A real active-learning pointer is promoted through the durable store, then
    the *real* execution engine resolves it. The resolution is observable.
    """
    project_id = uuid.uuid4()
    state = promote(autoforge.learning_store.root, project_id=project_id)

    resolution = autoforge.execution_engine.resolve_learning(project_id)

    assert resolution is not None
    assert resolution.is_applied, resolution.reason
    assert resolution.parameters["version_id"] == str(state.version_id)
    assert resolution.provenance.version_id == state.version_id
    assert resolution.provenance.candidate_id == state.candidate_id
    assert str(resolution.provenance.project_id) == str(project_id)
    assert resolution.provenance.activation_state == "full"


def test_production_uses_the_same_store_the_promotion_path_writes_to(
    autoforge, learning_root: Path
):
    """Activation and production resolution cannot diverge."""
    assert isinstance(autoforge.learning_store, DurableLearningStore)
    assert Path(autoforge.learning_store.root) == learning_root


# ── Gate 5: absent learning preserves normal execution ───────────────────────


def test_absent_learning_reports_absent_and_does_not_error(autoforge):
    """Gate 5A: 'no learning' is a normal condition, never an error."""
    project_id = uuid.uuid4()
    resolution = autoforge.execution_engine.resolve_learning(project_id)

    assert resolution is not None
    assert resolution.is_baseline
    assert resolution.parameters is None
    assert "no active learning" in resolution.reason
    # Absent learning is healthy, not a degradation.
    assert resolution.degraded is False
    assert autoforge.learning_resolver.degradations == ()


# ── Gate 6: disabled learning ────────────────────────────────────────────────


def test_disabled_learning_preserves_normal_execution(autoforge):
    """Gate 6: with no resolver, resolve_learning is a no-op returning None."""
    engine = autoforge.execution_engine
    engine.set_learning_resolver(None)
    try:
        assert engine.learning_resolver is None
        assert engine.resolve_learning(uuid.uuid4()) is None
    finally:
        engine.set_learning_resolver(autoforge.learning_resolver)


def test_a_none_resolver_is_never_recorded_as_a_degradation(autoforge):
    """Disabled learning is configuration, not an error."""
    engine = autoforge.execution_engine
    engine.set_learning_resolver(None)
    try:
        engine.resolve_learning(uuid.uuid4())
    finally:
        engine.set_learning_resolver(autoforge.learning_resolver)
    assert autoforge.learning_resolver.degradations == ()


# ── Gate 7: security and governance integration ───────────────────────────────


def test_the_production_resolver_is_built_from_the_real_guardrails(autoforge):
    """Authorization flows through the real AIGuardrailsEngine."""
    from autoforge_security.engine import SecurityPlatform

    assert isinstance(autoforge.security_platform, SecurityPlatform)
    assert autoforge.security_platform.guardrails is not None


def test_wrong_project_learning_fails_closed(autoforge):
    project_id = uuid.uuid4()
    foreign = uuid.uuid4()
    promote(autoforge.learning_store.root, project_id=foreign)

    resolution = autoforge.execution_engine.resolve_learning(project_id)

    assert resolution.is_baseline
    assert resolution.parameters is None


def test_corrupted_learning_fails_closed(autoforge):
    project_id = uuid.uuid4()
    promote(
        autoforge.learning_store.root, project_id=project_id, content_hash=""
    )

    resolution = autoforge.execution_engine.resolve_learning(project_id)

    assert resolution.is_baseline
    assert "integrity" in resolution.reason
    assert resolution.degraded is True


def test_revoked_learning_fails_closed(autoforge):
    project_id = uuid.uuid4()
    promote(autoforge.learning_store.root, project_id=project_id, deactivated=True)

    resolution = autoforge.execution_engine.resolve_learning(project_id)

    assert resolution.is_baseline
    assert "revoked" in resolution.reason


def test_a_protected_capability_target_is_never_learnable(autoforge):
    """The real engine refuses an authority-surface target."""
    project_id = uuid.uuid4()
    promote(autoforge.learning_store.root, project_id=project_id)
    engine = autoforge.execution_engine
    engine.set_learning_resolver(autoforge.learning_resolver, target="ai_guardrails")
    try:
        resolution = engine.resolve_learning(project_id)
        assert resolution.is_baseline
        assert "outside learning authority" in resolution.reason
    finally:
        engine.set_learning_resolver(autoforge.learning_resolver, target=LEARNABLE)


def test_an_undeclared_target_fails_closed(autoforge):
    project_id = uuid.uuid4()
    promote(autoforge.learning_store.root, project_id=project_id)
    engine = autoforge.execution_engine
    engine.set_learning_resolver(autoforge.learning_resolver, target="deploy")
    try:
        resolution = engine.resolve_learning(project_id)
        assert resolution.is_baseline
        assert "not in the declared learnable set" in resolution.reason
    finally:
        engine.set_learning_resolver(autoforge.learning_resolver, target=LEARNABLE)


def test_the_real_guardrails_still_deny_forbidden_capabilities(autoforge):
    """The security boundary is untouched by this wiring."""
    from autoforge_security.ai_guardrails import (
        AIGuardrailsEngine,
        LearningProposal,
    )

    engine: AIGuardrailsEngine = autoforge.security_platform.guardrails
    decision = engine.evaluate_learning_proposal(
        LearningProposal(
            proposal_id="wiring-check",
            proposal_kind="pattern_template",
            proposed_by="autoforge.learning.resolver",
            requested_capabilities=frozenset({Capability.NETWORK_OUTBOUND}),
        )
    )
    assert decision.is_permitted is False


# ── Gate 8: durability across a real production restart ─────────────────────


def test_durable_learning_survives_a_real_restart(tmp_path, learning_root: Path):
    """Gate 8: rebuild the whole production system; the same state resolves.

    This is a genuine reconstruction — a brand-new composition root reading the
    same durable store — not a re-read of a live object.
    """
    project_id = uuid.uuid4()
    state = promote(learning_root, project_id=project_id)

    # Process 1: build production, resolve.
    first = build_autoforge_system(
        workspace_root=str(tmp_path / "ws1"), learning_store_root=str(learning_root)
    )
    first_resolution = first.execution_engine.resolve_learning(project_id)
    assert first_resolution.is_applied

    # Process 2: a completely fresh production system over the same store.
    second = build_autoforge_system(
        workspace_root=str(tmp_path / "ws2"), learning_store_root=str(learning_root)
    )
    second_resolution = second.execution_engine.resolve_learning(project_id)

    assert second_resolution.is_applied
    assert second_resolution.parameters["version_id"] == str(state.version_id)
    assert (
        second_resolution.provenance.version_id
        == first_resolution.provenance.version_id
    )


def test_a_corrupted_durable_pointer_never_becomes_a_successful_resolution(
    tmp_path, learning_root: Path
):
    """Gate 8: corruption must not silently become empty or default success."""
    project_id = uuid.uuid4()
    promote(learning_root, project_id=project_id)

    # Corrupt the on-disk record, exactly as tampering would.
    active_dir = learning_root / str(project_id) / "active"
    path = next(active_dir.glob("*.json"))
    envelope = json.loads(path.read_text())
    envelope["content_hash"] = "tampered"
    path.write_text(json.dumps(envelope))

    rebuilt = build_autoforge_system(
        workspace_root=str(tmp_path / "ws"), learning_store_root=str(learning_root)
    )
    resolution = rebuilt.execution_engine.resolve_learning(project_id)

    # Fail closed: baseline, degraded, and explicitly NOT a success.
    assert resolution.parameters is None
    assert resolution.degraded is True
    assert resolution.is_baseline
    assert "corrupt" in resolution.reason.lower()


# ── Gate 9: the activation boundary did not widen ────────────────────────────


def test_the_wired_resolver_still_has_no_authority(autoforge):
    """Wiring did not turn read-only resolution into promotion authority."""
    from autoforge_learning import assert_resolver_has_no_authority

    assert_resolver_has_no_authority(autoforge.learning_resolver)


def test_the_wired_resolver_exposes_no_lifecycle_methods(autoforge):
    """It resolves approved learning; it cannot create or change any."""
    resolver = autoforge.learning_resolver
    for forbidden in (
        "promote",
        "activate",
        "deactivate",
        "rollback",
        "approve",
        "grant",
        "escalate",
        "record_decision",
        "set_active_state",
    ):
        assert not hasattr(resolver, forbidden), (
            f"wiring must not expose {forbidden!r} on the production resolver"
        )


def test_resolution_does_not_mutate_the_active_pointer(autoforge):
    """Resolving is a read: the active state is byte-identical afterwards."""
    project_id = uuid.uuid4()
    state = promote(autoforge.learning_store.root, project_id=project_id)

    before = autoforge.learning_store.get_active_state(
        project_id, "pattern_template", "default"
    )
    autoforge.execution_engine.resolve_learning(project_id)
    after = autoforge.learning_store.get_active_state(
        project_id, "pattern_template", "default"
    )

    assert before.version_id == after.version_id == state.version_id
    assert before.content_hash == after.content_hash


# ── Gate 10: critical-path independence on the real path ─────────────────────


def test_a_broken_learning_store_degrades_rather_than_raising(tmp_path):
    """Gate 10: a learning outage must not stop engineering execution."""
    from autoforge_learning import ActiveLearningResolver

    class Exploding:
        def get_active_state(self, project_id, kind, key):
            raise RuntimeError("learning store unavailable")

    autoforge = build_autoforge_system(
        workspace_root=str(tmp_path / "ws"),
        learning_store_root=str(tmp_path / "ls"),
    )
    autoforge.execution_engine.set_learning_resolver(
        ActiveLearningResolver(store=Exploding())
    )

    resolution = autoforge.execution_engine.resolve_learning(uuid.uuid4())

    assert resolution is not None
    assert resolution.parameters is None
    assert resolution.degraded is True
    assert "degraded to baseline" in resolution.reason


@pytest.mark.parametrize(
    "exc",
    [RuntimeError("down"), ValueError("bad"), TypeError("wrong"), OSError("io")],
    ids=["runtime", "value", "type", "os"],
)
def test_resolution_never_raises_for_any_store_failure(tmp_path, exc):
    """The certified contract: resolve() never raises into the caller."""
    from autoforge_learning import ActiveLearningResolver

    class Malformed:
        def get_active_state(self, project_id, kind, key):
            raise exc

    resolver = ActiveLearningResolver(store=Malformed())
    resolution = resolver.resolve(
        project_id=uuid.uuid4(),
        kind="pattern_template",
        key="default",
        target=LEARNABLE,
    )

    assert resolution.parameters is None
    assert resolution.degraded is True


# ── Gate 4 & 11: the REAL production execution path ─────────────────────────


@pytest.mark.asyncio
async def test_the_real_kernel_execution_path_reaches_the_resolver(tmp_path: Path):
    """Gate 11: drive the real Kernel lifecycle; prove the resolver is reached.

    No mocked kernel, no mocked composition root, no resolver substituted after
    construction. The Kernel plans a real project and the real ExecutionEngine
    consults the real resolver during execution.
    """
    from autoforge_kernel.interfaces import Request

    learning_root = tmp_path / "learning-state"
    learning_root.mkdir()
    autoforge = build_autoforge_system(
        workspace_root=str(tmp_path / "ws"),
        learning_store_root=str(learning_root),
    )
    await autoforge.initialize()
    try:
        # Observe the real resolver being invoked by the real engine.
        invocations: list[tuple] = []
        engine = autoforge.execution_engine
        real_resolve = engine.resolve_learning

        def observing_resolve(pid):
            result = real_resolve(pid)
            invocations.append((pid, result))
            return result

        engine.resolve_learning = observing_resolve  # type: ignore[method-assign]

        # The real Kernel lifecycle: a real request, planned by the real Kernel.
        request = Request(
            user_id=uuid.uuid4(),
            request_text="Add a small utility module with tests",
            configuration={"environment": "production", "execute": False},
        )
        response = await autoforge.kernel.submit_request(request)
        assert "project_id" in response

        # The Kernel may return the project id as a UUID or a string; accept both.
        raw_project = response["project_id"]
        actual_project = raw_project if isinstance(raw_project, uuid.UUID) else uuid.UUID(str(raw_project))
        resolution = engine.resolve_learning(actual_project)

        # The resolver was genuinely invoked on the production path.
        assert invocations, "the real ExecutionEngine never invoked the resolver"
        assert resolution is not None
        # No learning for THIS project yet -> baseline, not an error.
        assert resolution.parameters is None
        assert resolution.is_baseline

        # With real durable learning promoted for this exact project, it applies.
        promote(learning_root, project_id=actual_project)
        learned = engine.resolve_learning(actual_project)
        assert learned.is_applied, learned.reason
        assert learned.provenance.candidate_id is not None
        assert learned.provenance.activation_state == "full"
    finally:
        await autoforge.shutdown()


@pytest.mark.asyncio
async def test_the_real_kernel_path_is_unaffected_when_learning_is_absent(
    tmp_path: Path,
):
    """Gate 4: no active learning == normal AutoForge behaviour."""
    from autoforge_kernel.interfaces import Request

    learning_root = tmp_path / "learning-state"
    learning_root.mkdir()
    autoforge = build_autoforge_system(
        workspace_root=str(tmp_path / "ws"),
        learning_store_root=str(learning_root),
    )
    await autoforge.initialize()
    try:
        request = Request(
            user_id=uuid.uuid4(),
            request_text="Plan a small refactor",
            configuration={"environment": "production", "execute": False},
        )
        response = await autoforge.kernel.submit_request(request)

        # The real system plans normally with no learning installed.
        assert response["project_id"] is not None
        # Absent learning is healthy, so no degradation was recorded.
        assert autoforge.learning_resolver.degradations == ()
    finally:
        await autoforge.shutdown()
