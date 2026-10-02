# AutoForge Learning (Phase 19)

Phase 19B-1 foundation: immutable learning domain models, authoritative
evidence representation, real evidence collection, and the `ProposalGateway`
security boundary.

Phase 19B-2 adds the **safe promotion pipeline** on top of that foundation:
durable evaluation, the nine-invariant regression gate, human approval through
the existing HITL manager, a pre-created rollback handle, atomic promotion,
and deterministic rollback.

## What this package is

* **Immutable models only.** `ExperienceRecord`, `EvidenceRef`,
  `LearningSignal`, `LearningCandidate`, `ProposalDecision`, `ValidationSummary`,
  `EvaluationReport`, `ApprovalRecord`, `RollbackHandle`, `PromotionRecord`.
* **Evidence collection** from existing authoritative systems
  (durable artifact catalog, completion/validation results, runtime state).
* **`ProposalGateway`** — the *only* sanctioned entry point for a learning
  candidate, which routes every proposal through the certified
  `AIGuardrailsEngine.evaluate_learning_proposal()` boundary.
* **The nine protected invariants** (`invariants`) — transcribed verbatim from
  Gate 19A-8, each with an explicit `PASS` / `FAIL` / `UNAVAILABLE` /
  `NOT_APPLICABLE` result.
* **`RegressionEvaluator`** — fail-closed. Absent evidence is `UNAVAILABLE`,
  never `PASS`.
* **`DurableLearningStore`** — project-scoped, crash-safe, immutable candidate
  identity, distinct from artifact persistence.
* **`ApprovalCoordinator`** — bound to the *existing* `SecurityPlatform`
  `HITLManager` + `GovernancePolicyEngine`. Human-only.
* **`PromotionService`** — rollback handle created *before* activation, atomic
  commit, idempotent, deterministic rollback.
* **`LearningAuditor`** — routed through the certified `AuditEngine`.
* **`TelemetryCollector`** — counters derived from real records.

## The lifecycle

```
candidate → evidence → evaluate (9 invariants) → HITL approval
          → rollback handle → atomic promotion → audit → rollback
```

Every stage is an explicit, separately callable method on
`LearningLifecycleService`. There is no `run_everything` shortcut that could
skip a gate.

## What this package is NOT

* It does **not** connect promoted learning into any execution engine.
  The active-state pointer is written; nothing in the platform reads it yet.
  (Gate 13 keeps that wiring out of this gate.)
* It does **not** promote without a human decision recorded by the security
  platform.
* It does **not** modify source code.
* It does **not** grant authority. Level 5 is unreachable by construction.
* It creates **no** second security, approval, or audit component.

`ProposalGateway` returning `PERMITTED` means only *"this proposal may proceed
to the next controlled learning stage."* Promotion is a separate, later,
human-authorized act.

## Architecture basis

All decisions derive from the Gate 19A documents in `phase19/`. This package
implements M-01, M-02, M-03, **M-04** (the non-negotiable production call site
into `evaluate_learning_proposal()`), **M-06**, **M-08** (the regression
evaluator), **M-10** (approval), **M-11** (atomic promotion) and **M-12**
(deterministic rollback).