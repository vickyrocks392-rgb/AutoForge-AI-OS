"""Phase 19 FINAL — production learning integration tests (Gates 1–4, 23).

These prove the four 19B-3 production conditions are closed and that no-learning
is indistinguishable from pre-learning AutoForge.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from autoforge_learning.production import (
    LEARNABLE_TARGETS,
    PROTECTED_TARGETS,
    ActiveLearningResolver,
    AuthorizationDenied,
    ProductionResolution,
    assert_resolver_has_no_authority,
)
from autoforge_learning.store import ActiveLearningState

KIND = "pattern_template"
KEY = "default"
TARGET = "prompt_strategy"


@pytest.fixture()
def project_id() -> uuid.UUID:
    return uuid.uuid4()


def make_state(
    project_id: uuid.UUID,
    *,
    kind: str = KIND,
    key: str = KEY,
    content_hash: str = "a" * 64,
    deactivated: bool = False,
    activated_in_future: bool = False,
    version: int = 1,
) -> ActiveLearningState:
    now = datetime.now(timezone.utc)
    return ActiveLearningState(
        project_id=project_id,
        kind=kind,
        key=key,
        version_id=uuid.uuid4(),
        version_number=version,
        candidate_id=uuid.uuid4(),
        content_hash=content_hash,
        activation_timestamp=(
            now + timedelta(days=1) if activated_in_future else now
        ),
        deactivation_timestamp=(now if deactivated else None),
        scope_kind="project",
    )


class Store:
    """Minimal in-memory reader matching the production protocol."""

    def __init__(self, state) -> None:
        self.state = state

    def get_active_state(self, project_id, kind, key):
        return self.state


def resolver_for(state, *, authorize=lambda s, p: True, parameters=None):
    return ActiveLearningResolver(
        store=Store(state),
        parameters_for=parameters or (lambda s: {"template": "learned"}),
        authorize=authorize,
    )


# ── Gate 2: every failure mode preserves baseline behaviour ──────────────────


def test_learning_disabled_is_baseline(project_id):
    resolver = ActiveLearningResolver(store=None)
    assert resolver.enabled is False
    r = resolver.resolve(project_id=project_id, kind=KIND, key=KEY, target=TARGET)
    assert r.is_baseline
    assert r.parameters is None


def test_no_active_learning_is_baseline(project_id):
    r = resolver_for(None).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline
    assert "no active learning" in r.reason
    # Absent learning is normal, not a degradation.
    assert r.degraded is False


def test_revoked_learning_is_baseline(project_id):
    r = resolver_for(make_state(project_id, deactivated=True)).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline
    assert "revoked" in r.reason


def test_expired_learning_is_baseline(project_id):
    r = resolver_for(make_state(project_id, activated_in_future=True)).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline


def test_corrupted_learning_is_baseline(project_id):
    r = resolver_for(make_state(project_id, content_hash="")).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline
    assert r.degraded is True
    assert "integrity" in r.reason


def test_wrong_project_learning_is_baseline(project_id):
    foreign = make_state(uuid.uuid4())
    r = resolver_for(foreign).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline
    assert r.degraded is True


def test_incompatible_learning_is_baseline(project_id):
    r = resolver_for(make_state(project_id, kind="other_kind")).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline
    assert "incompatible" in r.reason


def test_unauthorized_learning_is_baseline(project_id):
    r = resolver_for(make_state(project_id), authorize=lambda s, p: False).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_baseline
    assert "authorization refused" in r.reason


def test_missing_authorizer_is_baseline_not_skip(project_id):
    """Absence of an authorizer is a denial, not an implicit permission."""
    resolver = ActiveLearningResolver(
        store=Store(make_state(project_id)), parameters_for=lambda s: {"x": 1}
    )
    r = resolver.resolve(project_id=project_id, kind=KIND, key=KEY, target=TARGET)
    assert r.is_baseline
    assert "authorizer" in r.reason


# ── Gate 3: bounded targets, real application, provenance ────────────────────


def test_authorized_learning_is_applied_with_provenance(project_id):
    state = make_state(project_id)
    r = resolver_for(state).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=TARGET
    )
    assert r.is_applied
    assert r.parameters == {"template": "learned"}
    prov = r.provenance
    assert prov is not None
    assert prov.version_id == state.version_id
    assert prov.candidate_id == state.candidate_id
    assert str(prov.project_id) == str(project_id)
    assert prov.activation_state == "full"
    d = prov.to_dict()
    for field in (
        "learning_id",
        "version_id",
        "candidate_id",
        "project_id",
        "activation_state",
    ):
        assert field in d


@pytest.mark.parametrize("protected", sorted(PROTECTED_TARGETS))
def test_protected_targets_are_permanently_not_learnable(project_id, protected):
    """Learning can never influence a security or authority decision point."""
    r = resolver_for(make_state(project_id)).resolve(
        project_id=project_id, kind=KIND, key=KEY, target=protected
    )
    assert r.is_baseline
    assert "outside learning authority" in r.reason


def test_the_learnable_target_set_is_bounded_and_non_security():
    assert set(LEARNABLE_TARGETS).isdisjoint(PROTECTED_TARGETS)
    for target in LEARNABLE_TARGETS:
        assert target not in PROTECTED_TARGETS
    for forbidden in ("authorization", "credential", "guardrail", "trust", "audit"):
        assert not any(forbidden in t for t in LEARNABLE_TARGETS)


def test_an_undeclared_target_is_baseline(project_id):
    r = resolver_for(make_state(project_id)).resolve(
        project_id=project_id, kind=KIND, key=KEY, target="deploy_to_production"
    )
    assert r.is_baseline
    assert "not in the declared learnable set" in r.reason


# ── Gate 1 / safety principle: the resolver grants nothing ───────────────────


def test_the_resolver_exposes_no_authority(project_id):
    assert_resolver_has_no_authority(resolver_for(make_state(project_id)))


# ── Gate 23: critical-path independence ──────────────────────────────────────


class ExplodingStore:
    def get_active_state(self, project_id, kind, key):
        raise RuntimeError("learning store unavailable")


@pytest.mark.parametrize(
    "disabled",
    [True, False],
    ids=["learning_disabled", "learning_store_outage"],
)
def test_learning_outage_never_stops_engineering_execution(disabled, project_id):
    """A learning failure degrades to baseline; it never raises.

    A missing store (learning disabled) is a *configuration*, not a degradation,
    so it records nothing. An exploding store is a genuine outage and must be
    recorded truthfully.
    """
    resolver = ActiveLearningResolver(
        store=None if disabled else ExplodingStore(),
        parameters_for=lambda s: {"x": 1},
        authorize=lambda s, p: True,
    )
    r = resolver.resolve(project_id=project_id, kind=KIND, key=KEY, target=TARGET)
    assert isinstance(r, ProductionResolution)
    assert r.is_baseline
    if disabled:
        assert resolver.degradations == ()
    else:
        assert resolver.degradations
        assert r.degraded is True


def test_degradations_are_recorded_truthfully(project_id):
    resolver = ActiveLearningResolver(store=ExplodingStore())
    resolver.resolve(project_id=project_id, kind=KIND, key=KEY, target=TARGET)
    assert len(resolver.degradations) == 1
    assert "degraded to baseline" in resolver.degradations[0]