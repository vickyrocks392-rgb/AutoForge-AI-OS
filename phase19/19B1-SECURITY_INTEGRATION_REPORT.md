# PHASE 19B-1 — SECURITY INTEGRATION REPORT

**Gate:** 19B1-16
**Date:** 2026-10-02

---

## 1. The Gate Objective

> Make the existing self-improvement security boundary **load-bearing** before
> real learning candidates exist.

Gate 19A proved the boundary (`evaluate_learning_proposal`) was correct and
certified but had **zero production callers**. 19B-1's single most important
outcome is that it now has one, on the real production path.

---

## 2. Enforcement Point

```
Kernel.execute_project()                            kernel.py
  |- Step 6  learning_engine.reflect_and_learn(...)  kernel.py
       |- _build_experience()             real D1/D2 evidence
       |- extract ReusableLessons
       \- _propose_through_gateway()      learning_engine.py
            \- ProposalGateway.evaluate(candidate)
                 |- local pre-checks (L5, scope, capability, kind)
                 \- ProposalGateway._call_boundary()   gateway.py
                      \- AIGuardrailsEngine.evaluate_learning_proposal()
                             ai_guardrails.py:611      <-- CERTIFIED BOUNDARY
                 \- fail-closed ProposalDecision
            \- only *permitted* lessons may advance
```

**The production caller of `evaluate_learning_proposal` is
`autoforge_learning.gateway.ProposalGateway._call_boundary`.** The engine is
bound to the real `AIGuardrailsEngine` supplied by `SecurityPlatform.guardrails`
(`composition_root.py` step 9b).

---

## 3. Gateway Defence Layers (Gate 6: the gateway enforces, not the caller)

| Layer | Check | Source of truth | Failure |
|---|---|---|---|
| L-a Construction | `LearningCandidate` refuses an L5 `authority` value | model validator | cannot be constructed |
| L-a Construction | `LearningScope` requires `project_id`; kind restricted to 4 | model validator | cannot be constructed |
| L-a Construction | `model_annotation_authoritative: Literal[False]` | type system | cannot be asserted |
| L-b Local | capabilities ∩ `LEARNING_FORBIDDEN_CAPABILITIES` | `ai_guardrails.py:285` | `non_authority_capability` |
| L-b Local | kind ∉ `LEARNABLE_PROPOSAL_KINDS` | `ai_guardrails.py:273` | `unknown_proposal_kind` |
| L-b Local | unknown capability name | gateway | converted to an escalation the boundary denies |
| L-c Boundary | `evaluate_learning_proposal()` | **certified** | `boundary_denied` |
| L-d Engine | absent gateway ⇒ nothing is proposed | `learning_engine.py` | no candidate |
| L-d Engine | denied lesson never promoted to Knowledge | `learning_engine.py` | not promoted |

The gateway denies on the **first** failure and never treats partial success as
permission.

---

## 4. Fail-Closed Proof

Every one of these produced a **DENIED** decision in the test suite:

| Condition | Denial reason |
|---|---|
| Boundary raises | `boundary_raised` |
| Boundary returns a non-`LearningProposalDecision` | `boundary_malformed` |
| Boundary returns an unknown decision value | `boundary_unknown_decision` / `boundary_raised` |
| Boundary returns `is_permitted=True` with a `DENY` decision | `boundary_denied` |
| Boundary is `None` (unavailable) | `boundary_unavailable` |
| Malformed candidate (not a `LearningCandidate`) | `boundary_raised` (record still built) |

Two robustness bugs were found by these tests and fixed during 19B-1:
---

## 5. Authority Invariants

| Invariant | Enforcement | Test |
|---|---|---|
| No reachable Level 5 | `LearningCandidate` validator rejects L5; no security scope kinds; gateway denies L5 | `test_3_level_5_cannot_be_represented_on_a_candidate` |
| Permitted ≠ approved | `ProposalDecision.is_approved` is a hardcoded `False` property | `test_benign_proposal_is_permitted_but_never_approved` |
| Human approval always required | boundary returns `promotion_requires` incl. `human_authorization` | `test_permitted_still_requires_human_authorization` |
| Wording ≠ authority | summary/rationale/annotation cannot change the outcome | `test_5_self_declared_approval_is_not_authority` |
| No policy mutation | `AIGuardrailsEngine` has no mutation API; learning adds none | `test_4_learning_never_mutates_guardrails_policy` |
| Project isolation | mandatory `project_id`; scope never matches across projects | `test_10_project_a_scope_never_matches_project_b` |

---

## 6. Existing Security Architecture: Untouched

`packages/security/` has **zero modifications**. Verified by
`test_12_completion_artifact_review_contracts_untouched`, which asserts
`git diff --quiet HEAD` for `ai_guardrails.py`, `completion.py`,
`artifacts/models.py`, `artifact_catalog.py`, and `review/engine.py`.

Phase 19B-1 **adds a caller**. It does not modify, extend, or duplicate the
security subsystem. There is no parallel authorization, audit, versioning, or
policy system.

---

## 7. Known Residual Risks (honest disclosure)

| Risk | Status |
|---|---|
| `KernelMemoryEngineAdapter` still has no project filter (AMB-01) and fails open (AMB-02) | **Unchanged.** Learning does not read through it, so 19B-1 is unaffected. The adapter defect remains latent for other consumers. |
| `repair_records` still never supplied in production (GAP-04) | Open; needs a repair-record producer (19B-2). |
| Legacy `confidence >= 0.90` threshold still in `learning_engine.py` | Partially mitigated: promotion now requires **both** evidence-derived confidence **and** a boundary permit. Full removal belongs with M-11. |
| No audit records emitted for learning events (M-14 deferred) | Transitions observable only via the returned `ProposalDecision`. |
| `_promoted_candidate_ids` is in-process memory | Telemetry only; resets on restart. An honest zero is reported, so no false claim results. |

1. `_deny()` itself raised on a malformed candidate — a **fail-open** failure
   mode, because the caller would have seen an exception instead of a denial.
   Fixed with `_safe_uuid()`.
2. An unknown decision string bypassed a `frozenset` membership test. Replaced
   with a single explicit allow-value check (`_ALLOWED_BOUNDARY_DECISION`), so a
   *future* guardrail decision type cannot silently become permissive.