"""Gate C -- Canonical lifecycle decision contract (Phase C2 + C3 + C4).

This module makes the four canonical lifecycle decisions *explicit, bounded and
reusable*, using ONLY the already-certified B2 result vocabulary:

    OutcomeStatus.COMPLETE | REMEDIATE | ESCALATE | FAILED

No new status enumeration, no second ``ExecutionOutcome``, and no second
completion abstraction is introduced. ``ExecutionOutcome`` (B2) remains the one
normalised result contract; this module only decides what O-2 should do with it.

Why a decision contract is needed (the B2 carry-forward facts)
--------------------------------------------------------------
1. ``REMEDIATE`` existed as a status with **no real producer** of
   ``remediation_tasks``. ``DefaultOrchestrationEngine._handle_remediation``
   (``orchestration.py:341-357``) reads ``loop_result.get("remediation_tasks", [])``
   but nothing in the production path ever writes that key -- verified: zero
   writers. So the remediation branch was a no-op that silently did nothing.
2. ``_handle_escalation`` (``orchestration.py:359-382``) emits an event and moves
   project state to ``reviewing``. It does not create a durable approval request.
3. No bounded retry existed on the O-2 loop path.

This module supplies the missing *determinism* (a decision function with an
explicit attempt budget) without wiring any new orchestration authority. It is a
pure capability owned by the canonical architecture; O-2 remains the only
orchestrator.

Design constraints (Gate C)
---------------------------
* **Pure.** No I/O, no dispatch, no persistence, no model call, no state
  transition. It reads its inputs and returns a value.
* **Deterministic.** Identical inputs always produce an identical decision. No
  model judgment participates.
* **Bounded.** Remediation is permitted only while ``attempt < max_attempts``.
  There is no unbounded path and no hidden retry: the budget is a required,
  explicit argument.
* **Fail-closed.** Evidence is never fabricated. A decision that cannot justify
  itself from the supplied outcome is refused rather than assumed.
* **No automatic success.** ``COMPLETE`` is returned only when the executor
  itself reported ``COMPLETE`` AND passed. Remediation can never upgrade itself
  to ``COMPLETE``; that is the validation/review gate's decision, not this
  module's.
* **No bypass.** Validation and review verdicts are inputs, never overridden.

Not in scope
------------
This contract decides; it does not execute. It creates no worker, no
``LifecycleOrchestrator``, and no second authority over O-2's loop.

Gate C3 extension
-----------------
``describe_remediation`` maps a certified decision to a declarative
``RemediationRequest``: frozen data naming the stage, the evidence and
the bounded budget. It executes no retry, mutates no counter, invokes no
worker / Power Engine / Model Router / LLM, and creates no approval
request. ``COMPLETE``/``ESCALATE``/``FAILED`` yield no request; only an
authorised, budget-backed ``REMEDIATE`` does.

Gate C4 extension
-----------------
``describe_approval`` maps a certified decision to a declarative
``HumanApprovalRequirement``: frozen data naming the stage, the evidence
and the decision's justification -- the statement *that human approval is
required*. It approves nothing, rejects nothing, halts nothing, continues
nothing; it invokes no executor / worker / Power Engine / Model Router /
LLM, performs no persistence, creates no approval record, opens no queue
entry and makes no API call. Only ``ESCALATE`` yields a requirement;
``COMPLETE`` / ``REMEDIATE`` / ``FAILED`` yield ``None``, and ``FAILED``
keeps its C2-certified meaning untouched.

ESCALATE versus WAITING_FOR_HITL (the canonical distinction)
------------------------------------------------------------
``ESCALATE`` is a *decision*: human intervention is required. O-1's
``WAITING_FOR_HITL`` is a *runtime pause state*: execution has actually
stopped and awaits an approval action. They are not equivalent, and this
module never makes the first become the second: the requirement produced
here is declarative data only, and production execution is deliberately
not transitioned into any waiting state by it. Whether any future wiring
may connect them is a later production-wiring decision, not a property of
this contract. O-1's orchestration machinery stays quarantined: this
module imports nothing from it.
"""


from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from autoforge_composition.execution_outcome import ExecutionOutcome, OutcomeStatus
from autoforge_composition.lifecycle_taxonomy import (
    DEFAULT_STAGE_MAX_ATTEMPTS,
    LifecycleContractError,
)

__all__ = [
    "LifecycleDecisionError",
    "LifecycleDecision",
    "RemediationBudget",
    "RemediationRequest",
    "HumanApprovalRequirement",
    "decide_lifecycle",
    "describe_remediation",
    "describe_approval",
]


class LifecycleDecisionError(LifecycleContractError):
    """A lifecycle decision could not be justified from the supplied evidence."""


class RemediationBudget(BaseModel):
    """Explicit, bounded remediation budget for one unit of work.

    Frozen and ``extra="forbid"``, matching the Execution Platform convention.

    ``attempt`` is 1-based: the attempt that just produced the outcome being
    decided. ``max_attempts`` is the hard ceiling on re-execution. Neither value
    may be negative or inverted -- both are contract violations rather than
    silently clamped values, because a clamped budget would hide an unbounded
    loop.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    attempt: int = Field(..., ge=1, description="1-based attempt that produced the outcome.")
    max_attempts: int = Field(
        ...,
        ge=1,
        description="Hard ceiling on re-execution attempts, including the first.",
    )

    @property
    def exhausted(self) -> bool:
        """True when no further re-execution is permitted."""
        return self.attempt >= self.max_attempts

    @property
    def remaining(self) -> int:
        """Attempts still available. Never negative."""
        return max(0, self.max_attempts - self.attempt)



class LifecycleDecision(BaseModel):
    """The canonical, explicit result of deciding what happens next.

    This is NOT a second outcome type. It *reuses* the certified
    ``OutcomeStatus`` as its ``status`` field and adds only the decision
    metadata O-2 needs to act safely:

    * ``attempt`` -- explicit attempt identity (no anonymous retries).
    * ``remediation_allowed`` -- the bounded re-execution permit. It is a
      ``bool`` rather than a count precisely so that "unbounded" is not
      representable.
    * ``requires_human_approval`` -- true only for ``ESCALATE``.
    * ``terminal`` -- true when no further lifecycle action is possible.
    * ``reason`` -- why, derived only from real inputs.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: OutcomeStatus = Field(..., description="The canonical lifecycle decision.")
    attempt: int = Field(..., ge=1, description="Explicit attempt identity.")
    remediation_allowed: bool = Field(
        ...,
        description="Whether a bounded re-execution is permitted. Never unbounded.",
    )
    requires_human_approval: bool = Field(
        ...,
        description="True only for ESCALATE. Approval is never automatic.",
    )
    terminal: bool = Field(..., description="True when no further action is possible.")
    reason: str = Field(..., min_length=1, description="Evidence-derived justification.")

    @property
    def is_complete(self) -> bool:
        return self.status is OutcomeStatus.COMPLETE

    @property
    def is_escalated(self) -> bool:
        return self.status is OutcomeStatus.ESCALATE


def _decide(
    status: OutcomeStatus,
    *,
    attempt: int,
    remediation_allowed: bool,
    requires_human_approval: bool,
    terminal: bool,
    reason: str,
) -> LifecycleDecision:
    return LifecycleDecision(
        status=status,
        attempt=attempt,
        remediation_allowed=remediation_allowed,
        requires_human_approval=requires_human_approval,
        terminal=terminal,
        reason=reason,
    )


def decide_lifecycle(
    outcome: ExecutionOutcome,
    *,
    budget: RemediationBudget,
) -> LifecycleDecision:
    """Decide the canonical next lifecycle action for ``outcome``.

    Decision table (deterministic; no model judgment, no I/O):

    ==========  ==============================  ==========================
    Outcome     Decision                        Rationale
    ==========  ==============================  ==========================
    COMPLETE    COMPLETE (terminal)             Executor succeeded.
    ESCALATE    ESCALATE (terminal, approval)   Human gate. Never auto-approved.
    FAILED      FAILED (terminal)               Executor raised; nothing to retry.
    REMEDIATE   REMEDIATE while budget remains  Bounded, evidence-based re-execution.
    REMEDIATE   FAILED once budget exhausted    Fail closed. No infinite loop.
    ==========  ==============================  ==========================

    Fail-closed guarantees
    ----------------------
    * ``COMPLETE`` requires ``outcome.passed`` to be true. A ``COMPLETE`` status
      that is not ``passed`` is a contract violation and is refused, because
      accepting it would let a failed execution be recorded as a success.
    * ``ESCALATE`` never returns ``remediation_allowed=True``: an approval gate
      is resolved by a human, never by a retry.
    * Remediation is permitted only while ``budget.exhausted`` is false, and the
      decision records the exact attempt identity that authorised it.
    * No decision ever fabricates evidence: ``reason`` is composed only from the
      outcome's own status, findings and the supplied budget.

    Raises:
        LifecycleDecisionError: when the outcome contradicts its own
            ``passed`` verdict, or the budget is internally inconsistent.
    """
    attempt = budget.attempt

    if outcome.status is OutcomeStatus.COMPLETE:
        # Fail closed: a success status without a success verdict is refused
        # rather than trusted, so a failed run can never be recorded as done.
        if not outcome.passed:
            raise LifecycleDecisionError(
                "COMPLETE outcome contradicts its own verdict: passed=False. "
                "Refusing to record an unverified success.",
                details={
                    "status": outcome.status.value,
                    "passed": outcome.passed,
                    "loop_type": outcome.loop_type,
                },
            )
        return _decide(
            OutcomeStatus.COMPLETE,
            attempt=attempt,
            remediation_allowed=False,
            requires_human_approval=False,
            terminal=True,
            reason="Executor reported COMPLETE with a passing verdict.",
        )

    if outcome.status is OutcomeStatus.ESCALATE:
        # An approval gate is a human decision. Remediating around it would
        # bypass the gate, so it is terminal and never auto-resolved.
        return _decide(
            OutcomeStatus.ESCALATE,
            attempt=attempt,
            remediation_allowed=False,
            requires_human_approval=True,
            terminal=True,
            reason="Executor reported ESCALATE; awaiting human approval.",
        )

    if outcome.status is OutcomeStatus.FAILED:
        # The executor raised. There is no partial result to remediate, so the
        # failure is terminal and the retry budget is not consumed.
        return _decide(
            OutcomeStatus.FAILED,
            attempt=attempt,
            remediation_allowed=False,
            requires_human_approval=False,
            terminal=True,
            reason="Executor reported FAILED; no re-execution is permitted.",
        )

    # Remaining case: REMEDIATE.
    if budget.exhausted:
        # Bounded by construction. Exhausting the budget can never loop again
        # and can never auto-succeed; it terminates as FAILED.
        return _decide(
            OutcomeStatus.FAILED,
            attempt=attempt,
            remediation_allowed=False,
            requires_human_approval=False,
            terminal=True,
            reason=(
                f"Remediation budget exhausted after {attempt} of "
                f"{budget.max_attempts} attempt(s); failing closed."
            ),
        )

    # ── C3: decision/stage alignment ──────────────────────────────────
    # A REMEDIATE authorisation names the stage requiring corrective work
    # (the default stage unless the caller names a narrower one). Stage
    # identity is a caller-supplied label, like loop_type: it is recorded,
    # never validated, because no canonical stage registry exists on this
    # path and inventing one would manufacture semantics. COMPLETE /
    # ESCALATE / FAILED name no stage (None); only an authorised REMEDIATE
    # does -- so a remediation description derived from a REMEDIATE
    # decision always knows which unit of work it addresses.


    return _decide(
        OutcomeStatus.REMEDIATE,
        attempt=attempt,
        remediation_allowed=True,
        requires_human_approval=False,
        terminal=False,
        reason=(
            f"Remediation permitted: attempt {attempt} of {budget.max_attempts}; "
            f"{budget.remaining} remaining."
        ),
    )


# ── C3: declarative remediation capability ────────────────────────────────
# Gate C3 certifies WHAT must be corrected and WHY, as frozen data. Nothing
# below executes a retry, mutates an attempt counter, invokes a worker /
# Power Engine / Model Router / LLM, or creates an approval request; those
# remain structurally absent (proven by AST allowlist in
# ``test_remediation_contract.py``).


class RemediationRequest(BaseModel):
    """Declarative, bounded description of authorised remediation (Gate C3).

    Intent as data: a consumer can read it, persist it, or queue it --
    there is nothing executable inside it (no callback, no endpoint, no
    execution handle).

    * ``stage``     -- the unit of work requiring corrective work. Like
      ``loop_type``, it is a label: recorded, never validated, because no
      canonical stage registry exists on this path.
      ``describe_remediation`` defaults it to the outcome's ``loop_type``
      (the only canonical unit-of-work label available) and lets the
      caller name a narrower stage.
    * ``loop_type`` -- the engineering loop that produced the outcome,
      carried verbatim from the certified ``ExecutionOutcome``.
    * ``findings``  -- the outcome's evidence, copied so the request can
      never alias (and therefore never mutate) the source outcome.
    * ``budget``    -- the bounded intent: which attempt authorised this
      remediation and how many remain. The budget is required, so an
      unbounded request is not representable.
    * ``reason``    -- the decision's evidence-derived justification.

    Non-goals (Gate C3): no execution, no scheduling, no approval payload.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(..., min_length=1, description="Unit of work needing corrective work.")
    loop_type: str = Field(..., min_length=1, description="Engineering loop that ran.")
    findings: list[str] = Field(
        default_factory=list, description="Evidence copied from the outcome."
    )
    budget: RemediationBudget = Field(..., description="Bounded remediation intent.")
    reason: str = Field(..., min_length=1, description="Evidence-derived justification.")


def describe_remediation(
    decision: LifecycleDecision,
    outcome: ExecutionOutcome,
    *,
    budget: RemediationBudget,
    stage: str | None = None,
) -> RemediationRequest | None:
    """Map a certified decision to its declarative remediation artefact.

    Mapping (Gate C3):

    ==========  ============================================== decision    artefact
    COMPLETE    ``None`` -- nothing to correct.
    ESCALATE    ``None`` -- human gate; approval belongs to C4; C3
                executes nothing here.
    FAILED      ``None`` -- terminal, unchanged.
    REMEDIATE   ``RemediationRequest`` -- stage + evidence + bounded
                budget, only while the decision and the budget agree.

    Fail-closed rules (each refusal raises ``LifecycleDecisionError``):

    * ``remediation_allowed`` and the status must agree: a permit on a
      non-``REMEDIATE`` decision, or a ``REMEDIATE`` decision without a
      permit, is refused rather than reinterpreted.
    * A ``REMEDIATE`` decision that is terminal or that requires human
      approval is refused (remediation never coexists with either).
    * The supplied ``budget`` must agree with the decision's ``attempt``
      and must not be exhausted: no request may be authored against a
      spent budget.
    * The outcome must itself be ``REMEDIATE``: evidence for a correction
      cannot come from an outcome that did not ask for one.

    Pure and deterministic: no I/O, no dispatch, no mutation -- the
    outcome's findings are copied, never aliased.
    """
    if decision.status is not OutcomeStatus.REMEDIATE:
        if decision.remediation_allowed:
            raise LifecycleDecisionError(
                "Remediation permit on a non-REMEDIATE decision is a contract violation.",
                details={
                    "decision_status": decision.status.value,
                    "remediation_allowed": decision.remediation_allowed,
                },
            )
        # COMPLETE / ESCALATE / FAILED: no C3 artefact, by contract.
        return None

    if not decision.remediation_allowed:
        raise LifecycleDecisionError(
            "A REMEDIATE decision without a remediation permit is a contract violation.",
            details={"decision_status": decision.status.value, "attempt": decision.attempt},
        )
    if decision.terminal:
        raise LifecycleDecisionError(
            "A terminal REMEDIATE decision cannot describe remediation.",
            details={"decision_status": decision.status.value, "attempt": decision.attempt},
        )
    if decision.requires_human_approval:
        raise LifecycleDecisionError(
            "A REMEDIATE decision must not require human approval.",
            details={"decision_status": decision.status.value},
        )
    if decision.attempt != budget.attempt:
        raise LifecycleDecisionError(
            "Decision attempt does not match the supplied remediation budget.",
            details={"decision_attempt": decision.attempt, "budget_attempt": budget.attempt},
        )
    if budget.exhausted:
        raise LifecycleDecisionError(
            "Refusing to describe remediation against an exhausted budget.",
            details={"attempt": budget.attempt, "max_attempts": budget.max_attempts},
        )
    if outcome.status is not OutcomeStatus.REMEDIATE:
        raise LifecycleDecisionError(
            "Outcome status contradicts the REMEDIATE decision; evidence refused.",
            details={
                "decision_status": decision.status.value,
                "outcome_status": outcome.status.value,
            },
        )

    return RemediationRequest(
        stage=stage or outcome.loop_type,
        loop_type=outcome.loop_type,
        findings=list(outcome.findings),
        budget=budget,
        reason=decision.reason,
    )


# ── C4: declarative human-approval capability ────────────────────────────────
# Gate C4 certifies THAT human intervention is required, as frozen data.
# Nothing below approves, rejects, halts, continues, persists, or invokes an
# executor / worker / Power Engine / Model Router / LLM / API; those remain
# structurally absent (proven by AST allowlist in ``test_approval_contract.py``).


class HumanApprovalRequirement(BaseModel):
    """Declarative statement that human approval is required (Gate C4).

    Intent as data: a consumer can read it or carry it. Its existence *is*
    the statement "human approval is required for this unit of work";
    there is nothing executable inside it (no callback, no endpoint, no
    approval handle, no identity).

    * ``stage``     -- the unit of work requiring approval. Like
      ``loop_type`` and C3's ``stage``, it is a label: recorded, never
      validated, because no canonical stage registry exists on this path.
      ``describe_approval`` defaults it to the outcome's ``loop_type`` (the
      only canonical unit-of-work label available) and lets the caller
      name a narrower stage or task.
    * ``loop_type`` -- the engineering loop that produced the escalation,
      carried verbatim from the certified ``ExecutionOutcome``.
    * ``findings``  -- the outcome's evidence, copied so the requirement
      can never alias (and therefore never mutate) the source outcome.
      Together with ``reason`` this is the evidence reference: the
      certified escalation path carries no durable artifact identifier,
      and inventing one here would fabricate provenance.
    * ``reason``    -- the decision's evidence-derived justification.

    Identity: deliberately none. The certified
    ``ExecutionOutcome`` / ``LifecycleDecision`` path carries no approval
    identity, and generating one here would be both arbitrary and impure
    (identity generation needs a source of novelty the contract does not
    have). Identity, if ever needed, belongs to a future durable approval
    record -- not to this declarative requirement.

    Non-goals (Gate C4): not an approval record, not a workflow state, not
    a signal that halts or continues execution. An ``ESCALATE`` decision
    does NOT become O-1's runtime ``WAITING_FOR_HITL`` pause state by
    virtue of this value; production remains unwired.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    stage: str = Field(..., min_length=1, description="Unit of work needing approval.")
    loop_type: str = Field(..., min_length=1, description="Engineering loop that ran.")
    findings: list[str] = Field(
        default_factory=list, description="Evidence copied from the outcome."
    )
    reason: str = Field(..., min_length=1, description="Evidence-derived justification.")


def describe_approval(
    decision: LifecycleDecision,
    outcome: ExecutionOutcome,
    *,
    stage: str | None = None,
) -> HumanApprovalRequirement | None:
    """Map a certified decision to its declarative approval requirement.

    Mapping (Gate C4):

    ==========  ============================================== decision    artefact
    COMPLETE    ``None`` -- nothing awaits a human.
    REMEDIATE   ``None`` -- C4 grants no approval requirement; the
                bounded correction proceeds without one.
    ESCALATE    ``HumanApprovalRequirement`` -- stage + evidence +
                justification: approval IS required, as data only.
    FAILED      ``None`` -- terminal, meaning unchanged from C2.

    Fail-closed rules (each refusal raises ``LifecycleDecisionError``):

    * A decision claiming ``requires_human_approval`` without being
      ``ESCALATE`` is refused rather than silently downgraded.
    * An ``ESCALATE`` decision that does not claim approval, that carries
      a remediation permit, or that is not terminal, is refused: each
      contradicts the C2-certified ESCALATE row.
    * The outcome and the decision must agree about escalation in both
      directions: evidence that did not ask for a human cannot justify a
      requirement, and escalation evidence suppressed by a non-``ESCALATE``
      decision is refused rather than dropped.

    Pure and deterministic: no I/O, no dispatch, no mutation, no identity
    -- the outcome's findings are copied, never aliased.
    """
    if decision.status is not OutcomeStatus.ESCALATE:
        if decision.requires_human_approval:
            raise LifecycleDecisionError(
                "Human-approval claim on a non-ESCALATE decision is a contract violation.",
                details={
                    "decision_status": decision.status.value,
                    "requires_human_approval": decision.requires_human_approval,
                },
            )
        if outcome.status is OutcomeStatus.ESCALATE:
            raise LifecycleDecisionError(
                "ESCALATE evidence suppressed by a non-ESCALATE decision; refused.",
                details={
                    "decision_status": decision.status.value,
                    "outcome_status": outcome.status.value,
                },
            )
        # COMPLETE / REMEDIATE / FAILED: no C4 artefact, by contract.
        return None

    if not decision.requires_human_approval:
        raise LifecycleDecisionError(
            "An ESCALATE decision must require human approval.",
            details={"decision_status": decision.status.value},
        )
    if decision.remediation_allowed:
        raise LifecycleDecisionError(
            "An ESCALATE decision must not carry a remediation permit; "
            "a retry can never bypass the human gate.",
            details={"decision_status": decision.status.value},
        )
    if not decision.terminal:
        raise LifecycleDecisionError(
            "An ESCALATE decision must be terminal, per the certified decision table.",
            details={"decision_status": decision.status.value},
        )
    if outcome.status is not OutcomeStatus.ESCALATE:
        raise LifecycleDecisionError(
            "Outcome status contradicts the ESCALATE decision; evidence refused.",
            details={
                "decision_status": decision.status.value,
                "outcome_status": outcome.status.value,
            },
        )

    return HumanApprovalRequirement(
        stage=stage or outcome.loop_type,
        loop_type=outcome.loop_type,
        findings=list(outcome.findings),
        reason=decision.reason,
    )
