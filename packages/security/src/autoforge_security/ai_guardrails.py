"""
AI Guardrails Layer — canonical enforcement boundary for AI-originated actions.

Architecture position (composes with, does not replace, the certified platform):

    AI / model
        ↓
    proposal                       (TrustLevel-tagged content)
        ↓
    AI Guardrails                  ← THIS MODULE (AIGuardrailsEngine)
        ↓
    identity                       (SecurityPlatform.authorize)
        ↓
    worker capability
        ↓
    project / resource scope
        ↓
    authorization                  (AuthorizationEngine / GovernancePolicyEngine)
        ↓
    sandbox / network / credential policy
        ↓
    HITL if required               (HITLManager)
        ↓
    deterministic validation
        ↓
    execution
        ↓
    audit / event emission         (AuditEngine / SecurityEventPublisher)

Core invariants (all enforced deterministically, none model-claim dependent):

1. INV-NON_AUTHORITATIVE: model output can never grant authority. No decision in
   this module consults model-supplied claims about identity, permission, or
   policy. Content trust is *declared by the platform*, never by the producer.
2. INV-FAIL_CLOSED: any error, malformed request, or engine fault yields DENY for
   security-sensitive operations. Unavailable guardrails never imply "allow".
3. INV-NO-SELF-AUTHORIZE: a request whose trust level is below HUMAN_AUTHORITY
   can never satisfy a REQUIRE_HITL or REQUIRE_ELEVATED_AUTHORITY requirement, no
   matter what the request payload claims.
4. INV-TAMPER-RESISTANT: guardrail policy is immutable at runtime. There is no API,
   method, or model-reachable path that mutates policy from untrusted input.
5. INV-AUDITABLE: every decision carries correlation with
   project / workflow / task / worker / execution.
6. INV-IMMEDIATE: `enforce()` is designed to be called immediately before the side
   effect, not only at planning time.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Mapping

from pydantic import BaseModel, ConfigDict, Field


# ── Trust Levels ──────────────────────────────────────────────────────────


class TrustLevel(str, Enum):
    """Ordered authority tiers for content entering the AI execution path.

    Rank is explicit and monotonic. Higher rank may inform lower rank but never
    the reverse: no lower-trust content may override higher-trust authority.
    """

    SYSTEM_POLICY = "system_policy"
    HUMAN_AUTHORITY = "human_authority"
    CUSTOMER_INSTRUCTION = "customer_instruction"
    PLATFORM_GENERATED_DATA = "platform_generated_data"
    RETRIEVED_DATA = "retrieved_data"
    LEGACY_SOURCE = "legacy_source"
    EXTERNAL_TOOL_OUTPUT = "external_tool_output"
    MODEL_OUTPUT = "model_output"
    UNTRUSTED_GENERATED_CONTENT = "untrusted_generated_content"

    @property
    def rank(self) -> int:
        return _TRUST_RANK[self]


_TRUST_RANK: Mapping[TrustLevel, int] = {
    TrustLevel.SYSTEM_POLICY: 100,
    TrustLevel.HUMAN_AUTHORITY: 90,
    TrustLevel.CUSTOMER_INSTRUCTION: 70,
    TrustLevel.PLATFORM_GENERATED_DATA: 60,
    TrustLevel.RETRIEVED_DATA: 50,
    TrustLevel.LEGACY_SOURCE: 45,
    TrustLevel.EXTERNAL_TOOL_OUTPUT: 30,
    TrustLevel.MODEL_OUTPUT: 20,
    TrustLevel.UNTRUSTED_GENERATED_CONTENT: 10,
}

#: Trust levels that may never originate from a model or model-reachable input.
NON_AUTHORITATIVE_TRUST: frozenset[TrustLevel] = frozenset(
    {
        TrustLevel.RETRIEVED_DATA,
        TrustLevel.LEGACY_SOURCE,
        TrustLevel.EXTERNAL_TOOL_OUTPUT,
        TrustLevel.MODEL_OUTPUT,
        TrustLevel.UNTRUSTED_GENERATED_CONTENT,
    }
)

#: Trust levels whose content is treated strictly as DATA, never as INSTRUCTIONS.
DATA_ONLY_TRUST: frozenset[TrustLevel] = frozenset(
    {
        TrustLevel.RETRIEVED_DATA,
        TrustLevel.LEGACY_SOURCE,
        TrustLevel.EXTERNAL_TOOL_OUTPUT,
        TrustLevel.UNTRUSTED_GENERATED_CONTENT,
    }
)
# ── Action Classification ─────────────────────────────────────────────────


class ActionClass(str, Enum):
    """Deterministic classification of an AI-proposed action.

    Classification is computed from platform-declared action facts. It is never
    accepted from model output.
    """

    READ = "read"
    WRITE = "write"
    DELETE = "delete"
    EXECUTE = "execute"
    NETWORK = "network"
    CREDENTIAL = "credential"
    PUBLISH = "publish"
    DEPLOY = "deploy"
    MIGRATE = "migrate"
    GOVERNANCE = "governance"


#: Actions whose effects are irreversible or escape the workspace. These are
#: security-sensitive and fail closed.
SECURITY_SENSITIVE_CLASSES: frozenset[ActionClass] = frozenset(
    {
        ActionClass.DELETE,
        ActionClass.EXECUTE,
        ActionClass.CREDENTIAL,
        ActionClass.PUBLISH,
        ActionClass.DEPLOY,
        ActionClass.MIGRATE,
        ActionClass.GOVERNANCE,
    }
)


# ── Capabilities ──────────────────────────────────────────────────────────


class Capability(str, Enum):
    """Least-privilege capability scopes.

    These extend — and do not replace — the existing ``Permissions`` taxonomy and
    ``WorkerSecurityProfile`` model. Capabilities describe *what a side effect
    needs*, which is orthogonal to *which role holds a permission*.
    """

    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    FILESYSTEM_DELETE = "filesystem.delete"

    PROCESS_EXECUTE = "process.execute"

    NETWORK_OUTBOUND = "network.outbound"

    GIT_READ = "git.read"
    GIT_WRITE = "git.write"
    GIT_DESTRUCTIVE = "git.destructive"

    CREDENTIAL_REQUEST = "credentials.request"
    CREDENTIAL_USE = "credentials.use"
    CREDENTIAL_ADMINISTER = "credentials.administer"

    ARTIFACT_CREATE = "artifacts.create"
    ARTIFACT_MODIFY = "artifacts.modify"
    ARTIFACT_PUBLISH = "artifacts.publish"
    ARTIFACT_DELETE = "artifacts.delete"

    DEPLOYMENT_PREPARE = "deployment.prepare"
    DEPLOYMENT_EXECUTE = "deployment.execute"

    SECURITY_READ = "security.read"
    SECURITY_MODIFY = "security.modify"


#: Capability demanded by each action class. This is the capability matrix that
#: makes least privilege explicit and machine-checkable.
ACTION_CAPABILITIES: Mapping[ActionClass, frozenset[Capability]] = {
    ActionClass.READ: frozenset({Capability.FILESYSTEM_READ}),
    ActionClass.WRITE: frozenset({Capability.FILESYSTEM_WRITE}),
    ActionClass.DELETE: frozenset({Capability.FILESYSTEM_DELETE}),
    ActionClass.EXECUTE: frozenset({Capability.PROCESS_EXECUTE}),
    ActionClass.NETWORK: frozenset({Capability.NETWORK_OUTBOUND}),
    ActionClass.CREDENTIAL: frozenset({Capability.CREDENTIAL_USE}),
    ActionClass.PUBLISH: frozenset({Capability.ARTIFACT_PUBLISH}),
    ActionClass.DEPLOY: frozenset({Capability.DEPLOYMENT_EXECUTE}),
    ActionClass.MIGRATE: frozenset({Capability.DEPLOYMENT_EXECUTE}),
    ActionClass.GOVERNANCE: frozenset({Capability.SECURITY_MODIFY}),
}



# ── Decisions ─────────────────────────────────────────────────────────────


class GuardrailDecisionType(str, Enum):
    """Canonical guardrail outcomes."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_HITL = "require_hitl"
    REQUIRE_ELEVATED_AUTHORITY = "require_elevated_authority"
    INVALID_REQUEST = "invalid_request"


class GuardrailRequest(BaseModel):
    """A single AI-originated action proposal presented for enforcement.

    Every field is platform-supplied. Model output may populate ``proposed_action``
    and ``payload`` but can never populate ``declared_trust_level``,
    ``worker_capabilities``, or ``platform_permissions`` — those are authority
    facts held by the platform.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposed_action: str
    action_class: ActionClass
    resource: str
    declared_trust_level: TrustLevel
    worker_id: str | None = None
    worker_type: str | None = None
    worker_capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    platform_permissions: frozenset[str] = Field(default_factory=frozenset)
    requires_hitl: bool = False
    project_id: str | None = None
    workflow_id: str | None = None
    task_id: str | None = None
    execution_id: str | None = None
    correlation_id: str | None = None
    trace_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)


class GuardrailDecision(BaseModel):
    """Deterministic, auditable guardrail outcome."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    decision: GuardrailDecisionType
    is_allowed: bool
    reason: str
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    required_capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    satisfied_capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    missing_capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    policy_version: str = "1.0.0"
    correlation_id: str | None = None
    details: dict[str, Any] = Field(default_factory=dict)

    @property
    def blocked(self) -> bool:
        return not self.is_allowed


# ── Self-Improvement Boundary (GATE 9) ────────────────────────────────────

#: Kinds of change a learning/self-improvement system is permitted to *propose*.
LEARNABLE_PROPOSAL_KINDS: frozenset[str] = frozenset(
    {
        "workflow_definition",
        "routing_rule",
        "optimization_hint",
        "pattern_template",
        "documentation_pattern",
    }
)

#: Capabilities a learning proposal may never request. This is the explicit
#: anti-self-elevation contract required before Phase 19 ships.
LEARNING_FORBIDDEN_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.CREDENTIAL_USE,
        Capability.CREDENTIAL_ADMINISTER,
        Capability.CREDENTIAL_REQUEST,
        Capability.NETWORK_OUTBOUND,
        Capability.SECURITY_MODIFY,
        Capability.DEPLOYMENT_EXECUTE,
        Capability.PROCESS_EXECUTE,
        Capability.FILESYSTEM_DELETE,
        Capability.GIT_DESTRUCTIVE,
    }
)


class LearningProposal(BaseModel):
    """A proposed change emitted by a learning / self-improvement subsystem."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    proposal_id: str
    proposal_kind: str
    proposed_by: str
    target_scope: str = ""
    requested_capabilities: frozenset[Capability] = Field(default_factory=frozenset)
    rationale: str = ""
    correlation_id: str | None = None


class LearningProposalDecision(BaseModel):
    """Outcome of a self-improvement security boundary evaluation."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    is_permitted: bool
    decision: GuardrailDecisionType
    reason: str
    promotion_requires: tuple[str, ...] = ()
    forbidden_capabilities: frozenset[Capability] = Field(default_factory=frozenset)


class AIGuardrailsEngine:
    """Deterministic enforcement boundary for AI-originated actions.

    The engine decides; it never executes. Authority decisions are delegated to
    the certified ``SecurityPlatform``. This engine only determines whether a
    proposal is well-formed, sufficiently trusted, and capability-covered.

    Tamper resistance: there is deliberately no ``set_policy`` / ``mutate`` /
    ``reload`` method. The policy surface is fixed at construction time and
    exposed read-only, so no model-reachable code path can widen it.
    """

    POLICY_VERSION = "1.0.0"

    def __init__(
        self,
        *,
        allowed_proposal_kinds: frozenset[str] = LEARNABLE_PROPOSAL_KINDS,
        require_hitl_for_sensitive: bool = True,
        policy_version: str = POLICY_VERSION,
    ) -> None:
        self._allowed_proposal_kinds = allowed_proposal_kinds
        self._require_hitl_for_sensitive = require_hitl_for_sensitive
        self._policy_version = policy_version

    @property
    def policy_version(self) -> str:
        return self._policy_version

    @property
    def allowed_proposal_kinds(self) -> frozenset[str]:
        return self._allowed_proposal_kinds

    # ── Validation & classification ────────────────────────────────────────

    @staticmethod
    def validate_request(request: Any) -> GuardrailRequest | None:
        """Structurally validate a proposed request.

        Returns ``None`` when the request is unusable. Callers MUST treat ``None``
        as INVALID_REQUEST (fail closed) and must not attempt to coerce it.
        """
        if isinstance(request, GuardrailRequest):
            return request
        if not isinstance(request, Mapping):
            return None
        try:
            return GuardrailRequest.model_validate(dict(request))
        except Exception:
            return None

    @staticmethod
    def classify_action(action: str) -> ActionClass:
        """Deterministically classify an action string.

        Derived from the platform action namespace, never from model output.
        Unrecognised actions classify as ``EXECUTE`` (the most restrictive
        bucket) so unknown actions fail closed.
        """
        normalized = (action or "").strip().lower()
        if not normalized:
            return ActionClass.EXECUTE
        if normalized.startswith(("read", "get", "list", "view", "search", "inspect")):
            return ActionClass.READ
        if normalized.startswith(("delete", "remove", "destroy", "purge", "drop")):
            return ActionClass.DELETE
        if normalized.startswith(("network", "http", "fetch", "outbound", "request_url")):
            return ActionClass.NETWORK
        if normalized.startswith(("credential", "secret", "token")):
            return ActionClass.CREDENTIAL
        if normalized.startswith(("publish", "release")):
            return ActionClass.PUBLISH
        if normalized.startswith(("deploy", "cutover")):
            return ActionClass.DEPLOY
        if normalized.startswith("migrat"):
            return ActionClass.MIGRATE
        if normalized.startswith(("governance", "policy", "security_config", "configure")):
            return ActionClass.GOVERNANCE
        if normalized.startswith(("write", "create", "update", "modify", "patch", "put")):
            return ActionClass.WRITE
        # Unknown / uncategorised -> most restrictive bucket.
        return ActionClass.EXECUTE


# ── Capability evaluation ───────────────────────────────────────────────

    @staticmethod
    def required_capabilities(action_class: ActionClass) -> frozenset[Capability]:
        """Capabilities demanded by an action class."""
        return ACTION_CAPABILITIES.get(action_class, frozenset())

    @staticmethod
    def evaluate_capabilities(
        action_class: ActionClass,
        granted: frozenset[Capability],
    ) -> tuple[frozenset[Capability], frozenset[Capability], frozenset[Capability]]:
        """Return ``(required, satisfied, missing)`` for a capability set."""
        required = ACTION_CAPABILITIES.get(action_class, frozenset())
        return required, required & granted, required - granted

    # ── Canonical enforcement ──────────────────────────────────────────────

    def enforce(self, request: Any) -> GuardrailDecision:
        """Deterministically decide whether an AI proposal may proceed.

        Single canonical enforcement entry point, intended to be invoked
        immediately before the side effect. Fail-closed at every step:

        1. structural validation   -> INVALID_REQUEST
        2. action classification   -> re-derived, never trusted from payload
        3. trust evaluation        -> DENY for non-authoritative self-elevation
        4. capability evaluation   -> DENY on missing capability
        5. HITL requirement        -> REQUIRE_HITL
        6. allow
        """
        validated = self.validate_request(request)
        if validated is None:
            return GuardrailDecision(
                decision=GuardrailDecisionType.INVALID_REQUEST,
                is_allowed=False,
                reason="Guardrail request failed structural validation; refusing untrusted input.",
                policy_version=self._policy_version,
                details={"error": "malformed_or_unusable_request"},
            )

        try:
            return self._enforce_validated(validated)
        except Exception as exc:  # pragma: no cover - defensive fail-closed path
            # INV-FAIL_CLOSED: an unexpected engine fault must never become ALLOW.
            return GuardrailDecision(
                decision=GuardrailDecisionType.DENY,
                is_allowed=False,
                reason=f"Guardrail evaluation faulted; failing closed ({type(exc).__name__}).",
                policy_version=self._policy_version,
                correlation_id=validated.correlation_id,
                details={"error": "engine_fault", "exception": type(exc).__name__},
            )


    def _enforce_validated(self, req: GuardrailRequest) -> GuardrailDecision:
        # 1. Action classification is re-derived by the platform, never trusted
        #    from the request payload.
        derived_class = self.classify_action(req.proposed_action)
        if derived_class != req.action_class:
            return GuardrailDecision(
                decision=GuardrailDecisionType.INVALID_REQUEST,
                is_allowed=False,
                reason=(
                    f"Declared action_class '{req.action_class.value}' does not match the "
                    f"platform-derived class '{derived_class.value}' for action "
                    f"'{req.proposed_action}'."
                ),
                policy_version=self._policy_version,
                correlation_id=req.correlation_id,
                details={
                    "declared_action_class": req.action_class.value,
                    "derived_action_class": derived_class.value,
                },
            )

        required, satisfied, missing = self.evaluate_capabilities(
            derived_class, req.worker_capabilities
        )

        # 2. INV-NO-SELF-AUTHORIZE: a non-authoritative proposal can never change
        #    security/governance policy.
        if derived_class is ActionClass.GOVERNANCE and req.declared_trust_level in NON_AUTHORITATIVE_TRUST:
            return GuardrailDecision(
                decision=GuardrailDecisionType.DENY,
                is_allowed=False,
                reason=(
                    f"Security/governance policy changes cannot originate from "
                    f"'{req.declared_trust_level.value}' content. The model is never authoritative."
                ),
                required_capabilities=required,
                satisfied_capabilities=satisfied,
                missing_capabilities=missing,
                policy_version=self._policy_version,
                correlation_id=req.correlation_id,
                details={
                    "action_class": derived_class.value,
                    "trust_level": req.declared_trust_level.value,
                },
            )

        # 3. Capability coverage is mandatory: no capability, no execution.
        if missing:
            return GuardrailDecision(
                decision=GuardrailDecisionType.DENY,
                is_allowed=False,
                reason=(
                    f"Worker lacks required capability/capabilities "
                    f"{sorted(c.value for c in missing)} for action class "
                    f"'{derived_class.value}'."
                ),
                required_capabilities=required,
                satisfied_capabilities=satisfied,
                missing_capabilities=missing,
                policy_version=self._policy_version,
                correlation_id=req.correlation_id,
                details={
                    "action_class": derived_class.value,
                    "worker_id": req.worker_id,
                    "worker_type": req.worker_type,
                },
            )


# 4. Elevated-authority requirement: only high-trust content may proceed,
        #    and even then it is escalated rather than self-satisfied.
        if self._requires_elevated_authority(req, derived_class):
            if req.declared_trust_level.rank < TrustLevel.HUMAN_AUTHORITY.rank:
                return GuardrailDecision(
                    decision=GuardrailDecisionType.REQUIRE_ELEVATED_AUTHORITY,
                    is_allowed=False,
                    reason=(
                        f"Action '{req.proposed_action}' requires elevated authority; "
                        f"'{req.declared_trust_level.value}' content cannot self-authorize."
                    ),
                    required_capabilities=required,
                    satisfied_capabilities=satisfied,
                    missing_capabilities=missing,
                    policy_version=self._policy_version,
                    correlation_id=req.correlation_id,
                    details={"action_class": derived_class.value},
                )

        # 5. HITL: escalate rather than approve. A proposal can never declare
        #    itself already-approved.
        if self._requires_hitl(req, derived_class):
            return GuardrailDecision(
                decision=GuardrailDecisionType.REQUIRE_HITL,
                is_allowed=False,
                reason=(
                    f"Action '{req.proposed_action}' ({derived_class.value}) requires human "
                    "approval before execution."
                ),
                required_capabilities=required,
                satisfied_capabilities=satisfied,
                missing_capabilities=missing,
                policy_version=self._policy_version,
                correlation_id=req.correlation_id,
                details={"action_class": derived_class.value, "requires_hitl": True},
            )

        return GuardrailDecision(
            decision=GuardrailDecisionType.ALLOW,
            is_allowed=True,
            reason=(
                f"Action '{req.proposed_action}' ({derived_class.value}) permitted: "
                f"capabilities satisfied and trust level '{req.declared_trust_level.value}' "
                "sufficient."
            ),
            required_capabilities=required,
            satisfied_capabilities=satisfied,
            missing_capabilities=missing,
            policy_version=self._policy_version,
            correlation_id=req.correlation_id,
            details={
                "action_class": derived_class.value,
                "trust_level": req.declared_trust_level.value,
            },
        )

    def _requires_hitl(self, req: GuardrailRequest, action_class: ActionClass) -> bool:
        if req.requires_hitl:
            return True
        if self._require_hitl_for_sensitive and action_class in SECURITY_SENSITIVE_CLASSES:
            return True
        return False

    @staticmethod
    def _requires_elevated_authority(req: GuardrailRequest, action_class: ActionClass) -> bool:
        """Actions that may only proceed under human/system authority."""
        if action_class in {ActionClass.GOVERNANCE, ActionClass.CREDENTIAL}:
            return True
        return req.declared_trust_level in NON_AUTHORITATIVE_TRUST and action_class in {
            ActionClass.DEPLOY,
            ActionClass.MIGRATE,
            ActionClass.PUBLISH,
        }


# ── Self-improvement boundary (GATE 9) ─────────────────────────────────

    def evaluate_learning_proposal(self, proposal: Any) -> LearningProposalDecision:
        """Evaluate a self-improvement proposal against the security boundary.

        Learning systems may PROPOSE. They may never grant themselves permissions,
        capabilities, credential access, unrestricted network access, sandbox
        escapes, security-policy modifications, or HITL bypasses.
        """
        if not isinstance(proposal, LearningProposal):
            if isinstance(proposal, Mapping):
                try:
                    proposal = LearningProposal.model_validate(dict(proposal))
                except Exception:
                    return LearningProposalDecision(
                        is_permitted=False,
                        decision=GuardrailDecisionType.INVALID_REQUEST,
                        reason="Learning proposal failed structural validation.",
                    )
            else:
                return LearningProposalDecision(
                    is_permitted=False,
                    decision=GuardrailDecisionType.INVALID_REQUEST,
                    reason="Learning proposal is not a valid proposal object.",
                )

        escalation = proposal.requested_capabilities & LEARNING_FORBIDDEN_CAPABILITIES
        if escalation:
            return LearningProposalDecision(
                is_permitted=False,
                decision=GuardrailDecisionType.DENY,
                reason=(
                    f"Learning proposal '{proposal.proposal_id}' requests forbidden "
                    f"capability/capabilities {sorted(c.value for c in escalation)}. "
                    "Self-improvement may never escalate its own security boundary."
                ),
                forbidden_capabilities=LEARNING_FORBIDDEN_CAPABILITIES,
            )

        if proposal.proposal_kind not in self._allowed_proposal_kinds:
            return LearningProposalDecision(
                is_permitted=False,
                decision=GuardrailDecisionType.DENY,
                reason=(
                    f"Learning proposal kind '{proposal.proposal_kind}' is not an approved "
                    f"learnable kind. Approved: {sorted(self._allowed_proposal_kinds)}."
                ),
                forbidden_capabilities=LEARNING_FORBIDDEN_CAPABILITIES,
            )

        return LearningProposalDecision(
            is_permitted=True,
            decision=GuardrailDecisionType.ALLOW,
            reason=(
                f"Learning proposal '{proposal.proposal_id}' is a permitted proposal; it must "
                "still pass validation, security review, and authorization/HITL before promotion."
            ),
            promotion_requires=(
                "deterministic_validation",
                "security_review",
                "human_authorization",
                "hitl_when_consequential",
            ),
            forbidden_capabilities=LEARNING_FORBIDDEN_CAPABILITIES,
        )
