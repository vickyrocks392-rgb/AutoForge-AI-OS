# Phase 19B-2 — Implementation Report

**Gate:** 19B-2 — Validation, Evaluation, and the Promotion Path
**Type:** IMPLEMENTATION
**Date:** 2026-10-02
**Baseline HEAD:** `b9c188c8c461854695b76d5148ec407d40bfbda7`
**Architecture basis:** `phase19/` Gate 19A documents (19A-5, 19A-6, 19A-8, 19A-12, 19A-13)

---

## 1. Verdict

```
19B-2: CERTIFIED
```

All Gate 23 criteria are satisfied. Evidence is in
`PHASE_19B2_TEST_MATRIX.md`, `PHASE_19B2_SECURITY_REPORT.md` and
`PHASE_19B2_CERTIFICATION_REPORT.md`.

---

## 2. What was built

The safe promotion pipeline, end to end:

```
Durable Learning Candidate
        ↓
Evidence-backed Evaluation (9 protected invariants)
        ↓
Regression Evaluation (all nine, fail closed)
        ↓
9-Invariant Safety/Regression Gate
        ↓
Human Approval / HITL  (existing HITLManager + GovernancePolicyEngine)
        ↓
Pre-created Rollback Handle  (durable, verified, BEFORE any change)
        ↓
Atomic Promotion  (single pointer write)
        ↓
Audit Emission  (certified AuditEngine)
        ↓
Deterministic Rollback
```

### Production source (8 new modules, 1 modified)

| Module | Purpose | Gate |
|---|---|---|
| `invariants.py` | The nine protected invariants, transcribed from 19A-8 §2 | 3 |
| `evaluation.py` | `RegressionEvaluator` + `EvidenceAssessor`, fail-closed | 3, 4 |
| `store.py` | `DurableLearningStore` — project-scoped, crash-safe | 2 |
| `approval.py` | `ApprovalCoordinator` bound to the certified HITL | 5 |
| `promotion.py` | `PromotionService` — handle-before-activation, atomic, rollback | 6, 7, 8 |
| `audit.py` | `LearningAuditor` routed through `AuditEngine` | 9 |
| `telemetry.py` | `TelemetryCollector` — counters from real records | 16 |
| `lifecycle.py` | `LearningLifecycleService` — the canonical assembly | 21 |
| `__init__.py` | Exports (modified) | — |

---

## 3. The architectural principle, enforced structurally

> Learning may propose. Learning may be evaluated. Learning may be approved.
> **Only the existing security/governance architecture may authorize promotion.**

Each clause is a mechanism, not a comment:

| Principle | Mechanism | Test |
|---|---|---|
| A model's confidence is never authoritative | The evaluator has no confidence input; a Q4 (model) evidence reference can never satisfy an invariant | `test_model_generated_evidence_never_satisfies_an_invariant` |
| Deterministic checks stay authoritative | PI-1/PI-2/PI-9 are ABSOLUTE tripwires; any violation fails regardless of gains elsewhere | `test_security_violation_disqualifies_despite_gains_everywhere_else` |
| Human approval is mandatory | `PromotionService` Gate D calls `ApprovalCoordinator.verify`, which re-checks status, human subject type, expiry and HITL lineage | `test_promotion_without_hitl_is_refused` |
| The model cannot impersonate approval | `ApprovalRecord._approval_requires_a_human` is a pydantic validator; the certified `HITLManager` independently refuses non-human subjects | `test_an_approval_record_cannot_be_self_declared_approved`, `test_a_worker_cannot_approve_even_with_the_governance_role` |
| Security/authority stays outside learning | No learning module calls a guardrail/authorization/credential mutation API (AST-verified); the boundary is re-consulted at promotion time | `test_no_module_grants_authority_to_a_model`, `test_no_parallel_security_or_audit_component_is_created` |

---

## 4. Key design decisions

**The store reuses the repository's existing durability discipline.**
`PhysicalArtifactStore` (18-K) publishes atomically: staging write → `fsync` →
`os.replace` → directory `fsync`. `DurableLearningStore` adopts exactly that
sequence. No parallel database framework was introduced, and learning
persistence remains a *separate* store from artifact persistence
(`test_the_store_is_distinct_from_artifact_persistence`).

**Absent data is typed, never defaulted.** `InvariantMetrics` has only
`Optional` fields. `None` and `0` are different facts, and a metric that was
never measured produces no evidence reference at all.

**The report cannot lie about itself.** Two `model_validator`s on
`EvaluationReport` reject a report that omits an invariant, and reject one
whose `promotable` flag contradicts its own per-invariant results.

**An approval refusal is a promotion refusal.** `PromotionService` wraps
`ApprovalError` into `PromotionError` so a caller cannot treat a gate refusal
as transient and retry around it.

**Audit failure has its own outcome.** If the promotion committed but its
success audit could not be emitted, the result is `PromotionAuditError`, the
durable record says `PROMOTED` **and** carries `audit_failure_reason`. Both
facts are recorded; neither is converted into a clean success (Gate 17).

**Concurrency uses one lock, not a framework.** `PromotionService` holds a
single `threading.RLock` around its check-then-act sequence — the same
discipline the store already uses — so two racing promotions produce exactly
one promotion.

---

## 5. Defects found and fixed during this gate

These were found by the tests, not by inspection:

| # | Defect | Fix |
|---|---|---|
| 1 | `set_active_state` wrote by `state_id` while `get_active_state` read by `kind:key` — promotion was invisible | Both now use the deterministic `<kind>__<key>` path |
| 2 | `PromotionService` re-raised raw infrastructure errors, so a disk failure escaped as `OSError` | All refusals now surface as `PromotionError`, chaining the cause |
| 3 | A post-commit audit failure produced *both* a `PROMOTED` and a contradictory `FAILED` record | `PromotionAuditError` + `audit_failure_reason` on the record |
| 4 | Two concurrent promotions both passed the idempotency check | Promotion critical section serialised |
| 5 | `verify()` called `platform.hitl()` — `hitl` is a property | Corrected to `platform.hitl` |
| 6 | An `APPROVED` record could name a non-human approver | `_approval_requires_a_human` pydantic validator |

---

## 6. Regression protection

Every existing suite was run before and after. See
`PHASE_19B2_CERTIFICATION_REPORT.md` §4 for the full matrix.

Two suites fail **in this environment, identically at the pristine baseline**
(verified by stashing all 19B-2 work and re-running):

* `packages/power_engines` — 1 failure, health-check script exit code.
* `packages/composition` — 3 failures, all requiring a live model provider at
  `127.0.0.1:8080` that cannot reach HuggingFace from this environment.

Neither is caused by 19B-2. No failure was hidden.

---

## 7. Explicitly deferred

Not implemented in 19B-2, by design:

* Autonomous experimentation / RL / recursive self-improvement.
* Source-code self-modification.
* Autonomous promotion without HITL.
* **Wiring promoted learning into any execution engine** (Gate 13). The
  active-state pointer is written and readable; no production consumer reads
  it. `test_no_production_engine_reads_the_active_learning_state` enforces
  this.
* Automatic rollback on invariant regression (19A-13 §4 describes it as a
  Phase 19 aspiration; the *mechanism* exists and is deterministic, but the
  monitoring trigger is not wired).
* PI-8 customer-outcome measurement (deferred by 19A-8 §2 itself).

---

## 8. Traceability

| Requirement | Implementation | Tests |
|---|---|---|
| M-02 durable store | `store.py` | `test_store_durability_concurrency.py` (16) |
| M-08 regression evaluator | `invariants.py`, `evaluation.py` | `test_adversarial_evidence_evaluation.py` (24) |
| M-10 approval | `approval.py` | `test_adversarial_approval.py` (18) |
| M-11 atomic promotion | `promotion.py` | `test_adversarial_promotion.py` (16) |
| M-12 deterministic rollback | `promotion.py` | `test_adversarial_promotion.py` |
| M-14 audit | `audit.py` | `test_telemetry_and_audit.py` (9) |
| M-16 telemetry | `telemetry.py` | `test_telemetry_and_audit.py` |
| Gate 11 isolation | `store.py` | `test_adversarial_isolation.py` (9) |
| Gate 12 authority | `promotion.py`, `store.py` | `test_adversarial_security.py` (29) |
| Gate 13 no behaviour change | — | `test_promotion_architecture.py` (26) |
| Gate 20 protected systems | — | `test_promotion_architecture.py` |
| Gate 21 architecture | `lifecycle.py` | `test_promotion_architecture.py` |